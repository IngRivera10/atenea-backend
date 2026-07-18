"""
test_gemini_key.py — Smoke test aislado para Gemini via Vertex AI Express.
NO modifica archivos de producción. Borrar después de usar.
Objetivo: diagnosticar API_KEY_SERVICE_BLOCKED en proyecto 498178868408.
"""
import os
import sys
import traceback

# Cargar .env manualmente (sin depender de python-dotenv si no está instalado)
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
print(f"🔑 GOOGLE_API_KEY cargada: {GOOGLE_API_KEY[:12]}... ({len(GOOGLE_API_KEY)} chars)")
print(f"   Tipo detectado: {'Vertex AI Express (AQ.)' if GOOGLE_API_KEY.startswith('AQ.') else 'AI Studio clásica (AIzaSy...)' if GOOGLE_API_KEY.startswith('AIza') else 'DESCONOCIDO'}")

if not GOOGLE_API_KEY:
    print("❌ ERROR: GOOGLE_API_KEY no encontrada en .env")
    sys.exit(1)

try:
    from google import genai
    print(f"✅ google-genai importado: {genai.__version__}")
except ImportError as e:
    print(f"❌ ERROR: google-genai no instalado: {e}")
    print("   Instala con: pip install google-genai")
    sys.exit(1)

PROJECT = "498178868408"
LOCATION = "us-central1"
MODEL = "gemini-2.0-flash"  # NO modificar — decisión de arquitectura

print(f"\n📡 Creando cliente Vertex AI...")
print(f"   project={PROJECT}, location={LOCATION}, vertexai=True")

try:
    client = genai.Client(
        vertexai=True,
        api_key=GOOGLE_API_KEY,
    )
    print(f"✅ Cliente creado exitosamente")
except Exception as e:
    print(f"❌ ERROR al crear cliente: {e}")
    traceback.print_exc()
    sys.exit(1)

print(f"\n🚀 Llamando a {MODEL} con prompt 'ping'...")

try:
    response = client.models.generate_content(
        model=MODEL,
        contents="ping",
    )
    print(f"✅ RESPUESTA EXITOSA:")
    print(f"   Texto: {response.text}")
    if response.usage_metadata:
        print(f"   Tokens prompt: {response.usage_metadata.prompt_token_count}")
        print(f"   Tokens candidatos: {response.usage_metadata.candidates_token_count}")
    print(f"   Response completo: {response}")
except Exception as e:
    print(f"❌ ERROR en llamada a Gemini:")
    print(f"   Tipo: {type(e).__name__}")
    print(f"   Mensaje: {e}")
    print(f"\n--- TRACEBACK COMPLETO ---")
    traceback.print_exc()
    print(f"--- FIN TRACEBACK ---")
    sys.exit(1)

print(f"\n✅ Smoke test PASSED — Gemini 2.0 Flash funcionando correctamente via Vertex AI.")