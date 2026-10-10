# Guía experta: Hyper3D Rodin — de una imagen a una figura 3D imprimible (y vendible)

> Investigación realizada en octubre de 2026 con ~22 agentes de búsqueda sobre fuentes
> primarias (docs oficiales, repos de DeemosTech leídos a nivel de código, ToS, BOE,
> reguladores UE) + análisis de tutoriales en vídeo vía Gemini + **prueba real end-to-end**
> ejecutada con los scripts de esta carpeta. Los precios/límites de Hyper3D cambian rápido:
> verifica en hyper3d.ai/pricing antes de presupuestar.

---

## 1. Resumen ejecutivo

- **Rodin (hyper3d.ai, de Deemos Tech)** es, en 2026, el generador imagen→3D con mejor
  fidelidad geométrica del mercado. La generación actual es **Gen-2.5** (mayo 2026), con
  5 niveles de "esfuerzo" (`Gen-2.5-Extreme-Low` … `Gen-2.5-Extreme-High`, hasta 2–10M caras).
- **Automatizar la web con un navegador (Playwright/Puppeteer) viola los ToS** (§6.3 prohíbe
  robots/scripts no autorizados). **La vía correcta y oficial es la API REST**, con todo un
  ecosistema oficial para agentes: MCP server, CLI npm, plugin de Claude Code, nodos ComfyUI
  y addon de Blender. No hay motivo para emular a un humano en la web.
- La API nativa requiere **plan Business (~120 $/mes)**; para probar existe la **clave
  gratuita oficial `vibecoding`** (limitada), y para producción sin suscripción,
  **fal.ai revende Rodin a ~0,40 $/generación** (0,80 $ Extreme-High).
- **La malla de Rodin NO está garantizada como estanca**, pero nuestra prueba real confirmó
  lo mejor que decía la literatura: el export viene fragmentado por costuras UV y, una vez
  **soldados los vértices, resultó perfectamente watertight** (1 componente, 0 aristas
  abiertas). Aun así, la verificación/reparación local es **obligatoria** en un pipeline
  autónomo: nada en la API lo garantiza contractualmente.
- El negocio de figuras personalizadas desde foto es real (30–150 € en Etsy, tartas de boda
  119–400 €, nicho mascotas en auge), con margen bruto de material >90%; el coste real es la
  mano de obra, exactamente lo que este pipeline automatiza. **Línea roja legal**: figuras de
  famosos o personajes con marca NO son vendibles (LO 1/1982 art. 7.6 + STS 486/2022,
  copyright/trademark); solo clientes que consienten expresamente.

---

## 2. La plataforma (lo que hace un humano en hyper3d.ai/workspace/rodin)

Flujo del workspace: subir 1–5 imágenes y/o prompt → **Generate** (preview orbital
gratuito) → ajustes de geometría (pose T/A, modo Creative/Faithful, simetría, Redo gratis,
"BANG to Parts" gratis) → **Confirm** (aquí se gastan los créditos) → generación de material
→ panel **Pack**: exportar `.glb/.fbx/.obj/.usdz/.stl` con variantes Base/LOD/High-poly.

Herramientas complementarias de la plataforma:
- **BANG**: descomposición en piezas (para imprimir por partes o cama pequeña); también por
  API (`/api/v2/bang`, strength 2–12).
- **OmniCraft Mesh Editor**: editor web con remesh por vóxeles, retopología, decimación,
  esculpido y pintura PBR; importa OBJ/FBX/GLB/STL/PLY/DAE ≤200 MB, exporta OBJ/PLY/STL.
  Es la vía de reparación "oficial" si no quieres Blender.
- **Rodin Gen-2 Edit / Part Refine**: edición por prompt de regiones del modelo (workspace).
- **ChatAvatar**: producto hermano para cabezas/avatares animables; **sin API pública**
  (verificado: 0 menciones en todo el tooling oficial) — para nuestro pipeline, ignorar.
- En Formnext Asia 2026 demostraron preparación de impresión con IA (reconstrucción de
  malla, separación de colores a 3MF, corte por cama); estado de despliegue aún parcial.

---

## 3. Automatización: vías disponibles (de mejor a peor)

