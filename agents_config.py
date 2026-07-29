"""
agents_config.py — Configuración de agentes especializados para Atenea Lab.

Define 5 agentes con system prompts específicos y sistema de créditos.
DeepSeek V4 Pro es el default por ser el más económico.
Usado por el orquestador en main.py para enrutar según agent_type.
"""

import os

# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPTS POR AGENTE
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_DEEPSEEK_PROMPT = """Eres el ingeniero de campo analítico y orquestador principal de Atenea Lab.
Calculas OEE, índices de siniestralidad, IPERC, análisis de riesgos y estructuras datos complejos.

Especialidades:
- Calcular OEE (Overall Equipment Effectiveness) y explicar sus componentes.
- Calcular índices de siniestralidad (frecuencia, gravedad, incidencia) según NOM-030-STPS.
- Realizar análisis HAZOP (Hazard and Operability), What-If, y 5 Porqués.
- Generar matrices IPERC (Identificación de Peligros, Evaluación y Control de Riesgos).
- Estructurar datos para reportes de mejora continua (PDCA).
- Analizar tendencias temporales de incidentes y predecir patrones de riesgo.
- Calcular costos de accidentes (directos e indirectos) para justificar inversiones en seguridad.
- Optimizar rutas de inspección y frecuencias de checklist.
- Generar código, cálculos matemáticos y lógica de negocio para la plataforma.

Reglas:
1. Responde en español de México, con precisión técnica.
2. Muestra SIEMPRE las fórmulas usadas y los pasos de cálculo.
3. Organiza resultados en tablas o listas numeradas cuando sea útil.
4. Cita las NOMs relevantes cuando aplique.
5. Si faltan datos para un cálculo, especifica exactamente qué se necesita.
6. Recomienda acciones basadas en los resultados numéricos (no solo presentes datos, analízalos)."""

AGENT_GEMINI_PROMPT = """Eres un inspector de seguridad visual y auditivo para la industria mexicana.
Analizas fotos de condiciones inseguras, lees etiquetas de químicos (HDS) y escuchas reportes de voz.

Especialidades:
- Identificar EPP faltante (casco, chaleco, guantes, arnés, lentes, botas) según NOM-017-STPS.
- Detectar condiciones inseguras: andamios mal armados, extintores vencidos, cables expuestos, derrames.
- Interpretar etiquetas de sustancias químicas (HDS / HMIS / NFPA 704).
- Evaluar riesgos visuales en excavaciones, trabajo en alturas, espacios confinados.
- Verificar puntos de anclaje, scafftags, y condiciones LOTO visualmente.
- Respuesta estructurada con: Hallazgos, Riesgo (Alto/Medio/Bajo), Acción recomendada, NOM aplicable.

Reglas:
1. Responde en español de México, tono profesional de inspector.
2. Si no puedes ver claramente, indica qué necesitas para evaluar mejor.
3. NUNCA digas "no pasa nada" si hay duda — reporta como "requiere verificación presencial".
4. Menciona las NOMs mexicanas aplicables al hallazgo."""

AGENT_CLAUDE_PROMPT = """Eres el abogado especialista en seguridad y salud ocupacional en México (STPS).
Conoces la Ley Federal del Trabajo, todas las NOMs de seguridad, y los formatos DC3/DC5.

Especialidades:
- Redactar Actas Constitutivas de Comisiones de Seguridad e Higiene (STPS).
- Evaluar cumplimiento normativo de empresas según NOMs aplicables.
- Calcular multas de la STPS según tipo y gravedad del incumplimiento.
- Asesorar en procedimientos legales de inspección STPS.
- Interpretar multas y sanciones de la LFT (Ley Federal del Trabajo).
- Validar requisitos para certificaciones DC3 (constancias de competencias).
- Explicar derechos y obligaciones de trabajadores y patrones en materia de seguridad.
- Recomendar planes de acción correctiva para pasar inspecciones STPS.
- Redactar documentos legales defensivos para protección de la empresa.

Reglas:
1. Responde en español de México, lenguaje jurídico accesible.
2. Cita SIEMPRE el artículo o NOM específica que aplica (ej: "NOM-019-STPS-2011, Artículo 7").
3. Diferencia entre obligatorio y recomendable.
4. Si un tema requiere asesoría legal presencial, indícalo.
5. NUNCA sustituyas a un abogado real — esto es orientación preventiva.
6. Usa el contexto de NOMs proporcionado cuando cites normativas específicas."""

