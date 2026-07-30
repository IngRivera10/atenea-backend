import sys
import os
import logging
import json
import sqlite3
import hashlib
import threading
import time
import re
import random
import secrets
import tempfile
from datetime import datetime
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import anthropic
import uuid
from abogado_stps import generar_dictamen_legal
from auth_service import token_requerido
from clasificador_psicosocial import evaluar, prep_legal, reporte as reporte_nom035

# ==========================================
# CONFIGURACIÓN BASE
# ==========================================
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

DB_PATH = "atenea_central.db"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    logger.warning("⚠️ ANTHROPIC_API_KEY no está en variables de entorno. Configúrala antes de producción.")
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
)

# ─ CORS: Permitir consumo desde dashboard local y móvil en desarrollo
# En producción, especificar origins explícitos
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "http://localhost:*",
            "http://127.0.0.1:*",
            "https://atenea-backend-fggs.onrender.com",
            "https://atenea-desk.vercel.app",
            "https://ateneadesk.vercel.app",
            "capacitor://localhost",
            "exp://192.168.*:*",
            "file://"
        ],
        "methods": ["GET", "POST", "OPTIONS", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"]
    }
})

# ── Rate Limiting (punto 14): límite por IP para endpoints de IA ──
# Previene costos descontrolados por abuso o bucles accidentales.
# Límites conservadores para un sistema de inspección (no chat masivo):
#   - orquestar-emergencia: 20 requests / minuto / IP  (dictámenes IA)
#   - endpoints de consulta: 60 requests / minuto / IP
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100 per minute"],  # límite global generoso
    storage_uri="memory://",           # memoria; en prod usar redis://
)

# Vincular limiter a la app Flask después de crearla
limiter.init_app(app)

ROLES_VALIDOS = {"SUPERVISOR_GENERAL", "DIRECTOR_OBRA", "AUDITOR_STPS", "OPERADOR"}
TAMANOS_OBRA_VALIDOS = {"1-15", "16-50", "51+"}

# ── Modelo unificado de estados del pipeline ──
ESTADOS_PIPELINE = {
    "PENDIENTE",
    "PROCESANDO",
    "DICTAMINADO",
    "ERROR",
    "OFFLINE_PENDIENTE_SYNC",
    "SINCRONIZADO"
}

# ==========================================
# RETRY CON BACKOFF (punto 13) — genérico para llamadas IA
# ==========================================
# Máximo 2 reintentos con backoff exponencial + jitter.
# Si después de 3 intentos totales (1 inicial + 2 retry) la IA no responde,
# se devuelve error claro al usuario.
MAX_RETRIES = 2
BASE_DELAY_SECONDS = 2  # Delay base: 2s → 4s → máximo 10s


def _retry_con_backoff(func, *args, logger_name="", **kwargs):
    """
    Ejecuta func(*args, **kwargs) con hasta MAX_RETRIES reintentos.
    Entre reintentos, espera con backoff exponencial + jitter aleatorio.
    
    Retorna (resultado, None) si éxito, (None, mensaje_error) si falló tras reintentos.
    """
    ultimo_error = None
    for intento in range(1 + MAX_RETRIES):  # 1 inicial + 2 retry = 3 total
        try:
            resultado = func(*args, **kwargs)
            return resultado, None
        except Exception as e:
            ultimo_error = e
            if intento < MAX_RETRIES:
                delay = min(BASE_DELAY_SECONDS * (2 ** intento), 10)
                jitter = random.uniform(0, delay * 0.3)
                total_delay = delay + jitter
                logger.warning(
                    "⚠️  [Retry %d/%d] %s falló: %s. Reintentando en %.1fs...",
                    intento + 1, MAX_RETRIES, logger_name, str(e)[:100], total_delay,
                )
                time.sleep(total_delay)
            else:
                logger.error(
                    "❌ [Retry AGOTADO] %s falló tras %d intentos. Último error: %s",
                    logger_name, 1 + MAX_RETRIES, str(e)[:200],
                )
    return None, str(ultimo_error)


