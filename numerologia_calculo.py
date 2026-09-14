"""
Cálculo de numerología Pitagórica estándar: Camino de Vida, Expresión,
Alma, Personalidad y Año Personal, más el número de compatibilidad entre
dos personas.

Por qué esto vive en un módulo aparte y NO en el prompt de la IA: mismo
motivo que vdot.py en el bot de running. Un modelo de lenguaje es
no-determinista haciendo aritmética; si le pides "calcula el camino de
vida" dentro del prompt, puede darte números distintos para la misma
persona en dos preguntas distintas. Aquí la cuenta se hace una sola vez,
con funciones puras, y el resultado ya calculado se le pasa a la IA como
un dato más del contexto — ella ya no calcula nada, solo interpreta y
conecta lo que ya está resuelto.

DECISIÓN DE ALCANCE (Fase 1): números maestros (11, 22, 33) NO se
preservan por ahora — todo se reduce hasta un solo dígito (1-9). Esto es
una simplificación deliberada, no un error: la tradición numerológica
"completa" preserva esos números en pasos intermedios del cálculo, pero
se decidió posponerlo. El único punto de cambio si se activa más
adelante es reducir_a_digito() — el resto de las funciones no necesita
tocarse.

NOTA TÉCNICA sobre por qué reducir todo junto es válido: la raíz digital
(suma repetida de dígitos hasta un solo dígito) es invariante frente al
agrupamiter — reducir cada parte por separado y sumar, o sumar todo y
reducir al final, da siempre el mismo resultado (congruencia módulo 9).
Por eso no hace falta reducir día/mes/año o nombre/vocales/consonantes
por separado antes de sumar: sumar todo de una vez y reducir al final es
matemáticamente equivalente y más simple de mantener.
"""

import unicodedata
from datetime import date

# Tabla Pitagórica estándar: A=1, B=2, ... I=9, J=1, K=2, ... R=9, S=1...
TABLA_PITAGORICA = {
    letra: (indice % 9) + 1
    for indice, letra in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
}

VOCALES = set("AEIOU")


def _normalizar_nombre(nombre: str) -> str:
    """
    Pasa a mayúsculas, quita tildes/diéresis (José -> JOSE, Ruíz -> RUIZ)
    y descarta todo lo que no sea una letra A-Z (espacios, guiones,
    apóstrofes). La tabla Pitagórica solo tiene sentido definido para
    A-Z, así que cualquier símbolo restante se ignora en vez de romper
    el cálculo.
    """
    if not nombre:
        return ""
    sin_tildes = unicodedata.normalize("NFKD", nombre)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return "".join(c for c in sin_tildes.upper() if "A" <= c <= "Z")


def reducir_a_digito(numero: int) -> int:
    """
    Suma dígitos repetidamente hasta llegar a un solo dígito (1-9).
    Ver nota de alcance arriba: no preserva números maestros por ahora.
    """
    numero = abs(int(numero))
    while numero > 9:
        numero = sum(int(d) for d in str(numero))
    return numero


def _suma_letras(nombre_normalizado: str, filtro=None) -> int:
    """
    Suma los valores Pitagóricos de las letras de un nombre ya
    normalizado. 'filtro' es una función letra -> bool para quedarse
    solo con vocales, solo consonantes, o None para todas.
    """
    letras = nombre_normalizado if filtro is None else [
        c for c in nombre_normalizado if filtro(c)
    ]
    return sum(TABLA_PITAGORICA[c] for c in letras)


def calcular_camino_vida(dia: int, mes: int, anio: int) -> int:
    """
    Camino de Vida: el número central de la carta, derivado solo de la
    fecha de nacimiento (no depende del nombre).
    """
    digitos = f"{dia}{mes}{anio}"
    total = sum(int(d) for d in digitos)
    return reducir_a_digito(total)


def calcular_expresion(nombre_completo: str) -> int:
    """Expresión / Destino: suma de TODAS las letras del nombre completo."""
    nombre = _normalizar_nombre(nombre_completo)
    return reducir_a_digito(_suma_letras(nombre))


def calcular_alma(nombre_completo: str) -> int:
    """Alma: suma de solo las VOCALES del nombre completo."""
    nombre = _normalizar_nombre(nombre_completo)
    return reducir_a_digito(_suma_letras(nombre, filtro=lambda c: c in VOCALES))


def calcular_personalidad(nombre_completo: str) -> int:
    """Personalidad: suma de solo las CONSONANTES del nombre completo."""
    nombre = _normalizar_nombre(nombre_completo)
    return reducir_a_digito(_suma_letras(nombre, filtro=lambda c: c not in VOCALES))


