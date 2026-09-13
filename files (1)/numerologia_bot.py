import os
import sqlite3
import logging
from datetime import datetime, date, time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from numerologia_db import DB_PATH, iniciar_db
from numerologia_contexto import obtener_contexto_numerologico
from numerologia_calculo import (
    calcular_camino_vida,
    calcular_numero_compatibilidad,
    calcular_numero_del_dia,
    parsear_fecha_iso,
)
from numerologia_coach import pedir_respuesta_maestro, pedir_lectura_completa, pedir_interpretacion_compatibilidad
from numerologia_selector_fecha import (
    validar_anio_nacimiento,
    construir_teclado_meses,
    construir_teclado_dias,
    parsear_mes_callback,
    parsear_dia_callback,
    nombre_mes,
    construir_fecha_iso,
    PREFIJO_MES,
    PREFIJO_DIA,
)

load_dotenv()
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "No se encontró TELEGRAM_BOT_TOKEN. "
        "Crea un archivo .env con la línea: TELEGRAM_BOT_TOKEN=tu_token_aqui"
    )

# Zona horaria para el envío diario del número del día. Cámbiala si el
# bot corre pensando en usuarios de otro país (ver nota en 'Mi evolución'
# / fases futuras sobre zona horaria por usuario, todavía no implementada).
ZONA_HORARIA = ZoneInfo("America/Bogota")
HORA_NUMERO_DIA = time(hour=7, minute=0, tzinfo=ZONA_HORARIA)

# Interpretación fija y breve por dígito del Día Personal (1-9). Deliberadamente
# NO se llama a la IA para el envío push diario: sería una llamada pagada
# por cada usuario, cada día, sin que nadie la haya pedido explícitamente
# — mismo criterio que 'recordatorio_diario' en el bot de running. Si el
# usuario quiere profundizar, puede preguntarle al maestro directamente.
SIGNIFICADOS_NUMERO_DIA = {
    1: "Un día para iniciar, tomar la delantera y no esperar a que otros decidan por ti.",
    2: "Un día para la calma, la escucha y trabajar de a dos en vez de forzar todo solo/a.",
    3: "Un día con energía expresiva y social — buen momento para comunicar algo que traías guardado.",
    4: "Un día de orden y trabajo de base — lo que construyas hoy con disciplina, rinde después.",
    5: "Un día de movimiento e imprevistos — flexibilidad antes que rigidez en el plan.",
    6: "Un día orientado a vínculos cercanos y responsabilidades afectivas — el hogar pide atención.",
    7: "Un día para pausar, observar y no apurar respuestas — introspección antes que acción.",
    8: "Un día de poder personal y temas prácticos — buen momento para gestiones y decisiones concretas.",
    9: "Un día de cierre — soltar algo que ya cumplió su ciclo, antes de empezar algo nuevo.",
}


# ---------- Acceso a datos ----------
# Mismo criterio que bot_v6.py: consultas directas acá, sin capa extra de
# repositorio, porque son pocas y triviales. Todo lo que sí necesita
# lógica (cálculo, ensamblado de contexto) ya vive en sus propios módulos.

def obtener_usuario(telegram_id):
    conexion = sqlite3.connect(DB_PATH)
    conexion.row_factory = sqlite3.Row
    cursor = conexion.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE telegram_id = ?", (telegram_id,))
    fila = cursor.fetchone()
    conexion.close()
    return dict(fila) if fila else None


def guardar_perfil_basico(telegram_id, nombre_completo, fecha_nacimiento_iso):
    ahora = datetime.now().isoformat()
    conexion = sqlite3.connect(DB_PATH)
    cursor = conexion.cursor()
    cursor.execute(
        """
        INSERT INTO usuarios (telegram_id, nombre_completo, fecha_nacimiento, fecha_registro, fecha_actualizacion)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            nombre_completo=excluded.nombre_completo,
            fecha_nacimiento=excluded.fecha_nacimiento,
            fecha_actualizacion=excluded.fecha_actualizacion
        """,
        (telegram_id, nombre_completo, fecha_nacimiento_iso, ahora, ahora),
    )
    conexion.commit()
    conexion.close()


