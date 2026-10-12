#!/usr/bin/env python3
"""Prueba de concepto: interfaz web (Gradio) foto -> figura 3D imprimible EN COLOR.

Dos tipos de figura, ambos sin pintura a mano:
  - REALISTA: modelo fiel a las fotos + pack de color (OBJ+MTL+textura) listo para
    un servicio de impresion full-color (p. ej. JLC3DP resina full-color).
  - CARTOON: la foto se estiliza primero con Gemini (muneco coleccionable cabezon,
    colores planos) y el resultado se imprime en FDM multicolor (Bambu + AMS)
    importando el pack de color en Bambu Studio.

Salidas: visor 3D interactivo (GLB con textura), STL estanco escalado, ZIP de color
e informe de imprimibilidad.

Uso:
  pip install -r requirements.txt gradio pymeshfix
  export HYPER3D_API_KEY=...   # opcional; sin ella usa la clave de prueba 'vibecoding'
  export GEMINI_API_KEY=...    # solo necesario para el modo cartoon
  python app.py [--share]      # --share crea un enlace publico temporal gradio.live
"""

import base64
import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import gradio as gr
import requests
import trimesh

import mesh_check
import rodin_pipeline

MODO_REALISTA = "Realista"
MODO_CARTOON = "Cartoon estilizado"
# Ambos modos producen el pack de color para impresion full-color de servicio
# (p. ej. JLC3DP resina full-color): producto premium sin pintura a mano.

PROV_NATIVO = "Hyper3D nativo (clave propia o 'vibecoding')"
PROV_FAL = "fal.ai (pago por uso, ~0,40 $/generación)"
PROV_TRIPO = "Tripo (pago por uso, ~0,10 $/generación — ideal borradores)"
FAL_ENDPOINT = "fal-ai/hyper3d/rodin/v2.5"
TRIPO_BASE = "https://api.tripo3d.ai/v2/openapi"

PRESETS = {
    "Borrador rápido (~30 s)": [
        "--tier", "Gen-2.5-Low", "--mesh-mode", "Raw", "--quality-override", "20000",
        "--material", "PBR", "--texture-mode", "low",
    ],
    "Alta calidad (~2-4 min, 1M caras)": [
        "--tier", "Gen-2.5-High", "--mesh-mode", "Raw", "--quality", "high",
        "--material", "PBR",
    ],
    "Busto hiperrealista (Extreme-High + Micro)": [
        "--tier", "Gen-2.5-Extreme-High", "--mesh-mode", "Raw", "--quality", "high",
        "--material", "PBR", "--is-micro", "--texture-delight",
    ],
}

PROMPT_CARTOON = (
    "Transforma la foto en una figura coleccionable estilo cartoon 3D: cabeza grande, "
    "cuerpo pequeño, rasgos simplificados y amables, colores planos y vivos, cuerpo "
    "completo de pie sobre una peana cilíndrica sencilla, fondo blanco uniforme, "
    "iluminación suave de estudio, una sola figura centrada. Conserva el peinado, la "
    "ropa y los rasgos reconocibles del sujeto de la foto."
)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _gemini_image_model(api_key: str) -> str:
    """Modelo de imagen configurado, o autodescubierto si el configurado no existe."""
    preferido = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    r = requests.get(f"{GEMINI_BASE}/models", params={"key": api_key}, timeout=30)
    if r.status_code != 200:
        return preferido
    nombres = [m.get("name", "").removeprefix("models/") for m in r.json().get("models", [])
               if "generateContent" in m.get("supportedGenerationMethods", [])]
    if preferido in nombres:
        return preferido
    candidatos = [n for n in nombres if "image" in n and "embed" not in n]
    if not candidatos:
        raise gr.Error(f"No hay modelo de imagen disponible en esta clave de Gemini. "
                       f"Modelos vistos: {nombres[:10]}")
    return sorted(candidatos)[-1]


