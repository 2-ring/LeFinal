#!/usr/bin/env bash
# Run on an Oscar compute node with internet access.
set -euo pipefail

: "${MOLMO_ROOT:?Set MOLMO_ROOT to an absolute project directory on Oscar.}"
if [[ "$MOLMO_ROOT" != /* ]]; then
    echo "MOLMO_ROOT must be absolute so future jobs can use the same environment." >&2
    exit 1
fi

config_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_file="${1:-$config_dir/so101.yaml}"
if [[ ! -r "$config_file" && $# -eq 0 && -n "${SLURM_JOB_ID:-}" ]]; then
    # sbatch spools the script itself. Its --chdir directory still contains the YAML.
    config_file="$PWD/so101.yaml"
fi
if [[ ! -r "$config_file" ]]; then
    echo "Pass the path to so101.yaml as the first argument." >&2
    exit 1
fi
export UV_CACHE_DIR="${UV_CACHE_DIR:-$HOME/scratch/lefinal-cache/uv}"
export HF_XET_CACHE="${HF_XET_CACHE:-$HOME/scratch/lefinal-cache/xet}"
export HF_HUB_CACHE="$MOLMO_ROOT/hub"
export UV_PYTHON_INSTALL_DIR="$MOLMO_ROOT/python"
export UV_PROJECT_ENVIRONMENT="$MOLMO_ROOT/env"
export UV_LINK_MODE=copy
mkdir -p "$MOLMO_ROOT"

# Install uv only if the node doesn't already provide it.
if command -v uv >/dev/null 2>&1; then
    uv_bin="$(command -v uv)"
else
    python3 -m venv "$MOLMO_ROOT/bootstrap"
    "$MOLMO_ROOT/bootstrap/bin/python" -m pip install uv
    uv_bin="$MOLMO_ROOT/bootstrap/bin/uv"
fi

source_dir="$MOLMO_ROOT/lerobot-v0.7.0"
if [[ ! -d "$source_dir" ]]; then
    git clone --depth 1 --branch v0.7.0 https://github.com/huggingface/lerobot.git "$source_dir"
fi
if [[ "$(git -C "$source_dir" rev-parse HEAD)" != 410c095eacc0011d998a73383eb94abed2715af0 ]]; then
    echo "Expected the LeRobot v0.7.0 release in $source_dir." >&2
    exit 1
fi
if [[ ! -x "$UV_PROJECT_ENVIRONMENT/bin/python" ]]; then
    "$uv_bin" venv --python 3.12 --managed-python "$UV_PROJECT_ENVIRONMENT"
fi
# Oscar's driver 575 supports CUDA 12.9. LeRobot's release lock selects CUDA 13.
# Use PyTorch's matching CUDA 12.8 wheels for the Python 3.12 x86-64 environment.
wheel_base=https://download.pytorch.org/whl/cu128
wheel_tag=cp312-cp312-manylinux_2_28_x86_64.whl
"$uv_bin" pip install --python "$UV_PROJECT_ENVIRONMENT/bin/python" \
    "${source_dir}[remote,molmoact2]" \
    "torch @ $wheel_base/torch-2.11.0%2Bcu128-$wheel_tag" \
    "torchvision @ $wheel_base/torchvision-0.26.0%2Bcu128-$wheel_tag"

"$MOLMO_ROOT/env/bin/python" - "$config_file" <<'PY'
import json
from pathlib import Path
import sys

from huggingface_hub import snapshot_download
import yaml

deployment = yaml.safe_load(Path(sys.argv[1]).read_text())
model = deployment["model"]
converted = snapshot_download(model["repo_or_path"], revision=model["revision"])
print("LeRobot checkpoint:", converted, flush=True)

# v0.7.0 initializes the original model before loading the converted weights.
# Cache the upstream main reference, which both saved configs request by default.
policy = json.loads((Path(converted) / "config.json").read_text())
upstream = snapshot_download(
    policy["checkpoint_path"],
    revision=policy["checkpoint_revision"],
    ignore_patterns=["*.py", "*.pyc", "__pycache__/*"],
)
print("Ai2 checkpoint:", upstream, flush=True)
PY

if [[ ! "$config_file" -ef "$MOLMO_ROOT/so101.yaml" ]]; then
    install -m 644 "$config_file" "$MOLMO_ROOT/so101.yaml"
fi
echo "Server environment, model cache, and so101.yaml are ready in $MOLMO_ROOT"
