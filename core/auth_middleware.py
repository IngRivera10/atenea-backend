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
    """Inicializa el Admin SDK. Busca credenciales en este orden:
    1. FIREBASE_CREDENTIALS_B64 (Render, producción) — pasa dict directo, sin archivo temp
    2. FIREBASE_SERVICE_ACCOUNT_BASE64 (Render, nombre alternativo)
    3. FIREBASE_CREDENTIALS (Render, nombre alternativo legacy)
    4. GOOGLE_APPLICATION_CREDENTIALS (path local)
    """
    global _firebase_initialized
    if _firebase_initialized:
        return

    import base64
    import json

    cred = None

    # Probar los 3 nombres posibles para base64 inline
    # Certificate() acepta dict directamente desde firebase-admin>=6
    for var_name in ["FIREBASE_CREDENTIALS_B64", "FIREBASE_SERVICE_ACCOUNT_BASE64", "FIREBASE_CREDENTIALS"]:
        creds_b64 = os.environ.get(var_name, "")
        if creds_b64:
            try:
                creds_dict = json.loads(base64.b64decode(creds_b64).decode("utf-8"))
                cred = firebase_admin.credentials.Certificate(creds_dict)
                logger.info("🔐 Firebase Admin inicializado desde %s (dict directo)", var_name)
                break
            except Exception as e:
                logger.error("❌ Error decodificando %s: %s", var_name, e)

    # Método 2: GOOGLE_APPLICATION_CREDENTIALS (path de archivo, desarrollo local)
    if cred is None:
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if cred_path and os.path.isfile(cred_path):
            cred = firebase_admin.credentials.Certificate(cred_path)
            logger.info("🔐 Firebase Admin inicializado con: %s", os.path.basename(cred_path))
        else:
            logger.warning(
                "⚠️ Ninguna variable de credenciales Firebase configurada correctamente. "
                "Usando credenciales por defecto de Google Cloud."
            )

    # Pasar project_id explícitamente como fallback por si el JSON de credenciales
    # está incompleto o se decodificó mal desde base64 en producción (Render).
    # [ARCH] El SDK de Firebase Admin extrae project_id del JSON de Certificate()
    # automáticamente, pero si FIREBASE_CREDENTIALS_B64 contiene un JSON corrupto
    # sin ese campo, initialize_app() falla con "A project ID is required".
    # Pasarlo explícitamente como segundo argumento elimina esta dependencia.
    firebase_admin.initialize_app(cred, {
        "projectId": "atenea-lab-b86ca",
    })
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
        # [E2.1] check_revoked=True: un ID Token revocado queda bloqueado.
        # Complementa Firestore disabled como segunda capa.
        decoded = auth.verify_id_token(id_token, check_revoked=True)
        logger.debug("🔐 Token verificado: uid=%s email=%s", decoded.get("uid"), decoded.get("email"))
        return decoded
    except auth.UserDisabledError:
        # [E2.1] Cuenta suspendida en Firebase Auth (Capa 1) -> 403, no 401.
        # HTTPException NO es ValueError: _extract_and_verify_token no lo
        # re-mapea a 401, se propaga con su 403.
        raise HTTPException(
            status_code=403,
            detail="Cuenta deshabilitada. Vuelve a iniciar sesión.",
        )
    except auth.ExpiredIdTokenError:
        raise ValueError("Token expirado. Vuelve a iniciar sesión.")
    except auth.RevokedIdTokenError:
        raise ValueError("Token revocado. Vuelve a iniciar sesión.")
    except auth.InvalidIdTokenError:
        raise ValueError("Token inválido. Vuelve a iniciar sesión.")
    except Exception as e:
        logger.error("❌ Error verificando token: %s", e)
        raise ValueError("Error de autenticación.")


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
        # [ARCH] E1.1-05: FAIL-CLOSED — un usuario disabled nunca obtiene
        # Premium aunque tenga plan=premium o role=admin. Esto es la Capa 1
        # (authorization flag en Firestore); la Capa 2 (Firebase Auth disabled
        # vía Admin SDK) se integra en E2.
        if user_data.get("disabled") is True:
            logger.warning("🚫 Usuario %s está disabled — acceso denegado", uid)
            return False

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


async def _extract_and_verify_token(authorization: Optional[str]) -> dict:
    """
    [ARCH] Paso común de extracción y verificación de token Firebase.
    Extraído para evitar duplicación entre verificar_acceso_premium y
    verificar_identidad. Ambos necesitan validar el token; la diferencia
    está en qué hacen después (plan premium vs. solo identidad).

    Raises:
        HTTPException 401: Si no hay token, formato inválido, o token inválido/expirado.
    """
    # Inicializar Firebase Admin (lazy, solo cuando se use)
    _init_firebase()

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Token de autenticación requerido. Incluye 'Authorization: Bearer <id_token>'",
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Formato de autorización inválido. Usa 'Bearer <id_token>'",
        )

    id_token = parts[1]

    try:
        decoded = verificar_id_token(id_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    return decoded


async def verificar_identidad(
    authorization: Optional[str] = Header(None),
) -> dict:
    """
    [ARCH] Dependencia FastAPI que verifica SOLO la identidad (token Firebase
    válido). No exige plan Premium. Usar en endpoints que consumen recursos
    de IA pero no requieren suscripción de pago (ej: /api/vision/inspect,
    /api/talent/*).

    A diferencia de verificar_acceso_premium, NO consulta Firestore para
    verificar el plan — solo valida que el token sea legítimo.

    Returns:
        dict con uid y email del usuario verificado.

    Raises:
        HTTPException 401: Si no hay token o es inválido.
    """
    decoded = await _extract_and_verify_token(authorization)
    uid = decoded.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Token válido pero sin uid. Re-autentica.")
    return {
        "uid": uid,
        "email": decoded.get("email", "desconocido"),
    }


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
        dict con uid, email del usuario verificado

    Raises:
        HTTPException 401: Si no hay token o es inválido
        HTTPException 403: Si el usuario no tiene plan Premium
    """
    decoded = await _extract_and_verify_token(authorization)

    uid = decoded.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Token válido pero sin uid. Re-autentica.")
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
