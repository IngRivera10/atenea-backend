import os
from firebase_admin import auth, credentials, initialize_app
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# Inicializar Firebase Admin si no está inicializado
cred = credentials.Certificate({
    "type": "service_account",
    "project_id": os.getenv("FIREBASE_PROJECT_ID"),
    "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace('\\n', '\n') if os.getenv("FIREBASE_PRIVATE_KEY") else "",
    "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
    "client_id": os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL")
})

try:
    initialize_app(cred)
    print("Firebase Admin SDK inicializado correctamente.")
except ValueError:
    print("Firebase Admin SDK ya estaba inicializado.")

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Rutas públicas que no necesitan autenticación
        public_paths = ["/", "/health", "/api/chat"]
        if any(request.url.path.startswith(p) for p in public_paths):
            return await call_next(request)

        # Verificar token de Firebase
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Token de autorización faltante")

        token = auth_header.split(" ")[1]
        try:
            decoded_token = auth.verify_id_token(token)
            request.state.user = decoded_token
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Token inválido: {str(e)}")

        return await call_next(request)
