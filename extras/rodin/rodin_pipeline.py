#!/usr/bin/env python3
"""Pipeline imagen -> modelo 3D con la API oficial de Hyper3D Rodin (Gen-2.5).

Flujo asincrono verificado contra el cliente oficial de DeemosTech
(rodin3d-skills) en octubre de 2026:

  1. POST {base}/rodin      (multipart/form-data)  -> {uuid, jobs.subscription_key}
  2. POST {base}/status     ({"subscription_key"}) -> jobs[].status  (Waiting|Generating|Done|Failed)
  3. POST {base}/download   ({"task_uuid": uuid})  -> list[{name,url}]  (las URLs CADUCAN en 10 min)

Autenticacion: cabecera "Authorization: Bearer <API_KEY>".
  - Clave de produccion: https://hyper3d.ai/api-dashboard (requiere plan Business).
  - Clave de prueba gratuita y oficial: la cadena literal "vibecoding" (limitada).

Uso tipico para una figura imprimible:

  python rodin_pipeline.py --image frontal.jpg --image perfil.jpg --image espalda.jpg \
      --tier Gen-2.5-High --mesh-mode Raw --quality high --format stl --output ./salida

Despues ejecuta mesh_check.py sobre el STL: Rodin NO garantiza una malla
estanca (watertight) y la verificacion/reparacion local es obligatoria.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

DEFAULT_BASE_URL = "https://api.hyper3d.com/api/v2"
FREE_TEST_KEY = "vibecoding"  # clave oficial de prueba, con limites de uso

TIERS = [
    "Gen-2.5-Extreme-Low", "Gen-2.5-Low", "Gen-2.5-Medium",
    "Gen-2.5-High", "Gen-2.5-Extreme-High",
    "Gen-2", "Regular", "Detail", "Smooth", "Sketch",
]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Genera un modelo 3D con Hyper3D Rodin a partir de imagenes")
    p.add_argument("--image", action="append", default=[],
                   help="Imagen de referencia (repetible, max 5; JPEG/PNG/WebP, 512px-4096px, <16MB). "
                        "La PRIMERA imagen guia la textura/material.")
    p.add_argument("--prompt", default=None, help="Prompt de texto opcional (guia material/estilo)")
    p.add_argument("--tier", default="Gen-2.5-High", choices=TIERS,
                   help="Nivel de calidad de geometria (por defecto Gen-2.5-High; nunca omitir: sin tier cae a Gen-1.5)")
    p.add_argument("--mesh-mode", default="Raw", choices=["Raw", "Quad"],
                   help="Raw=triangulos con maximo detalle (recomendado para imprimir); Quad=topologia para editar")
    p.add_argument("--quality", default="high", choices=["high", "medium", "low", "extra-low"],
                   help="Preset de caras: Raw high=1M, medium=500k, low=60k, extra-low=20k")
    p.add_argument("--quality-override", type=int, default=None,
                   help="Numero de caras exacto (Raw 500-1M; 2M en tiers High/Extreme-High; Quad max 200k)")
    p.add_argument("--format", default="stl", choices=["glb", "usdz", "fbx", "obj", "stl"],
                   help="Formato de geometria (stl para imprimir; glb/obj si necesitas color)")
    p.add_argument("--material", default="PBR", choices=["PBR", "Shaded", "All", "None"],
                   help="'None' ahorra tiempo si solo imprimes monocolor")
    p.add_argument("--seed", type=int, default=None, help="Semilla 0-65535 para reproducibilidad")
    p.add_argument("--ta-pose", action="store_true",
                   help="Fuerza pose T/A en humanoides (para rigging; NO usar si quieres conservar la pose de la foto)")
    p.add_argument("--bbox", nargs=3, type=int, metavar=("ANCHO", "ALTO", "LARGO"), default=None,
                   help="Restringe proporciones [W,H,L] (enteros 1-300)")
    p.add_argument("--geometry-instruct-mode", default="faithful", choices=["faithful", "creative"],
                   help="faithful=fiel a la imagen (parecido); creative=la IA idealiza")
    p.add_argument("--hd-texture", action="store_true", help="Pasada extra de superresolucion de textura")
    p.add_argument("--texture-delight", action="store_true",
                   help="Elimina iluminacion 'cocinada' de referencias brillantes")
    p.add_argument("--texture-mode", default=None,
                   choices=["legacy", "extreme-low", "low", "medium", "high", "extreme-high"],
                   help="Calidad de textura (extreme-high: +2 creditos, hasta 12K con HighPack)")
    p.add_argument("--highpack", action="store_true", help="Addon HighPack: texturas 4K (+1 credito)")
    p.add_argument("--use-original-alpha", action="store_true",
                   help="Usa el canal alfa de la imagen (fondo ya recortado)")
    p.add_argument("--is-micro", action="store_true",
                   help="Micro-relieve en la geometria (poros, pliegues); SOLO valido con tier Gen-2.5-Extreme-High")
    p.add_argument("--api-key", default=None,
                   help="Clave API (por defecto: env HYPER3D_API_KEY, si no la clave de prueba 'vibecoding')")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--output", default="./rodin_output", help="Directorio de descarga")
    p.add_argument("--poll-interval", type=float, default=10.0)
    p.add_argument("--max-polls", type=int, default=90, help="90 x 10s = 15 min de espera maxima")
    return p


def resolve_api_key(cli_key: str | None) -> str:
    key = cli_key or os.environ.get("HYPER3D_API_KEY") or FREE_TEST_KEY
    if key == FREE_TEST_KEY:
        print("AVISO: usando la clave de prueba gratuita 'vibecoding' (limitada). "
              "Para produccion define HYPER3D_API_KEY (requiere plan Business).", file=sys.stderr)
    return key


def submit(args: argparse.Namespace, session: requests.Session, headers: dict) -> dict:
    if not args.image and not args.prompt:
        sys.exit("Necesitas al menos --image o --prompt")
    if len(args.image) > 5:
        sys.exit("Maximo 5 imagenes")

    # Los booleanos viajan como cadenas "true"/"false"; bbox como "[W,H,L]".
    data: list[tuple[str, str]] = [("tier", args.tier),
                                   ("geometry_file_format", args.format),
                                   ("material", args.material),
                                   ("mesh_mode", args.mesh_mode),
                                   ("quality", args.quality),
                                   ("geometry_instruct_mode", args.geometry_instruct_mode)]
    if args.prompt:
        data.append(("prompt", args.prompt))
    if args.quality_override is not None:
        data.append(("quality_override", str(args.quality_override)))
    if args.seed is not None:
        data.append(("seed", str(args.seed)))
    if args.ta_pose:
        data.append(("TAPose", "true"))
    if args.bbox:
        data.append(("bbox_condition", json.dumps(args.bbox)))
    if args.hd_texture:
        data.append(("hd_texture", "true"))
    if args.texture_delight:
        data.append(("texture_delight", "true"))
    if args.texture_mode:
        data.append(("texture_mode", args.texture_mode))
    if args.use_original_alpha:
        data.append(("use_original_alpha", "true"))
    if args.is_micro:
        data.append(("is_micro", "true"))
    if args.highpack:
        data.append(("addons", "HighPack"))

    files = []
    try:
        for path in args.image:
            fp = Path(path)
            if not fp.is_file():
                sys.exit(f"No existe la imagen: {path}")
            files.append(("images", (fp.name, open(fp, "rb"), "application/octet-stream")))

        print(f"Enviando tarea: tier={args.tier} mesh={args.mesh_mode} quality={args.quality} "
              f"formato={args.format} imagenes={len(args.image)}")
        # Sin reintentos automaticos del submit: reintentar un POST de creacion
        # puede duplicar tareas (y cobrar creditos dos veces).
        resp = session.post(f"{args.base_url}/rodin", headers=headers, data=data,
                            files=files or None, timeout=120)
    finally:
        for _, (_, fh, _) in files:
            fh.close()

    try:
        body = resp.json()
    except ValueError:
        sys.exit(f"Respuesta no JSON (HTTP {resp.status_code}): {resp.text[:300]}")
    if resp.status_code not in (200, 201) or not body.get("uuid"):
        sys.exit(f"Fallo al enviar (HTTP {resp.status_code}): {json.dumps(body)[:500]}")
    return body


def wait_until_done(base_url: str, headers: dict, session: requests.Session,
                    subscription_key: str, interval: float, max_polls: int) -> None:
    for attempt in range(1, max_polls + 1):
        time.sleep(interval)
        try:
            resp = session.post(f"{base_url}/status", headers=headers,
                                json={"subscription_key": subscription_key}, timeout=60)
            jobs = resp.json().get("jobs", [])
        except (requests.RequestException, ValueError) as exc:
            print(f"  poll {attempt}: error transitorio ({exc}); reintento...", file=sys.stderr)
            continue
        statuses = [j.get("status") for j in jobs]
        print(f"  poll {attempt}: {statuses}")
        if statuses and any(s == "Failed" for s in statuses):
            sys.exit("La generacion ha FALLADO en el servidor (los creditos de tareas fallidas se devuelven).")
        if statuses and all(s == "Done" for s in statuses):
            return
    sys.exit(f"Tiempo de espera agotado tras {max_polls} intentos")


def download_all(base_url: str, headers: dict, session: requests.Session,
                 task_uuid: str, out_dir: Path) -> list[Path]:
    resp = session.post(f"{base_url}/download", headers=headers,
                        json={"task_uuid": task_uuid}, timeout=60)
    items = resp.json().get("list", [])
    if not items:
        sys.exit(f"Descarga vacia: {resp.text[:300]}")
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    # Las URLs caducan en 10 minutos: descargar TODO inmediatamente.
    for item in items:
        name, url = item["name"], item["url"]
        dest = out_dir / Path(name).name
        with session.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
        print(f"  descargado {dest} ({dest.stat().st_size / 1e6:.2f} MB)")
        saved.append(dest)
    return saved


def main() -> None:
    args = build_parser().parse_args()
    headers = {"Authorization": f"Bearer {resolve_api_key(args.api_key)}"}
    session = requests.Session()

    body = submit(args, session, headers)
    task_uuid = body["uuid"]
    subscription_key = body["jobs"]["subscription_key"]
    print(f"Tarea aceptada: uuid={task_uuid}")

    print("Esperando a que termine la generacion...")
    wait_until_done(args.base_url, headers, session, subscription_key,
                    args.poll_interval, args.max_polls)

    print("Descargando resultados (URLs caducan en 10 min)...")
    saved = download_all(args.base_url, headers, session, task_uuid, Path(args.output))

    print("\nListo. Archivos:")
    for p in saved:
        print(f"  {p}")
    stls = [p for p in saved if p.suffix.lower() in (".stl", ".obj", ".glb")]
    if stls:
        print(f"\nSiguiente paso: python mesh_check.py {stls[0]} --repair --out {stls[0].stem}_print.stl")


if __name__ == "__main__":
    main()
