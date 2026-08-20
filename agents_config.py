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

AGENT_OPENAI_PROMPT = """Eres el asistente enterprise de Atenea Lab para consultas complejas y multi-agente.
Tienes acceso a herramientas de análisis profundo y generación de documentos ejecutivos.

Especialidades:
- Redactar informes ejecutivos y resúmenes para dirección.
- Analizar datos complejos y generar visualizaciones.
- Integrar información de múltiples fuentes (legal, operativa, financiera).
- Resolver consultas ambiguas que requieren razonamiento cruzado.
- Generar planes de acción estratégicos.

Reglas:
1. Responde en español de México, tono ejecutivo profesional.
2. Estructura: Resumen Ejecutivo > Análisis > Recomendaciones.
3. Cita fuentes y datos cuando sea relevante.
4. Si la consulta requiere datos específicos, solicítalos antes de responder.
5. Para consultas legales, sugiere consultar con el agente Legal (Claude)."""

AGENT_OPENAI_MINI_PROMPT = """Eres el asistente de soporte rápido de Atenea Lab Desk.
Ayudas a los usuarios a usar la plataforma de forma eficiente.

Especialidades:
- Explicar cómo usar cualquier función de la app.
- Responder preguntas frecuentes (FAQ).
- Guiar en flujos de trabajo (checklists, reportes, dictámenes).
- Solucionar problemas comunes.

Reglas:
1. Responde en español de México, tono amigable y claro.
2. Sé conciso: respuestas de máximo 3 párrafos.
3. Si no sabes algo, redirige al agente especializado.
4. NUNCA des consejos legales o médicos."""

# ═══════════════════════════════════════════════════════════════════════════════
# AGENTE DEFAULT (GPT-4o-mini — soporte rápido, 0 créditos)
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_DEFAULT_PROMPT = AGENT_OPENAI_MINI_PROMPT

# ═══════════════════════════════════════════════════════════════════════════════
# MAPEO DE AGENT_TYPE → CONFIGURACIÓN (incluye costo en créditos)
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_TYPE_MAPPING = {
    "deepseek": {
        "model": "deepseek",
        "label": "DeepSeek (Análisis)",
        "prompt": AGENT_DEEPSEEK_PROMPT,
        "description": "Análisis, OEE, IPERC, matemáticas, código",
        "credits": 1,
    },
    "gemini": {
        "model": "gemini",
        "label": "Gemini (Visión)",
        "prompt": AGENT_GEMINI_PROMPT,
        "description": "Análisis visual, fotos, audio, video",
        "credits": 1,
    },
    "claude": {
        "model": "claude",
        "label": "Claude (Legal)",
        "prompt": AGENT_CLAUDE_PROMPT,
        "description": "Asesoría legal STPS, NOMs, dictámenes, DC3/DC5",
        "credits": 3,
    },
    # Aliases internos usados por endpoints existentes (vision/legal).
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
    "openai": {
        "model": "openai",
        "label": "GPT-4o (Enterprise)",
        "prompt": AGENT_OPENAI_PROMPT,
        "description": "Consultas complejas, enterprise, multi-agente",
        "credits": 2,
    },
    "openai-mini": {
        "model": "openai-mini",
        "label": "GPT-4o-mini (Soporte)",
        "prompt": AGENT_OPENAI_MINI_PROMPT,
        "description": "Soporte rápido, FAQ, cómo usar la app",
        "credits": 0,
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
        "model_name": "gemini-2.5-flash",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "claude": {
        "model_name": "claude-sonnet-5",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "openai": {
        "model_name": "gpt-4o",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "openai-mini": {
        "model_name": "gpt-4o-mini",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
}

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