AGENT_GLM_PROMPT = """Eres el ingeniero de estructuración de datos de Atenea Lab.
Especialista en generar documentos estructurados, Excel, PPT y reportes ejecutivos.

Especialidades:
- Convertir datos de incidentes en reportes Excel formateados.
- Generar presentaciones PPT ejecutivas con gráficos y KPIs.
- Estructurar datos en tablas, CSV, y formatos exportables.
- Crear manuales de seguridad estructurados capítulo por capítulo.
- Organizar grandes volúmenes de datos en formatos empresariales.

Reglas:
1. Responde siempre con datos estructurados (tablas, listas, formato exportable).
2. Usa formato Markdown con tablas cuando sea posible.
3. Organiza jerárquicamente (Capítulo > Sección > Subsección).
4. Responde en español de México."""

AGENT_HUNYUAN_PROMPT = """Eres el consultor empresarial de Atenea Lab.
Generas presentaciones, resúmenes ejecutivos y comunicaciones corporativas de alto nivel.

Especialidades:
- Generar resúmenes ejecutivos para gerencia y dirección.
- Crear contenido para presentaciones corporativas (PPT/Google Slides).
- Redactar comunicados de seguridad para toda la empresa.
- Estructurar reportes ESG (Environmental, Social, Governance).
- Preparar dashboards narrativos para juntas directivas.

Reglas:
1. Lenguaje ejecutivo, profesional, orientado a resultados.
2. Estructura clara: Resumen Ejecutivo > Análisis > Recomendaciones.
3. Incluye métricas y KPIs cuando sea relevante.
4. Responde en español de México, tono corporativo."""

# ═══════════════════════════════════════════════════════════════════════════════
# AGENTE DEFAULT (DeepSeek — más barato y versátil)
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_DEFAULT_PROMPT = AGENT_DEEPSEEK_PROMPT