def guardar_lectura(telegram_id, texto, anio):
    ahora = datetime.now().isoformat()
    conexion = sqlite3.connect(DB_PATH)
    cursor = conexion.cursor()
    cursor.execute(
        "UPDATE usuarios SET lectura_texto = ?, lectura_generada_en = ?, "
        "lectura_generada_para_anio = ? WHERE telegram_id = ?",
        (texto, ahora, anio, telegram_id),
    )
    conexion.commit()
    conexion.close()


def guardar_compatibilidad(telegram_id, nombre_otra_persona, fecha_otra_persona_iso, numero_compatibilidad):
    conexion = sqlite3.connect(DB_PATH)
    cursor = conexion.cursor()
    cursor.execute(
        """
        INSERT INTO compatibilidades
            (telegram_id, nombre_otra_persona, fecha_nacimiento_otra_persona, numero_compatibilidad, fecha_consulta)
        VALUES (?, ?, ?, ?, ?)
        """,
        (telegram_id, nombre_otra_persona, fecha_otra_persona_iso, numero_compatibilidad, datetime.now().isoformat()),
    )
    conexion.commit()
    conexion.close()


def obtener_usuarios_con_perfil_completo():
    """
    Devuelve [(telegram_id, nombre_completo, fecha_nacimiento), ...] de
    todos los usuarios que ya completaron el registro. Se usa para el
    envío diario del número del día — a diferencia del bot de running,
    acá no filtramos por 'día preferido' porque el número del día aplica
    todos los días, no solo días de entrenamiento.
    """
    conexion = sqlite3.connect(DB_PATH)
    cursor = conexion.cursor()
    cursor.execute(
        "SELECT telegram_id, nombre_completo, fecha_nacimiento FROM usuarios "
        "WHERE nombre_completo IS NOT NULL AND fecha_nacimiento IS NOT NULL"
    )
    filas = cursor.fetchall()
    conexion.close()
    return filas


def dividir_mensaje_largo(texto, limite=3500):
    """Telegram no acepta mensajes de más de 4096 caracteres; parte en saltos de línea cuando puede."""
    if len(texto) <= limite:
        return [texto]
    partes = []
    resto = texto
    while len(resto) > limite:
        corte = resto.rfind("\n\n", 0, limite)
        if corte == -1:
            corte = resto.rfind("\n", 0, limite)
        if corte == -1:
            corte = limite
        partes.append(resto[:corte].strip())
        resto = resto[corte:].strip()
    if resto:
        partes.append(resto)
    return partes


async def enviar_mensaje_largo(chat_id, texto, context: ContextTypes.DEFAULT_TYPE, reply_markup=None):
    partes = dividir_mensaje_largo(texto)
    for i, parte in enumerate(partes):
        es_ultima = i == len(partes) - 1
        await context.bot.send_message(
            chat_id=chat_id, text=parte, reply_markup=reply_markup if es_ultima else None
        )


# ---------- Menú principal persistente ----------
BTN_MIS_NUMEROS = "🔢 Mis números"
BTN_MI_ANIO = "📅 Mi año"
BTN_NUMERO_DIA = "☀️ Mi número de hoy"
BTN_COMPATIBILIDAD = "❤️ Compatibilidad"
BTN_ACTUALIZAR = "⚙️ Actualizar mis datos"


