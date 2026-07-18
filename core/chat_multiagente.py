"""
chat_multiagente.py — Despachador multiagente para el chat de Atenea Lab Desk.

Provee una función por proveedor de IA (Claude, Gemini, DeepSeek) y una función
despachadora unificada `generar_respuesta_chat(model, messages)` que decide cuál
invocar según el modelo solicitado.

Patrón consistente con abogado_stps.py: clientes inicializados al importar,
API keys desde variables de entorno, logging estructurado.
"""

import os
import time
import logging
from typing import Dict, List, Any

import anthropic
from google import genai
from openai import OpenAI

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE MODELOS (modelos ya validados en el proyecto)
# ═══════════════════════════════════════════════════════════════════════════

# Claude: modelo conversacional más capaz que Haiku (uso Premium)
# No modificamos MODELO_HAIKU de main.py — este es un modelo distinto para chat
MODELO_CLAUDE_CHAT = "claude-sonnet-4-6"

# Gemini: mismo modelo validado en abogado_stps.py (gemini-2.5-flash)
MODELO_GEMINI_CHAT = "gemini-2.5-flash"

# DeepSeek: modelo conversacional estándar
MODELO_DEEPSEEK_CHAT = "deepseek-chat"

# ═══════════════════════════════════════════════════════════════════════════
# CLIENTES SINGLETON (patrón consistente con el proyecto)
# ═══════════════════════════════════════════════════════════════════════════

# Claude — mismo SDK que main.py
_cliente_anthropic: anthropic.Anthropic | None = None


def _get_cliente_anthropic() -> anthropic.Anthropic:
    global _cliente_anthropic
    if _cliente_anthropic is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY no configurada en variables de entorno")
        _cliente_anthropic = anthropic.Anthropic(api_key=api_key)
        logger.info("🤖 Cliente Anthropic (Claude) inicializado — modelo chat: %s", MODELO_CLAUDE_CHAT)
    return _cliente_anthropic


# Gemini — mismo SDK que abogado_stps.py (google-genai)
_cliente_gemini: genai.Client | None = None


def _get_cliente_gemini() -> genai.Client:
    global _cliente_gemini
    if _cliente_gemini is None:
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY no configurada en variables de entorno")
        # Detectar si es una key de Vertex AI Express (formato AQ.Ab8...) o API key clásica (AIzaSy...)
        if api_key.startswith("AQ."):
            # Vertex AI Express key — requiere vertexai=True
            _cliente_gemini = genai.Client(vertexai=True, api_key=api_key)
            logger.info("🔮 Cliente Gemini (Vertex AI Express) inicializado — modelo chat: %s", MODELO_GEMINI_CHAT)
        else:
            # API key clásica de AI Studio (AIzaSy...)
            _cliente_gemini = genai.Client(api_key=api_key)
            logger.info("🔮 Cliente Gemini (AI Studio) inicializado — modelo chat: %s", MODELO_GEMINI_CHAT)
    return _cliente_gemini


# DeepSeek — API compatible con OpenAI SDK
_cliente_deepseek: OpenAI | None = None


def _get_cliente_deepseek() -> OpenAI:
    global _cliente_deepseek
    if _cliente_deepseek is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY no configurada en variables de entorno")
        _cliente_deepseek = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        )
        logger.info("🧠 Cliente DeepSeek inicializado — modelo chat: %s", MODELO_DEEPSEEK_CHAT)
    return _cliente_deepseek


# ═══════════════════════════════════════════════════════════════════════════
# FUNCIONES POR PROVEEDOR
# ═══════════════════════════════════════════════════════════════════════════