def estilizar_cartoon(foto: Path, api_key: str, out_dir: Path) -> Path:
    """Convierte la foto en imagen de figura cartoon con la API de Gemini."""
    modelo = _gemini_image_model(api_key)
    mime = "image/webp" if foto.suffix.lower() == ".webp" else (
        "image/png" if foto.suffix.lower() == ".png" else "image/jpeg")
    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime,
                                 "data": base64.b64encode(foto.read_bytes()).decode()}},
                {"text": PROMPT_CARTOON},
            ]
        }]
    }
    r = requests.post(f"{GEMINI_BASE}/models/{modelo}:generateContent",
                      params={"key": api_key}, json=payload, timeout=300)
    if r.status_code != 200:
        raise gr.Error(f"Gemini ({modelo}) devolvió HTTP {r.status_code}: {r.text[:300]}")
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        raise gr.Error(f"Respuesta inesperada de Gemini: {json.dumps(r.json())[:300]}")
    for part in parts:
        blob = part.get("inline_data") or part.get("inlineData")
        if blob and blob.get("data"):
            dest = out_dir / "cartoon.png"
            dest.write_bytes(base64.b64decode(blob["data"]))
            return dest
    texto = " ".join(p.get("text", "") for p in parts)[:300]
    raise gr.Error(f"Gemini no devolvió imagen (modelo {modelo}). Respuesta: {texto}")


def generar_fal(paths: list, args, fal_key: str, out_dir: Path, progress) -> Path:
    """Genera via fal.ai (revendedor oficial de Rodin, sin suscripcion). Devuelve el GLB."""
    try:
        import fal_client
    except ImportError:
        raise gr.Error("Falta el cliente de fal: pip install fal-client")
    client = fal_client.SyncClient(key=fal_key)

    progress(0.05, desc="Subiendo imágenes a fal.ai…")
    urls = [client.upload_file(str(p)) for p in paths]

    argumentos = {
        "input_image_urls": urls,
        "tier": args.tier,
        "geometry_file_format": "glb",
        "material": args.material,
        "quality": args.quality,
    }
    if args.seed is not None:
        argumentos["seed"] = args.seed
    if args.highpack:
        argumentos["addons"] = ["HighPack"]
    if args.is_micro:
        argumentos["is_micro"] = True
    if args.bbox:
        argumentos["bbox_condition"] = args.bbox

    progress(0.1, desc="Enviando a Rodin vía fal.ai…")

    def _submit(argus):
        handle = client.submit(FAL_ENDPOINT, arguments=argus)
        t0 = time.time()
        while True:
            st = handle.status(with_logs=False)
            nombre = type(st).__name__
            if nombre == "Completed":
                return handle.get()
            progress(min(0.65, 0.1 + (time.time() - t0) / 300 * 0.5),
                     desc=f"Generando en fal.ai… ({nombre.lower()}, {int(time.time()-t0)} s)")
            time.sleep(5)

    try:
        resultado = _submit(argumentos)
    except Exception as e:
        texto = str(e)
        # Si fal rechaza algun campo (el esquema del revendedor cambia), se
        # reintenta una vez sin los campos opcionales conflictivos.
        opcionales = ["addons", "is_micro", "bbox_condition", "quality", "material"]
        if any(k in texto for k in opcionales):
            for k in opcionales:
                if k in texto:
                    argumentos.pop(k, None)
            try:
                resultado = _submit(argumentos)
            except Exception as e2:
                raise gr.Error(f"fal.ai rechazó la petición: {e2}")
        else:
            raise gr.Error(f"Error de fal.ai: {texto[:400]}")

    mesh = resultado.get("model_mesh") or {}
    url = mesh.get("url")
    if not url:
        raise gr.Error(f"fal.ai no devolvió modelo: {json.dumps(resultado)[:300]}")
    progress(0.68, desc="Descargando modelo…")
    glb = out_dir / (mesh.get("file_name") or "modelo_fal.glb")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        glb.write_bytes(r.content)
    return glb


