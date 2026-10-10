#!/usr/bin/env python3
"""Extrae el flujo de trabajo de un tutorial de YouTube usando la API de Gemini.

Gemini acepta URLs de YouTube directamente como entrada de video (file_data),
asi que no hace falta descargar el video ni la transcripcion. Util cuando
la red local bloquea youtube.com pero permite generativelanguage.googleapis.com.

Requisitos: pip install requests ; variable de entorno GEMINI_API_KEY
(clave de Google AI Studio: https://aistudio.google.com/apikey).

Uso:
  python video_workflow_extract.py "https://www.youtube.com/watch?v=XXXX" [pregunta]
"""

import json
import os
import sys

import requests

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
DEFAULT_PROMPT = (
    "Analiza este tutorial en detalle. Devuelve en español: "
    "1) titulo y autor; 2) lista paso a paso del flujo de trabajo completo que muestra, "
    "con cada herramienta/software usado y los ajustes concretos que toca; "
    "3) los criterios o trucos de experto que menciona (que mira, que corrige, que evita); "
    "4) el resultado final y como lo valida. Se exhaustivo y literal con nombres de "
    "herramientas, parametros y valores."
)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    url = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PROMPT
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("Define GEMINI_API_KEY (clave de Google AI Studio)")

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {
        "contents": [{
            "parts": [
                {"file_data": {"file_uri": url}},
                {"text": prompt},
            ]
        }]
    }
    resp = requests.post(endpoint, params={"key": api_key}, json=payload, timeout=600)
    if resp.status_code != 200:
        sys.exit(f"HTTP {resp.status_code}: {resp.text[:800]}")
    body = resp.json()
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        sys.exit(f"Respuesta inesperada: {json.dumps(body)[:800]}")
    print(text)


if __name__ == "__main__":
    main()
