#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup.sh – One-shot environment setup for CheXOne Production
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
# What it does:
#   1. Creates conda env "chexone311" (Python 3.11) if it doesn't exist
#   2. Installs all Python dependencies from requirements.txt
#   3. Downloads model weights from HuggingFace (cached, ~14 GB first time)
#   4. Runs a quick smoke test on one patient
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="chexone311"
PYTHON_VER="3.11"
SMOKE_PATIENT="15adb042e5149aca8f045e3fab6cf7f8"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  CheXOne Production – Environment Setup"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── 1. Check conda ───────────────────────────────────────────────────────────
if ! command -v conda &>/dev/null; then
    echo "ERROR: conda not found. Install Miniconda or Anaconda first:"
    echo "  https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

# ── 2. Create / reuse conda environment ──────────────────────────────────────
if conda env list | grep -qE "^${ENV_NAME}\s"; then
    echo "✓ Conda env '${ENV_NAME}' already exists"
else
    echo "Creating conda env '${ENV_NAME}' (Python ${PYTHON_VER}) ..."
    conda create -y -n "${ENV_NAME}" python="${PYTHON_VER}"
    echo "✓ Conda env created"
fi

# ── 3. Install Python dependencies ──────────────────────────────────────────
echo ""
echo "Installing Python packages ..."
conda run --no-capture-output -n "${ENV_NAME}" \
    pip install --upgrade pip
conda run --no-capture-output -n "${ENV_NAME}" \
    pip install -r "${SCRIPT_DIR}/requirements.txt"
echo "✓ Dependencies installed"

# ── 4. Check GPU ─────────────────────────────────────────────────────────────
echo ""
echo "Checking GPU availability ..."
GPU_OK=$(conda run --no-capture-output -n "${ENV_NAME}" \
    python -c "import torch; print('yes' if torch.cuda.is_available() else 'no')" 2>/dev/null || echo "no")

if [ "$GPU_OK" = "yes" ]; then
    GPU_NAME=$(conda run --no-capture-output -n "${ENV_NAME}" \
        python -c "import torch; print(torch.cuda.get_device_name(0))" 2>/dev/null)
    echo "✓ GPU detected: ${GPU_NAME}"
else
    echo "⚠ No GPU detected. Inference will run on CPU (very slow, ~30 min/patient)."
    echo "  For production use, an NVIDIA GPU with ≥16 GB VRAM is required."
fi

# ── 5. Pre-download model weights ───────────────────────────────────────────
echo ""
echo "Downloading model weights from HuggingFace (if not cached) ..."
echo "  This may take 10-20 minutes on first run (~14 GB)."
conda run --no-capture-output -n "${ENV_NAME}" \
    python -c "
from huggingface_hub import snapshot_download
path = snapshot_download('StanfordAIMI/CheXOne')
print(f'✓ Model cached at: {path}')
"

# ── 6. Smoke test ────────────────────────────────────────────────────────────
echo ""
echo "Running smoke test (1 patient: ${SMOKE_PATIENT}) ..."
cd "${SCRIPT_DIR}"
conda run --no-capture-output -n "${ENV_NAME}" \
    python run_local.py --patient "${SMOKE_PATIENT}"

# Verify outputs
EXPECTED_FILES=(
    "outputs/${SMOKE_PATIENT}/${SMOKE_PATIENT}_original.png"
    "outputs/${SMOKE_PATIENT}/${SMOKE_PATIENT}_model_only.png"
    "outputs/${SMOKE_PATIENT}/${SMOKE_PATIENT}_annotated.png"
    "outputs/${SMOKE_PATIENT}/${SMOKE_PATIENT}_results.json"
)
ALL_OK=true
for f in "${EXPECTED_FILES[@]}"; do
    if [ -f "${SCRIPT_DIR}/${f}" ]; then
        echo "  ✓ ${f}"
    else
        echo "  ✗ MISSING: ${f}"
        ALL_OK=false
    fi
done

echo ""
echo "═══════════════════════════════════════════════════════════════"
if [ "$ALL_OK" = true ]; then
    echo "  ✓ Setup complete! Everything works."
    echo ""
    echo "  Quick start:"
    echo "    conda activate ${ENV_NAME}"
    echo "    cd ${SCRIPT_DIR}"
    echo "    make run-local              # all 5 patients"
    echo "    make run-local-single P=<image_id>  # one patient"
else
    echo "  ⚠ Setup finished but smoke test had missing outputs."
    echo "    Check the errors above."
fi
echo "═══════════════════════════════════════════════════════════════"
echo ""