| Vía | Coste | Notas |
|---|---|---|
| **API REST nativa** (`api.hyper3d.com/api/v2`) | 0,5 créditos/gen (≈0,29–0,75 $) | Requiere plan Business; control total; la que usan nuestros scripts |
| Clave de prueba `vibecoding` (misma API) | gratis | Oficial (posts de @DeemosTech), limitada por día; validada en nuestra prueba con Gen-2.5-Low y Gen-2.5-High |
| **fal.ai** `fal-ai/hyper3d/rodin/v2.5` | 0,40 $/gen (0,80 $ Extreme-High; HighPack +0,80 $) | Sin suscripción; imágenes por URL; colas y webhooks |
| CLI oficial `@hyper3d/cli` (npm, Node ≥22) | créditos de tu cuenta | `hyper3d auth login` (OAuth) + `generate/status/result/bang` |
| MCP oficial `DeemosTech/rodin-api-mcp` | créditos | OJO: esquema anticuado (Gen-1.5) y un bug conocido; mejor los scripts propios |
| Plugin Claude Code `DeemosTech/rodin3d-skills` | créditos | `/plugin marketplace add DeemosTech/rodin3d-skills`; su `api_client.py` es la referencia del contrato wire |
| ComfyUI (`DeemosTech/ComfyUI-Rodin`) / Blender addon / blender-mcp | créditos | Para flujos visuales o integración con Blender |
| ~~Automatización del navegador~~ | — | **Prohibida por ToS §6.3**; además frágil (OAuth Google bloquea headless) |

---

## 4. La API al detalle (contrato verificado en el código oficial)

### Flujo asíncrono (3 endpoints, todos POST, auth `Authorization: Bearer <KEY>`)

```
1) POST /api/v2/rodin      multipart/form-data
   -> 201 {error, message, uuid, jobs:{uuids:[...], subscription_key}}
2) POST /api/v2/status     {"subscription_key": ...}
   -> {jobs:[{uuid, status}]}   status ∈ Waiting|Generating|Done|Failed
3) POST /api/v2/download   {"task_uuid": <uuid de nivel superior>}
   -> {list:[{name, url}]}     ¡descargar YA: las URLs caducan en ~10 min!
```

⚠️ Los ficheros se sirven desde **`file.hyper3d.com`** (CDN aparte: añádelo al firewall).
⚠️ No reintentes el POST de envío ante excepciones de red: duplica tareas (y cobros).
⚠️ Resultados retenidos 7 días; los datos de API no se usan para entrenar (política oficial).

### Parámetros que importan (Gen-2.5)