def generar_tripo(paths: list, args, tripo_key: str, out_dir: Path, progress) -> Path:
    """Genera via la API oficial de Tripo. Devuelve el GLB con textura PBR.

    Nota: por simplicidad la PoC usa solo la PRIMERA imagen (image_to_model);
    el modo multivista de Tripo exige exactamente 4 vistas ordenadas.
    """
    headers = {"Authorization": f"Bearer {tripo_key}"}

    progress(0.05, desc="Subiendo imagen a Tripo…")
    foto = paths[0]
    with open(foto, "rb") as fh:
        r = requests.post(f"{TRIPO_BASE}/upload", headers=headers,
                          files={"file": (foto.name, fh)}, timeout=120)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or body.get("code") != 0:
        raise gr.Error(f"Tripo upload fallo (HTTP {r.status_code}): {r.text[:300]}")
    token = body["data"]["image_token"]

    ext = foto.suffix.lstrip(".").lower() or "png"
    if ext == "jpeg":
        ext = "jpg"  # Tripo espera "jpg"; "jpeg" (extension tipica de iPhone) falla
    tarea = {
        "type": "image_to_model",
        "file": {"type": ext, "file_token": token},
        "texture": True,
        "pbr": True,
    }
    if os.environ.get("TRIPO_MODEL_VERSION"):
        tarea["model_version"] = os.environ["TRIPO_MODEL_VERSION"]
    if args.quality_override:
        tarea["face_limit"] = args.quality_override

    progress(0.1, desc="Enviando tarea a Tripo…")
    r = requests.post(f"{TRIPO_BASE}/task", headers=headers, json=tarea, timeout=60)
    body = r.json()
    if r.status_code != 200 or body.get("code") != 0:
        raise gr.Error(f"Tripo rechazo la tarea (HTTP {r.status_code}): {r.text[:400]}")
    task_id = body["data"]["task_id"]

    t0 = time.time()
    while True:
        time.sleep(5)
        try:
            d = requests.get(f"{TRIPO_BASE}/task/{task_id}", headers=headers,
                             timeout=60).json().get("data", {})
        except Exception:
            continue
        estado = d.get("status")
        progress(min(0.65, 0.1 + d.get("progress", 0) / 100 * 0.55),
                 desc=f"Generando en Tripo… ({estado}, {int(time.time()-t0)} s)")
        if estado == "success":
            break
        if estado in ("failed", "cancelled", "banned", "expired"):
            raise gr.Error(f"Tarea de Tripo terminada en estado '{estado}'")
        if time.time() - t0 > 900:
            raise gr.Error("Tiempo de espera agotado en Tripo")

    salida = d.get("output", {})
    url = salida.get("pbr_model") or salida.get("model")
    if isinstance(url, dict):
        url = url.get("url")
    if not url:
        raise gr.Error(f"Tripo no devolvio modelo: {json.dumps(salida)[:300]}")
    progress(0.68, desc="Descargando modelo…")
    glb = out_dir / "modelo_tripo.glb"
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        glb.write_bytes(r.content)
    return glb


def exportar_pack_color(glb: Path, out_dir: Path) -> Path:
    """GLB -> carpeta con OBJ+MTL+textura -> ZIP (valido para JLC3DP y Bambu Studio)."""
    pack = out_dir / "pack_color"
    pack.mkdir(exist_ok=True)
    m = trimesh.load(str(glb), force="mesh")  # conserva TextureVisuals
    m.export(str(pack / "modelo.obj"))        # escribe tambien .mtl y la textura
    return Path(shutil.make_archive(str(out_dir / "pack_color"), "zip", pack))


