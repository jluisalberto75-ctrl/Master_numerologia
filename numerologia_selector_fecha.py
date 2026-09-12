"""
Selector de fecha de nacimiento sin texto libre para día/mes, pensado
para que sea físicamente imposible que el usuario arme una fecha
inválida o ambigua:

- El AÑO se pide como texto porque es la única parte donde un número de
  4 dígitos no tiene "orden" que confundir (nadie escribe el año al
  revés). Se valida que esté en un rango de vida humana razonable.
- El MES se elige con botones con el NOMBRE (Enero, Febrero...), nunca
  con el número — así se elimina de raíz la ambigüedad clásica de
  '08/03' (¿8 de marzo o 3 de agosto?).
- El DÍA se elige con botones, pero generados dinámicamente según el mes
  y el año ya elegidos: solo se muestran los días que existen de
  verdad. calendar.monthrange() ya resuelve años bisiestos, así que
  nunca se ofrece un 30 de febrero ni un 31 de abril como opción.

Este módulo solo construye teclados y valida/parsea — no sabe nada de
Telegram Application ni de estados de conversación. Eso vive en el
bot, igual que teclados.py en el bot de running.
"""

import calendar
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

MESES = [
    (1, "Enero"), (2, "Febrero"), (3, "Marzo"), (4, "Abril"),
    (5, "Mayo"), (6, "Junio"), (7, "Julio"), (8, "Agosto"),
    (9, "Septiembre"), (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre"),
]

# Prefijos de callback_data, para no chocar con otros botones inline que
# el bot pueda tener más adelante (ej. selección de metodología, menús).
PREFIJO_MES = "sf_mes_"
PREFIJO_DIA = "sf_dia_"

EDAD_MINIMA = 5
EDAD_MAXIMA = 120


def validar_anio_nacimiento(texto: str):
    """
    Valida el año escrito como texto libre. Devuelve el año (int) si es
    válido, o None si no lo es (para que el handler del bot decida qué
    mensaje de error mostrar). Rango: entre EDAD_MAXIMA y EDAD_MINIMA
    años de vida respecto a hoy, para filtrar años imposibles (ej. '3000'
    o '1850') sin ser demasiado restrictivo con casos reales.
    """
    texto = texto.strip()
    if not texto.isdigit() or len(texto) != 4:
        return None
    anio = int(texto)
    anio_actual = date.today().year
    if anio_actual - EDAD_MAXIMA <= anio <= anio_actual - EDAD_MINIMA:
        return anio
    return None


def construir_teclado_meses() -> InlineKeyboardMarkup:
    """Teclado de 12 botones con el NOMBRE del mes (nunca el número)."""
    filas = []
    fila_actual = []
    for numero, nombre in MESES:
        fila_actual.append(
            InlineKeyboardButton(nombre, callback_data=f"{PREFIJO_MES}{numero}")
        )
        if len(fila_actual) == 3:
            filas.append(fila_actual)
            fila_actual = []
    if fila_actual:
        filas.append(fila_actual)
    return InlineKeyboardMarkup(filas)


def construir_teclado_dias(mes: int, anio: int) -> InlineKeyboardMarkup:
    """
    Teclado con solo los días que existen de verdad para ese mes/año.
    calendar.monthrange(anio, mes) devuelve (día de la semana del día 1,
    cantidad de días del mes) — la segunda parte ya tiene en cuenta años
    bisiestos, así que un 30 de febrero o un 31 de abril nunca aparecen
    como opción.
    """
    _, dias_en_mes = calendar.monthrange(anio, mes)
    filas = []
    fila_actual = []
    for dia in range(1, dias_en_mes + 1):
        fila_actual.append(
            InlineKeyboardButton(str(dia), callback_data=f"{PREFIJO_DIA}{dia}")
        )
        if len(fila_actual) == 7:
            filas.append(fila_actual)
            fila_actual = []
    if fila_actual:
        filas.append(fila_actual)
    return InlineKeyboardMarkup(filas)


def parsear_mes_callback(callback_data: str):
    """callback_data -> número de mes (int), o None si no matchea el prefijo."""
    if not callback_data.startswith(PREFIJO_MES):
        return None
    return int(callback_data[len(PREFIJO_MES):])


def parsear_dia_callback(callback_data: str):
    """callback_data -> número de día (int), o None si no matchea el prefijo."""
    if not callback_data.startswith(PREFIJO_DIA):
        return None
    return int(callback_data[len(PREFIJO_DIA):])


def nombre_mes(numero_mes: int) -> str:
    return dict(MESES)[numero_mes]


def construir_fecha_iso(dia: int, mes: int, anio: int) -> str:
    """(dia, mes, anio) -> 'YYYY-MM-DD', el formato en el que se guarda en la base de datos."""
    return f"{anio:04d}-{mes:02d}-{dia:02d}"