def calcular_numero_cumpleanos(dia_nacimiento: int) -> int:
    """
    Número de Cumpleaños: el día de nacimiento reducido a un solo
    dígito. Es el más simple de los cinco números "clásicos" de la
    carta (Camino de Vida, Expresión, Alma, Personalidad, Cumpleaños) —
    no depende del nombre, solo del día.
    """
    return reducir_a_digito(dia_nacimiento)


def calcular_anio_personal(dia: int, mes: int, anio_actual: int) -> int:
    """
    Año Personal: se recalcula cada año (por eso NO se guarda como
    columna fija en la base de datos, ver database.py). Combina el día y
    mes de nacimiento con el año calendario actual.
    """
    digitos = f"{dia}{mes}{anio_actual}"
    total = sum(int(d) for d in digitos)
    return reducir_a_digito(total)


def calcular_mes_personal(anio_personal: int, mes_actual: int) -> int:
    """Mes Personal: combina el Año Personal vigente con el mes calendario actual."""
    return reducir_a_digito(anio_personal + mes_actual)


def calcular_dia_personal(mes_personal: int, dia_actual: int) -> int:
    """Día Personal: combina el Mes Personal vigente con el día calendario actual."""
    return reducir_a_digito(mes_personal + dia_actual)


def calcular_numero_del_dia(dia_nacimiento: int, mes_nacimiento: int, fecha_referencia: date = None) -> dict:
    """
    Calcula la cascada completa Año Personal -> Mes Personal -> Día
    Personal para una fecha de referencia dada (por defecto, hoy).
    Se expone como cascada completa (no solo el día) porque el Día
    Personal no tiene sentido aislado de los dos anteriores — y así el
    trabajo diario del bot (numerologia_bot.py) no tiene que reimplementar
    ninguno de los tres pasos, solo leer el resultado.

    'fecha_referencia' se recibe como parámetro (no se toma
    date.today() adentro) por el mismo motivo que 'anio' en
    perfil_numerologico_completo: mantiene la función determinista y
    fácil de probar con una fecha fija.
    """
    fecha_referencia = fecha_referencia if fecha_referencia is not None else date.today()
    anio_personal = calcular_anio_personal(dia_nacimiento, mes_nacimiento, fecha_referencia.year)
    mes_personal = calcular_mes_personal(anio_personal, fecha_referencia.month)
    dia_personal = calcular_dia_personal(mes_personal, fecha_referencia.day)
    return {
        "anio_personal": anio_personal,
        "mes_personal": mes_personal,
        "dia_personal": dia_personal,
        "fecha_referencia": fecha_referencia.isoformat(),
    }


def calcular_numero_compatibilidad(
    dia1: int, mes1: int, anio1: int, dia2: int, mes2: int, anio2: int
) -> int:
    """
    Número de compatibilidad "general" entre dos personas, a partir de
    sus Caminos de Vida (reduce(camino_1 + camino_2)) — mismo criterio
    que el ejemplo del diseño original (Camino 1 + Camino 7 -> 8). Se
    mantiene como función simple porque algunas partes del bot solo
    necesitan este número suelto; para la interpretación completa de
    compatibilidad usar calcular_compatibilidad_completa().
    """
    camino1 = calcular_camino_vida(dia1, mes1, anio1)
    camino2 = calcular_camino_vida(dia2, mes2, anio2)
    return reducir_a_digito(camino1 + camino2)


def calcular_compatibilidad_completa(
    nombre_completo_1: str, dia1: int, mes1: int, anio1: int,
    nombre_completo_2: str, dia2: int, mes2: int, anio2: int,
) -> dict:
    """
    Compatibilidad en tres ejes, no uno solo — un maestro real nunca da
    compatibilidad mirando un único número. Cada eje mira algo distinto
    de la relación:
    - camino_vida: hacia dónde va cada quién en la vida, si el proyecto
      de fondo de ambos tiende a alinearse o a tensionarse.
    - expresion: cómo se comunican y se muestran hacia afuera el uno al
      otro.
    - alma: si conectan a nivel emocional/motivacional, más allá de lo
      que se ve por fuera.
    Cada eje se calcula igual: reduce(número_persona1 + número_persona2).
    Se devuelven también los números individuales de cada persona (no
    solo el resultado combinado) porque el maestro de IA los necesita
    para explicar POR QUÉ da ese resultado, no solo repetirlo.
    """
    camino1, camino2 = calcular_camino_vida(dia1, mes1, anio1), calcular_camino_vida(dia2, mes2, anio2)
    expresion1, expresion2 = calcular_expresion(nombre_completo_1), calcular_expresion(nombre_completo_2)
    alma1, alma2 = calcular_alma(nombre_completo_1), calcular_alma(nombre_completo_2)

    return {
        "camino_vida": {
            "persona1": camino1, "persona2": camino2,
            "compatibilidad": reducir_a_digito(camino1 + camino2),
        },
        "expresion": {
            "persona1": expresion1, "persona2": expresion2,
            "compatibilidad": reducir_a_digito(expresion1 + expresion2),
        },
        "alma": {
            "persona1": alma1, "persona2": alma2,
            "compatibilidad": reducir_a_digito(alma1 + alma2),
        },
    }


