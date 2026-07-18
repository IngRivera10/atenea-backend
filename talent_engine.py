"""
talent_engine.py — Motor de Talento Atenea: IPA, matching y validación de habilidades.

El Índice de Potencial Atenea (IPA) mide el potencial del trabajador (0-1000),
NO sus años de experiencia. Se compone de:
  - Aprendizaje (40%): Cursos completados, micro-cuestionarios aprobados
  - Actitud y Valores (30%): Reportes near-miss, charlas, karma de supervisores
  - Habilidad Validada IA (30%): Sellos de habilidad otorgados por Gemini/Claude
"""

import logging
import json
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# ROLES TALENT (Firestore-compatible)
# ═══════════════════════════════════════════════════════════════════════════════

TALENT_ROLES = {
    "obrero": {"label": "Obrero / Talento", "tier": 1},
    "supervisor_n1": {"label": "Supervisor Nivel 1 (Área)", "tier": 2},
    "supervisor_n2": {"label": "Supervisor Nivel 2 (Turno)", "tier": 3},
    "supervisor_n3": {"label": "Supervisor Nivel 3 (Coordinador)", "tier": 4},
    "instructor": {"label": "Instructor / Capacitador DC3", "tier": 3},
    "comisionado_dc5": {"label": "Comisionado DC5", "tier": 2},
}