| Parámetro | Valores | Para figura imprimible |
|---|---|---|
| `images` | 1–5 ficheros (JPEG/PNG/WebP, 512–4096 px, <16 MB) | la **1ª imagen** manda en la textura |
| `tier` | `Gen-2.5-{Extreme-Low,Low,Medium,High,Extreme-High}` | **nunca lo omitas** (sin tier cae a Gen-1.5); `High` es el dulce; `Extreme-High` (+0,5 cr) hasta 2M caras |
| `mesh_mode` | `Raw` (triángulos) / `Quad` | **Raw** para imprimir (máximo detalle); Quad solo si vas a esculpir/editar |
| `quality` | high/medium/low/extra-low (Raw: 1M/500k/60k/20k caras) | `high`; o `quality_override` con cifra exacta (500–1M; 2M en tiers High/Extreme-High; Quad máx. 200k) |
| `geometry_file_format` | glb/usdz/fbx/obj/**stl** | `stl` directo, o `glb` y convertir en local (nuestra opción: así conservas color) |
| `material` | PBR/Shaded/All/None | `None`/`Shaded` si solo imprimes monocolor (más rápido); `PBR` si quieres textura |
| `geometry_instruct_mode` | `faithful`/`creative` | **faithful** para parecido con la foto; creative "idealiza" |
| `seed` | 0–65535 | fíjala: itera barato y regenera la buena en tier alto con la misma semilla |
| `TAPose` | bool | `true` solo para personajes a riggear; `false` conserva la pose de la foto |
| `bbox_condition` | `[ancho,alto,largo]` (1–300) | restringir proporciones |
| `use_original_alpha` | bool | `true` si la imagen ya trae el fondo recortado (PNG con alfa) |
| Texturas | `hd_texture`, `texture_delight`, `texture_mode`, `addons=HighPack` | irrelevantes para impresión monocolor; HighPack +1 cr = 4K; `texture_mode=extreme-high` +2 cr (hasta 12K); `texture_delight` si la foto tiene brillos/iluminación dura |
| multi-vista | `condition_mode` concat/fuse (Gen-1/2) → en Gen-2.5 se usa el orden de `images` (+`image_label` opcional) | concat = varias vistas del MISMO objeto |

Errores típicos: `400 INVALID_REQUEST`, `401 USER_NOT_FOUND/UNAUTHORIZED`,
`429` (throttling), `INSUFFICIENT_FUND`, `SUBSCRIPTION_PLAN_TOO_LOW` ("se requiere
Business para Gen-2.5"), `NO_ACTIVE_SUBSCRIPTION`. Los fallos devuelven los créditos.

### Recetas oficiales

- **Máxima calidad**: `tier=Gen-2.5-High, quality=high, mesh_mode=Raw, material=PBR,
  hd_texture, texture_delight, addons=HighPack`.
- **Borrador rápido** (~20–40 s, validado en nuestra prueba): `tier=Gen-2.5-Low,
  material=Shaded, mesh_mode=Raw, quality_override=20000, texture_mode=low`.
- **Busto hiperrealista desde fotos de móvil** (tutorial de BioMakers, analizado con
  Gemini — el flujo experto exacto para caras reales):
  `tier=Gen-2.5-Extreme-High` (+0,5 cr) + **`is_micro=true`** (incrusta poros, párpados y
  surcos del pelo EN la geometría — crucial para imprimir, porque los mapas de normales no
  se imprimen) + **`texture_delight=true`** (neutraliza las sombras de las fotos de móvil)
  + `texture_mode=extreme-high` + `addons=HighPack` (12K) + `mesh_mode=Raw` con el máximo
  de caras. Entrada: frente + **perfiles estrictos izquierdo y derecho + nuca** (sin la
  nuca y los perfiles, la IA deforma la parte trasera y las orejas). Impresión del
  tutorial: Bambu Studio con soportes árbol en mentón/cejas/nariz/pelo, FDM en filamento
  gris claro; para máximo detalle facial, resina.

---

## 5. Preparar la imagen de entrada (el 50% del resultado)

Del tutorial de **Kuttercraft** (el vídeo que enviaste, analizado con Gemini) + guías 2026:

1. **Quita el fondo** → PNG con transparencia (remove.bg a mano; `rembg` en Python para el
   agente). Con JPG de fondo plano la IA "aplasta" los laterales adaptándose al marco;
   con PNG recortado interpreta bien la silueta. Pasa `use_original_alpha=true`.
2. **Limpia elementos espurios**: gotas, manchas, sombras duras, degradados — la IA los
   convierte en geometría colgante real.
3. **Escala/nitidez**: si la imagen es <1024 px, upscale previo (Upscayl/REAL-ESRGAN x3–4).
   Rango admitido 512–4096 px; ideal ≥1024×1024, sujeto ocupando >50% del encuadre.
4. **Multi-vista cuando importe el parecido**: frontal + perfil + espalda (3–5 imágenes,
   diseño/escala/iluminación consistentes) vence casi siempre a una sola "foto bonita".
   El truco experto 2026: generar primero un *turnaround* consistente con un modelo de
   imagen (Nano Banana / Seedream) y trocearlo en vistas para Rodin. La 1ª imagen define
   la textura: pon primero la que mejor muestre color y superficie.
5. **Itera**: la generación tiene varianza; genera 2–3 veces (misma seed ± variaciones) y
   quédate con la malla más limpia. Los redos antes de confirmar son gratis en la web.
6. Casos difíciles conocidos: pelo fino/mechones, orejas, geometría trasera inventada
   (la IA "alucina" lo que no ve), simetrías fantasma en formas orgánicas.

---

## 6. Imprimibilidad: del GLB/STL de Rodin a la impresora

### Lo que aprendimos (y verificamos con la prueba real)

- El export de Rodin viene **fragmentado por costuras UV** (nuestra prueba: 1.677
  "componentes" y 13.542 aristas frontera aparentes). **No es daño real**: tras soldar
  vértices ignorando UV/normales (`merge_vertices(merge_tex=True, merge_norm=True)` en
  trimesh) quedó **perfectamente estanca**: 1 componente, 0 agujeros, normales coherentes.
- Aun así **verifica siempre**: no hay garantía contractual, los tests independientes son
  pocos, y los fallos de diseño (base no plana, paredes finas, pelo de 0,2 mm) no los
  arregla ninguna comprobación topológica.

### Pipeline de reparación local (nuestros scripts)

```
rodin_pipeline.py  →  mesh_check.py  →  (si hace falta) blender_remesh.py  →  slicer
```

1. `mesh_check.py`: suelda vértices → limpia caras degeneradas → elimina islas pequeñas →
   `fill_holes` → normales → si sigue abierta, **pymeshfix** (MeshFix: reconstruye una
   malla estanca única; la herramienta con más garantías según la literatura) → escala a
   mm reales (GLB es Y-arriba: el script lo rota a Z-arriba).
2. `blender_remesh.py` (Blender headless): remesh por vóxeles OpenVDB — el "martillo" que
   soluciona cualquier malla a costa de detalle < tamaño de vóxel (0,2–0,4 para 120 mm).
3. Slicer con reparación propia: PrusaSlicer `--repair` / Netfabb (lo que hacía Kuttercraft).

### Valores de referencia para resina (figuras 10–15 cm)

- Proceso: **MSLA/resina** (detalle ~0,1 mm) para figuras; FDM solo para piezas grandes,
  robustas o multicolor sin pintar.
- Capa 0,05 mm estándar (0,03 para pieza vitrina); paredes huecas 2–3 mm; **≥2 orificios
  de drenaje de 3–4 mm** en puntos bajos; inclinación 30–45°; soportes automáticos +
  repaso manual en puntas finas y bajos de mentón/mandíbula (lo que el auto siempre falla).
- Engrosa antes de imprimir todo lo que baje de ~0,6 mm sin soporte / 0,4 mm con soporte
  (mechones de pelo, dedos).
- Pelado de la cadena 100% headless (verificada en código fuente):
  `prusa-slicer --export-sla --load perfil_sla.ini` (hollowing_enable=1, supports_enable=1
  → genera soportes automáticos sin GUI) → `UVtoolsCmd convert salida.sl1 ctb/goo`.
  Único hueco sin solución headless nativa: **los orificios de drenaje** (gizmo de GUI) —
  solución: taladrarlos a nivel de malla (boolean con cilindros via trimesh+manifold3d)
  o preparar una vez un 3MF con agujeros y relaminar por CLI.
- Color: STL no lleva color. Para multicolor: GLB→3MF (Bambu AMS, hasta 16 filamentos) o
  servicios full-color (JLC3DP resina full-color desde ~5 $, acepta OBJ+MTL+textura 4K).

---

## 7. El pipeline del agente completo (arquitectura objetivo)

```
[foto cliente] → validación/consentimiento → rembg (+upscale si <1024px)
      → (opcional) turnaround multi-vista con modelo de imagen
      → Rodin API: borrador rápido  → ¿OK visual? (preview_render / render propio)
      → Rodin API: tier High/Extreme-High, Raw, seed fijada, faithful, GLB+PBR
      → descarga inmediata (URLs 10 min; CDN file.hyper3d.com)
      → mesh_check.py (soldar/verificar/reparar/escalar mm)
      → [monocolor] STL → prusa-slicer --export-sla → UVtoolsCmd → impresora
        [color]     GLB→3MF → Bambu / servicio full-color
      → control de calidad visual (render 3 vistas) → cliente aprueba → imprimir/enviar
```

Prueba real ejecutada (10-oct-2026, clave `vibecoding`): imagen `niño de comunión` 2000×2000
→ Gen-2.5-Low rápido en ~20 s → GLB 1,21 MB → reparado y escalado → **STL estanco de
50×52×120 mm listo para slicer**. La pasada Gen-2.5-High (1M caras) funciona igual con
`--tier Gen-2.5-High --quality high`.

Costes por figura (solo generación): 0,40–0,80 $ en fal.ai; ~0,29–0,75 $ en API nativa
según plan. Material resina figura 12 cm: ~1–4 $. El resto es margen y mano de obra.

---

## 8. Producto vendible: mercado y economía

- **Precios observados (2026)**: figura personalizada desde foto en Etsy 30–100 $
  (pintadas a mano 100–190 $); mascotas 30–100 $ según tamaño (3"–12"); **tartas de boda
  119–400 $** (el nicho premium); minis D&D commoditizadas (Hero Forge 20–30 $) — ahí el
  parecido fotográfico es el diferenciador. STL digitales solos: 5–12 $.
- **Nicho más fuerte medido**: memoriales de mascotas (mercado creciendo ~9%/año); la IA
  desde foto permite además figuras de mascotas/personas fallecidas (imposible con
  escáner/fotogrametría de cabina, su competencia directa).
- **Economía unitaria** (referencia del sector): figura 12 cm vende a 79–120 $, coste total
  ~45 $ (dominado por laminado/lavado/curado/lijado/pintura, no material). Todo lo que
  automatices del modelado y post-procesado es margen directo.
- Mitigaciones estándar del sector: **preview digital antes de imprimir** (nuestro render
  de 3 vistas), pasada de retoque opcional, tallas escalonadas, suplemento por pintado.
- Sin impresora propia: JLC3DP (resina desde céntimos, X-Resin para figuras, full-color),
  Craftcloud (comparador), Treatstock (makers locales). Shapeways quebró en 2024 y
  renació más pequeño — no construir el negocio sobre un único servicio.
- Acabado vendible: lavado IPA 2–5 min → curado UV → lijado 220→600 → imprimación
  (Vallejo aerógrafo ~30 PSI) → acrílicos → barniz. Tiers de calidad de pintura:
  mesa 5–15 €, parade 18–55 €, vitrina 50–200 €+.

---

## 9. Legal (España/UE) — léelo antes de vender nada

- **Famosos: NO.** LO 1/1982 art. 7.6: usar imagen/nombre/voz con fines comerciales sin
  consentimiento expreso es intromisión ilegítima; la STS 486/2022 cierra la puerta a las
  excepciones del art. 8 cuando hay ánimo de lucro. Personajes con marca (Marvel, etc.):
  además copyright + trademark. El modelo de Chris Evans de la imagen de referencia solo
  vale como benchmark técnico privado, nunca como producto.
- **Clientes**: consentimiento **expreso** (casilla en el checkout) que nombre el fin
  comercial; el que sube la foto debe garantizar el consentimiento de TODAS las personas
  retratadas. **Menores**: consentimiento escrito de los representantes legales (y régimen
  del Ministerio Fiscal del art. 3); edad de consentimiento de datos en España: 14 años.
  **Fallecidos**: herederos (art. 4; hasta 80 años).
- **GDPR**: subir la foto del cliente a Rodin es una transferencia a Deemos Corporation
  (Delaware; origen Shanghái; ubicación real de proceso no publicada, sin DPA/SCC públicas
  ni certificación DPF). Para producción: pedir DPA/SCCs a hello@deemos.com + TIA,
  informar en la política de privacidad (retención API: 7 días, sin uso para entrenar),
  y auto-borrar fotos y mallas tras el pedido. La foto de una cara para generar malla no
  es automáticamente dato biométrico del art. 9 (Recital 51), pero pide consentimiento
  explícito igualmente.
- **AI Act (art. 50, vigente desde ago-2026)**: etiqueta los previews digitales
  fotorrealistas como "generado con IA" (la figura física difícilmente es deepfake, el
  render sí puede serlo); en Etsy la divulgación de uso de IA en la descripción es
  obligatoria por sus Creativity Standards. **Amazon Handmade: incompatible** (prohíbe
  "automated technology"); Shopify es el canal más limpio para un flujo automatizado.
- **Derechos sobre el output**: Rodin dice "no limitamos tu uso del Output" sujeto a plan
  (la licencia comercial plena aparece ligada a planes de pago; el output de IA sin autoría
  humana no genera copyright propio) → el foso del negocio es la personalización y el
  servicio, no la propiedad del modelo 3D.

---

## 10. Decisiones recomendadas para tu proyecto

1. **Generación**: API nativa con `vibecoding` para desarrollo; **fal.ai para producción**
   (sin cuota mensual) salvo que el volumen justifique Business (>~300 figuras/mes).
2. **Parámetros por defecto**: `Gen-2.5-High + Raw + quality high + faithful + seed fijada`,
   `GLB+PBR` (color para preview/3MF) y STL derivado en local.
3. **Post-procesado**: `mesh_check.py` siempre; `blender_remesh.py` como fallback; cadena
   PrusaSlicer CLI + UVtools si imprimes en resina propia.
4. **Agente**: no toques el navegador; el plugin oficial `rodin3d-skills` ya convierte a
   Claude Code en operador de Rodin, y nuestros scripts hacen lo mismo sin dependencias.
5. **Producto**: empieza por mascotas/parejas/comuniones (tu imagen de prueba es exactamente
   el producto), preview digital siempre, checkout con consentimientos, Shopify o Etsy
   (con divulgación IA).

---

## 11. Archivos de esta carpeta

| Archivo | Qué hace |
|---|---|
| `app.py` | **Prueba de concepto con interfaz web (Gradio)**: sube fotos → visor 3D + STL imprimible |
| `rodin_pipeline.py` | Cliente API completo: enviar → sondear → descargar (defaults de impresión) |
| `mesh_check.py` | Informe + reparación de imprimibilidad (trimesh/pymeshfix) + escalado a mm |
| `blender_remesh.py` | Remesh por vóxeles con Blender headless (fallback a prueba de todo) |
| `video_workflow_extract.py` | Extrae el flujo de un tutorial de YouTube vía Gemini (`GEMINI_API_KEY`) |
| `requirements.txt` | `requests`, `trimesh`, `numpy` (+opcionales `pymeshfix`, `fal-client`) |

Uso mínimo:

```bash
pip install -r requirements.txt pymeshfix
export HYPER3D_API_KEY=...   # u omite para usar la clave de prueba 'vibecoding'
python rodin_pipeline.py --image figura.png --tier Gen-2.5-High --format glb --output ./out
python mesh_check.py ./out/base_basic_pbr.glb --repair --height-mm 120 --out figura_print.stl

# o la interfaz web (visor 3D incluido):
pip install gradio
python app.py            # abre http://127.0.0.1:7860  (--share para enlace publico)
```

## 12. Fuentes principales

- Especificación oficial Gen-2.5: `docs.hyper3d.ai/en/api-specification/rodin-gen2-5` y
  `developer.hyper3d.ai/api-specification/rodin-gen2.5`
- Código oficial (contrato wire): `github.com/DeemosTech/rodin3d-skills`,
  `DeemosTech/ComfyUI-Rodin`, `DeemosTech/hyper3d-cli`, `DeemosTech/rodin-api-mcp`,
  `DeemosTech/rodin3d-bang-skills`
- ToS/legal Hyper3D: `hyper3d.ai/legal/{terms,privacy,copyright-license}`,
  `developer.hyper3d.ai/legal/data-policy`
- fal.ai: `fal.ai/models/fal-ai/hyper3d/rodin/v2.5`
- Impresión: guías Formlabs/JLC3DP/Lychee/ChiTuBox; fuente PrusaSlicer (claves SLA CLI);
  `github.com/sn4k3/UVtools`; `pyvista/pymeshfix`; 3dnatives (Formnext Asia 2026)
- Negocio/legal ES-UE: BOE LO 1/1982; STS 486/2022; AEPD; Comisión Europea (AI Act art. 50);
  Etsy Creativity Standards
- Tutoriales: Kuttercraft (imagen 2D→impresión, analizado vía Gemini), BioMakers (busto
  hiperrealista desde fotos de móvil con Gen-2.5 Extreme-High+Micro+Delight, analizado vía
  Gemini), Scenario/Runware/WaveSpeed (espejos de la API), geeky-gadgets (flujo multi-vista
  Nano Banana)