def generar(files: list, modo: str, proveedor: str, preset: str, altura_mm: float,
            textura_4k: bool, api_key: str, fal_key: str, tripo_key: str,
            gemini_key: str, progress=gr.Progress()):
    if not files:
        raise gr.Error("Sube al menos una foto.")
    if len(files) > 5:
        raise gr.Error("Máximo 5 imágenes.")
    paths = [Path(f if isinstance(f, str) else f.name) for f in files]

    out_dir = Path(tempfile.mkdtemp(prefix="rodin_"))
    imagen_estilizada = None

    # Modo cartoon: estilizar la primera foto con Gemini antes de Rodin.
    if modo == MODO_CARTOON:
        gkey = gemini_key.strip() or os.environ.get("GEMINI_API_KEY", "")
        if not gkey:
            raise gr.Error("El modo cartoon necesita una clave de Gemini "
                           "(campo de la izquierda o variable GEMINI_API_KEY).")
        progress(0.02, desc="Estilizando la foto con Gemini…")
        imagen_estilizada = estilizar_cartoon(paths[0], gkey, out_dir)
        paths = [imagen_estilizada]

    argv = []
    for p in paths:
        argv += ["--image", str(p)]
    argv += PRESETS[preset]
    if textura_4k:
        argv += ["--highpack"]
    argv += ["--format", "glb", "--output", str(out_dir)]
    if api_key.strip():
        argv += ["--api-key", api_key.strip()]
    args = rodin_pipeline.build_parser().parse_args(argv)

    if proveedor == PROV_TRIPO:
        tkey = tripo_key.strip() or os.environ.get("TRIPO_API_KEY", "")
        if not tkey:
            raise gr.Error("Tripo necesita una TRIPO_API_KEY (campo de la izquierda o variable TRIPO_API_KEY).")
        glb = generar_tripo(paths, args, tkey, out_dir, progress)
        return _postproceso(glb, modo, preset, altura_mm, out_dir,
                            imagen_estilizada, progress)

    if proveedor == PROV_FAL:
        fkey = fal_key.strip() or os.environ.get("FAL_KEY", "")
        if not fkey:
            raise gr.Error("fal.ai necesita una FAL_KEY (campo de la izquierda o variable FAL_KEY).")
        if args.quality_override and args.quality_override <= 20000:
            args.quality = "extra-low"  # aproximacion del modo rapido en fal
        glb = generar_fal(paths, args, fkey, out_dir, progress)
        return _postproceso(glb, modo, preset, altura_mm, out_dir,
                            imagen_estilizada, progress)

    try:
        session = requests.Session()
        headers = {"Authorization": f"Bearer {rodin_pipeline.resolve_api_key(args.api_key)}"}

        progress(0.08, desc="Enviando a Rodin…")
        body = rodin_pipeline.submit(args, session, headers)
        task_uuid = body["uuid"]
        sub_key = body["jobs"]["subscription_key"]

        t0 = time.time()
        for _ in range(args.max_polls):
            time.sleep(args.poll_interval)
            try:
                r = session.post(f"{args.base_url}/status", headers=headers,
                                 json={"subscription_key": sub_key}, timeout=60)
                statuses = [j.get("status") for j in r.json().get("jobs", [])]
            except Exception:
                continue
            done = statuses.count("Done")
            progress(0.1 + 0.55 * (done / max(len(statuses), 1)),
                     desc=f"Generando… {done}/{len(statuses)} trabajos ({int(time.time()-t0)} s)")
            if any(s == "Failed" for s in statuses):
                raise gr.Error("La generación falló en el servidor (los créditos se devuelven).")
            if statuses and all(s == "Done" for s in statuses):
                break
        else:
            raise gr.Error("Tiempo de espera agotado.")

        progress(0.68, desc="Descargando (las URLs caducan en 10 min)…")
        saved = rodin_pipeline.download_all(args.base_url, headers, session,
                                            task_uuid, out_dir)
    except SystemExit as e:  # los helpers del CLI salen con sys.exit(mensaje)
        msg = str(e)
        if "INSUFFICIENT_FUND" in msg or "API_INSUFFICIENT_FUNDS" in msg:
            msg = ("Sin créditos: la clave de prueba 'vibecoding' agota su cupo diario "
                   "(se renueva cada día). Pon tu propia API key de Hyper3D o inténtalo mañana.")
        raise gr.Error(msg)

    glb = next((p for p in saved if p.suffix.lower() == ".glb"), None)
    if glb is None:
        raise gr.Error(f"No llegó ningún GLB; archivos: {[p.name for p in saved]}")
    return _postproceso(glb, modo, preset, altura_mm, out_dir, imagen_estilizada, progress)