# ═══════════════════════════════════════════════════════════════════════════════
# CÁLCULO DEL IPA (Índice de Potencial Atenea)
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_ipa_components(user_profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calcula los componentes del IPA basado en los datos del perfil del usuario.
    NO requiere IA — es un cálculo determinista a partir de métricas en Firestore.

    Args:
        user_profile: {
            "cursos_completados": int,       # Cursos finalizados
            "cuestionarios_aprobados": int,  # Micro-quizzes superados
            "reportes_nearmiss": int,        # Reportes de seguridad realizados
            "charlas_asistidas": int,        # Charlas de 5 min atendidas
            "karma_supervisor": int,         # Puntos de karma (0-100)
            "sellos_habilidad": int,         # Sellos de habilidad validados por IA
            "horas_capacitacion": int,       # Horas totales de capacitación
        }

    Returns:
        {
            "ipa_total": int,        # 0-1000
            "aprendizaje": int,      # 0-400
            "actitud_valores": int,  # 0-300
            "habilidad_ia": int,     # 0-300
            "nivel": str,            # "Básico", "Intermedio", "Avanzado", "Experto"
            "badges": [str],         # Insignias desbloqueadas
        }
    """
    cursos = user_profile.get("cursos_completados", 0)
    quizzes = user_profile.get("cuestionarios_aprobados", 0)
    reportes = user_profile.get("reportes_nearmiss", 0)
    charlas = user_profile.get("charlas_asistidas", 0)
    karma = user_profile.get("karma_supervisor", 0)
    sellos = user_profile.get("sellos_habilidad", 0)
    horas = user_profile.get("horas_capacitacion", 0)

    # ── Aprendizaje (40% = 400 puntos) ──
    aprendizaje = min(400, (cursos * 40) + (quizzes * 15) + (horas * 2))

    # ── Actitud y Valores (30% = 300 puntos) ──
    actitud = min(300, (reportes * 15) + (charlas * 10) + karma)

    # ── Habilidad Validada IA (30% = 300 puntos) ──
    habilidad = min(300, sellos * 75)

    ipa_total = aprendizaje + actitud + habilidad

    # ── Nivel ──
    if ipa_total >= 800:
        nivel = "Experto"
    elif ipa_total >= 600:
        nivel = "Avanzado"
    elif ipa_total >= 350:
        nivel = "Intermedio"
    else:
        nivel = "Básico"

    # ── Badges ──
    badges = []
    if cursos >= 3:
        badges.append("🎓 Aprendiz Dedicado")
    if reportes >= 5:
        badges.append("🛡️ Guardián de Seguridad")
    if karma >= 50:
        badges.append("⭐ Líder en Confianza")
    if sellos >= 2:
        badges.append("🏅 Habilidades Certificadas IA")
    if ipa_total >= 800:
        badges.append("💎 Talento Diamante")

    return {
        "ipa_total": ipa_total,
        "aprendizaje": aprendizaje,
        "actitud_valores": actitud,
        "habilidad_ia": habilidad,
        "nivel": nivel,
        "badges": badges,
        "desglose": {
            "cursos_completados": cursos,
            "cuestionarios_aprobados": quizzes,
            "horas_capacitacion": horas,
            "reportes_nearmiss": reportes,
            "charlas_asistidas": charlas,
            "karma_supervisor": karma,
            "sellos_habilidad": sellos,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MATCHING SEMÁNTICO DE TALENTO (DeepSeek)
# ═══════════════════════════════════════════════════════════════════════════════

MATCH_SYSTEM_PROMPT = """Eres el motor de matching de talento de Atenea Lab.
Tu función es evaluar si un candidato tiene el POTENCIAL adecuado para un puesto,
basándote en su IPA (Índice de Potencial Atenea), sellos de habilidad y valores de seguridad.
NO evalúes años de experiencia. Evalúa potencial de crecimiento, actitud y habilidades validadas.

Para cada match, asigna un score de compatibilidad (0-100) y explica por qué.
Prioriza candidatos con:
- IPA alto (especialmente en la categoría relevante al puesto)
- Sellos de habilidad relacionados al puesto
- Alta participación en reportes de seguridad (actitud proactiva)
- Karma positivo de supervisores"""


def build_match_prompt(candidato: Dict, requisitos: Dict) -> str:
    """Construye el prompt para que DeepSeek evalúe el match."""
    ipa = candidato.get("ipa", {})
    return f"""
CANDIDATO:
- IPA Total: {ipa.get('ipa_total', 0)}/1000 (Nivel: {ipa.get('nivel', 'Desconocido')})
- Aprendizaje: {ipa.get('aprendizaje', 0)}/400
- Actitud y Valores: {ipa.get('actitud_valores', 0)}/300
- Habilidad Validada IA: {ipa.get('habilidad_ia', 0)}/300
- Badges: {', '.join(ipa.get('badges', []))}
- Sellos de Habilidad: {candidato.get('sellos', [])}
- Cursos Completados: {ipa.get('desglose', {}).get('cursos_completados', 0)}
- Reportes Near-Miss: {ipa.get('desglose', {}).get('reportes_nearmiss', 0)}

REQUISITOS DEL PUESTO:
- IPA Mínimo: {requisitos.get('ipa_minimo', 0)}
- Habilidades Deseadas: {requisitos.get('habilidades', [])}
- Valores Buscados: {requisitos.get('valores', [])}
- Disponibilidad para Aprender: {requisitos.get('disponibilidad_aprender', 'Media')}

Evalúa el match y responde en JSON:
{{"score": 0-100, "razon": "explicación concisa", "recomendado": true/false, "fortalezas": [], "areas_mejora": []}}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDACIÓN DE HABILIDADES POR IA (Gemini Vision / Claude)
# ═══════════════════════════════════════════════════════════════════════════════

SKILL_VALIDATION_PROMPT = """Eres un evaluador de habilidades industriales de Atenea Lab.
Tu trabajo es validar si un trabajador demuestra competencia en una habilidad específica
basándote en evidencia (video, audio o texto descriptivo).

Evalúa:
1. ¿El trabajador demuestra conocimiento práctico de la habilidad? (Sí/No/Parcial)
2. ¿Sigue procedimientos de seguridad? (Sí/No/Parcial)
3. ¿Qué nivel de dominio muestra? (Básico/Intermedio/Avanzado)

Responde en JSON:
{{"aprobado": true/false, "nivel": "Básico|Intermedio|Avanzado", "comentarios": "feedback constructivo", "sello_otorgado": "nombre del sello si aprueba"}}

Reglas:
- Si demuestra conocimiento práctico Y sigue seguridad → APROBADO
- Si falta seguridad pero tiene conocimiento → PARCIAL (no otorgar sello, sugerir capacitación)
- Si no demuestra conocimiento → NO APROBADO"""


def build_skill_validation_prompt(habilidad: str, evidencia_descripcion: str) -> str:
    """Construye el prompt para validar una habilidad."""
    return f"HABILIDAD A EVALUAR: {habilidad}\n\nEVIDENCIA PROPORCIONADA POR EL TRABAJADOR:\n{evidencia_descripcion}\n\nEvalúa según los criterios establecidos."


# ═══════════════════════════════════════════════════════════════════════════════
# CATÁLOGO DE HABILIDADES Y SELLOS
# ═══════════════════════════════════════════════════════════════════════════════

SKILL_CATALOG = [
    {"id": "nom033", "nombre": "NOM-033 Espacios Confinados", "categoria": "seguridad", "ipa_bonus": 75},
    {"id": "nom009", "nombre": "NOM-009 Trabajo en Alturas", "categoria": "seguridad", "ipa_bonus": 75},
    {"id": "nom029", "nombre": "NOM-029 Eléctrica / LOTO", "categoria": "seguridad", "ipa_bonus": 75},
    {"id": "montacargas", "nombre": "Manejo de Montacargas", "categoria": "operacion", "ipa_bonus": 75},
    {"id": "soldadura", "nombre": "Soldadura Industrial", "categoria": "oficio", "ipa_bonus": 75},
    {"id": "primeros_auxilios", "nombre": "Primeros Auxilios", "categoria": "emergencia", "ipa_bonus": 50},
    {"id": "liderazgo", "nombre": "Liderazgo de Equipos", "categoria": "supervision", "ipa_bonus": 75},
    {"id": "reporte_activo", "nombre": "Reporte Activo de Riesgos", "categoria": "valores", "ipa_bonus": 50},
    {"id": "epp_inspeccion", "nombre": "Inspección de EPP", "categoria": "seguridad", "ipa_bonus": 50},
    {"id": "excavacion", "nombre": "Excavaciones y Zanjas", "categoria": "construccion", "ipa_bonus": 75},
]