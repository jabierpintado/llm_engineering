#!/bin/bash
# Configuracion automatica de la app Rodin en macOS.
# Uso (una sola linea en el Terminal):
#   bash <(curl -sL https://raw.githubusercontent.com/jabierpintado/llm_engineering/claude/rodin-3d-generation-ysg526/extras/rodin/setup_mac.sh)
set -e

echo "== Paso 1/5: buscando un Python adecuado (3.10-3.13) =="
PY=""
for v in 3.13 3.12 3.11 3.10; do
  if command -v python$v >/dev/null 2>&1; then PY=python$v; break; fi
done
if [ -z "$PY" ]; then
  # 3.14 recien salido: muchas librerias aun no tienen binarios -> evitarlo
  if command -v python3.14 >/dev/null 2>&1; then
    echo "Solo encuentro Python 3.14 (demasiado nuevo para algunas librerias)."
  fi
  echo ""
  echo ">> Necesitas Python 3.12 o 3.13. Descarga el instalador aqui:"
  echo "   https://www.python.org/downloads/release/python-3137/"
  echo "   (archivo 'macOS 64-bit universal2 installer', doble clic, Instalar)"
  echo "   Despues ABRE UN TERMINAL NUEVO y repite este mismo comando."
  exit 1
fi
echo "Usare: $PY ($($PY --version))"

echo "== Paso 2/5: repositorio =="
if [ ! -d "$HOME/llm_engineering/.git" ]; then
  git clone https://github.com/jabierpintado/llm_engineering.git "$HOME/llm_engineering"
fi
cd "$HOME/llm_engineering"
git fetch origin claude/rodin-3d-generation-ysg526
git checkout claude/rodin-3d-generation-ysg526
git pull --ff-only origin claude/rodin-3d-generation-ysg526 || true

echo "== Paso 3/5: entorno virtual limpio =="
cd extras/rodin
rm -rf venv
$PY -m venv venv
source venv/bin/activate

echo "== Paso 4/5: dependencias (puede tardar 2-3 min) =="
pip install --upgrade pip -q
pip install -q -r requirements.txt

echo "== Paso 5/5: arrancando la app =="
echo ""
echo ">> Cuando aparezca la URL https://xxxx.gradio.live, abrela en el navegador."
echo ">> Para relanzar otro dia:  cd ~/llm_engineering/extras/rodin && source venv/bin/activate && python app.py --share"
echo ""
exec python app.py --share