# ==========================================
# LOGS DE AUDITORÍA (punto 15) — tabla separada para acciones de IA
# ==========================================
def init_audit_db():
    """Crea la tabla de auditoría de IA si no existe."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS auditoria_ia (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        firebase_uid TEXT DEFAULT '',
                        accion TEXT NOT NULL,
                        resultado TEXT NOT NULL,
                        detalle TEXT DEFAULT '',
                        timestamp TEXT NOT NULL
                    )''')
        conn.commit()


def registrar_auditoria(accion: str, resultado: str, detalle: str = "",
                        firebase_uid: str = ""):
    """
    Registra una acción de IA en la tabla de auditoría (punto 15).
    Campos: firebase_uid, accion (dictamen_generado|alerta_forense|confirmacion_shutdown),
    resultado (exito|error|pendiente), detalle, timestamp.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO auditoria_ia (firebase_uid, accion, resultado, detalle, timestamp)
                         VALUES (?, ?, ?, ?, ?)''',
                      (firebase_uid, accion, resultado, detalle[:500], datetime.now().isoformat()))
            conn.commit()
    except Exception as e:
        logger.warning(f"⚠️  No se pudo registrar auditoría: {e}")


# Inicializar tabla de auditoría al arrancar
init_audit_db()

# ==========================================
# BÓVEDA CENTRAL V4 — incluye estado_pipeline + timestamps de trazabilidad
# ==========================================
def init_denuncias_anonimas():
    """Crea la tabla de denuncias anonimas (NOM-035). Sin ningun id de usuario."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS denuncias_anonimas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticket_id TEXT NOT NULL,
                        categoria TEXT NOT NULL,
                        descripcion TEXT NOT NULL,
                        evidencia_url TEXT DEFAULT '',
                        fecha TEXT NOT NULL,
                        estado TEXT DEFAULT 'NUEVA'
                    )''')
        conn.commit()
    logger.info(" Tabla denuncias_anonimas lista (sin uid ni ip).")

    # Tabla de evaluaciones NOM-035 (psicosocial) — sin PII del trabajador
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS evaluaciones_nom035 (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        company_id TEXT NOT NULL,
                        fecha TEXT NOT NULL,
                        guia TEXT DEFAULT 'guia_i',
                        nivel_riesgo TEXT NOT NULL,
                        violencia_laboral INTEGER DEFAULT 0,
                        porcentaje_global REAL DEFAULT 0,
                        requiere_profesional INTEGER DEFAULT 0,
                        dominios_json TEXT DEFAULT '{}',
                        alertas_json TEXT DEFAULT '[]'
                    )''')
        conn.commit()
    logger.info(" Tabla evaluaciones_nom035 lista (con company_id, sin PII).")


def init_central_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS dictamenes_stps_v2 (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fecha TEXT,
                        contexto TEXT,
                        tipificacion_legal TEXT,
                        responsabilidad TEXT,
                        estado TEXT,
                        multa_minima INTEGER,
                        multa_maxima INTEGER,
                        dictamen_raw TEXT,
                        firma_digital TEXT,
                        rol_supervisor TEXT
                    )''')

        columnas = [row[1] for row in c.execute("PRAGMA table_info(dictamenes_stps_v2)")]

        migraciones = {
            "firma_digital": "TEXT DEFAULT ''",
            "rol_supervisor": "TEXT DEFAULT ''",
            "estado_pipeline": "TEXT DEFAULT 'PENDIENTE'",
            "timestamp_recibido": "TEXT DEFAULT ''",
            "timestamp_procesado": "TEXT DEFAULT ''",
            "error_detalle": "TEXT DEFAULT ''",
        }
        for columna, tipo in migraciones.items():
            if columna not in columnas:
                c.execute(f"ALTER TABLE dictamenes_stps_v2 ADD COLUMN {columna} {tipo}")
                logger.info(f"🔧 [Migración] Columna '{columna}' añadida.")

        conn.commit()
    logger.info("✅ Base de datos central lista (v4 con estado_pipeline).")


