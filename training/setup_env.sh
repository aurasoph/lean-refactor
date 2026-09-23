#!/usr/bin/env bash
# Run this on the LOGIN node (needs internet) once, before submitting the
# sbatch job — GPU compute nodes on Hyak are assumed to have no outbound
# internet, so the venv and the base model both have to be staged here first.
set -euo pipefail

ROOT=/gscratch/amath/aurasoph/lean-refactor-training
PY=/gscratch/amath/aurasoph/.uv_python/cpython-3.12.13-linux-x86_64-gnu/bin/python3
VENV="$ROOT/venv"
export HF_HOME=/gscratch/amath/aurasoph/hf_cache

mkdir -p "$ROOT/logs" "$ROOT/checkpoints"

if [ ! -d "$VENV" ]; then
  "$PY" -m venv "$VENV"
fi
source "$VENV/bin/activate"

pip install --upgrade pip
# cu121 wheel: bundles its own CUDA runtime, only needs a driver new enough
# for it (true on the gpu-rtx6k nodes) — no dependency on the module system's
# cuda/* versions.
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r "$(dirname "$0")/requirements.txt"

echo "--- pre-downloading base model into HF_HOME=$HF_HOME (compute nodes have no internet) ---"
# MODELS="m-a-p/OProver-8B" ./setup_env.sh to stage the real base (~16GB).
# Also copy train_sft.py and templates/ into $ROOT: the default --chat-template
# is resolved next to train_sft.py.
for m in ${MODELS:-Qwen/Qwen2.5-Coder-1.5B-Instruct}; do
  python3 -c "from huggingface_hub import snapshot_download; print('cached', snapshot_download('$m'))"
done

echo "env ready at $VENV"
