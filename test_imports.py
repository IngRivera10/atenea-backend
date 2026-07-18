"""Script rápido para verificar que todos los imports funcionan correctamente."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

print("1. Cargando variables de entorno...")
print(f"   ANTHROPIC_API_KEY: {'✓' if os.environ.get('ANTHROPIC_API_KEY') else '✗'}")
print(f"   GOOGLE_API_KEY: {'✓' if os.environ.get('GOOGLE_API_KEY') else '✗'}")
print(f"   DEEPSEEK_API_KEY: {'✓' if os.environ.get('DEEPSEEK_API_KEY') else '✗'}")

print("\n2. Importando paquetes externos...")
import anthropic; print("   anthropic ✓")
from google import genai; print("   google-genai ✓")
from openai import OpenAI; print("   openai ✓")
import firebase_admin; print("   firebase_admin ✓")

print("\n3. Importando módulos locales...")
from core.chat_multiagente import generar_respuesta_chat; print("   core.chat_multiagente ✓")
from core.auth_middleware import verificar_acceso_premium; print("   core.auth_middleware ✓")

print("\n✅ Todos los imports funcionan correctamente.")