def _postproceso(glb: Path, modo: str, preset: str, altura_mm: float,
                 out_dir: Path, imagen_estilizada, progress):
    progress(0.75, desc="Empaquetando color (OBJ+MTL+textura)…")
    zip_color = exportar_pack_color(glb, out_dir)

    progress(0.85, desc="Verificando y reparando la malla…")
    mesh = mesh_check.load_mesh(str(glb))
    mesh.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
    mesh = mesh_check.weld_and_clean(mesh)
    estanca_tras_soldar = mesh.is_watertight
    if not estanca_tras_soldar:
        mesh = mesh_check.repair(mesh, keep_fraction=0.02)

    mesh.apply_scale(altura_mm / mesh.extents[2])
    # Consejo unanime de los expertos: base plana (~1 mm) para la primera capa.
    mesh = mesh_check.aplanar_base(mesh, 1.0)
    stl_path = out_dir / "modelo_imprimible.stl"
    mesh.export(stl_path)

    dims = mesh.extents
    siguiente = (
        "Sube pack_color.zip a un pedido de resina FULL-COLOR (p. ej. JLC3DP): OBJ + MTL + "
        "textura — imprimen la figura ya en color, acabado premium sin pintar. "
        "El STL es solo el respaldo para impresión monocolor."
    )
    informe = (
        f"Modo: {modo}\nPreset: {preset}\n"
        f"Caras: {len(mesh.faces):,}  |  Estanca (watertight): {mesh.is_watertight}"
        f"{' (tras soldar costuras UV)' if estanca_tras_soldar else ' (tras reparación)'}\n"
        f"Componentes: {mesh.body_count}  |  Normales consistentes: {mesh.is_winding_consistent}\n"
        f"Dimensiones: {dims[0]:.1f} × {dims[1]:.1f} × {dims[2]:.1f} mm  |  Base aplanada 1 mm\n"
        f"Revisa antes de imprimir: manos/dedos (Rodin los alarga o fusiona a veces) y la espalda.\n"
        f"Siguiente paso: {siguiente}"
    )
    progress(1.0, desc="Listo")
    return (str(glb), str(stl_path), str(zip_color), informe,
            str(imagen_estilizada) if imagen_estilizada else None)


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Foto → Figura 3D en color") as demo:
        gr.Markdown(
            "# 🧍→🗿 Foto a figura 3D imprimible en color\n"
            "Sube **1–5 fotos** (la primera manda en la textura; para caras: frontal + "
            "perfiles + nuca). Elige el estilo: **realista** o **cartoon** (la foto se "
            "estiliza primero con Gemini). En ambos casos obtienes el **pack de color** "
            "para impresión full-color de servicio (producto premium, sin pintura a mano). "
            "Sin clave API de Hyper3D usa la clave de prueba gratuita `vibecoding` (limitada)."
        )
        with gr.Row():
            with gr.Column(scale=1):
                fotos = gr.File(label="Fotos (1–5)", file_count="multiple",
                                file_types=["image"], type="filepath")
                modo = gr.Radio([MODO_REALISTA, MODO_CARTOON], label="Estilo de figura",
                                value=MODO_REALISTA)
                proveedor = gr.Radio([PROV_NATIVO, PROV_FAL, PROV_TRIPO],
                                     label="Proveedor de generación", value=PROV_NATIVO)
                textura_4k = gr.Checkbox(label="Textura 4K (HighPack, +1 crédito) — "
                                               "recomendado para impresión full-color",
                                         value=False)
                preset = gr.Dropdown(list(PRESETS), label="Preset de calidad",
                                     value="Alta calidad (~2-4 min, 1M caras)")
                altura = gr.Slider(30, 300, value=120, step=5,
                                   label="Altura de impresión (mm)")
                api_key = gr.Textbox(label="API key de Hyper3D (proveedor nativo)", type="password",
                                     placeholder="vacío = clave de prueba 'vibecoding'")
                fal_key = gr.Textbox(label="FAL_KEY (proveedor fal.ai)", type="password",
                                     placeholder="vacío = variable FAL_KEY")
                tripo_key = gr.Textbox(label="TRIPO_API_KEY (proveedor Tripo)", type="password",
                                       placeholder="vacío = variable TRIPO_API_KEY")
                gemini_key = gr.Textbox(label="API key de Gemini (solo modo cartoon)",
                                        type="password",
                                        placeholder="vacío = variable GEMINI_API_KEY")
                boton = gr.Button("🚀 Generar figura", variant="primary")
                estilizada = gr.Image(label="Imagen estilizada (entrada a Rodin)",
                                      interactive=False)
            with gr.Column(scale=2):
                visor = gr.Model3D(label="Modelo generado (GLB con textura)",
                                   clear_color=[0.94, 0.94, 0.94, 1.0], height=420)
                zip_out = gr.File(label="Pack de color (OBJ+MTL+textura) — para impresión full-color")
                stl_out = gr.File(label="STL (geometría sola, para impresión monocolor)")
                informe = gr.Textbox(label="Informe", lines=7)
        boton.click(generar,
                    inputs=[fotos, modo, proveedor, preset, altura, textura_4k,
                            api_key, fal_key, tripo_key, gemini_key],
                    outputs=[visor, stl_out, zip_out, informe, estilizada])
        gr.Markdown(
            "⚠️ Solo fotos propias o con consentimiento expreso de la persona retratada "
            "(LO 1/1982). Estilo cartoon genérico: no uses marcas ni personajes con "
            "copyright si el destino es la venta."
        )
    return demo


if __name__ == "__main__":
    build_ui().launch(share="--share" in sys.argv, server_name="0.0.0.0")
