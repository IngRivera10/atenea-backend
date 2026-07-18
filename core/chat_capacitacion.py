"""
chat_capacitacion.py — Modo capacitación para el chat multiagente de Atenea Lab.
Fase 3C: responde preguntas educativas sobre seguridad STPS, uso de la app,
y normativa. NO sustituye a un primer respondiente en emergencias reales.

Modelo por defecto: Claude Haiku 4.5 (consultas educativas de volumen medio-alto).
Escala a Sonnet 5 si la pregunta requiere análisis profundo de un dictamen.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT — MODO CAPACITACIÓN
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT_CAPACITACION = """Eres Atenea, la asistente de capacitación en seguridad industrial de Atenea Lab. Tu función es educar, explicar y orientar — NUNCA sustituir a un primer respondiente humano en una emergencia real.

IDIOMA: Español de México. Tono: profesional, claro y accesible (como si hablaras con un compañero de obra, no con un abogado).

LO QUE SÍ PUEDES HACER:
- Explicar normativa STPS en lenguaje simple
- Explicar cómo usar cualquier función de la app Atenea Lab
- Dar contexto educativo sobre procedimientos de seguridad industrial
- Responder dudas sobre un dictamen ya generado (explicar por qué se llegó a esa conclusión, qué significa cada campo)
- Aclarar la diferencia entre severidad de urgencia operativa y severidad legal
- Orientar sobre cómo configurar roles de seguridad en una obra

LO QUE NO PUEDES HACER:
- Generar dictámenes legales nuevos (eso lo hace abogado_stps.py, no el chat)
- Analizar imágenes de seguridad (eso lo hace forense_cctv.py)
- Dar instrucciones que sustituyan la decisión de un primer respondiente humano

REGLAS DE SEGURIDAD — EMERGENCIAS ACTIVAS (OBLIGATORIO):
Si el usuario describe una situación que suena a emergencia activa o peligro inminente (alguien está en riesgo AHORA, hay un accidente en curso, una persona está herida o atrapada, hay un incendio activo, etc.), DEBES responder EXACTAMENTE con este mensaje y NADA MÁS de contenido técnico:

"🚨 Esto suena a una emergencia activa. NO esperes mi respuesta. Contacta DE INMEDIATO a:
• Tu Brigada de Emergencia o Responsable de Zona (por teléfono o en persona)
• Si hay heridos, llama al 911
La app de Atenea Lab puede notificar a las comisiones de seguridad, pero en una emergencia en curso, la comunicación directa por teléfono es más rápida. ¿Necesitas ayuda para usar la app UNA VEZ que la emergencia esté controlada?"

Después de este mensaje, NO des consejos técnicos sobre qué hacer durante la emergencia.

BASE DE CONOCIMIENTO (FAQ de referencia):
{faq_context}

