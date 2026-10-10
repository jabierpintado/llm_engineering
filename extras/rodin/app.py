#!/usr/bin/env python3
"""Prueba de concepto: interfaz web (Gradio) foto -> modelo 3D imprimible.

Sube 1-5 fotos, elige un preset y obtendras:
  - el modelo 3D con textura en un visor interactivo (GLB),
  - el STL imprimible (estanco, escalado a la altura elegida) para descargar,
  - un informe de imprimibilidad.

Uso:
  pip install -r requirements.txt gradio pymeshfix
  export HYPER3D_API_KEY=...   # opcional; sin ella usa la clave de prueba 'vibecoding'
  python app.py [--share]      # --share crea un enlace publico temporal gradio.live
"""

import sys
import tempfile
import time
from pathlib import Path

import gradio as gr
import trimesh

import mesh_check
import rodin_pipeline

PRESETS = {
    "Borrador rápido (~30 s)": [
        "--tier", "Gen-2.5-Low", "--mesh-mode", "Raw", "--quality-override", "20000",
        "--material", "Shaded", "--texture-mode", "low",
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


def generar(files: list, preset: str, altura_mm: float, api_key: str,
            progress=gr.Progress()):
    if not files:
        raise gr.Error("Sube al menos una foto (idealmente frontal + perfiles).")
    if len(files) > 5:
        raise gr.Error("Máximo 5 imágenes.")

    out_dir = Path(tempfile.mkdtemp(prefix="rodin_"))
    argv = []
    for f in files:
        argv += ["--image", f if isinstance(f, str) else f.name]
    argv += PRESETS[preset]
    argv += ["--format", "glb", "--output", str(out_dir)]
    if api_key.strip():
        argv += ["--api-key", api_key.strip()]
    args = rodin_pipeline.build_parser().parse_args(argv)

    try:
        import requests
        session = requests.Session()
        headers = {"Authorization": f"Bearer {rodin_pipeline.resolve_api_key(args.api_key)}"}

        progress(0.05, desc="Enviando a Rodin…")
        body = rodin_pipeline.submit(args, session, headers)
        task_uuid = body["uuid"]
        sub_key = body["jobs"]["subscription_key"]

        # Sondeo con barra de progreso propia (en vez del wait bloqueante del CLI).
        t0 = time.time()
        for i in range(args.max_polls):
            time.sleep(args.poll_interval)
            try:
                r = session.post(f"{args.base_url}/status", headers=headers,
                                 json={"subscription_key": sub_key}, timeout=60)
                statuses = [j.get("status") for j in r.json().get("jobs", [])]
            except Exception:
                continue
            done = statuses.count("Done")
            progress(0.05 + 0.6 * (done / max(len(statuses), 1)),
                     desc=f"Generando… {done}/{len(statuses)} trabajos ({int(time.time()-t0)} s)")
            if any(s == "Failed" for s in statuses):
                raise gr.Error("La generación falló en el servidor (los créditos se devuelven).")
            if statuses and all(s == "Done" for s in statuses):
                break
        else:
            raise gr.Error("Tiempo de espera agotado.")

        progress(0.7, desc="Descargando (las URLs caducan en 10 min)…")
        saved = rodin_pipeline.download_all(args.base_url, headers, session,
                                            task_uuid, out_dir)
    except SystemExit as e:  # los helpers del CLI salen con sys.exit(mensaje)
        raise gr.Error(str(e))

    glb = next((p for p in saved if p.suffix.lower() == ".glb"), None)
    if glb is None:
        raise gr.Error(f"No llegó ningún GLB; archivos: {[p.name for p in saved]}")

    progress(0.75, desc="Verificando y reparando la malla…")
    mesh = mesh_check.load_mesh(str(glb))
    mesh.apply_transform(trimesh.transformations.rotation_matrix(3.14159265 / 2, [1, 0, 0]))
    mesh = mesh_check.weld_and_clean(mesh)
    estanca_tras_soldar = mesh.is_watertight
    if not estanca_tras_soldar:
        mesh = mesh_check.repair(mesh, keep_fraction=0.02)

    factor = altura_mm / mesh.extents[2]
    mesh.apply_scale(factor)
    stl_path = out_dir / "modelo_imprimible.stl"
    mesh.export(stl_path)

    dims = mesh.extents
    informe = (
        f"Caras: {len(mesh.faces):,}  |  Estanca (watertight): {mesh.is_watertight}"
        f"{' (tras soldar costuras UV)' if estanca_tras_soldar else ' (tras reparación)'}\n"
        f"Componentes: {mesh.body_count}  |  Normales consistentes: {mesh.is_winding_consistent}\n"
        f"Dimensiones: {dims[0]:.1f} × {dims[1]:.1f} × {dims[2]:.1f} mm\n"
        f"Preset: {preset}\n"
        f"Siguiente paso: abre el STL en PrusaSlicer/Lychee (resina: huecos 2-3 mm de pared "
        f"y ≥2 drenajes de 3-4 mm si lo vacías; soportes árbol en mentón/nariz/pelo)."
    )
    progress(1.0, desc="Listo")
    return str(glb), str(stl_path), informe


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Foto → Figura 3D imprimible (Rodin)") as demo:
        gr.Markdown(
            "# 🧍→🗿 Foto a figura 3D imprimible\n"
            "Sube **1–5 fotos** (la primera manda en la textura; para caras: frontal + "
            "perfiles estrictos + nuca), elige preset y pulsa Generar. "
            "Sin clave API usa la clave de prueba gratuita `vibecoding` (limitada)."
        )
        with gr.Row():
            with gr.Column(scale=1):
                fotos = gr.File(label="Fotos (1–5)", file_count="multiple",
                                file_types=["image"], type="filepath")
                preset = gr.Dropdown(list(PRESETS), label="Preset de calidad",
                                     value="Alta calidad (~2-4 min, 1M caras)")
                altura = gr.Slider(30, 300, value=120, step=5,
                                   label="Altura de impresión (mm)")
                api_key = gr.Textbox(label="API key de Hyper3D (opcional)", type="password",
                                     placeholder="vacío = clave de prueba 'vibecoding'")
                boton = gr.Button("🚀 Generar modelo 3D", variant="primary")
            with gr.Column(scale=2):
                visor = gr.Model3D(label="Modelo generado (GLB con textura)",
                                   clear_color=[0.94, 0.94, 0.94, 1.0], height=420)
                stl_out = gr.File(label="STL imprimible (estanco, escalado)")
                informe = gr.Textbox(label="Informe de imprimibilidad", lines=6)
        boton.click(generar, inputs=[fotos, preset, altura, api_key],
                    outputs=[visor, stl_out, informe])
        gr.Markdown(
            "⚠️ Solo fotos propias o con consentimiento expreso de la persona retratada "
            "(LO 1/1982). Nada de famosos ni personajes con marca si el destino es la venta."
        )
    return demo


if __name__ == "__main__":
    build_ui().launch(share="--share" in sys.argv, server_name="0.0.0.0")
