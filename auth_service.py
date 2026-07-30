"""
auth_service.py — Decorador de autenticación JWT para Flask.
Usa JWT_SECRET_KEY desde variable de entorno (.env).
"""
import os
import jwt
from functools import wraps
from flask import request, jsonify

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-fallback-secret-change-in-prod")
if SECRET_KEY == "dev-fallback-secret-change-in-prod":
    import logging
    logging.warning("⚠️ JWT_SECRET_KEY no configurada en variables de entorno. Usando fallback de desarrollo. NO USAR EN PRODUCCIÓN.")


def token_requerido(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"mensaje": "Token faltante o inválido"}), 401
        try:
            token = auth_header.split(" ")[1]
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.user_role = data.get("role")
        except Exception:
            return jsonify({"mensaje": "Token inválido"}), 401
        return f(*args, **kwargs)
    return decorated