def teclado_principal():
    return ReplyKeyboardMarkup(
        [[BTN_MIS_NUMEROS, BTN_NUMERO_DIA], [BTN_MI_ANIO, BTN_COMPATIBILIDAD], [BTN_ACTUALIZAR]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def construir_texto_numero_dia(nombre_completo: str, dia_personal: int) -> str:
    """
    Arma el texto fijo (sin IA) del número del día. Función compartida
    entre el job diario y el botón bajo demanda, para no repetir el
    formato en dos lugares.
    """
    significado = SIGNIFICADOS_NUMERO_DIA.get(dia_personal, "")
    return (
        f"☀️ {nombre_completo}, tu número personal de hoy es el {dia_personal}.\n\n"
        f"{significado}\n\n"
        "Si quieres que el maestro lo conecte con algo puntual de tu día "
        "(trabajo, una relación, una decisión), solo pregúntale."
    )


# ---------- Estados de la encuesta (registro) ----------
NOMBRE_COMPLETO, ANIO_NACIMIENTO, MES_NACIMIENTO, DIA_NACIMIENTO = range(4)

# ---------- Estados del flujo de compatibilidad ----------
COMPAT_NOMBRE, COMPAT_ANIO, COMPAT_MES, COMPAT_DIA = range(50, 54)


# ============================================================
# === REGISTRO ===
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    perfil = obtener_usuario(update.effective_user.id)

    if perfil and perfil.get("nombre_completo") and perfil.get("fecha_nacimiento"):
        await update.message.reply_text(
            f"¡Hola de nuevo, {perfil['nombre_completo']}! 👋 Ya tengo tu perfil.\n"
            "¿Qué quieres hacer?",
            reply_markup=teclado_principal(),
        )
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "🔮 Hola. Soy tu guía de numerología.\n"
        "Solo necesito dos cosas para armar tu perfil: tu nombre completo "
        "y tu fecha de nacimiento.\n\n"
        "¿Cómo te llamas? (nombre completo, con apellidos)"
    )
    return NOMBRE_COMPLETO


async def recibir_nombre_completo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if len(texto) < 3:
        await update.message.reply_text("Escribe tu nombre completo, con apellidos.")
        return NOMBRE_COMPLETO
    context.user_data["nombre_completo"] = texto
    await update.message.reply_text("¿En qué año naciste? (ej: 1994)")
    return ANIO_NACIMIENTO


async def recibir_anio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    anio = validar_anio_nacimiento(update.message.text)
    if anio is None:
        await update.message.reply_text(
            "Escribe solo el año, con 4 dígitos (ej: 1994). Tiene que ser un año real de nacimiento."
        )
        return ANIO_NACIMIENTO
    context.user_data["anio_nacimiento"] = anio
    await update.message.reply_text(
        "Ahora el mes:", reply_markup=construir_teclado_meses()
    )
    return MES_NACIMIENTO


async def recibir_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mes = parsear_mes_callback(query.data)
    context.user_data["mes_nacimiento"] = mes
    anio = context.user_data["anio_nacimiento"]
    await query.edit_message_text(f"Mes: {nombre_mes(mes)}. Ahora el día:")
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Elige el día:",
        reply_markup=construir_teclado_dias(mes, anio),
    )
    return DIA_NACIMIENTO


async def recibir_dia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dia = parsear_dia_callback(query.data)
    anio = context.user_data["anio_nacimiento"]
    mes = context.user_data["mes_nacimiento"]
    nombre_completo = context.user_data["nombre_completo"]
    fecha_iso = construir_fecha_iso(dia, mes, anio)

    await query.edit_message_text(f"Día: {dia} de {nombre_mes(mes)} de {anio}. ¡Listo! 🎉")

    telegram_id = update.effective_user.id
    guardar_perfil_basico(telegram_id, nombre_completo, fecha_iso)

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Dame un momento para armar tu lectura numerológica completa...",
    )
    await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")

    anio_actual = date.today().year
    contexto = obtener_contexto_numerologico(telegram_id, anio=anio_actual)
    lectura = pedir_lectura_completa(contexto)

    if lectura:
        guardar_lectura(telegram_id, lectura, anio_actual)
        await enviar_mensaje_largo(query.message.chat_id, lectura, context)
    else:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Tuve un problema generando tu lectura. Puedes pedirla de nuevo con "
            f"'{BTN_MIS_NUMEROS}' en el menú.",
        )

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Usa el menú de abajo cuando quieras. 🔮",
        reply_markup=teclado_principal(),
    )
    return ConversationHandler.END


