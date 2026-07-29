"""
main.py — Entrypoint del backend de chat multiagente de Atenea Lab.

FastAPI + Uvicorn. Endpoints:
  - GET  /health          → Health check
  - POST /api/chat        → Chat multiagente (Claude/Gemini/DeepSeek) — requiere auth Premium

Uso:
  uvicorn main:app --host 0.0.0.0 --port 8000
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload   # desarrollo
"""

import os
import sys
import base64
import time
import logging
from datetime import datetime

from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Asegurar que core/ está en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Cargar variables de entorno desde .env (solo en desarrollo local)
load_dotenv()

from core.chat_multiagente import generar_respuesta_chat, llamar_gemini
from core.auth_middleware import verificar_acceso_premium
from agents_config import get_agent_config, list_agents, AGENT_DEFAULT_PROMPT, validate_credits, get_agent_credits, PROVIDER_CONFIG, OPENROUTER_BASE_URL, call_zhipu_direct
from talent_engine import calculate_ipa_components, build_match_prompt, build_skill_validation_prompt, MATCH_SYSTEM_PROMPT, SKILL_VALIDATION_PROMPT, SKILL_CATALOG, TALENT_ROLES

# ═══════════════════════════════════════════════════════════════════════════
# LOGGING — mismo formato y estructura que main.py original (Flask)
# ═══════════════════════════════════════════════════════════════════════════

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# APP FASTAPI
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Atenea Lab — Chat Multiagente",
    description="Backend de chat para Atenea Lab Desk. Soporta Claude, Gemini y DeepSeek con autenticación Premium.",
    version="1.0.0",
)

