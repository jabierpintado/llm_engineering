#!/usr/bin/env python3
"""Verificacion y reparacion basica de imprimibilidad para mallas de Rodin.

Rodin NO garantiza mallas estancas (watertight): su exportador STL escribe
vertices duplicados en las costuras, asi que el primer paso siempre es
soldar vertices (merge_vertices) antes de evaluar nada. Este script:

  1. Carga STL/OBJ/GLB/PLY con trimesh.
  2. Suelda vertices y limpia caras degeneradas/duplicadas.
  3. Informa: watertight, normales consistentes, componentes conexas,
     caras, dimensiones, volumen.
  4. Con --repair: elimina islas pequenas, rellena agujeros, corrige normales.
  5. Con --height-mm: escala el modelo a la altura fisica deseada.
  6. Exporta el resultado con --out.

Para reparaciones serias (agujeros grandes, geometria interna, paredes
finas) usa Blender headless (remesh por voxeles) o pymeshlab — ver la guia.

Uso:
  python mesh_check.py modelo.stl                          # solo informe
  python mesh_check.py modelo.stl --repair --height-mm 120 --out figura_print.stl
"""

import argparse
import sys

import numpy as np
import trimesh


def load_mesh(path: str) -> trimesh.Trimesh:
    loaded = trimesh.load(path, force="mesh")
    if isinstance(loaded, trimesh.Scene):
        loaded = loaded.to_mesh()
    if not isinstance(loaded, trimesh.Trimesh) or loaded.faces.shape[0] == 0:
        sys.exit(f"No se pudo cargar una malla valida de {path}")
    return loaded


def report(mesh: trimesh.Trimesh, label: str) -> None:
    ext = mesh.extents
    print(f"\n--- {label} ---")
    print(f"  caras: {len(mesh.faces):,}   vertices: {len(mesh.vertices):,}")
    print(f"  watertight (estanca): {mesh.is_watertight}")
    print(f"  normales consistentes: {mesh.is_winding_consistent}")
    print(f"  componentes conexas: {mesh.body_count}")
    print(f"  dimensiones (x,y,z): {ext[0]:.2f} x {ext[1]:.2f} x {ext[2]:.2f} (unidades del archivo)")
    if mesh.is_watertight:
        print(f"  volumen: {mesh.volume:,.2f}")
    open_edges = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
    print(f"  aristas frontera (agujeros): {len(open_edges)}")


def weld_and_clean(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    return mesh


def repair(mesh: trimesh.Trimesh, keep_fraction: float) -> trimesh.Trimesh:
    # 1) Quitar islas flotantes: conservar componentes con un numero de caras
    #    relevante respecto a la mayor (los "floaters" tipicos de mallas IA).
    parts = mesh.split(only_watertight=False)
    if len(parts) > 1:
        biggest = max(len(p.faces) for p in parts)
        kept = [p for p in parts if len(p.faces) >= biggest * keep_fraction]
        dropped = len(parts) - len(kept)
        if dropped:
            print(f"  reparacion: eliminadas {dropped} islas pequenas (de {len(parts)} componentes)")
        mesh = trimesh.util.concatenate(kept) if len(kept) > 1 else kept[0]

    # 2) Rellenar agujeros y corregir orientacion de normales.
    trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fix_inversion(mesh)
    mesh = weld_and_clean(mesh)
    return mesh


def main() -> None:
    p = argparse.ArgumentParser(description="Chequeo/reparacion de imprimibilidad de mallas")
    p.add_argument("input", help="Archivo STL/OBJ/GLB/PLY")
    p.add_argument("--repair", action="store_true", help="Intenta reparar (islas, agujeros, normales)")
    p.add_argument("--keep-fraction", type=float, default=0.02,
                   help="Umbral de caras (fraccion de la componente mayor) para conservar islas (def. 0.02)")
    p.add_argument("--height-mm", type=float, default=None,
                   help="Escala el modelo a esta altura en mm (eje Z) para el slicer")
    p.add_argument("--out", default=None, help="Ruta de salida (STL recomendado)")
    args = p.parse_args()

    mesh = load_mesh(args.input)
    report(mesh, "ORIGINAL (tal cual viene del archivo)")

    mesh = weld_and_clean(mesh)
    report(mesh, "TRAS SOLDAR VERTICES (asi hay que evaluar un STL de Rodin)")

    if args.repair:
        mesh = repair(mesh, args.keep_fraction)
        report(mesh, "TRAS REPARACION")
        if not mesh.is_watertight:
            print("\nAVISO: sigue sin ser estanca. Para imprimir con garantias haz un "
                  "remesh por voxeles en Blender:\n"
                  "  blender --background --python blender_remesh.py -- entrada.stl salida.stl 0.4\n"
                  "o deja que el slicer (PrusaSlicer/Lychee) aplique su reparacion automatica.")

    if args.height_mm:
        current = mesh.extents[2]
        if current <= 0:
            sys.exit("Altura actual nula; no se puede escalar")
        factor = args.height_mm / current
        mesh.apply_scale(factor)
        print(f"\nEscalado x{factor:.4f} -> altura {mesh.extents[2]:.1f} mm "
              f"({mesh.extents[0]:.1f} x {mesh.extents[1]:.1f} x {mesh.extents[2]:.1f} mm)")

    if args.out:
        mesh.export(args.out)
        print(f"\nExportado: {args.out}")
    elif args.repair or args.height_mm:
        print("\n(No se ha guardado nada: anade --out salida.stl)")


if __name__ == "__main__":
    main()