async def llamar_claude(messages: List[Dict[str, str]], system_prompt: str = "") -> Dict[str, Any]:
    """
    Llama a Claude (Anthropic) para chat conversacional.

    Args:
        messages: Lista de mensajes en formato [{"role": "user"|"assistant", "content": "..."}]
        system_prompt: Instrucción de sistema opcional para contexto del asistente

    Returns:
        {
            "content": str,
            "model": str,
            "tokens_entrada": int,
            "tokens_salida": int,
            "costo_usd": float,
            "tiempo_s": float
        }
    """
    inicio = time.time()
    cliente = _get_cliente_anthropic()

    # Convertir mensajes al formato esperado por Anthropic
    anthropic_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
    ]

    kwargs = {
        "model": MODELO_CLAUDE_CHAT,
        "max_tokens": 2048,
        "temperature": 0.7,
        "messages": anthropic_messages,
    }
    if system_prompt:
        kwargs["system"] = system_prompt

    try:
        respuesta = cliente.messages.create(**kwargs)
        duracion = round(time.time() - inicio, 2)

        contenido = respuesta.content[0].text if respuesta.content else ""
        tokens_entrada = respuesta.usage.input_tokens
        tokens_salida = respuesta.usage.output_tokens

        # Costo estimado: Sonnet ~$3/$15 por 1M tokens (entrada/salida)
        costo = (tokens_entrada * 3 / 1_000_000) + (tokens_salida * 15 / 1_000_000)

        logger.info(
            "✅ Claude | %d in / %d out tokens | %.2fs | $%.6f USD",
            tokens_entrada, tokens_salida, duracion, costo,
        )

        return {
            "content": contenido,
            "model": MODELO_CLAUDE_CHAT,
            "tokens_entrada": tokens_entrada,
            "tokens_salida": tokens_salida,
            "costo_usd": round(costo, 6),
            "tiempo_s": duracion,
        }

    except anthropic.APIStatusError as e:
        logger.error("❌ Claude API error (status %s): %s", e.status_code, e.message)
        raise RuntimeError(f"Claude no disponible (HTTP {e.status_code}): {e.message}") from e
    except anthropic.APITimeoutError as e:
        logger.error("❌ Claude timeout: %s", e)
        raise RuntimeError("Claude agotó el tiempo de espera. Intenta de nuevo.") from e
    except anthropic.APIConnectionError as e:
        logger.error("❌ Claude connection error: %s", e)
        raise RuntimeError("No se pudo conectar con Claude. Revisa tu conexión.") from e


async def llamar_gemini(messages: List[Dict[str, str]], system_prompt: str = "") -> Dict[str, Any]:
    """
    Llama a Gemini (Google) para chat conversacional.

    Args:
        messages: Lista de mensajes en formato [{"role": "user"|"assistant", "content": "..."}]
        system_prompt: Instrucción de sistema opcional para contexto del asistente

    Returns:
        {
            "content": str,
            "model": str,
            "tokens_entrada": int,
            "tokens_salida": int,
            "costo_usd": float,
            "tiempo_s": float
        }
    """
    inicio = time.time()
    cliente = _get_cliente_gemini()

    # Construir el prompt como texto estructurado (Gemini no tiene sistema de roles nativo como Anthropic)
    partes = []
    if system_prompt:
        partes.append(f"[Instrucciones del sistema]\n{system_prompt}\n")

    for m in messages:
        role_label = "Usuario" if m["role"] == "user" else "Asistente"
        partes.append(f"[{role_label}]\n{m['content']}")

    prompt_completo = "\n\n".join(partes)

    try:
        response = cliente.models.generate_content(
            model=MODELO_GEMINI_CHAT,
            contents=prompt_completo,
        )

        duracion = round(time.time() - inicio, 2)

        contenido = response.text if response.text else ""
        tokens_entrada = response.usage_metadata.prompt_token_count if response.usage_metadata else 0
        tokens_salida = response.usage_metadata.candidates_token_count if response.usage_metadata else 0

        # Costo estimado: Gemini Flash ~$0.15/$0.60 por 1M tokens (entrada/salida)
        costo = (tokens_entrada * 0.15 / 1_000_000) + (tokens_salida * 0.60 / 1_000_000)

        logger.info(
            "✅ Gemini | %d in / %d out tokens | %.2fs | $%.6f USD",
            tokens_entrada, tokens_salida, duracion, costo,
        )

        return {
            "content": contenido,
            "model": MODELO_GEMINI_CHAT,
            "tokens_entrada": tokens_entrada,
            "tokens_salida": tokens_salida,
            "costo_usd": round(costo, 6),
            "tiempo_s": duracion,
        }

    except Exception as e:
        error_msg = str(e).lower()
        if "429" in error_msg or "quota" in error_msg or "rate" in error_msg:
            logger.error("❌ Gemini rate limit: %s", e)
            raise RuntimeError("Gemini: límite de cuota alcanzado. Intenta de nuevo en unos segundos.") from e
        elif "timeout" in error_msg or "timed out" in error_msg:
            logger.error("❌ Gemini timeout: %s", e)
            raise RuntimeError("Gemini agotó el tiempo de espera.") from e
        else:
            logger.error("❌ Gemini error: %s", e)
            raise RuntimeError(f"Gemini no disponible: {e}") from e


