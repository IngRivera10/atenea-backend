"""
auth_middleware.py — Middleware de autenticación Firebase para el backend de chat.

Verifica que cada petición incluya un ID Token válido de Firebase Auth
y que el usuario tenga plan Premium (o rol admin) antes de permitir
el acceso al endpoint /api/chat.

El Admin SDK ignora las reglas de Firestore — acceso total al backend.
"""

import os
import logging
from typing import Optional

import firebase_admin
from firebase_admin import auth, firestore

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# INICIALIZAR FIREBASE ADMIN SDK
# ═══════════════════════════════════════════════════════════════════════════

_firebase_initialized = False


def _init_firebase():
    """Inicializa el Admin SDK usando la variable de entorno GOOGLE_APPLICATION_CREDENTIALS
    o el archivo de service account del proyecto Firebase."""
    global _firebase_initialized
    if _firebase_initialized:
        return

    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

    if cred_path and os.path.isfile(cred_path):
        cred = firebase_admin.credentials.Certificate(cred_path)
        logger.info("🔐 Firebase Admin inicializado con: %s", os.path.basename(cred_path))
    else:
        # Intentar con credenciales por defecto (Google Cloud environment)
        logger.warning(
            "⚠️ GOOGLE_APPLICATION_CREDENTIALS no encontrado en %s. "
            "Usando credenciales por defecto de Google Cloud.", cred_path
        )
        cred = None

    firebase_admin.initialize_app(cred)
    _firebase_initialized = True


# ═══════════════════════════════════════════════════════════════════════════
# FUNCIÓN DE VERIFICACIÓN DE ID TOKEN
# ═══════════════════════════════════════════════════════════════════════════


def verificar_id_token(id_token: str) -> dict:
    """
    Verifica un ID Token de Firebase Auth y retorna el payload decodificado.

    Args:
        id_token: El token JWT enviado por el cliente (Firebase Auth)

    Returns:
        dict con uid, email, etc.

    Raises:
        ValueError: Si el token es inválido, expirado o revocado
    """
    try:
        decoded = auth.verify_id_token(id_token)
        logger.debug("🔐 Token verificado: uid=%s email=%s", decoded.get("uid"), decoded.get("email"))
        return decoded
    except auth.ExpiredIdTokenError:
        raise ValueError("Token expirado. Vuelve a iniciar sesión.")
    except auth.RevokedIdTokenError:
        raise ValueError("Token revocado. Vuelve a iniciar sesión.")
    except auth.InvalidIdTokenError:
        raise ValueError("Token inválido. Vuelve a iniciar sesión.")
    except Exception as e:
        logger.error("❌ Error verificando token: %s", e)
        raise ValueError(f"Error de autenticación: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# FUNCIÓN DE VERIFICACIÓN DE PLAN PREMIUM
# ═══════════════════════════════════════════════════════════════════════════


def verificar_plan_premium(uid: str) -> bool:
    """
    Verifica que el usuario tenga plan Premium o rol admin en Firestore.

    El campo 'plan' puede ser 'free' o 'premium'.
    El campo 'role' puede ser 'admin', 'gerente', 'supervisor', 'tecnico'.
    Los admins tienen acceso Premium implícito (confirmado en auth.js del Desk).

    Args:
        uid: El UID del usuario verificado

    Returns:
        True si el usuario tiene acceso (premium o admin), False si es free

    Raises:
        RuntimeError: Si no se puede consultar Firestore
    """
    try:
        db = firestore.client()
        doc_ref = db.collection("users").document(uid)
        doc = doc_ref.get()

        if not doc.exists:
            logger.warning("⚠️ Usuario %s no encontrado en Firestore", uid)
            return False

        user_data = doc.to_dict()
        plan = user_data.get("plan", "free")
        role = user_data.get("role", "")

        # Admin tiene acceso implícito a todo (incluyendo chat Premium)
        if role == "admin":
            logger.info("✅ Usuario %s es admin — acceso Premium implícito", uid)
            return True

        if plan == "premium":
            logger.info("✅ Usuario %s tiene plan Premium — acceso concedido", uid)
            return True

        logger.info("🚫 Usuario %s tiene plan '%s' — acceso denegado", uid, plan)
        return False

    except Exception as e:
        logger.error("❌ Error consultando Firestore para usuario %s: %s", uid, e)
        raise RuntimeError(f"No se pudo verificar el plan del usuario: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# DEPENDENCIA FASTAPI — para inyección en endpoints
# ═══════════════════════════════════════════════════════════════════════════

from fastapi import Header, HTTPException


async def verificar_acceso_premium(
    authorization: Optional[str] = Header(None),
) -> dict:
    """
    Dependencia FastAPI que verifica el ID Token y el plan Premium.

    Se inyecta en los endpoints que requieren autenticación Premium:
        @app.post("/api/chat")
        async def chat(..., user=Depends(verificar_acceso_premium)):

    Args:
        authorization: Header HTTP "Authorization: Bearer <id_token>"

    Returns:
        dict con uid, email, plan, role del usuario verificado

    Raises:
        HTTPException 401: Si no hay token o es inválido
        HTTPException 403: Si el usuario no tiene plan Premium
    """
    # Inicializar Firebase Admin (lazy, solo cuando se use)
    _init_firebase()

    # 1. Verificar que existe el header Authorization
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Token de autenticación requerido. Incluye 'Authorization: Bearer <id_token>'",
        )

    # 2. Extraer el token del header "Bearer <token>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Formato de autorización inválido. Usa 'Bearer <id_token>'",
        )

    id_token = parts[1]

    # 3. Verificar el ID Token con Firebase Auth
    try:
        decoded = verificar_id_token(id_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    uid = decoded.get("uid")
    email = decoded.get("email", "desconocido")

    # 4. Verificar plan Premium en Firestore
    try:
        es_premium = verificar_plan_premium(uid)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not es_premium:
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado. El chat multiagente requiere plan Premium. Actualiza tu plan en Configuración.",
        )

    return {
        "uid": uid,
        "email": email,
        "access": "premium",
    }