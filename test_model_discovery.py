"""
test_model_discovery.py — Prueba variantes del nombre de modelo en Vertex AI.
NO modifica archivos de producción.
"""
import os, sys

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v

from google import genai
client = genai.Client(vertexai=True, api_key=os.environ["GOOGLE_API_KEY"])

CANDIDATES = [
    "gemini-2.0-flash-001",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-001",
    "publishers/google/models/gemini-2.0-flash-001",
    "publishers/google/models/gemini-2.0-flash",
]

for name in CANDIDATES:
    try:
        r = client.models.generate_content(model=name, contents="ping")
        print(f"✅ OK: {name} -> {r.text[:80]}")
    except Exception as e:
        print(f"❌ FAIL: {name} -> {type(e).__name__}: {str(e)[:200]}")