def parsear_fecha_iso(fecha_iso: str):
    """
    'YYYY-MM-DD' (formato en el que se guarda en la base de datos) ->
    (dia, mes, anio) como enteros. Pública porque el bot también la
    necesita (ej. para sacar la fecha propia ya guardada y calcular
    compatibilidad contra la fecha de otra persona). La
    validación/parseo de lo que el usuario escribe en la encuesta
    (selector_fecha.py, con botones) es un problema distinto y vive en
    esa capa, no acá — este módulo solo confía en que ya llega
    normalizado a ISO.
    """
    anio, mes, dia = fecha_iso.split("-")
    return int(dia), int(mes), int(anio)


def perfil_numerologico_completo(
    nombre_completo: str,
    fecha_nacimiento_iso: str,
    nombre_uso_actual: str = None,
    anio: int = None,
) -> dict:
    """
    Punto de entrada único para el resto del bot (equivalente a
    obtener_metodologia_vdot en el bot de running): dado el perfil
    básico del usuario, devuelve todos los números ya calculados, listos
    para pasarle a la IA como contexto.

    Si se pasa nombre_uso_actual (nombre distinto al de nacimiento),
    incluye también una comparación de Expresión/Alma/Personalidad entre
    ambos nombres, para la función "¿qué cambia si uso otro nombre?".

    'anio' es el año calendario para el que se calcula el Año Personal;
    si no se pasa, se usa el año actual. Se deja como parámetro (en vez
    de tomar datetime.now() adentro) para que el cálculo sea
    determinista y fácil de probar.
    """
    dia, mes, anio_nacimiento = parsear_fecha_iso(fecha_nacimiento_iso)
    anio = anio if anio is not None else date.today().year

    perfil = {
        "camino_vida": calcular_camino_vida(dia, mes, anio_nacimiento),
        "expresion": calcular_expresion(nombre_completo),
        "alma": calcular_alma(nombre_completo),
        "personalidad": calcular_personalidad(nombre_completo),
        "numero_cumpleanos": calcular_numero_cumpleanos(dia),
        "anio_personal": calcular_anio_personal(dia, mes, anio),
        "anio_personal_calculado_para": anio,
    }

    if nombre_uso_actual and _normalizar_nombre(nombre_uso_actual) != _normalizar_nombre(nombre_completo):
        perfil["comparacion_nombre_uso"] = {
            "nombre_uso_actual": nombre_uso_actual,
            "expresion": calcular_expresion(nombre_uso_actual),
            "alma": calcular_alma(nombre_uso_actual),
            "personalidad": calcular_personalidad(nombre_uso_actual),
        }

    return perfil


def es_lectura_vigente(lectura_generada_en, lectura_generada_para_anio, fecha_actualizacion, anio_actual=None):
    """
    Decide si la lectura cacheada (usuarios.lectura_texto) sigue siendo
    válida o hay que regenerarla. Dos condiciones de vencimiento
    independientes:
    1. El usuario actualizó sus datos DESPUÉS de que se generó la
       lectura (fecha_actualizacion > lectura_generada_en).
    2. Cambió el año calendario desde que se generó (el Año Personal ya
       no es el mismo), a diferencia del plan_texto del bot de running,
       que solo vence por cambio de datos.
    Si falta cualquiera de los tres primeros valores (nunca se generó
    una lectura todavía), no es vigente.
    """
    if not lectura_generada_en or not lectura_generada_para_anio:
        return False
    anio_actual = anio_actual if anio_actual is not None else date.today().year
    if lectura_generada_para_anio != anio_actual:
        return False
    if fecha_actualizacion and fecha_actualizacion > lectura_generada_en:
        return False
    return True
