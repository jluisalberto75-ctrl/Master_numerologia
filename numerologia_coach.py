import os
import json
import logging
from openai import OpenAI

from numerologia_prompt import (
    SYSTEM_PROMPT,
    construir_mensaje_usuario,
    construir_mensaje_lectura_completa,
    construir_mensaje_compatibilidad,
)

logger = logging.getLogger(__name__)

MODELO = "gpt-4o-mini"

_client = None  # se crea perezosamente, ver _obtener_cliente()


def _api_configurada() -> bool:
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY no está configurada en el entorno.")
        return False
    return True


def _obtener_cliente():
    """
    Crea el cliente de OpenAI solo la primera vez que hace falta, y solo
    después de confirmar que la clave existe. Si se crea a nivel de
    módulo (como estaba en ia_coach.py del bot de running), el proceso
    entero revienta al importar el archivo cuando falta la variable de
    entorno, ANTES de que _api_configurada() tenga oportunidad de dar un
    mensaje de error controlado.
    """
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def _llamar_ia(mensaje_usuario: str, max_tokens: int):
    """
    Punto único de llamada a la API, para no repetir el try/except y el
    manejo de errores en cada función pública de este módulo.
    """
    response = _obtener_cliente().chat.completions.create(
        model=MODELO,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": mensaje_usuario},
        ],
        temperature=0.7,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


def pedir_respuesta_maestro(contexto: dict, pregunta_usuario: str):
    """
    Genera una respuesta del maestro para la conversación abierta
    ("Pregúntale al maestro"), usando el contexto completo del usuario.
    """
    if not contexto:
        return "No tengo tu perfil todavía. Escribe /start para hacer el registro primero."

    if not _api_configurada():
        return (
            "Tengo un problema de configuración de mi lado (falta la clave de "
            "IA). Avísale a mi administrador, por favor."
        )

    contexto_json = json.dumps(contexto, ensure_ascii=False)
    mensaje = construir_mensaje_usuario(contexto_json, pregunta_usuario)

    try:
        return _llamar_ia(mensaje, max_tokens=800)
    except Exception:
        logger.exception("Error llamando a la IA en pedir_respuesta_maestro")
        return (
            "Tuve un problema procesando tu pregunta (puede ser un límite de "
            "uso de la IA o un error temporal). Intenta de nuevo en un momento."
        )


def pedir_lectura_completa(contexto: dict):
    """
    Genera la lectura numerológica completa inicial, para cachear en
    usuarios.lectura_texto. Devuelve None si falla (el llamador decide
    qué mostrar en ese caso, igual que pedir_plan_inicial en el bot de
    running).
    """
    if not contexto:
        return None

    if not _api_configurada():
        return None

    contexto_json = json.dumps(contexto, ensure_ascii=False)
    mensaje = construir_mensaje_lectura_completa(contexto_json)

    try:
        return _llamar_ia(mensaje, max_tokens=1500)
    except Exception:
        logger.exception("Error llamando a la IA en pedir_lectura_completa")
        return None


def pedir_interpretacion_compatibilidad(
    contexto: dict, nombre_otra_persona: str, camino_vida_otra_persona: int, numero_compatibilidad: int
):
    """
    Genera la interpretación de una compatibilidad ya calculada (el
    número de compatibilidad y el camino de vida de la otra persona
    vienen resueltos desde numerologia_calculo.py, nunca los calcula la
    IA).
    """
    if not contexto:
        return None

    if not _api_configurada():
        return (
            "Tengo un problema de configuración de mi lado (falta la clave de "
            "IA). Avísale a mi administrador, por favor."
        )

    contexto_json = json.dumps(contexto, ensure_ascii=False)
    datos_otra_persona = json.dumps(
        {
            "nombre": nombre_otra_persona,
            "camino_vida": camino_vida_otra_persona,
            "numero_compatibilidad": numero_compatibilidad,
        },
        ensure_ascii=False,
    )
    mensaje = construir_mensaje_compatibilidad(contexto_json, datos_otra_persona)

    try:
        return _llamar_ia(mensaje, max_tokens=800)
    except Exception:
        logger.exception("Error llamando a la IA en pedir_interpretacion_compatibilidad")
        return (
            "Tuve un problema generando esa interpretación. Intenta de nuevo "
            "en un momento."
        )
