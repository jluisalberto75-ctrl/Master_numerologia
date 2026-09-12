"""
Arma el contexto completo de un usuario para el "maestro" de IA: sus
datos básicos, todos los números ya calculados (vía
numerologia_calculo.py), su memoria acumulada (notas_agente) y su
historial reciente de compatibilidades consultadas.

Por qué existe este módulo separado (mismo criterio que el bot de
running): es el ÚNICO lugar del proyecto que conoce a la vez el esquema
de la base de datos Y el motor de cálculo. Los handlers del bot nunca
deberían escribir SQL suelto ni llamar a numerologia_calculo
directamente — todos pasan por aquí. Eso significa que si mañana cambia
una columna, o se agrega un número nuevo a la carta, hay un solo lugar
que tocar para que tanto el bot como la IA lo vean reflejado.
"""

import sqlite3

from numerologia_db import DB_PATH
from numerologia_calculo import perfil_numerologico_completo, es_lectura_vigente

LIMITE_COMPATIBILIDADES_RECIENTES = 5
LIMITE_NOTAS_POR_TIPO = 20  # tope defensivo; no debería crecer sin límite


def obtener_contexto_numerologico(telegram_id, anio: int = None) -> dict | None:
    """
    Punto de entrada único para el resto del bot. Devuelve None si el
    usuario todavía no tiene perfil (no completó la encuesta), igual que
    obtener_contexto_corredor en el bot de running.

    'anio' se expone como parámetro (no se calcula adentro con
    date.today()) por la misma razón que en numerologia_calculo.py:
    mantiene la función fácil de probar con un año fijo en vez de
    depender de la fecha real del sistema.
    """
    conexion = sqlite3.connect(DB_PATH)
    conexion.row_factory = sqlite3.Row
    cursor = conexion.cursor()

    cursor.execute("SELECT * FROM usuarios WHERE telegram_id = ?", (telegram_id,))
    fila_usuario = cursor.fetchone()
    if not fila_usuario:
        conexion.close()
        return None
    usuario = dict(fila_usuario)

    # Si todavía no completó la encuesta (existe la fila pero sin los
    # dos datos mínimos), tampoco hay nada que calcular.
    if not usuario.get("nombre_completo") or not usuario.get("fecha_nacimiento"):
        conexion.close()
        return None

    # Memoria del agente: solo notas activas, más recientes primero
    cursor.execute(
        "SELECT tipo, texto, fecha FROM notas_agente "
        "WHERE telegram_id = ? AND activa = 1 "
        "ORDER BY fecha DESC LIMIT ?",
        (telegram_id, LIMITE_NOTAS_POR_TIPO),
    )
    memoria_agente = [dict(f) for f in cursor.fetchall()]

    # Historial de compatibilidades recientes
    cursor.execute(
        "SELECT nombre_otra_persona, numero_compatibilidad, fecha_consulta "
        "FROM compatibilidades WHERE telegram_id = ? "
        "ORDER BY fecha_consulta DESC LIMIT ?",
        (telegram_id, LIMITE_COMPATIBILIDADES_RECIENTES),
    )
    compatibilidades_recientes = [dict(f) for f in cursor.fetchall()]

    conexion.close()

    # Números ya calculados (nunca se le pide esto a la IA, ver docstring
    # de numerologia_calculo.py)
    numeros = perfil_numerologico_completo(
        nombre_completo=usuario["nombre_completo"],
        fecha_nacimiento_iso=usuario["fecha_nacimiento"],
        nombre_uso_actual=usuario.get("nombre_uso_actual"),
        anio=anio,
    )

    lectura_vigente = es_lectura_vigente(
        lectura_generada_en=usuario.get("lectura_generada_en"),
        lectura_generada_para_anio=usuario.get("lectura_generada_para_anio"),
        fecha_actualizacion=usuario.get("fecha_actualizacion"),
        anio_actual=anio,
    )

    return {
        "datos_personales": {
            "telegram_id": telegram_id,
            "nombre_completo": usuario["nombre_completo"],
            "nombre_uso_actual": usuario.get("nombre_uso_actual"),
            "fecha_nacimiento": usuario["fecha_nacimiento"],
        },
        "numeros": numeros,
        "memoria_agente": memoria_agente,
        "compatibilidades_recientes": compatibilidades_recientes,
        "lectura_cacheada": {
            "vigente": lectura_vigente,
            "texto": usuario.get("lectura_texto") if lectura_vigente else None,
        },
    }
