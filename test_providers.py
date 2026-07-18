"""Script de prueba de los 3 proveedores de IA (Claude, Gemini, DeepSeek)."""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from core.chat_multiagente import (
    llamar_claude, llamar_gemini, llamar_deepseek, generar_respuesta_chat
)

test_messages = [
    {"role": "user", "content": "Responde con una sola línea: ¿cuál es la capital de México?"}
]


async def probar_claude():
    print("\n🤖 Probando Claude...")
    try:
        r = await llamar_claude(test_messages)
        print(f"   ✅ Respuesta: {r['content'][:80]}...")
        print(f"   Modelo: {r['model']} | Tokens: {r['tokens_entrada']} in / {r['tokens_salida']} out | ${r['costo_usd']:.6f} | {r['tiempo_s']}s")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def probar_gemini():
    print("\n🔮 Probando Gemini...")
    try:
        r = await llamar_gemini(test_messages)
        print(f"   ✅ Respuesta: {r['content'][:80]}...")
        print(f"   Modelo: {r['model']} | Tokens: {r['tokens_entrada']} in / {r['tokens_salida']} out | ${r['costo_usd']:.6f} | {r['tiempo_s']}s")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def probar_deepseek():
    print("\n🧠 Probando DeepSeek...")
    try:
        r = await llamar_deepseek(test_messages)
        print(f"   ✅ Respuesta: {r['content'][:80]}...")
        print(f"   Modelo: {r['model']} | Tokens: {r['tokens_entrada']} in / {r['tokens_salida']} out | ${r['costo_usd']:.6f} | {r['tiempo_s']}s")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def probar_despachador():
    print("\n📤 Probando despachador unificado...")
    for model in ["claude", "gemini", "deepseek"]:
        try:
            r = await generar_respuesta_chat(model, test_messages)
            print(f"   ✅ {model}: {r['content'][:60]}... [{r['tiempo_s']}s, ${r['costo_usd']:.6f}]")
        except Exception as e:
            print(f"   ❌ {model}: {e}")


async def main():
    print("=" * 60)
    print("  PRUEBA DE PROVEEDORES DE IA")
    print("=" * 60)

    # Probar cada proveedor individualmente
    results = []
    results.append(await probar_claude())
    results.append(await probar_gemini())
    results.append(await probar_deepseek())

    # Probar despachador
    await probar_despachador()

    print("\n" + "=" * 60)
    print(f"  RESUMEN: {sum(results)}/3 proveedores respondieron correctamente")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())