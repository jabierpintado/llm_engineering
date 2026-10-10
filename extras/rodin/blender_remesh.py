#!/usr/bin/env python3
"""Remesh por voxeles con Blender headless: convierte cualquier malla en un
solido estanco (watertight) listo para slicer. Es el "martillo" que arregla
lo que trimesh no puede (agujeros grandes, geometria interna, autointersecciones).

Uso:
  blender --background --python blender_remesh.py -- entrada.stl salida.stl [voxel_mm]

voxel_mm (por defecto 0.4): tamano de voxel EN LAS UNIDADES DEL ARCHIVO.
Mas pequeno = mas detalle y mas caras. Para una figura de ~120 mm, 0.2-0.4
conserva el detalle de resina; sube a 0.8 si el STL resultante pesa demasiado.
"""

import sys

import bpy


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 2:
        print(__doc__)
        sys.exit(1)
    src, dst = argv[0], argv[1]
    voxel = float(argv[2]) if len(argv) > 2 else 0.4

    bpy.ops.wm.read_factory_settings(use_empty=True)

    ext = src.rsplit(".", 1)[-1].lower()
    if ext == "stl":
        bpy.ops.wm.stl_import(filepath=src)
    elif ext == "obj":
        bpy.ops.wm.obj_import(filepath=src)
    elif ext in ("glb", "gltf"):
        bpy.ops.import_scene.gltf(filepath=src)
    else:
        sys.exit(f"Formato no soportado: {ext}")

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        sys.exit("No se importo ninguna malla")

    # Unir todo en un solo objeto y aplicar remesh volumetrico.
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active

    mod = obj.modifiers.new(name="VoxelRemesh", type="REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel
    bpy.ops.object.modifier_apply(modifier=mod.name)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.ops.wm.stl_export(filepath=dst, export_selected_objects=True)
    print(f"Remesh OK -> {dst} (voxel={voxel})")


if __name__ == "__main__":
    main()