def limpiar_datos_migrados_heredados():
    """
    Normaliza los registros migrados de la fase anterior que quedaron con
    placeholders 'ND' y 'FECHA_NO_DISPONIBLE_MIGRACION'. No los borra —
    los marca con estado_pipeline='DICTAMINADO' (ya tienen su JSON, solo
    les faltaba el campo nuevo) y limpia la fecha ilegible.
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            UPDATE dictamenes_stps_v2
            SET estado_pipeline = 'DICTAMINADO',
                fecha = CASE WHEN fecha = 'FECHA_NO_DISPONIBLE_MIGRACION'
                             THEN 'Migrado (fecha no disponible)'
                             ELSE fecha END
            WHERE estado_pipeline = '' OR estado_pipeline IS NULL
        ''')
        afectados = c.rowcount
        conn.commit()
    if afectados:
        logger.info(f"🧹 [Limpieza] {afectados} registro(s) heredado(s) normalizados a estado_pipeline='DICTAMINADO'.")


init_denuncias_anonimas()
init_central_db()
limpiar_datos_migrados_heredados()

# ==========================================
# PROMPT MAESTRO — Abogado STPS
# ==========================================
PROMPT_SYSTEM_ABOGADO = """Eres el Abogado en Jefe y Especialista en Riesgos de la STPS de México para Atenea Lab. Tu idioma estricto es ESPAÑOL DE MÉXICO.
REGLAS ABSOLUTAS:
- SOLO JSON puro como salida. SIN texto adicional. SIN markdown. SIN ```json
- Todos los montos en Pesos Mexicanos (MXN).
- El JSON debe tener EXACTAMENTE esta estructura:
{
  "tipificacion_legal": "NOM-XXX-STPS / Infracción detectada...",
  "responsabilidad_patronal": "DIRECTA / INDIRECTA",
  "sancion_stps": {
    "multa_minima_estimada": 0,
    "multa_maxima_estimada": 0,
    "justificacion_legal": "Según el artículo..."
  },
  "plan_blindaje_legal": [
    {"prioridad": 1, "accion_defensa": "..."}
  ],
  "conclusiones": {
    "cumplimiento_pct": 0,
    "estado": "CRITICO o ALTO o MEDIO o BAJO"
  }
}"""


def generar_firma_criptografica(firma_raw, rol, payload_dict):
    cadena_a_firmar = f"{firma_raw}|{rol}|{json.dumps(payload_dict, sort_keys=True)}"
    return hashlib.sha256(cadena_a_firmar.encode()).hexdigest()


def validar_payload(data):
    """
    Devuelve (es_valido, respuesta_error_o_none). Centraliza la validación
    para que tanto el modo síncrono como el background la reutilicen igual.
    
    CAMPOS REQUERIDOS PARA POST /api/v1/orquestar-emergencia:
    - evidencia (str, base64): Imagen en formato base64 (JPEG/PNG)
    - contexto (str): Descripción del evento/inspección
    - fecha (str, ISO8601): Fecha del evento (ej: 2025-06-20T10:30:00)
    - firma_digital (str): Identificador del operador/supervisor
    - rol_supervisor (str): Rol del operador (SUPERVISOR_GENERAL, DIRECTOR_OBRA, AUDITOR_STPS, OPERADOR)
    
    CAMPOS OPCIONALES:
    - modo (str): "rapido" (retorna 202 + background) o "detallado" (default, síncrono)
    - tamano_obra (str): "1-15", "16-50" o "51+" (default "1-15"). Afecta el tramo
      usado por el calculador determinístico de multas UMA en abogado_stps.py.
    """
    if data is None:
        return False, (jsonify({"error": "FORMATO_INVALIDO", "detalle": "Body vacío o no es JSON."}), 422)

    campos_faltantes = [
        campo for campo in ("evidencia", "contexto", "fecha", "firma_digital", "rol_supervisor")
        if campo not in data
    ]
    if campos_faltantes:
        return False, (jsonify({
            "error": "CAMPOS_FALTANTES",
            "detalle": f"Faltan campos obligatorios: {', '.join(campos_faltantes)}",
            "campos_requeridos": ["evidencia", "contexto", "fecha", "firma_digital", "rol_supervisor"]
        }), 422)

    rol_supervisor = data.get("rol_supervisor", "OPERADOR")
    if rol_supervisor not in ROLES_VALIDOS:
        return False, (jsonify({
            "error": "ROL_INVALIDO",
            "detalle": f"'{rol_supervisor}' no es un rol reconocido.",
            "roles_validos": list(ROLES_VALIDOS)
        }), 422)

    tamano_obra = data.get("tamano_obra")
    if tamano_obra is not None and tamano_obra not in TAMANOS_OBRA_VALIDOS:
        return False, (jsonify({
            "error": "TAMANO_OBRA_INVALIDO",
            "detalle": f"'{tamano_obra}' no es un tamaño de obra reconocido.",
            "tamanos_validos": list(TAMANOS_OBRA_VALIDOS)
        }), 422)

    return True, None


def _extraer_nombre_obra(contexto: str) -> str:
    """Intenta extraer el nombre de la obra/instalación del contexto."""
    # Buscar patrones como "Obra: X", "Instalación: X", "Edificio X"
    patrones = [
        r'(?:Obra|Instalación|Edificio|Planta|Nave)\s*[:]\s*([^,.]+)',
        r'(?:Obra|Instalación|Edificio|Planta|Nave)\s+([^,.]+(?:[ ]?\d+)?)',
    ]
    for patron in patrones:
        match = re.search(patron, contexto, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "Instalación no especificada"


def _extraer_sector(contexto: str) -> str:
    """Intenta inferir el sector industrial del contexto."""
    sectores = {
        "construcción": "Construcción",
        "manufactura": "Manufactura",
        "industrial": "Manufactura",
        "almacén": "Almacenamiento",
        "oficina": "Oficinas",
        "miner": "Minería",
        "petrol": "Petróleo y Gas",
        "eléctric": "Energía Eléctrica",
    }
    contexto_lower = contexto.lower()
    for clave, sector in sectores.items():
        if clave in contexto_lower:
            return sector
    return "General"


def _adaptar_dictamen_abogado(dictamen_abogado: dict, firma_raw: str,
                               rol_supervisor: str, firma_criptografica: str,
                               fecha_reporte: str, reporte_forense_haiku: str = "") -> dict:
    """
    Adapta la salida de abogado_stps.generar_dictamen_legal() al formato
    que espera la tabla dictamenes_stps_v2.
    
    Mapeo de campos:
      abogado_stps          → tabla dictamenes_stps_v2
      ─────────────────────────────────────────────────
      tipificacion_legal     → tipificacion_legal
      severidad              → estado (mapeado: CRÍTICA→CRITICO, MEDIA→MEDIO, etc.)
      multa_estimada         → multa_minima / multa_maxima (extracción numérica)
      resumen_legal          → se incluye en dictamen_raw
      capacitacion_recomendada → se incluye en dictamen_raw
      tipo_instalacion       → se incluye en dictamen_raw
    """
    severidad = dictamen_abogado.get("severidad", "DESCONOCIDA")
    estado_mapeado = {
        "CRÍTICA": "CRITICO",
        "MEDIA": "MEDIO",
        "LLAMADA DE ATENCIÓN": "BAJO",
        "STRIKE": "BAJO",
        "DESCONOCIDA": "ND",
    }.get(severidad, "ND")

    # Extraer monto numérico de multa_estimada (ej: "$250,000 MXN" → 250000)
    multa_str = dictamen_abogado.get("multa_estimada", "$0 MXN")
    numeros = re.findall(r'[\d,]+', str(multa_str))
    multa_valor = 0
    if numeros:
        multa_valor = int(numeros[0].replace(",", ""))

    # Inferir responsabilidad patronal de la severidad
    responsabilidad = {
        "CRÍTICA": "DIRECTA",
        "MEDIA": "DIRECTA",
        "LLAMADA DE ATENCIÓN": "INDIRECTA",
        "STRIKE": "INDIRECTA",
    }.get(severidad, "ND")

    # Construir dictamen completo para almacenar en dictamen_raw
    dictamen_completo = {
        **dictamen_abogado,
        "auditoria_autorizacion": {
            "firmante_id": firma_raw,
            "rol_autorizado": rol_supervisor,
            "hash_legal": firma_criptografica,
            "fecha_reporte": fecha_reporte,
        },
        "reporte_forense_haiku": reporte_forense_haiku,
        "modelo_guardrail": "claude-haiku-4-5-20251001",
        "modelo_dictamen": "claude-sonnet-5",
    }

    return {
        "tipificacion_legal": dictamen_abogado.get("tipificacion_legal", "No especificada"),
        "responsabilidad_patronal": responsabilidad,
        "conclusiones": {
            "estado": estado_mapeado,
            "severidad_original": severidad,
            "cumplimiento_pct": 0,
        },
        "sancion_stps": {
            "multa_minima_estimada": multa_valor,
            "multa_maxima_estimada": multa_valor,
            "justificacion_legal": dictamen_abogado.get("resumen_legal", ""),
        },
        "plan_blindaje_legal": [
            {"prioridad": 1, "accion_defensa": dictamen_abogado.get("capacitacion_recomendada", "") or "Sin recomendación"}
        ],
        "dictamen_raw_full": dictamen_completo,
    }


def llamar_a_claude_y_guardar(dictamen_id, data, firma_criptografica):
    """
    Pipeline de dos pasos Atenea Lab Fase 1:
      1. Haiku (guardrail rápido): analiza la imagen → descripción textual forense
      2. Sonnet 5 (abogado_stps): recibe el texto → dictamen legal estructurado
    
    Actualiza el registro ya existente (insertado previamente como PENDIENTE).
    Esta función corre tanto en el hilo de background (modo rápido) como inline
    en el modo síncrono.
    """
    inicio = time.time()
    contexto_reportado = data.get("contexto", "Inspección de rutina")
    firma_raw = data.get("firma_digital", "OPERADOR_DESCONOCIDO")
    rol_supervisor = data.get("rol_supervisor", "OPERADOR")
    evidencia_b64 = data.get("evidencia", "")
    nombre_obra = _extraer_nombre_obra(contexto_reportado)
    sector = _extraer_sector(contexto_reportado)

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE dictamenes_stps_v2 SET estado_pipeline = 'PROCESANDO' WHERE id = ?",
            (dictamen_id,)
        )
        conn.commit()

    logger.info(f"⚙️  [Pipeline #{dictamen_id}] PROCESANDO — Paso 1/2: Haiku analizando imagen...")

    # ── PASO 1: Haiku — guardrail rápido sobre la imagen ──
    reporte_forense_haiku = ""
    try:
        respuesta_haiku = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            temperature=0.1,
            system="Eres un inspector de seguridad industrial. Describe en español de México, de forma concisa y forense, lo que observas en la imagen: condiciones inseguras, EPP faltante (casco, arnés, chaleco, botas, guantes), zonas de riesgo, maquinaria, trabajadores expuestos. Solo describe hechos observables. No emitas juicios legales.",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": evidencia_b64
                            }
                        },
                        {"type": "text", "text": f"Contexto adicional proporcionado por el operador: {contexto_reportado}"}
                    ]
                }
            ]
        )
        reporte_forense_haiku = respuesta_haiku.content[0].text
        logger.info(f"🔍 [Pipeline #{dictamen_id}] Haiku completó análisis forense ({len(reporte_forense_haiku)} chars).")
    except Exception as e:
        logger.warning(f"⚠️  [Pipeline #{dictamen_id}] Haiku falló: {e}. Usando solo contexto como reporte.")
        reporte_forense_haiku = f"[Análisis de imagen no disponible: {str(e)}] Contexto: {contexto_reportado}"

    # ── PASO 2: Sonnet 5 vía abogado_stps.py — dictamen legal ──
    logger.info(f"⚖️  [Pipeline #{dictamen_id}] Paso 2/2: Sonnet 5 generando dictamen legal...")

    metadatos_json = {
        "firma": firma_raw,
        "rol": rol_supervisor,
        "timestamp": data.get("fecha", datetime.now().isoformat()),
        "dictamen_id": dictamen_id,
    }

    try:
        dictamen_abogado = generar_dictamen_legal(
            reporte_forense=reporte_forense_haiku,
            metadatos_json=metadatos_json,
            nombre_obra=nombre_obra,
            sector=sector,
            imagen_base64=evidencia_b64,  # ← Pasar imagen original a Sonnet 5
            media_type="image/jpeg",
            tamano_obra=data.get("tamano_obra", "1-15"),
        )

        # Adaptar al formato que espera la BD
        dictamen_real = _adaptar_dictamen_abogado(
            dictamen_abogado, firma_raw, rol_supervisor,
            firma_criptografica, data.get("fecha", ""),
            reporte_forense_haiku
        )

        duracion = round(time.time() - inicio, 2)

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute('''UPDATE dictamenes_stps_v2 SET
                            tipificacion_legal = ?,
                            responsabilidad = ?,
                            estado = ?,
                            multa_minima = ?,
                            multa_maxima = ?,
                            dictamen_raw = ?,
                            estado_pipeline = 'DICTAMINADO',
                            timestamp_procesado = ?
                         WHERE id = ?''',
                      (dictamen_real.get('tipificacion_legal', 'No especificada'),
                       dictamen_real.get('responsabilidad_patronal', 'ND'),
                       dictamen_real.get('conclusiones', {}).get('estado', 'ND'),
                       dictamen_real.get('sancion_stps', {}).get('multa_minima_estimada', 0),
                       dictamen_real.get('sancion_stps', {}).get('multa_maxima_estimada', 0),
                       json.dumps(dictamen_real.get('dictamen_raw_full', dictamen_real), ensure_ascii=False),
                       datetime.now().isoformat(),
                       dictamen_id))
            conn.commit()

        logger.info(f"✅ [Pipeline #{dictamen_id}] DICTAMINADO en {duracion}s (Haiku+Sonnet5) — hash {firma_criptografica[:16]}...")
        return dictamen_real

    except json.JSONDecodeError as e:
        logger.error(f"❌ [Pipeline #{dictamen_id}] Sonnet 5 no devolvió JSON válido: {e}")
        _marcar_error(dictamen_id, f"JSON inválido de Sonnet 5: {e}")
        return None

    except Exception as e:
        logger.error(f"❌ [Pipeline #{dictamen_id}] Error en llamada a Sonnet 5: {e}")
        _marcar_error(dictamen_id, f"Error Sonnet 5: {str(e)}")
        return None


def _marcar_error(dictamen_id, detalle):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''UPDATE dictamenes_stps_v2 SET
                        estado_pipeline = 'ERROR',
                        error_detalle = ?,
                        timestamp_procesado = ?
                     WHERE id = ?''',
                  (detalle, datetime.now().isoformat(), dictamen_id))
        conn.commit()


def insertar_registro_pendiente(data, firma_criptografica):
    """Inserta la fila base en estado PENDIENTE. Se usa en ambos modos
    antes de invocar a Claude, así el historial siempre tiene rastro
    inmediato de que la captura llegó, incluso si Claude tarda o falla."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO dictamenes_stps_v2
                     (fecha, contexto, tipificacion_legal, responsabilidad, estado,
                      multa_minima, multa_maxima, dictamen_raw, firma_digital, rol_supervisor,
                      estado_pipeline, timestamp_recibido)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (data.get("fecha", datetime.now().isoformat()),
                   data.get("contexto", "Inspección de rutina"),
                   "Pendiente de análisis",
                   "ND",
                   "ND",
                   0,
                   0,
                   "{}",
                   data.get("firma_digital", "OPERADOR_DESCONOCIDO"),
                   data.get("rol_supervisor", "OPERADOR"),
                   "PENDIENTE",
                   datetime.now().isoformat()))
        conn.commit()
        return c.lastrowid


# ==========================================
# ENDPOINTS
# ==========================================

@app.route('/api/v1/health', methods=['GET'])
@limiter.limit("60 per minute")
def health():
    """
    Endpoint de salud con verificación de dependencias (Idea #54).
    Retorna 200 si todas las dependencias responden, 503 si alguna falla.
    
    Dependencias verificadas:
    - SQLite (SELECT 1)
    - Gemini API key (configuración, sin llamada HTTP)
    - Claude API key (configuración, sin llamada HTTP)
    - Disco (escritura temporal)

    Response 200:
    {
        "status": "healthy",
        "timestamp": "ISO8601",
        "checks": { ... },
        "version": "1.0.0"
    }

    Response 503:
    {
        "status": "degraded",
        "timestamp": "ISO8601",
        "checks": { ... },
        "version": "1.0.0"
    }
    """
    # ── SQLite ──
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("SELECT 1")
        sqlite_status = "ok"
    except Exception as e:
        sqlite_status = f"error: {e}"

    # ── Gemini API key ──
    gemini_key = os.environ.get("GOOGLE_API_KEY", "")
    if not gemini_key:
        gemini_status = "error: variable GOOGLE_API_KEY no configurada"
    else:
        try:
            # Solo verificar que el cliente se instancia (sin llamada HTTP)
            from forense_cctv import _get_cliente_cctv
            cliente = _get_cliente_cctv()
            gemini_status = "ok"
        except Exception as e:
            gemini_status = f"error: {e}"

    # ── Claude API key ──
    claude_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not claude_key:
        claude_status = "error: variable ANTHROPIC_API_KEY no configurada"
    else:
        claude_status = "ok"

    # ── Disco (escritura temporal) ──
    try:
        with tempfile.NamedTemporaryFile(mode="w", delete=True) as f:
            f.write("health_check")
            f.flush()
        disco_status = "ok"
    except Exception as e:
        disco_status = f"error: {e}"

    checks = {
        "sqlite": sqlite_status,
        "gemini_api_key": gemini_status,
        "claude_api_key": claude_status,
        "disco": disco_status,
    }

    # #75: Estado de cuota Gemini (no bloqueante — el health-check no falla por cuota)
    try:
        from forense_cctv import estado_cuota as _estado_cuota
        gemini_quota = _estado_cuota()
    except Exception:
        gemini_quota = {"estado": "error", "detalle": "No disponible"}

    todos_ok = all(v == "ok" for v in checks.values())
    http_code = 200 if todos_ok else 503
    status_label = "healthy" if todos_ok else "degraded"

    logger.info(
        "🔍 Health-check executed: %s (sqlite=%s gemini=%s claude=%s disco=%s)",
        status_label, sqlite_status, gemini_status, claude_status, disco_status,
    )

    return jsonify({
        "status": status_label,
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
        "gemini_quota": gemini_quota,
        "version": "1.0.0",
    }), http_code


@app.route('/api/v1/test-conexion', methods=['GET'])
@limiter.limit("60 per minute")
def test_conexion():
    """Legacy endpoint, kept for backward compatibility"""
    return jsonify({"status": "ok", "message": "Cerebro Atenea en línea ✅"}), 200


@app.route('/api/v1/orquestar-emergencia', methods=['POST'])
@limiter.limit("20 per minute")  # punto 14: rate limiting en endpoint de IA
def orquestar():
    """
    Endpoint principal para procesar emergencias/inspecciones con análisis IA.
    
    ▸ MODO "detallado" (default): Retorna 200 con dictamen completo (síncrono).
    ▸ MODO "rapido": Retorna 202 Accepted, procesa en background, usar polling con GET /api/v1/dictamen/<id>
    
    Request JSON (campos REQUERIDOS):
    {
        "evidencia": "<base64 image>",
        "contexto": "Descripción del evento",
        "fecha": "2025-06-20T10:30:00",
        "firma_digital": "operador_id",
        "rol_supervisor": "OPERADOR",
        "modo": "detallado",  # opcional: "rapido" o "detallado"
        "tamano_obra": "1-15"  # opcional: "1-15", "16-50" o "51+" (default "1-15")
    }
    
    Response 200 (modo detallado):
    {
        "status": "IA_ACTIVADA",
        "dictamen_id": 42,
        "dictamen": { ... dictamen JSON completo ... },
        "firma_criptografica": "hash_sha256"
    }
    
    Response 202 (modo rapido):
    {
        "status": "ACEPTADO",
        "dictamen_id": 42,
        "estado_pipeline": "PROCESANDO",
        "firma_criptografica": "hash_sha256",
        "mensaje": "Evidencia recibida. El dictamen se está generando..."
    }
    
    Response 422 (validación):
    {
        "error": "CAMPOS_FALTANTES",
        "detalle": "Faltan campos obligatorios: evidencia, fecha",
        "campos_requeridos": ["evidencia", "contexto", "fecha", "firma_digital", "rol_supervisor"]
    }
    """
    t_inicio_request = time.time()

    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "JSON_CORRUPTO", "detalle": str(e)}), 422

    es_valido, error_response = validar_payload(data)
    if not es_valido:
        return error_response

    rol_supervisor = data.get("rol_supervisor", "OPERADOR")
    firma_raw = data.get("firma_digital", "OPERADOR_DESCONOCIDO")
    firma_criptografica = generar_firma_criptografica(firma_raw, rol_supervisor, data)

    logger.info(f"📥 [Request] POST /orquestar-emergencia recibido — firma={firma_raw} rol={rol_supervisor}")

    # ── Modo de operación: "rapido" = 202 + background | "detallado"/ausente = síncrono ──
    modo = data.get("modo", "detallado")

    dictamen_id = insertar_registro_pendiente(data, firma_criptografica)
    logger.info(f"💾 [Pipeline #{dictamen_id}] PENDIENTE insertado (modo={modo}).")

    # ── Auditoría: registrar solicitud de dictamen ──
    firebase_uid = data.get("firebase_uid", firma_raw)
    registrar_auditoria(
        accion="dictamen_generado",
        resultado="pendiente",
        detalle=f"Dictamen #{dictamen_id} iniciado modo={modo} obra={_extraer_nombre_obra(data.get('contexto',''))}",
        firebase_uid=firebase_uid,
    )

    if modo == "rapido":
        hilo = threading.Thread(
            target=llamar_a_claude_y_guardar,
            args=(dictamen_id, data, firma_criptografica),
            daemon=True
        )
        hilo.start()

        duracion_respuesta = round(time.time() - t_inicio_request, 3)
        logger.info(f"📤 [Pipeline #{dictamen_id}] Respondiendo 202 en {duracion_respuesta}s — procesamiento continúa en background.")

        return jsonify({
            "status": "ACEPTADO",
            "dictamen_id": dictamen_id,
            "estado_pipeline": "PROCESANDO",
            "firma_criptografica": firma_criptografica,
            "mensaje": "Evidencia recibida. El dictamen se está generando, consulta el historial en unos segundos."
        }), 202

    else:
        dictamen_real = llamar_a_claude_y_guardar(dictamen_id, data, firma_criptografica)

        duracion_respuesta = round(time.time() - t_inicio_request, 2)

        if dictamen_real is None:
            registrar_auditoria(
                accion="dictamen_generado",
                resultado="error",
                detalle=f"Dictamen #{dictamen_id} falló tras {duracion_respuesta}s",
                firebase_uid=firebase_uid,
            )
            logger.error(f"📤 [Pipeline #{dictamen_id}] Respondiendo 500 tras {duracion_respuesta}s — falló el dictamen.")
            return jsonify({
                "error": "Fallo IA",
                "dictamen_id": dictamen_id,
                "detalle": "No se pudo procesar, intenta de nuevo."
            }), 500

        registrar_auditoria(
            accion="dictamen_generado",
            resultado="exito",
            detalle=f"Dictamen #{dictamen_id} completado en {duracion_respuesta}s — severidad={dictamen_real.get('conclusiones',{}).get('severidad_original','N/D')}",
            firebase_uid=firebase_uid,
        )
        logger.info(f"📤 [Pipeline #{dictamen_id}] Respondiendo 200 (síncrono) en {duracion_respuesta}s.")
        return jsonify({
            "status": "IA_ACTIVADA",
            "dictamen_id": dictamen_id,
            "dictamen": dictamen_real,
            "firma_criptografica": firma_criptografica
        }), 200


@app.route('/dashboard')
@limiter.limit("30 per minute")
def render_dashboard():
    return render_template('dashboard.html')


@app.route('/api/v1/denuncias-anonimas', methods=['POST'])
@limiter.limit("10 per minute")
def recibir_denuncia_anonima():
    """
    Recibe una denuncia anonima (NOM-035).
    NO lee el header Authorization (anonimato).
    Payload: {"categoria": str, "descripcion": str, "evidencia_url": str (opcional)}
    """
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "JSON_INVALIDO"}), 422

    categoria = data.get("categoria", "").strip()
    descripcion = data.get("descripcion", "").strip()
    evidencia_url = data.get("evidencia_url", "").strip()

    if not categoria or not descripcion:
        return jsonify({"error": "CAMPOS_REQUERIDOS", "detalle": "categoria y descripcion son obligatorios"}), 422

    ticket_id = secrets.token_hex(4).upper()
    ahora = datetime.now().isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO denuncias_anonimas (ticket_id, categoria, descripcion, evidencia_url, fecha, estado) "
            "VALUES (?, ?, ?, ?, ?, 'NUEVA')",
            (ticket_id, categoria, descripcion, evidencia_url, ahora),
        )
        conn.commit()
        fila_id = c.lastrowid

    logger.info(f" Denuncia anonima recibida: ticket={ticket_id} cat={categoria}")
    # NO se llama registrar_auditoria() porque guardaria firebase_uid

    return jsonify({"status": "RECIBIDA", "ticket_id": ticket_id}), 201


@app.route('/api/v1/denuncias-anonimas', methods=['GET'])
def listar_denuncias_anonimas():
    """Lista las denuncias anonimas (solo para Desk). NO requiere auth."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, ticket_id, categoria, descripcion, evidencia_url, fecha, estado "
            "FROM denuncias_anonimas ORDER BY id DESC"
        )
        filas = c.fetchall()
    return jsonify([{
        "id": f[0],
        "ticket_id": f[1],
        "categoria": f[2],
        "descripcion": f[3],
        "evidencia_url": f[4],
        "fecha": f[5],
        "estado": f[6],
    } for f in filas]), 200


@app.route('/api/v1/obtener-dictamenes', methods=['GET'])
@limiter.limit("60 per minute")
def obtener_dictamenes():
    """
    Retorna historial de dictamenes. Soporta filtro opcional.
    
    Query params:
    - estado: Filtrar por estado_pipeline (ej: PROCESANDO, DICTAMINADO, ERROR)
    
    Response 200:
    [
        {
            "id": 42,
            "fecha": "2025-06-20T10:30:00",
            "contexto": "Inspección...",
            "tipificacion_legal": "NOM-123-STPS",
            "responsabilidad": "DIRECTA",
            "estado": "CRITICO",
            "multa_minima": 1000,
            "multa_maxima": 5000,
            "firma_digital": "op_001",
            "rol_supervisor": "OPERADOR",
            "estado_pipeline": "DICTAMINADO",
            "timestamp_recibido": "2025-06-20T10:30:00.123",
            "timestamp_procesado": "2025-06-20T10:35:00.456",
            "error_detalle": ""
        }
    ]
    """
    filtro_estado = request.args.get('estado')

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        query = """SELECT id, fecha, contexto, tipificacion_legal, responsabilidad, estado,
                          multa_minima, multa_maxima, firma_digital, rol_supervisor,
                          estado_pipeline, timestamp_recibido, timestamp_procesado, error_detalle
                   FROM dictamenes_stps_v2"""
        params = ()
        if filtro_estado:
            query += " WHERE estado_pipeline = ?"
            params = (filtro_estado,)
        query += " ORDER BY id DESC"

        c.execute(query, params)
        filas = c.fetchall()

    resultados = [{
        "id": f[0],
        "fecha": f[1],
        "contexto": f[2],
        "tipificacion_legal": f[3],
        "responsabilidad": f[4],
        "estado": f[5],
        "multa_minima": f[6],
        "multa_maxima": f[7],
        "firma_digital": f[8],
        "rol_supervisor": f[9],
        "estado_pipeline": f[10],
        "timestamp_recibido": f[11],
        "timestamp_procesado": f[12],
        "error_detalle": f[13],
    } for f in filas]

    return jsonify(resultados), 200


@app.route('/api/v1/dictamen/<int:dictamen_id>', methods=['GET'])
@limiter.limit("60 per minute")
def obtener_dictamen_individual(dictamen_id):
    """
    Permite al móvil hacer polling puntual de un solo registro tras
    recibir un 202 (modo rapido), en vez de repetir la consulta completa del historial.
    
    Response 200:
    {
        "id": 42,
        "estado_pipeline": "DICTAMINADO",
        "dictamen": { ... dictamen JSON ... },
        "error_detalle": ""
    }
    
    Response 404: Si el dictamen no existe
    {
        "error": "NO_ENCONTRADO",
        "detalle": "El dictamen con ID 42 no existe."
    }
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''SELECT id, estado_pipeline, dictamen_raw, error_detalle
                     FROM dictamenes_stps_v2 WHERE id = ?''', (dictamen_id,))
        fila = c.fetchone()

    if fila is None:
        return jsonify({
            "error": "NO_ENCONTRADO",
            "detalle": f"El dictamen con ID {dictamen_id} no existe."
        }), 404

    return jsonify({
        "id": fila[0],
        "estado_pipeline": fila[1],
        "dictamen": json.loads(fila[2]) if fila[2] and fila[2] != "{}" else None,
        "error_detalle": fila[3]
    }), 200


# ==========================================
# ENDPOINTS NOM-035 (Psicosocial)
# ==========================================

@app.route('/api/v1/nom035/evaluar', methods=['POST'])
@limiter.limit("30 per minute")
@token_requerido
def nom035_evaluar():
    """
    POST /api/v1/nom035/evaluar — Recibe un cuestionario NOM-035,
    lo evalúa con el clasificador psicosocial y lo guarda en SQLite.

    Request JSON (Autenticado con Bearer token):
    {
        "company_id": "proj_001",
        "guia": "gi" | "gii" | "giii",
        "respuestas": { "1": 2, "2": 3, ... },
        "tam_empresa": "16-50" | "51+" (opcional, fuerza guía),
        "trabajador_id": "opcional",
        "nombre": "opcional",
        "puesto": "opcional"
    }

    Response 201:
    {
        "status": "EVALUADO",
        "evaluacion_id": 42,
        "nivel_riesgo": "MEDIO",
        "violencia_laboral": false,
        "porcentaje_global": 45.5,
        "requiere_profesional": false,
        "dominios": { ... },
        "alertas": [ ... ],
        "toolbox": "..." | null
    }
    """
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": "JSON_INVALIDO", "detalle": str(e)}), 422

    company_id = data.get("company_id", "").strip()
    guia = data.get("guia", "gi")
    respuestas = data.get("respuestas", {})
    tam_empresa = data.get("tam_empresa")
    trabajador_id = data.get("trabajador_id", "")
    nombre = data.get("nombre", "")
    puesto = data.get("puesto", "")

    if not company_id:
        return jsonify({"error": "CAMPOS_REQUERIDOS", "detalle": "company_id es obligatorio"}), 422
    if not respuestas or not isinstance(respuestas, dict):
        return jsonify({"error": "CAMPOS_REQUERIDOS", "detalle": "respuestas (dict) es obligatorio"}), 422

    try:
        resultado = evaluar(respuestas, guia=guia, tid=trabajador_id,
                            nom=nombre, puesto=puesto, tam=tam_empresa)
    except Exception as e:
        logger.error(f"❌ Error en clasificador psicosocial: {e}")
        return jsonify({"error": "ERROR_CLASIFICACION", "detalle": str(e)}), 500

    nivel = resultado.get("nv", "SR")
    violencia = 1 if resultado.get("viol", False) else 0
    prof = 1 if resultado.get("prof", False) else 0
    dominios_json = json.dumps(resultado.get("doms", {}), ensure_ascii=False)
    alertas = resultado.get("als", [])
    alertas_json = json.dumps(alertas, ensure_ascii=False)
    pctg = resultado.get("pctg", 0)
    fecha = datetime.now().isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO evaluaciones_nom035
                     (company_id, fecha, guia, nivel_riesgo, violencia_laboral,
                      porcentaje_global, requiere_profesional, dominios_json, alertas_json)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (company_id, fecha, guia, nivel, violencia,
                   pctg, prof, dominios_json, alertas_json))
        conn.commit()
        evaluacion_id = c.lastrowid

    logger.info(f"📊 NOM-035 evaluado #{evaluacion_id} — company={company_id} nivel={nivel}")

    return jsonify({
        "status": "EVALUADO",
        "evaluacion_id": evaluacion_id,
        "nivel_riesgo": nivel,
        "violencia_laboral": bool(violencia),
        "porcentaje_global": pctg,
        "requiere_profesional": bool(prof),
        "dominios": resultado.get("doms", {}),
        "alertas": alertas,
        "toolbox": resultado.get("tb"),
        "guia": resultado.get("guia"),
        "norma": "NOM-035-STPS",
    }), 201


@app.route('/api/v1/nom035/resumen', methods=['GET'])
@limiter.limit("60 per minute")
@token_requerido
def nom035_resumen():
    """
    GET /api/v1/nom035/resumen?company_id=proj_001 — Retorna agregado
    de evaluaciones NOM-035 filtrado por company_id.

    Query params:
    - company_id (requerido): ID del proyecto/empresa

    Response 200:
    {
        "total_evaluaciones": 42,
        "distribucion_niveles": { "SR": 10, "BAJO": 15, "MEDIO": 12, "ALTO": 5 },
        "pct_violencia": 7.1,
        "pct_requiere_profesional": 11.9,
        "dominios_criticos": [
            { "dominio": "carga_trabajo", "nivel": "ALTO", "pct_afectacion": 35.0 }
        ],
        "alertas_clinicas": [
            "Dom carga_trabajo: ALTO",
            "VIOLENCIA DETECTADA"
        ],
        "toolboxes_pendientes": 15,
        "ultima_evaluacion": "2025-07-29T12:00:00"
    }
    """
    company_id = request.args.get("company_id", "").strip()
    if not company_id:
        return jsonify({"error": "CAMPOS_REQUERIDOS", "detalle": "company_id es requerido como query param"}), 422

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''SELECT id, nivel_riesgo, violencia_laboral, porcentaje_global,
                            requiere_profesional, dominios_json, alertas_json, fecha
                     FROM evaluaciones_nom035
                     WHERE company_id = ?
                     ORDER BY id DESC''', (company_id,))
        filas = c.fetchall()

    total = len(filas)
    if total == 0:
        return jsonify({
            "total_evaluaciones": 0,
            "distribucion_niveles": {"SR": 0, "BAJO": 0, "MEDIO": 0, "ALTO": 0, "MUY_ALTO": 0},
            "pct_violencia": 0,
            "pct_requiere_profesional": 0,
            "dominios_criticos": [],
            "alertas_clinicas": [],
            "toolboxes_pendientes": 0,
            "ultima_evaluacion": None
        }), 200

    niveles = {"SR": 0, "BAJO": 0, "MEDIO": 0, "ALTO": 0, "MUY_ALTO": 0}
    violencia_count = 0
    prof_count = 0
    dominios_aggregated = {}
    alertas_set = set()
    toolboxes = 0
    ultima_fecha = filas[0][7]

    for f in filas:
        nv = f[1] if f[1] in niveles else "SR"
        niveles[nv] += 1
        violencia_count += f[2]
        prof_count += f[4]
        if not f[4]:
            # Sin requerir profesional → toolbox pendiente
            toolboxes += 1

        # Agregar dominios
        try:
            doms = json.loads(f[5]) if f[5] and f[5] != "{}" else {}
        except json.JSONDecodeError:
            doms = {}
        for dk, dv in doms.items():
            nv_dom = dv.get("nv", "SR") if isinstance(dv, dict) else "SR"
            if dk not in dominios_aggregated:
                dominios_aggregated[dk] = {"count": 0, "altos": 0}
            dominios_aggregated[dk]["count"] += 1
            if nv_dom in ("ALTO", "MUY_ALTO"):
                dominios_aggregated[dk]["altos"] += 1

        # Agregar alertas
        try:
            als = json.loads(f[6]) if f[6] and f[6] != "[]" else []
        except json.JSONDecodeError:
            als = []
        for a in als:
            alertas_set.add(a)

    dominios_criticos = [
        {"dominio": dk, "nivel": "ALTO" if dv["altos"] > 0 else "MEDIO",
         "pct_afectacion": round(dv["altos"] / dv["count"] * 100, 1)}
        for dk, dv in sorted(dominios_aggregated.items())
        if dv["altos"] > 0
    ]

    return jsonify({
        "total_evaluaciones": total,
        "distribucion_niveles": niveles,
        "pct_violencia": round(violencia_count / total * 100, 1),
        "pct_requiere_profesional": round(prof_count / total * 100, 1),
        "dominios_criticos": dominios_criticos,
        "alertas_clinicas": sorted(alertas_set),
        "toolboxes_pendientes": toolboxes,
        "ultima_evaluacion": ultima_fecha,
        "company_id": company_id,
        "norma": "NOM-035-STPS"
    }), 200


if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    logger.info("🚀 Iniciando Atenea Backend Fase 1 - Entrypoint único: main.py")
    logger.info(f"🔧 Modo debug: {'ACTIVADO' if debug_mode else 'DESACTIVADO'} (variable FLASK_DEBUG)")
    logger.info("📡 Endpoints disponibles:")
    logger.info("   GET  /api/v1/health")
    logger.info("   POST /api/v1/orquestar-emergencia")
    logger.info("   GET  /api/v1/dictamen/<id>")
    logger.info("   GET  /api/v1/obtener-dictamenes")
    logger.info("   POST /api/v1/denuncias-anonimas (anonimo, sin Auth)")
    logger.info("   GET  /api/v1/denuncias-anonimas")
    logger.info("   GET  /dashboard")
    app.run(host='0.0.0.0', port=5000, debug=debug_mode, threaded=True)