HISTORIAL DE LA CONVERSACIÓN:
{conversation_history}
"""

# ═══════════════════════════════════════════════════════════════════════════
# FAQ CONTEXT (inyectado en el system prompt como few-shot knowledge)
# ═══════════════════════════════════════════════════════════════════════════

def _construir_faq_context(faqs: list) -> str:
    """Convierte la lista de FAQ en texto para el system prompt."""
    lineas = []
    for i, faq in enumerate(faqs, 1):
        lineas.append(f"{i}. P: {faq['pregunta']}")
        lineas.append(f"   R: {faq['respuesta']}")
        lineas.append("")
    return "\n".join(lineas)


# ═══════════════════════════════════════════════════════════════════════════
# DETECCIÓN DE EMERGENCIA ACTIVA (basada en keywords, no en IA)
# ═══════════════════════════════════════════════════════════════════════════

PALABRAS_EMERGENCIA = [
    "accidente ahora", "se acaba de caer", "se cayó ahorita",
    "está sangrando", "no responde", "inconsciente", "atrapado",
    "se está quemando", "fuego ahora", "explosión ahora",
    "está pasando ahorita", "emergencia en este momento",
    "hay un herido ahora", "se electrocutó", "se intoxicó",
    "derrumbándose", "colapsando ahorita",
]

MENSAJE_EMERGENCIA = (
    "🚨 Esto suena a una emergencia activa. NO esperes mi respuesta. "
    "Contacta DE INMEDIATO a:\n"
    "• Tu Brigada de Emergencia o Responsable de Zona (por teléfono o en persona)\n"
    "• Si hay heridos, llama al 911\n\n"
    "La app de Atenea Lab puede notificar a las comisiones de seguridad, "
    "pero en una emergencia en curso, la comunicación directa por teléfono "
    "es más rápida. ¿Necesitas ayuda para usar la app UNA VEZ que la "
    "emergencia esté controlada?"
)


def detectar_emergencia_activa(mensaje_usuario: str) -> bool:
    """
    Detecta si el mensaje del usuario describe una emergencia en curso.
    Usa keywords + heurísticas simples (no IA) para ser rápido y determinístico.
    
    Returns:
        True si el mensaje parece describir una emergencia activa.
    """
    msg_lower = mensaje_usuario.lower()
    
    # Palabras clave de emergencia activa
    for palabra in PALABRAS_EMERGENCIA:
        if palabra in msg_lower:
            return True
    
    # Combinaciones: "se cayó" + "ahora" / "ya" / " urgente"
    if ("se cayó" in msg_lower or "se callo" in msg_lower) and \
       any(p in msg_lower for p in ["ahora", "ya", "urgente", "auxilio", "ayuda"]):
        return True
    
    # "accidente" + indicador de inmediatez
    if "accidente" in msg_lower and \
       any(p in msg_lower for p in ["ahora", "en curso", "activo", "pasando"]):
        return True
    
    return False


# ═══════════════════════════════════════════════════════════════════════════
# CRITERIO DE ESCALAMIENTO: Haiku → Sonnet 5
# ═══════════════════════════════════════════════════════════════════════════
# Sonnet 5 se usa cuando la pregunta requiere análisis profundo de un dictamen
# ya generado (ej: "¿por qué mi dictamen dio CRÍTICA y no MEDIA?").
# Haiku 4.5 se usa para consultas educativas generales (FAQ, cómo usar la app).
#
# Criterios de escalamiento:
# - Menciona "dictamen" + pregunta analítica → Sonnet 5
# - Menciona "multa" + "¿por qué?" → Sonnet 5
# - Menciona "norma" o "NOM" + pregunta de interpretación → Sonnet 5
# - Preguntas generales, FAQ, cómo usar la app → Haiku 4.5

INDICADORES_ESCALAMIENTO = [
    "por qué el dictamen",
    "por qué la multa",
    "explica el dictamen",
    "analiza el dictamen",
    "interpretación de la nom",
    "interpretación de la norma",
    "diferencia entre critic",
    "cómo se calculó",
    "qué significa esta multa",
    "por qué severidad",
]

MODELO_DEFAULT_CAPACITACION = "claude-haiku-4-5-20251001"
MODELO_ESCALADO_CAPACITACION = "claude-sonnet-5"


def debe_escalar_a_sonnet(mensaje_usuario: str) -> bool:
    """
    Determina si la pregunta del usuario amerita escalar de Haiku a Sonnet 5.
    """
    msg_lower = mensaje_usuario.lower()
    for indicador in INDICADORES_ESCALAMIENTO:
        if indicador in msg_lower:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL DEL MODO CAPACITACIÓN
# ═══════════════════════════════════════════════════════════════════════════

def procesar_consulta_capacitacion(
    mensaje_usuario: str,
    faqs: Optional[list] = None,
    historial_conversacion: Optional[list] = None,
    cliente_anthropic=None,
) -> dict:
    """
    Procesa una consulta en modo capacitación.
    
    Args:
        mensaje_usuario: Texto de la pregunta del usuario.
        faqs: Lista de FAQs (dicts con 'pregunta' y 'respuesta'). Si es None, usa lista vacía.
        historial_conversacion: Mensajes previos para contexto. Si es None, sin historial.
        cliente_anthropic: Cliente Anthropic inicializado. Si es None, se devuelve error.
    
    Returns:
        {
            "respuesta": str,
            "modelo_usado": str,
            "es_emergencia": bool,
            "escalado_a_sonnet": bool,
        }
    """
    # ── Paso 1: Detección de emergencia (determinístico, no usa IA) ──
    if detectar_emergencia_activa(mensaje_usuario):
        return {
            "respuesta": MENSAJE_EMERGENCIA,
            "modelo_usado": "ninguno (emergencia detectada)",
            "es_emergencia": True,
            "escalado_a_sonnet": False,
        }
    
    # ── Paso 2: Determinar modelo ──
    escalar = debe_escalar_a_sonnet(mensaje_usuario)
    modelo = MODELO_ESCALADO_CAPACITACION if escalar else MODELO_DEFAULT_CAPACITACION
    
    # ── Paso 3: Construir FAQ context ──
    faqs_usar = faqs if faqs else []
    faq_texto = _construir_faq_context(faqs_usar)
    
    # ── Paso 4: Construir historial ──
    historial = historial_conversacion if historial_conversacion else []
    historial_texto = ""
    for msg in historial[-6:]:  # últimos 6 mensajes para contexto
        rol = "Usuario" if msg.get("role") == "user" else "Atenea"
        historial_texto += f"[{rol}]: {msg.get('content', '')}\n"
    
    # ── Paso 5: System prompt completo ──
    system_prompt = SYSTEM_PROMPT_CAPACITACION.format(
        faq_context=faq_texto,
        conversation_history=historial_texto if historial_texto else "(nueva conversación)",
    )
    
    # ── Paso 6: Si no hay cliente, devolver error claro ──
    if cliente_anthropic is None:
        return {
            "respuesta": "El servicio de capacitación no está disponible en este momento (cliente IA no inicializado).",
            "modelo_usado": "ninguno",
            "es_emergencia": False,
            "escalado_a_sonnet": False,
        }
    
    # ── Paso 7: Invocar a Claude ──
    try:
        respuesta_ia = cliente_anthropic.messages.create(
            model=modelo,
            max_tokens=800,
            temperature=0.5,
            system=system_prompt,
            messages=[
                {"role": "user", "content": mensaje_usuario},
            ],
        )
        
        texto_respuesta = respuesta_ia.content[0].text if respuesta_ia.content else ""
        
        return {
            "respuesta": texto_respuesta,
            "modelo_usado": modelo,
            "es_emergencia": False,
            "escalado_a_sonnet": escalar,
        }
    
    except Exception as e:
        logger.error(f"❌ chat_capacitacion: Error en llamada a Claude: {e}")
        return {
            "respuesta": f"No se pudo procesar tu consulta en este momento. Error: {str(e)[:200]}. Intenta de nuevo.",
            "modelo_usado": "error",
            "es_emergencia": False,
            "escalado_a_sonnet": False,
        }