async def iniciar_actualizacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Vamos a actualizar tu perfil. ¿Cómo te llamas? (nombre completo)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return NOMBRE_COMPLETO


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Cancelado. Escribe /start para volver a intentarlo.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ============================================================
# === MENÚ: MIS NÚMEROS / MI AÑO ===
# ============================================================

async def mostrar_mis_numeros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    perfil = obtener_usuario(telegram_id)
    if not perfil or not perfil.get("nombre_completo"):
        await update.message.reply_text("Todavía no tengo tu perfil. Escribe /start para registrarte.")
        return

    anio_actual = date.today().year
    contexto = obtener_contexto_numerologico(telegram_id, anio=anio_actual)

    if contexto["lectura_cacheada"]["vigente"]:
        await enviar_mensaje_largo(
            update.effective_chat.id, contexto["lectura_cacheada"]["texto"], context, reply_markup=teclado_principal()
        )
        return

    await update.message.chat.send_action(action="typing")
    lectura = pedir_lectura_completa(contexto)
    if lectura:
        guardar_lectura(telegram_id, lectura, anio_actual)
        await enviar_mensaje_largo(update.effective_chat.id, lectura, context, reply_markup=teclado_principal())
    else:
        await update.message.reply_text(
            "Tuve un problema generando tu lectura. Intenta de nuevo en un momento.",
            reply_markup=teclado_principal(),
        )


async def mostrar_mi_anio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    contexto = obtener_contexto_numerologico(telegram_id, anio=date.today().year)
    if not contexto:
        await update.message.reply_text("Todavía no tengo tu perfil. Escribe /start para registrarte.")
        return

    await update.message.chat.send_action(action="typing")
    respuesta = pedir_respuesta_maestro(
        contexto,
        "Interpreta en profundidad mi Año Personal actual (anio_personal) y qué "
        "tipo de energía suele traer un ciclo con ese número.",
    )
    await enviar_mensaje_largo(update.effective_chat.id, respuesta, context, reply_markup=teclado_principal())