# ── CORS: permitir consumo desde el Desk desplegado en Vercel ──
ALLOWED_ORIGINS = [
    "https://app.atenealabmx.com",
    "http://localhost:5173",  # Para desarrollo local
    "https://ateneadesk.vercel.app" # Por si acaso
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate Limiter: 20 req/min por IP (mismo patrón que flask-limiter en main.py) ──
limiter = Limiter(key_func=get_remote_address, default_limits=["20 per minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: HTTPException(status_code=429, detail="Demasiadas solicitudes. Espera un momento antes de intentar de nuevo."))

# ── Moderación backend (doble verificación, frontend + backend) ──
ABUSIVE_KEYWORDS = [
    "puta", "puto", "mierda", "pendejo", "cabrón", "chinga", "verga",
    "idiota", "imbécil", "estúpido", "fuck", "shit", "bitch", "asshole",
]
ILLEGAL_KEYWORDS = [
    "droga", "narcótico", "fraude", "soborno", "evadir", "ilegal",
    "hack", "pirate", "crack", "keygen", "lavado de dinero",
]
JAILBREAK_PATTERNS = [
    "ignora las instrucciones", "eres un", "actúa como", "eres ahora",
    "modo desarrollador", "developer mode", "dismiss previous",
    "olvida todo", "reset prompt",
]
MEDICAL_PATTERNS = [
    "me duele", "sangre", "fractura", "quemadura", "convulsión",
    "infarto", "paro cardíaco", "accidente grave",
]

MODERATION_RESPONSES = {
    "abusive": "No puedo responder a mensajes con lenguaje ofensivo. Si tienes una duda sobre cómo usar Atenea Lab Desk, por favor reformúlala con respeto y con gusto te ayudo.",
    "illegal": "No puedo ayudar con eso. Atenea Lab es una plataforma de seguridad industrial y cumplimiento normativo. Si necesitas asistencia legal real, contacta a tu supervisor o a la STPS.",
    "jailbreak": "Soy un asistente de capacitación de Atenea Lab Desk. Solo puedo ayudarte con dudas sobre el uso de la plataforma.",
    "medical": "No puedo evaluar situaciones reales de seguridad. Si hay un riesgo inminente, sigue tu protocolo de emergencia y contacta a tu supervisor de seguridad.",
}


async def call_glm_direct(prompt: str, agent_config: dict) -> str:
    """
    Llama directamente a la API de Zhipu (BigModel) para GLM 5.2 usando GLM_API_KEY.

    Args:
        prompt: Texto del usuario (último mensaje).
        agent_config: Configuración del agente GLM (de AGENT_TYPE_MAPPING).

    Returns:
        str con el contenido de la respuesta del modelo.

    Raises:
        RuntimeError: si GLM_API_KEY no está configurada o falla la petición.
    """
    import os
    import time
    import aiohttp

    api_key = os.environ.get("GLM_API_KEY", "")
    if not api_key:
        raise RuntimeError("GLM_API_KEY no configurada en variables de entorno")

    glm_provider_cfg = PROVIDER_CONFIG.get("glm", {})
    base_url_direct = glm_provider_cfg.get(
        "base_url_direct", "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    )
    model_name_direct = glm_provider_cfg.get("model_name_direct", "glm-5.2")
    system_prompt = agent_config.get("prompt", "")

    inicio = time.time()
    openai_messages = []
    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})
    openai_messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_name_direct,
        "messages": openai_messages,
        "max_tokens": glm_provider_cfg.get("max_tokens", 2048),
        "temperature": glm_provider_cfg.get("temperature", 0.7),
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                base_url_direct, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"GLM Direct HTTP {resp.status}: {error_text[:200]}")
                data = await resp.json()
                duracion = round(time.time() - inicio, 2)
                contenido = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                uso = data.get("usage", {})
                logger.info(
                    "🟢 [GLM-DIRECT] %s | %d in / %d out tokens | %.2fs",
                    model_name_direct,
                    uso.get("prompt_tokens", 0),
                    uso.get("completion_tokens", 0),
                    duracion,
                )
                return contenido
    except aiohttp.ClientError as e:
        logger.error("❌ [GLM-DIRECT] Error de conexión: %s", e)
        raise RuntimeError(f"GLM Direct no disponible: {e}") from e


async def call_tokenhub_direct(prompt: str, agent_config: dict) -> str:
    """
    Llama directamente a TokenHub (Tencent Cloud MAAS) para Hy3.
    Chat Completions API estandar. Usa TOKENHUB_API_KEY.

    Args:
        prompt: Texto del usuario (ultimo mensaje).
        agent_config: Configuración del agente Hunyuan (de AGENT_TYPE_MAPPING / PROVIDER_CONFIG).

    Returns:
        str con el contenido de la respuesta del modelo.

    Raises:
        RuntimeError: si TOKENHUB_API_KEY no esta configurada o falla la peticion.
    """
    import os
    import time
    import aiohttp

    api_key = os.environ.get("TOKENHUB_API_KEY", "")
    if not api_key:
        raise RuntimeError("TOKENHUB_API_KEY no configurada en variables de entorno")

    hy3_cfg = PROVIDER_CONFIG.get("hunyuan", {})
    base_url = hy3_cfg.get("base_url_direct", "https://tokenhub-intl.tencentcloudmaas.com/v1/chat/completions")
    model_id = hy3_cfg.get("model_direct", "hy3")
    system_prompt = agent_config.get("prompt", "")

    inicio = time.time()
    openai_messages = []
    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})
    openai_messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_id,
        "messages": openai_messages,
        "max_tokens": hy3_cfg.get("max_tokens", 2048),
        "temperature": hy3_cfg.get("temperature", 0.7),
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                base_url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"TokenHub HTTP {resp.status}: {error_text[:200]}")
                data = await resp.json()
                duracion = round(time.time() - inicio, 2)
                contenido = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                uso = data.get("usage", {})
                logger.info(
                    "🟣 [TOKENHUB] %s | %d in / %d out tokens | %.2fs",
                    model_id,
                    uso.get("prompt_tokens", 0),
                    uso.get("completion_tokens", 0),
                    duracion,
                )
                return contenido
    except aiohttp.ClientError as e:
        logger.error("❌ [TOKENHUB] Error de conexión: %s", e)
        raise RuntimeError(f"TokenHub no disponible: {e}") from e


