"""
Base de datos del bot de numerología.

Diseño deliberadamente distinto al del bot de running en un punto clave:
NO guardamos los números numerológicos (camino de vida, expresión, alma,
personalidad...) como columnas. Son el resultado de una función pura
sobre (nombre_completo, fecha_nacimiento) — recalcularlos es instantáneo
y así nunca quedan desincronizados si el usuario corrige su nombre o su
fecha. Lo que SÍ cacheamos es la LECTURA EN TEXTO que arma la IA a partir
de esos números, porque esa sí es cara (llamada a la API) y no cambia a
menos que cambien los datos de entrada o el año.

Esa última parte es la diferencia real con el bot de running: allí un
plan queda "viejo" solo si el usuario actualiza sus datos. Acá hay una
segunda razón de vencimiento que no depende del usuario: el Año Personal
se recalcula cada 1 de enero, así que una lectura de diciembre queda
desactualizada en enero aunque nadie haya tocado nada. Por eso guardamos
también el año para el que se generó la lectura (ver es_lectura_vigente
en numerologia_calculo.py, que compara ambas condiciones).
"""

import sqlite3
from datetime import datetime

DB_PATH = "numerologia.db"


def _asegurar_columnas_usuarios(cursor):
    """
    Migración no destructiva: si 'numerologia.db' ya existía sin alguna
    columna nueva, la agrega sin tocar los datos guardados. Mismo patrón
    que el bot de running — a medida que el bot crezca, cualquier columna
    nueva se agrega aquí, nunca borrando ni recreando la tabla.
    """
    cursor.execute("PRAGMA table_info(usuarios)")
    columnas_existentes = {fila[1] for fila in cursor.fetchall()}

    columnas_nuevas = {
        "nombre_uso_actual": "TEXT",
        "lectura_texto": "TEXT",
        "lectura_generada_en": "TEXT",
        "lectura_generada_para_anio": "INTEGER",
    }
    for columna, tipo in columnas_nuevas.items():
        if columna not in columnas_existentes:
            cursor.execute(f"ALTER TABLE usuarios ADD COLUMN {columna} {tipo}")


def _asegurar_columnas_compatibilidades(cursor):
    """
    Migración no destructiva para agregar los dos ejes nuevos de
    compatibilidad (Expresión y Alma) sin tocar las filas que ya
    existían solo con el eje de Camino de Vida.
    """
    cursor.execute("PRAGMA table_info(compatibilidades)")
    columnas_existentes = {fila[1] for fila in cursor.fetchall()}

    columnas_nuevas = {
        "numero_compatibilidad_expresion": "INTEGER",
        "numero_compatibilidad_alma": "INTEGER",
    }
    for columna, tipo in columnas_nuevas.items():
        if columna not in columnas_existentes:
            cursor.execute(f"ALTER TABLE compatibilidades ADD COLUMN {columna} {tipo}")


def iniciar_db():
    conexion = sqlite3.connect(DB_PATH)
    cursor = conexion.cursor()

    # ---------- Tabla principal: identidad numerológica del usuario ----------
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            telegram_id INTEGER PRIMARY KEY,

            -- Las ÚNICAS dos entradas que necesita numerologia_calculo.py
            -- para derivar todos los números. fecha_nacimiento se guarda
            -- siempre en formato ISO ('YYYY-MM-DD'), sin importar en qué
            -- formato la haya escrito el usuario en la encuesta (DD/MM/AAAA
            -- se parsea y normaliza antes de guardar) — así el módulo de
            -- cálculo no tiene que lidiar con ambigüedad de formatos.
            nombre_completo TEXT,
            fecha_nacimiento TEXT,

            -- Opcional: el nombre que la persona usa día a día, si es
            -- distinto al de nacimiento (ej. "Carlos Gómez" vs "Carlos
            -- Alberto Gómez López"). Permite la función de comparar
            -- Expresión/Alma/Personalidad de nombre de nacimiento vs
            -- nombre de uso, sin pedirle al usuario que lo reescriba
            -- cada vez que quiera esa comparación.
            nombre_uso_actual TEXT,

            -- Caché de la lectura completa generada por la IA. Ver
            -- docstring del módulo: vence si cambian los datos de entrada
            -- O si cambió el año (Año Personal). lectura_generada_en
            -- guarda un timestamp ISO, lectura_generada_para_anio guarda
            -- el año (int) usado en esa lectura específica.
            lectura_texto TEXT,
            lectura_generada_en TEXT,
            lectura_generada_para_anio INTEGER,

            -- Meta
            fecha_registro TEXT,
            fecha_actualizacion TEXT
        )
        """
    )
    _asegurar_columnas_usuarios(cursor)

    # ---------- Historial de compatibilidades consultadas ----------
    # Una fila por cada persona con la que el usuario pidió compatibilidad.
    # Se guarda como historial (no se sobreescribe) para poder ofrecer más
    # adelante algo como "ver compatibilidades anteriores" sin recalcular,
    # y para que la IA tenga contexto de con quién ya se habló antes si el
    # usuario vuelve a preguntar por la misma persona.
    #
    # numero_compatibilidad guarda el eje de Camino de Vida (el "general",
    # por compatibilidad con datos guardados antes de que existieran los
    # otros dos ejes). numero_compatibilidad_expresion y
    # numero_compatibilidad_alma son los otros dos ejes — ver
    # calcular_compatibilidad_completa() en numerologia_calculo.py para
    # el porqué de mirar tres números y no uno solo.
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS compatibilidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            nombre_otra_persona TEXT,
            fecha_nacimiento_otra_persona TEXT,
            numero_compatibilidad INTEGER,
            numero_compatibilidad_expresion INTEGER,
            numero_compatibilidad_alma INTEGER,
            fecha_consulta TEXT,
            FOREIGN KEY (telegram_id) REFERENCES usuarios(telegram_id)
        )
        """
    )
    _asegurar_columnas_compatibilidades(cursor)

    # ---------- Memoria abierta del agente ----------
    # Equivalente al notas_agente del bot de running, pero con 'tipo' sin
    # cerrar de antemano a valores fijos (allá era 'restriccion' /
    # 'preferencia' / 'sensacion', con significado físico claro). Acá el
    # dominio es distinto — lo que vale la pena recordar entre preguntas
    # es más abierto ("está atravesando un cambio de carrera", "ya le
    # expliqué qué es un número maestro") — así que 'tipo' queda como
    # texto libre que la propia lógica del bot decide con el tiempo, en
    # vez de forzar categorías que todavía no sabemos si tienen sentido
    # en este dominio.
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notas_agente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            tipo TEXT,
            texto TEXT,
            fecha TEXT,
            activa INTEGER DEFAULT 1,
            FOREIGN KEY (telegram_id) REFERENCES usuarios(telegram_id)
        )
        """
    )

    conexion.commit()
    conexion.close()
    print("Base de datos lista: usuarios, compatibilidades, notas_agente")


if __name__ == "__main__":
    iniciar_db()