async def mostrar_numero_dia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Versión bajo demanda del número del día (botón del menú) — mismo
    cálculo y mismo texto fijo que usa el envío automático, sin llamar a
    la IA. Así el usuario puede consultarlo cualquier día sin esperar al
    push de la mañana.
    """
    telegram_id = update.effective_user.id
    perfil = obtener_usuario(telegram_id)
    if not perfil or not perfil.get("fecha_nacimiento"):
        await update.message.reply_text("Todavía no tengo tu perfil. Escribe /start para registrarte.")
        return

    dia, mes, _anio = parsear_fecha_iso(perfil["fecha_nacimiento"])
    cascada = calcular_numero_del_dia(dia, mes)
    texto = construir_texto_numero_dia(perfil["nombre_completo"], cascada["dia_personal"])
    await update.message.reply_text(texto, reply_markup=teclado_principal())


async def numero_del_dia_diario(context: ContextTypes.DEFAULT_TYPE):
    """
    Job programado: le manda a cada usuario con perfil completo su
    número personal del día. Sin IA a propósito (ver comentario de
    SIGNIFICADOS_NUMERO_DIA) — mismo criterio que recordatorio_diario en
    el bot de running.
    """
    usuarios = obtener_usuarios_con_perfil_completo()
    for telegram_id, nombre_completo, fecha_nacimiento in usuarios:
        try:
            dia, mes, _anio = parsear_fecha_iso(fecha_nacimiento)
            cascada = calcular_numero_del_dia(dia, mes)
            texto = construir_texto_numero_dia(nombre_completo, cascada["dia_personal"])
            await context.bot.send_message(chat_id=telegram_id, text=texto)
        except Exception as error:
            # Un usuario bloqueó el bot, borró el chat, etc. No debe
            # frenar el envío a los demás.
            print(f"[bot] No se pudo enviar el número del día a {telegram_id}: {error}")


# ============================================================
# === COMPATIBILIDAD ===
# ============================================================

async def iniciar_compatibilidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    perfil = obtener_usuario(update.effective_user.id)
    if not perfil or not perfil.get("nombre_completo"):
        await update.message.reply_text("Todavía no tengo tu perfil. Escribe /start para registrarte.")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "💑 Vamos a ver la compatibilidad. ¿Cómo se llama la otra persona? (nombre completo)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return COMPAT_NOMBRE


async def recibir_nombre_otra_persona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if len(texto) < 3:
        await update.message.reply_text("Escribe el nombre completo de la otra persona.")
        return COMPAT_NOMBRE
    context.user_data["nombre_otra_persona"] = texto
    await update.message.reply_text(f"¿En qué año nació {texto}?")
    return COMPAT_ANIO


async def recibir_anio_otra_persona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    anio = validar_anio_nacimiento(update.message.text)
    if anio is None:
        await update.message.reply_text("Escribe solo el año, con 4 dígitos (ej: 1990).")
        return COMPAT_ANIO
    context.user_data["anio_otra_persona"] = anio
    await update.message.reply_text("Ahora el mes:", reply_markup=construir_teclado_meses())
    return COMPAT_MES


async def recibir_mes_otra_persona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mes = parsear_mes_callback(query.data)
    context.user_data["mes_otra_persona"] = mes
    anio = context.user_data["anio_otra_persona"]
    await query.edit_message_text(f"Mes: {nombre_mes(mes)}. Ahora el día:")
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Elige el día:",
        reply_markup=construir_teclado_dias(mes, anio),
    )
    return COMPAT_DIA


async def recibir_dia_otra_persona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dia = parsear_dia_callback(query.data)
    mes = context.user_data["mes_otra_persona"]
    anio = context.user_data["anio_otra_persona"]
    nombre_otra_persona = context.user_data["nombre_otra_persona"]
    fecha_otra_persona_iso = construir_fecha_iso(dia, mes, anio)

    await query.edit_message_text(f"Día: {dia} de {nombre_mes(mes)} de {anio}. Calculando... 🔮")

    telegram_id = update.effective_user.id
    usuario = obtener_usuario(telegram_id)
    dia_propio, mes_propio, anio_propio = parsear_fecha_iso(usuario["fecha_nacimiento"])

    numero_compatibilidad = calcular_numero_compatibilidad(
        dia_propio, mes_propio, anio_propio, dia, mes, anio
    )
    camino_vida_otra_persona = calcular_camino_vida(dia, mes, anio)

    guardar_compatibilidad(telegram_id, nombre_otra_persona, fecha_otra_persona_iso, numero_compatibilidad)

    await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
    contexto = obtener_contexto_numerologico(telegram_id, anio=date.today().year)
    respuesta = pedir_interpretacion_compatibilidad(
        contexto, nombre_otra_persona, camino_vida_otra_persona, numero_compatibilidad
    )

    if respuesta:
        await enviar_mensaje_largo(query.message.chat_id, respuesta, context, reply_markup=teclado_principal())
    else:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Tuve un problema generando la interpretación. Intenta de nuevo en un momento.",
            reply_markup=teclado_principal(),
        )
    return ConversationHandler.END


# ============================================================
# === CHAT ABIERTO: "Pregúntale al maestro" ===
# ============================================================

async def manejar_pregunta_maestro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    contexto = obtener_contexto_numerologico(telegram_id, anio=date.today().year)

    if contexto is None:
        await update.message.reply_text("Todavía no tengo tu perfil. Escribe /start para registrarte primero.")
        return

    await update.message.chat.send_action(action="typing")
    respuesta = pedir_respuesta_maestro(contexto, update.message.text)
    await enviar_mensaje_largo(update.effective_chat.id, respuesta, context, reply_markup=teclado_principal())


async def manejar_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Error no manejado", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Tuve un problema procesando eso. Intenta de nuevo en un momento, "
                "o escribe /start si el problema sigue."
            )
        except Exception:
            pass


# ============================================================
# === CONFIGURACIÓN DE LA APLICACIÓN ===
# ============================================================
# IMPORTANTE: nada de esto corre solo por importar el módulo (por eso
# vive dentro de main(), guardado detrás de "if __name__ == '__main__'").
# Con el bot de running, run_webhook() vivía suelto a nivel de módulo, lo
# que significa que CUALQUIER import del archivo (incluso solo para
# testear una función) levantaba el servidor. Acá se evita ese problema
# a propósito.

def construir_app():
    iniciar_db()
    app = Application.builder().token(TOKEN).build()

    registro = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(f"^{BTN_ACTUALIZAR}$"), iniciar_actualizacion),
        ],
        states={
            NOMBRE_COMPLETO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre_completo)],
            ANIO_NACIMIENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_anio)],
            MES_NACIMIENTO: [CallbackQueryHandler(recibir_mes, pattern=f"^{PREFIJO_MES}")],
            DIA_NACIMIENTO: [CallbackQueryHandler(recibir_dia, pattern=f"^{PREFIJO_DIA}")],
        },
        fallbacks=[CommandHandler("cancel", cancelar)],
    )

    compatibilidad = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_COMPATIBILIDAD}$"), iniciar_compatibilidad)],
        states={
            COMPAT_NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre_otra_persona)],
            COMPAT_ANIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_anio_otra_persona)],
            COMPAT_MES: [CallbackQueryHandler(recibir_mes_otra_persona, pattern=f"^{PREFIJO_MES}")],
            COMPAT_DIA: [CallbackQueryHandler(recibir_dia_otra_persona, pattern=f"^{PREFIJO_DIA}")],
        },
        fallbacks=[CommandHandler("cancel", cancelar)],
    )

    app.add_handler(registro)
    app.add_handler(compatibilidad)
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_MIS_NUMEROS}$"), mostrar_mis_numeros))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_MI_ANIO}$"), mostrar_mi_anio))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_NUMERO_DIA}$"), mostrar_numero_dia))
    # Cualquier otro texto se trata como pregunta para el maestro de IA
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_pregunta_maestro))
    app.add_error_handler(manejar_error)

    if app.job_queue is None:
        print(
            "⚠️  El envío diario del número del día está DESACTIVADO: falta la "
            "extensión job-queue. Instálala con:\n"
            '    pip install "python-telegram-bot[job-queue]"\n'
            "y vuelve a correr el bot."
        )
    else:
        app.job_queue.run_daily(
            numero_del_dia_diario,
            time=HORA_NUMERO_DIA,
            name="numero_del_dia_diario",
        )
        print(f"Número del día programado para las {HORA_NUMERO_DIA.strftime('%H:%M')} (hora Bogotá).")

    return app


def main():
    app = construir_app()

    # Render define automáticamente la variable de entorno RENDER=true en
    # todos sus servicios — la usamos para decidir solos si toca correr
    # con webhook (en Render) o con polling (en tu computador). Así no
    # hay que tocar el código al pasar de local a producción.
    if os.getenv("RENDER"):
        puerto = int(os.environ.get("PORT", 10000))
        # RENDER_EXTERNAL_URL también la pone Render sola, con la URL
        # pública real del servicio — a diferencia del bot de running,
        # acá no hay que copiar y pegar la URL a mano después de crear
        # el servicio.
        url_externa = os.getenv("RENDER_EXTERNAL_URL")
        if not url_externa:
            raise RuntimeError(
                "RENDER=true pero no se encontró RENDER_EXTERNAL_URL. "
                "Esto no debería pasar en un Web Service normal de Render — revisa la configuración del servicio."
            )
        print(f"🚀 Bot iniciado con WEBHOOK en el puerto {puerto}")
        print(f"📡 Webhook URL: {url_externa}/{TOKEN}")
        app.run_webhook(
            listen="0.0.0.0",
            port=puerto,
            url_path=TOKEN,
            webhook_url=f"{url_externa}/{TOKEN}",
        )
    else:
        print("🖥️  Corriendo en modo local (polling). Para producción en Render, esto cambia solo a webhook.")
        app.run_polling()


if __name__ == "__main__":
    main()