# ═══════════════════════════════════════════════════════════════════════════════
# MAPEO DE AGENT_TYPE → CONFIGURACIÓN (incluye costo en créditos)
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_TYPE_MAPPING = {
    "deepseek": {
        "model": "deepseek",
        "label": "🧠 DeepSeek (Análisis)",
        "prompt": AGENT_DEEPSEEK_PROMPT,
        "description": "Orquestador principal: OEE, IPERC, matemáticas, lógica, código",
        "credits": 1,
    },
    "vision": {
        "model": "gemini",
        "label": "👁 Inspector (Foto/Audio)",
        "prompt": AGENT_GEMINI_PROMPT,
        "description": "Análisis visual y auditivo de condiciones de seguridad",
        "credits": 1,
    },
    "legal": {
        "model": "claude",
        "label": "⚖ Legal (STPS)",
        "prompt": AGENT_CLAUDE_PROMPT,
        "description": "Asesoría legal, NOMs, multas STPS, DC3/DC5",
        "credits": 3,
    },
    "glm": {
        "model": "glm",
        "label": "📋 GLM-4 (Documentos)",
        "prompt": AGENT_GLM_PROMPT,
        "description": "Estructuración Excel, PPT, reportes y manuales (Premium, 2 créditos)",
        "credits": 2,
    },
    "flash": {
        "model": "flash",
        "label": "⚡ Flash (Gratis)",
        "prompt": AGENT_GLM_PROMPT,
        "description": "Consultas rápidas y soporte de campo vía GLM-4-Flash (GRATIS, 0 créditos)",
        "credits": 0,
    },
    "hunyuan": {
        "model": "hunyuan",
        "label": "🏢 Hunyuan (Ejecutivo)",
        "prompt": AGENT_HUNYUAN_PROMPT,
        "description": "Presentaciones, ESG, resúmenes ejecutivos",
        "credits": 2,
    },
    "kimi": {
        "model": "kimi",
        "label": "💻 Kimi K2.7 Code",
        "prompt": AGENT_GLM_PROMPT,
        "description": "Modelo de código y desarrollo avanzado (Kimi K2.7)",
        "credits": 1,
    },
    "minimax": {
        "model": "minimax",
        "label": "⚡ Minimax M3",
        "prompt": AGENT_GLM_PROMPT,
        "description": "Modelo generalista de alto rendimiento (Minimax M3)",
        "credits": 1,
    },
    "glm52": {
        "model": "glm52",
        "label": "🎯 GLM 5.2 Pro",
        "prompt": AGENT_GLM_PROMPT,
        "description": "Modelo premium de razonamiento y análisis (GLM 5.2)",
        "credits": 2,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAPEO DE MODELO → CONFIGURACIÓN DEL PROVEEDOR
# ═══════════════════════════════════════════════════════════════════════════════

PROVIDER_CONFIG = {
    "deepseek": {
        "model_name": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "gemini": {
        "model_name": "gemini-2.0-flash",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "claude": {
        "model_name": "claude-sonnet-4-20250514",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "glm": {
        "model_name": "glm-4",
        "provider": "zhipu_direct",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "flash": {
        "model_name": "glm-4-flash",
        "provider": "zhipu_direct",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "hunyuan": {
        "model_name": "hy3",
        "provider": "tokenhub_direct",
        "base_url_direct": "https://tokenhub-intl.tencentcloudmaas.com/v1/chat/completions",
        "model_direct": "hy3",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "kimi": {
        "model_name": "kimi-k2.7-code",
        "provider": "zhipu_direct",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "minimax": {
        "model_name": "minimax-m3",
        "provider": "zhipu_direct",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "glm52": {
        "model_name": "glm-5.2",
        "provider": "zhipu_direct",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# ZHIPU AI (BigModel) — Conexión directa, sin OpenRouter
# ═══════════════════════════════════════════════════════════════════════════════

ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


async def call_zhipu_direct(model: str, messages: list[dict], system_prompt: str = "") -> dict:
    """
    Llama directamente a la API de Zhipu AI (BigModel) usando ZHIPU_API_KEY.
    Endpoint OpenAI-compatible. Usado por GLM-4 (glm) y GLM-4-Flash (flash).

    Args:
        model: ID del modelo en Zhipu (ej: "glm-4" o "glm-4-flash").
        messages: Lista de mensajes [{"role": "user"|"assistant", "content": "..."}].
        system_prompt: Instrucción de sistema opcional.

    Returns:
        {
            "content": str,
            "model": str,
            "tokens_entrada": int,
            "tokens_salida": int,
            "costo_usd": float,
            "tiempo_s": float,
        }
    """
    import os
    import time
    import aiohttp
    import logging

    logger = logging.getLogger(__name__)
    api_key = os.environ.get("ZHIPU_API_KEY", "")
    if not api_key:
        raise RuntimeError("ZHIPU_API_KEY no configurada en variables de entorno")

    inicio = time.time()

    # Construir payload OpenAI-compatible
    openai_messages = []
    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})
    for m in messages:
        openai_messages.append({"role": m["role"], "content": m["content"]})

    payload = {
        "model": model,
        "messages": openai_messages,
        "max_tokens": 2048,
        "temperature": 0.7,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ZHIPU_BASE_URL, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"Zhipu HTTP {resp.status}: {error_text[:200]}")

                data = await resp.json()
                duracion = round(time.time() - inicio, 2)

                choice = data.get("choices", [{}])[0]
                contenido = choice.get("message", {}).get("content", "")
                uso = data.get("usage", {})
                tokens_entrada = uso.get("prompt_tokens", 0)
                tokens_salida = uso.get("completion_tokens", 0)

                logger.info(
                    "🐉 [ZHIPU] %s | %d in / %d out tokens | %.2fs",
                    model, tokens_entrada, tokens_salida, duracion,
                )

                return {
                    "content": contenido,
                    "model": model,
                    "tokens_entrada": tokens_entrada,
                    "tokens_salida": tokens_salida,
                    "costo_usd": 0.0,  # Zhipu directo: sin costo de pasarela
                    "tiempo_s": duracion,
                }

    except aiohttp.ClientError as e:
        logger.error("❌ [ZHIPU] Error de conexión: %s", e)
        raise RuntimeError(f"Zhipu no disponible: {e}") from e

# ═══════════════════════════════════════════════════════════════════════════════
# SISTEMA DE CRÉDITOS
# ═══════════════════════════════════════════════════════════════════════════════

def get_agent_credits(agent_type: str) -> int:
    """Retorna el costo en créditos de un agente. Default: 1 (DeepSeek)."""
    agent = AGENT_TYPE_MAPPING.get(agent_type)
    return agent["credits"] if agent else 1


def validate_credits(agent_type: str, balance: int) -> tuple[bool, str]:
    """
    Verifica si el balance de créditos es suficiente para usar un agente.
    Retorna (es_suficiente, mensaje).
    """
    required = get_agent_credits(agent_type)
    if balance < required:
        return False, f"Créditos Atenea insuficientes. Requeridos: {required}, Disponibles: {balance}"
    return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
# OPENROUTER — Pasarela unificada para GLM y Hunyuan
# ═══════════════════════════════════════════════════════════════════════════════

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


async def call_open_router(model: str, messages: list[dict], system_prompt: str = "") -> dict:
    """
    Llama a OpenRouter como pasarela unificada para modelos que no tienen API directa.
    Usado por GLM (zhipu/glm-4) y Hunyuan (tencent/hunyuan-lite).

    Args:
        model: ID del modelo en OpenRouter (ej: "zhipu/glm-4")
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
    """
    import os
    import time
    import aiohttp
    import logging

    logger = logging.getLogger(__name__)
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY no configurada en variables de entorno")

    inicio = time.time()

    # Construir payload OpenAI-compatible
    openai_messages = []
    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})
    for m in messages:
        openai_messages.append({"role": m["role"], "content": m["content"]})

    payload = {
        "model": model,
        "messages": openai_messages,
        "max_tokens": 2048,
        "temperature": 0.7,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://atenealab.mx",
        "X-Title": "Atenea Lab Desk",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_BASE_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"OpenRouter HTTP {resp.status}: {error_text[:200]}")

                data = await resp.json()
                duracion = round(time.time() - inicio, 2)

                choice = data.get("choices", [{}])[0]
                contenido = choice.get("message", {}).get("content", "")
                uso = data.get("usage", {})
                tokens_entrada = uso.get("prompt_tokens", 0)
                tokens_salida = uso.get("completion_tokens", 0)

                # Costo estimado genérico para OpenRouter
                costo = (tokens_entrada * 0.5 / 1_000_000) + (tokens_salida * 1.5 / 1_000_000)

                logger.info(
                    "🌐 [OPENROUTER] %s | %d in / %d out tokens | %.2fs | $%.6f USD",
                    model, tokens_entrada, tokens_salida, duracion, costo,
                )

                return {
                    "content": contenido,
                    "model": model,
                    "tokens_entrada": tokens_entrada,
                    "tokens_salida": tokens_salida,
                    "costo_usd": round(costo, 6),
                    "tiempo_s": duracion,
                }

    except aiohttp.ClientError as e:
        logger.error("❌ [OPENROUTER] Error de conexión: %s", e)
        raise RuntimeError(f"OpenRouter no disponible: {e}") from e


# ═══════════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════════════════════════

def get_agent_config(agent_type: str | None) -> dict:
    """
    Retorna la configuración completa del agente solicitado.
    Si agent_type es None o inválido, retorna DeepSeek (default, más barato).

    Returns:
        {
            "model": str,
            "label": str,
            "prompt": str,
            "description": str,
            "credits": int,
        }
    """
    if agent_type and agent_type in AGENT_TYPE_MAPPING:
        return AGENT_TYPE_MAPPING[agent_type]
    return AGENT_TYPE_MAPPING["deepseek"]


def list_agents() -> list[dict]:
    """Retorna la lista de agentes disponibles para el frontend (sin prompts)."""
    return [
        {
            "type": agent_type,
            "label": config["label"],
            "description": config["description"],
            "credits": config["credits"],
        }
        for agent_type, config in AGENT_TYPE_MAPPING.items()
    ]