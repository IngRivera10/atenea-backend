"""Genera un ID Token de Firebase para pruebas locales del endpoint /api/chat."""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

# Asegurar que Firebase Admin se inicializa
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "atenea_mobile", "atenea-lab-b86ca-firebase-adminsdk-fbsvc-b6b4d26b75.json"
)

import firebase_admin
from firebase_admin import auth

# Inicializar si no está ya
try:
    firebase_admin.get_app()
except ValueError:
    cred = firebase_admin.credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    firebase_admin.initialize_app(cred)

# UID del usuario de prueba (el mismo del populateFirestore.js)
TEST_UID = "eMuwIxjOzFeiBxmkz72uCpDvFeJ2"

print(f"Generando custom token para uid={TEST_UID}...")
custom_token = auth.create_custom_token(TEST_UID).decode()

print(f"Custom token (exchange this for an ID token using Firebase REST API):")
print(custom_token)
print()

# También podemos intentar obtener información del usuario
try:
    user = auth.get_user(TEST_UID)
    print(f"✅ Usuario encontrado: email={user.email}, plan={user.custom_claims}")
except Exception as e:
    print(f"⚠️ Usuario no encontrado: {e}")

print()
print("Para usar este token en curl, intercámbialo por un ID Token:")
print("  curl -X POST 'https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key=' \\")
print("    -H 'Content-Type: application/json' -d '{\"token\":\"" + custom_token + "\", \"returnSecureToken\": true}'")