async def llamar_deepseek(messages: List[Dict[str, str]], system_prompt: str = "") -> Dict[str, Any]:
    """
    Llama a DeepSeek vía API compatible con OpenAI SDK.

    Args:
        messages: Lista de mensajes en formato [{"role": "user"|"assistant", "content": "..."}]
        system_prompt: Instrucción de sistema opcional para contexto del asistente

    Returns:
        {
            "content": str,
            "model": str,
            "tokens_entrada": int,
            "tokens_salida": int,
            "costo_usd": float,
            "tiempo_s": float
        }
    """
    inicio = time.time()
    cliente = _get_cliente_deepseek()

    # Construir mensajes en formato OpenAI (DeepSeek compatible)
    openai_messages = []
    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})
    for m in messages:
        openai_messages.append({"role": m["role"], "content": m["content"]})

    try:
        response = cliente.chat.completions.create(
            model=MODELO_DEEPSEEK_CHAT,
            messages=openai_messages,
            max_tokens=2048,
            temperature=0.7,
        )

        duracion = round(time.time() - inicio, 2)

        choice = response.choices[0]
        contenido = choice.message.content if choice.message.content else ""
        tokens_entrada = response.usage.prompt_tokens if response.usage else 0
        tokens_salida = response.usage.completion_tokens if response.usage else 0

        # Costo estimado: DeepSeek ~$0.14/$0.28 por 1M tokens (entrada/salida)
        costo = (tokens_entrada * 0.14 / 1_000_000) + (tokens_salida * 0.28 / 1_000_000)

        logger.info(
            "✅ DeepSeek | %d in / %d out tokens | %.2fs | $%.6f USD",
            tokens_entrada, tokens_salida, duracion, costo,
        )

        return {
            "content": contenido,
            "model": MODELO_DEEPSEEK_CHAT,
            "tokens_entrada": tokens_entrada,
            "tokens_salida": tokens_salida,
            "costo_usd": round(costo, 6),
            "tiempo_s": duracion,
        }

    except Exception as e:
        error_msg = str(e).lower()
        if "429" in error_msg or "rate" in error_msg:
            logger.error("❌ DeepSeek rate limit: %s", e)
            raise RuntimeError("DeepSeek: límite de cuota alcanzado.") from e
        elif "timeout" in error_msg or "timed out" in error_msg:
            logger.error("❌ DeepSeek timeout: %s", e)
            raise RuntimeError("DeepSeek agotó el tiempo de espera.") from e
        elif "insufficient" in error_msg or "balance" in error_msg:
            logger.error("❌ DeepSeek saldo insuficiente: %s", e)
            raise RuntimeError("DeepSeek: saldo insuficiente en la cuenta.") from e
        else:
            logger.error("❌ DeepSeek error: %s", e)
            raise RuntimeError(f"DeepSeek no disponible: {e}") from e


# ═══════════════════════════════════════════════════════════════════════════
# DESPACHADOR UNIFICADO
# ═══════════════════════════════════════════════════════════════════════════

# GLM y Hunyuan van por OpenRouter
from agents_config import call_open_router, PROVIDER_CONFIG

MODELOS_VALIDOS = {
    "claude": (llamar_claude, MODELO_CLAUDE_CHAT),
    "gemini": (llamar_gemini, MODELO_GEMINI_CHAT),
    "deepseek": (llamar_deepseek, MODELO_DEEPSEEK_CHAT),
    "glm": (None, PROVIDER_CONFIG["glm"]["model_name"]),      # OpenRouter
    "hunyuan": (None, PROVIDER_CONFIG["hunyuan"]["model_name"]),  # OpenRouter
}


async def generar_respuesta_chat(
    model: str,
    messages: List[Dict[str, str]],
    system_prompt: str = "",
) -> Dict[str, Any]:
    """
    Despachador unificado: selecciona el proveedor según el modelo solicitado
    y retorna la respuesta estandarizada.

    Args:
        model: "claude", "gemini", o "deepseek"
        messages: Lista de mensajes [{"role": "user"|"assistant", "content": "..."}]
        system_prompt: Instrucción de sistema opcional

    Returns:
        {
            "content": str,
            "model": str,
            "tokens_entrada": int,
            "tokens_salida": int,
            "costo_usd": float,
            "tiempo_s": float
        }

    Raises:
        ValueError: Si el modelo no es válido
        RuntimeError: Si el proveedor falla
    """
    modelo_lower = model.lower().strip()
    if modelo_lower not in MODELOS_VALIDOS:
        validos = ", ".join(MODELOS_VALIDOS.keys())
        raise ValueError(f"Modelo '{model}' no válido. Opciones: {validos}")

    funcion, nombre_modelo = MODELOS_VALIDOS[modelo_lower]
    logger.info("📤 Despachando chat → %s (%s)", modelo_lower, nombre_modelo)

    # Si es GLM o Hunyuan, usar OpenRouter
    if modelo_lower in ("glm", "hunyuan"):
        resultado = await call_open_router(nombre_modelo, messages, system_prompt)
    else:
        resultado = await funcion(messages, system_prompt)

    resultado["model"] = nombre_modelo
    return resultado