def detectar_categoria_backend(texto: str) -> str | None:
    """Verifica un mensaje contra las 4 categorías de moderación. Retorna la categoría o None."""
    t = texto.lower()
    if any(k in t for k in ABUSIVE_KEYWORDS):
        return "abusive"
    if any(k in t for k in ILLEGAL_KEYWORDS):
        return "illegal"
    if any(p in t for p in JAILBREAK_PATTERNS):
        return "jailbreak"
    if any(p in t for p in MEDICAL_PATTERNS):
        return "medical"
    return None


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/health")
async def health():
    """
    Health check del backend de chat.

    Response 200:
    {
        "status": "ok",
        "message": "Atenea Chat Backend en línea ✅",
        "timestamp": "2026-07-12T19:00:00.123456"
    }
    """
    return {
        "status": "ok",
        "message": "Atenea Chat Backend en línea ✅",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/")
async def root():
    return {
        "message": "¡Bienvenido al Cerebro IA de Atenea Lab! 🧠🇲🇽",
        "status": "online",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/api/agents")
async def agents_list_endpoint():
    """
    Lista los agentes disponibles con sus etiquetas y descripciones.
    No requiere autenticación (informativo para el frontend).

    Response 200:
    {
        "agents": [
            {"type": "vision", "label": "👁 Inspector (Foto/Audio)", "description": "..."},
            {"type": "legal", "label": "⚖ Legal (STPS)", "description": "..."},
            {"type": "analytics", "label": "📊 Analítico (Datos)", "description": "..."}
        ],
        "default": "legal"
    }
    """
    return {
        "agents": list_agents(),
        "default": "deepseek",
    }


@app.post("/api/chat")
@limiter.limit("20/minute")
async def chat_endpoint(
    request: Request,
    user: dict = Depends(verificar_acceso_premium),
):
    """
    Endpoint principal de chat multiagente — requiere autenticación Premium.

    Headers requeridos:
        Authorization: Bearer <firebase_id_token>

    Request JSON:
    {
        "model": "claude" | "gemini" | "deepseek",
        "messages": [
            {"role": "user" | "assistant", "content": "..."}
        ],
        "context": {                          // opcional
            "userId": "string",
            "role": "string"
        }
    }

    Response 200:
    {
        "content": "Respuesta del modelo...",
        "model": "claude-sonnet-4-6",
        "tokens_entrada": 42,
        "tokens_salida": 150,
        "costo_usd": 0.002376,
        "tiempo_s": 1.23
    }

    Response 401: Token inválido o faltante
    Response 403: Usuario sin plan Premium
    Response 422: Body inválido o modelo no soportado
    Response 500: Error del proveedor de IA
    """
    t_inicio = time.time()
    uid = user.get("uid", "desconocido")
    email = user.get("email", "desconocido")

    # Parsear body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Body inválido. Se requiere JSON válido.")

    agent_type = body.get("agent_type", "deepseek").strip()  # Default: DeepSeek (más barato)
    model = body.get("model", "").strip()
    messages = body.get("messages", [])
    context = body.get("context", {})

    # Determinar configuración del agente según agent_type
    agent_config = get_agent_config(agent_type if agent_type else "deepseek")

    # ── Middleware de Créditos Atenea ──
    company_id = context.get("companyId") or user.get("company_id", "")
    credits_balance = context.get("creditsBalance", 999)  # TODO: leer de Firestore en producción
    is_valid, credit_msg = validate_credits(agent_type, credits_balance)
    if not is_valid:
        raise HTTPException(status_code=402, detail=credit_msg)

    # Si no se especifica model explícito, usar el del agente
    if not model:
        model = agent_config["model"]

    # Validar modelo resultante
    VALID_MODELS = ("claude", "gemini", "deepseek", "glm", "flash", "hunyuan", "kimi", "minimax", "glm52")
    if model not in VALID_MODELS:
        raise HTTPException(
            status_code=422,
            detail=f"Modelo '{model}' no válido. Opciones: {', '.join(VALID_MODELS)}. Usa agent_type en vez de model.",
        )

    if not messages or not isinstance(messages, list):
        raise HTTPException(
            status_code=422,
            detail="Campo 'messages' requerido. Debe ser una lista de mensajes.",
        )

    # Validar formato de messages
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
            raise HTTPException(
                status_code=422,
                detail=f"Mensaje {i} inválido. Cada mensaje requiere 'role' y 'content'.",
            )
        if msg["role"] not in ("user", "assistant"):
            raise HTTPException(
                status_code=422,
                detail=f"Mensaje {i}: role '{msg['role']}' inválido. Usa 'user' o 'assistant'.",
            )

    # ══════════════════════════════════════════════════════════════
    # DOBLE VERIFICACIÓN DE MODERACIÓN (backend, después del frontend)
    # ══════════════════════════════════════════════════════════════
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            cat = detectar_categoria_backend(msg.get("content", ""))
            if cat:
                logger.warning(
                    "🛡️ [MODERACIÓN] user=%s categoria=%s msg_preview=%.80s",
                    uid, cat, msg["content"][:80],
                )
                return {
                    "content": MODERATION_RESPONSES[cat],
                    "model": "moderation_block",
                    "tokens_entrada": 0,
                    "tokens_salida": 0,
                    "costo_usd": 0.0,
                    "tiempo_s": 0.0,
                    "moderado": True,
                    "categoria": cat,
                }

    # System prompt: usa el prompt del agente seleccionado
    system_prompt = agent_config["prompt"]

    # Si el agente es legal, inyectar contexto de NOMs mexicanas
    if agent_type == "legal":
        try:
            import json, os
            noms_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "noms_mexico.json")
            if os.path.exists(noms_path):
                with open(noms_path, "r", encoding="utf-8") as f:
                    noms_data = json.load(f)
                noms_context = "BASE DE CONOCIMIENTO DE NOMs MEXICANAS:\n\n"
                for nom in noms_data:
                    noms_context += (
                        f"📋 {nom['id']} — {nom['nombre']}\n"
                        f"   Aplicación: {nom.get('aplicacion', 'General')}\n"
                        f"   Puntos críticos: {nom.get('puntos_criticos_resumen', 'No disponible')}\n\n"
                    )
                system_prompt = f"{noms_context}\n\n{system_prompt}"
        except Exception as e:
            logger.warning("⚠️ No se pudo cargar NOMs context: %s", e)

    # Log de auditoría (mismo formato que bitacora_atenea.log del backend Flask)
    logger.info(
        "📥 [CHAT] user=%s email=%s agent=%s model=%s msgs=%d",
        uid, email, agent_type, model, len(messages),
    )

    # Invocar al proveedor de IA
    try:
        # Enrutamiento directo a Zhipu AI (GLM-4, GLM-4-Flash, Kimi, Minimax, GLM 5.2)
        if agent_type in ("glm", "flash", "kimi", "minimax", "glm52"):
            zhipu_cfg = PROVIDER_CONFIG.get(agent_type, {})
            zhipu_model = zhipu_cfg.get("model_name", "glm-4")
            resultado = await call_zhipu_direct(
                model=zhipu_model,
                messages=messages,
                system_prompt=system_prompt,
            )
            duracion_total = round(time.time() - t_inicio, 2)
            return {
                "content": resultado["content"],
                "model": zhipu_model,
                "tokens_entrada": resultado["tokens_entrada"],
                "tokens_salida": resultado["tokens_salida"],
                "costo_usd": 0.0,
                "tiempo_s": duracion_total,
            }

        # Enrutamiento directo a TokenHub (Hy3) — unica ruta valida
        if agent_type == "hunyuan":
            hy3_cfg = PROVIDER_CONFIG.get("hunyuan", {})
            prompt = ""
            for m in reversed(messages):
                if m["role"] == "user":
                    prompt = m["content"]
                    break
            contenido = await call_tokenhub_direct(prompt=prompt, agent_config=agent_config)
            duracion_total = round(time.time() - t_inicio, 2)
            return {
                "content": contenido,
                "model": hy3_cfg.get("model_direct", "hy3"),
                "tokens_entrada": 0,
                "tokens_salida": 0,
                "costo_usd": 0.0,
                "tiempo_s": duracion_total,
            }

        # Cualquier otro caso (deepseek, claude, gemini)
        resultado = await generar_respuesta_chat(
            model=model,
            messages=messages,
            system_prompt=system_prompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    duracion_total = round(time.time() - t_inicio, 2)

    # Log de auditoría (respuesta exitosa)
    logger.info(
        "📤 [CHAT] user=%s model=%s tokens_in=%d tokens_out=%d costo=$%.6f tiempo=%.2fs",
        uid,
        resultado["model"],
        resultado["tokens_entrada"],
        resultado["tokens_salida"],
        resultado["costo_usd"],
        duracion_total,
    )

    return {
        "content": resultado["content"],
        "model": resultado["model"],
        "tokens_entrada": resultado["tokens_entrada"],
        "tokens_salida": resultado["tokens_salida"],
        "costo_usd": resultado["costo_usd"],
        "tiempo_s": duracion_total,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINT: Inspección Visual (Gemini Vision)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/vision/inspect")
async def vision_inspect_endpoint(
    image: UploadFile = File(...),
    context: str = Form(""),
):
    """
    Endpoint de inspección visual con IA.
    Recibe una imagen y un contexto opcional, la analiza con Gemini Vision
    y retorna hallazgos de seguridad estructurados.

    Request: multipart/form-data
        - image: archivo de imagen (JPEG/PNG)
        - context: string opcional (ej: "Verificar uso de EPP en andamio")

    Response 200:
    {
        "hallazgos": "texto estructurado con hallazgos",
        "nivel_riesgo": "Alto" | "Medio" | "Bajo",
        "nom_aplicable": "NOM-017-STPS-2008, NOM-009-STPS-2011",
        "accion_recomendada": "texto con acción correctiva"
    }

    Response 400: Error del proveedor o imagen no válida
    """
    import base64

    t_inicio = time.time()

    # Validar tipo de imagen
    contenido = await image.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="Imagen vacía o no proporcionada.")

    content_type = image.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"Tipo de archivo no soportado: {content_type}. Usa JPEG o PNG.")

    # Convertir a Base64
    img_b64 = base64.b64encode(contenido).decode("utf-8")
    data_uri = f"data:{content_type};base64,{img_b64}"

    # Obtener configuración del agente visión
    agent_config = get_agent_config("vision")
    system_prompt = agent_config["prompt"]

    # Construir prompt con contexto
    user_prompt = "Analiza esta imagen de seguridad industrial."
    if context:
        user_prompt = f"Contexto del inspector: {context}\n\nAnaliza esta imagen de seguridad industrial e identifica riesgos, EPP faltante, o condiciones inseguras."

    # Construir mensajes para Gemini (formato multimodal)
    messages = [
        {
            "role": "user",
            "content": f"{user_prompt}\n\n[IMAGEN ADJUNTA EN BASE64 - {len(contenido)} bytes]",
        }
    ]

    logger.info("📸 [VISION] analizando imagen (%d bytes) contexto=%.60s", len(contenido), context[:60])

    try:
        # Llamar a Gemini con la imagen en Base64
        resultado = await llamar_gemini(messages, system_prompt)

        # Parsear respuesta estructurada
        contenido_texto = resultado.get("content", "")

        # Extraer nivel de riesgo
        nivel_riesgo = "Medio"
        if any(w in contenido_texto.lower() for w in ["alto", "crítico", "grave", "inminente", "urgente"]):
            nivel_riesgo = "Alto"
        elif any(w in contenido_texto.lower() for w in ["bajo", "leve", "mínimo", "sin riesgo"]):
            nivel_riesgo = "Bajo"

        # Extraer NOMs mencionadas
        import re
        noms_encontradas = re.findall(r'NOM-\d{3}-STPS-\d{4}', contenido_texto)
        nom_aplicable = ", ".join(noms_encontradas) if noms_encontradas else "NOM-017-STPS-2008 (EPP)"

        duracion = round(time.time() - t_inicio, 2)

        logger.info("📸 [VISION] completado en %.2fs | riesgo=%s | noms=%s", duracion, nivel_riesgo, nom_aplicable)

        return {
            "hallazgos": contenido_texto,
            "nivel_riesgo": nivel_riesgo,
            "nom_aplicable": nom_aplicable,
            "accion_recomendada": "Verificar los hallazgos detectados y aplicar las NOMs correspondientes.",
            "tiempo_s": duracion,
        }

    except RuntimeError as e:
        logger.error("❌ [VISION] Error del proveedor: %s", e)
        raise HTTPException(status_code=400, detail=f"Error al procesar la imagen: {e}")
    except Exception as e:
        logger.error("❌ [VISION] Error inesperado: %s", e)
        raise HTTPException(status_code=500, detail="Error interno al analizar la imagen.")


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS: ATENEA TALENT — IPA, Matching, Validación de Habilidades
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/talent/calculate-ipa")
async def talent_calculate_ipa(request: Request):
    """
    Calcula el Índice de Potencial Atenea (IPA) para un usuario.
    
    Request JSON:
    {
        "uid": "firebase_uid",
        "cursos_completados": 5,
        "cuestionarios_aprobados": 8,
        "reportes_nearmiss": 12,
        "charlas_asistidas": 20,
        "karma_supervisor": 75,
        "sellos_habilidad": 3,
        "horas_capacitacion": 40
    }

    Response 200:
    {
        "ipa_total": 750,
        "aprendizaje": 320,
        "actitud_valores": 275,
        "habilidad_ia": 225,
        "nivel": "Avanzado",
        "badges": ["🎓 Aprendiz Dedicado", "🛡️ Guardián de Seguridad", ...]
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Body inválido. Se requiere JSON válido.")

    profile = {
        "cursos_completados": body.get("cursos_completados", 0),
        "cuestionarios_aprobados": body.get("cuestionarios_aprobados", 0),
        "reportes_nearmiss": body.get("reportes_nearmiss", 0),
        "charlas_asistidas": body.get("charlas_asistidas", 0),
        "karma_supervisor": body.get("karma_supervisor", 0),
        "sellos_habilidad": body.get("sellos_habilidad", 0),
        "horas_capacitacion": body.get("horas_capacitacion", 0),
    }

    resultado = calculate_ipa_components(profile)
    logger.info("🧠 [TALENT] IPA calculado: %d (%s)", resultado["ipa_total"], resultado["nivel"])

    return resultado


@app.post("/api/talent/match")
async def talent_match(request: Request):
    """
    Matching semántico de talento usando DeepSeek.
    Evalúa potencial, NO años de experiencia.

    Request JSON:
    {
        "candidato": { "ipa": {...}, "sellos": [...] },
        "requisitos": { "ipa_minimo": 500, "habilidades": [...], "valores": [...] }
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Body inválido.")

    candidato = body.get("candidato", {})
    requisitos = body.get("requisitos", {})

    if not candidato or not requisitos:
        raise HTTPException(status_code=422, detail="Se requieren 'candidato' y 'requisitos'.")

    prompt = build_match_prompt(candidato, requisitos)
    messages = [{"role": "user", "content": prompt}]

    try:
        resultado = await generar_respuesta_chat(
            model="deepseek",
            messages=messages,
            system_prompt=MATCH_SYSTEM_PROMPT,
        )
        return {
            "match_result": resultado.get("content", ""),
            "model": resultado.get("model", "deepseek-chat"),
        }
    except Exception as e:
        logger.error("❌ [TALENT] Error en matching: %s", e)
        raise HTTPException(status_code=500, detail=f"Error en matching: {e}")


@app.post("/api/talent/validate-skill")
async def talent_validate_skill(request: Request):
    """
    Valida una habilidad demostrada por un trabajador usando IA.
    Si aprueba, otorga un "Sello de Habilidad" que sube el IPA.

    Request JSON:
    {
        "habilidad": "Manejo de Montacargas",
        "evidencia": "descripción o transcripción de video/audio"
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Body inválido.")

    habilidad = body.get("habilidad", "")
    evidencia = body.get("evidencia", "")

    if not habilidad or not evidencia:
        raise HTTPException(status_code=422, detail="Se requieren 'habilidad' y 'evidencia'.")

    prompt = build_skill_validation_prompt(habilidad, evidencia)
    messages = [{"role": "user", "content": prompt}]

    try:
        resultado = await generar_respuesta_chat(
            model="claude",
            messages=messages,
            system_prompt=SKILL_VALIDATION_PROMPT,
        )
        return {
            "validacion": resultado.get("content", ""),
            "model": resultado.get("model", "claude-sonnet"),
        }
    except Exception as e:
        logger.error("❌ [TALENT] Error en validación: %s", e)
        raise HTTPException(status_code=500, detail=f"Error en validación: {e}")


@app.get("/api/talent/skills")
async def talent_skills_catalog():
    """Retorna el catálogo de habilidades y sellos disponibles."""
    return {
        "skills": SKILL_CATALOG,
        "total": len(SKILL_CATALOG),
    }


@app.get("/api/talent/roles")
async def talent_roles_catalog():
    """Retorna los roles de talento disponibles en la plataforma."""
    return {"roles": TALENT_ROLES}


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINT: Webhook de WhatsApp (Ingesta de campo)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/webhooks/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Webhook para recibir mensajes de WhatsApp (Twilio/Meta API).
    Procesa texto e imágenes desde el campo y los estructura como reportes.

    Request JSON:
    {
        "from": "+5215551234567",
        "body": "Se cayó un andamio en la nave 3",
        "image_url": "https://..."  // opcional
    }

    Response 200:
    {
        "ticket_type": "incidente",
        "resumen": "texto estructurado",
        "nivel_riesgo": "Alto" | "Medio" | "Bajo",
        "datos_extraidos": {...}
    }
    """
    import base64
    import re

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Body inválido. Se requiere JSON válido.")

    from_number = body.get("from", "desconocido")
    message_body = body.get("body", "")
    image_url = body.get("image_url", "")

    if not message_body and not image_url:
        raise HTTPException(status_code=422, detail="Se requiere 'body' o 'image_url' en el payload.")

    logger.info("📱 [WHATSAPP] from=%s body=%.80s image=%s", from_number, message_body[:80], bool(image_url))

    # ── Si hay imagen, enviar al Agente Visión ──
    if image_url:
        try:
            import urllib.request

            # Descargar imagen desde URL
            req = urllib.request.Request(image_url, headers={"User-Agent": "AteneaLab/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                img_bytes = resp.read()

            img_b64 = base64.b64encode(img_bytes).decode("utf-8")
            context = message_body or "Reporte de campo vía WhatsApp"
            user_prompt = f"Contexto del reporte de campo: {context}\n\nAnaliza esta imagen de condiciones de seguridad."

            agent_config = get_agent_config("vision")
            messages = [{"role": "user", "content": f"{user_prompt}\n\n[IMAGEN ADJUNTA]"}]

            resultado = await llamar_gemini(messages, agent_config["prompt"])
            hallazgos = resultado.get("content", "No se pudieron analizar los hallazgos.")

            return {
                "ticket_type": "inspeccion_visual",
                "resumen": hallazgos,
                "nivel_riesgo": "Medio",
                "origen": f"whatsapp:{from_number}",
                "datos_extraidos": {
                    "telefono": from_number,
                    "mensaje_original": message_body[:200],
                    "imagen_procesada": True,
                },
            }

        except Exception as e:
            logger.error("❌ [WHATSAPP] Error procesando imagen: %s", e)
            raise HTTPException(status_code=400, detail=f"Error al procesar la imagen: {e}")

    # ── Solo texto: estructurar como reporte con Agente Legal ──
    agent_config = get_agent_config("legal")
    structuring_prompt = (
        f"Estructura el siguiente mensaje de WhatsApp como un reporte de incidente de seguridad:\n\n"
        f"Mensaje: \"{message_body}\"\n\n"
        f"Responde en formato JSON con: tipo_incidente, descripcion, nivel_riesgo (Alto/Medio/Bajo), "
        f"ubicacion (si se menciona), personas_involucradas (si se menciona), accion_inmediata."
    )

    messages = [{"role": "user", "content": structuring_prompt}]

    try:
        resultado = await generar_respuesta_chat(
            model="claude",
            messages=messages,
            system_prompt=agent_config["prompt"],
        )

        contenido = resultado.get("content", "")

        # Intentar parsear JSON de la respuesta
        datos = {
            "ticket_type": "incidente",
            "resumen": contenido,
            "nivel_riesgo": "Medio",
            "origen": f"whatsapp:{from_number}",
            "datos_extraidos": {
                "telefono": from_number,
                "mensaje_original": message_body[:200],
            },
        }

        # Detectar nivel de riesgo del texto
        if any(w in message_body.lower() for w in ["cayó", "fuego", "explosión", "muerto", "herido", "grave", "accidente"]):
            datos["nivel_riesgo"] = "Alto"
        elif any(w in message_body.lower() for w in ["falta", "roto", "vencido", "sin", "peligro"]):
            datos["nivel_riesgo"] = "Medio"

        return datos

    except Exception as e:
        logger.error("❌ [WHATSAPP] Error del agente: %s", e)
        raise HTTPException(status_code=500, detail=f"Error al procesar el mensaje: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ENTRYPOINT (ejecución directa con python main.py)
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("DEBUG", "False").lower() == "true"

    logger.info("🚀 Iniciando Atenea Chat Backend (FastAPI)")
    logger.info("🔧 Debug: %s", "ACTIVADO" if debug else "DESACTIVADO")
    logger.info("📡 Endpoints disponibles:")
    logger.info("   GET  /health")
    logger.info("   POST /api/chat  (requiere auth Premium)")
    logger.info("🌐 CORS allowed origins: %s", ALLOWED_ORIGINS)

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=debug,
    )  
