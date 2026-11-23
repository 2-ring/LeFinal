#!/usr/bin/env bash
# Submit from lefinal-oscar with MOLMO_ROOT pointing to the completed setup.
#SBATCH --job-name=lefinal-live
#SBATCH --partition=gpu-debug
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=3
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --constraint=h100|l40s|a6000|a40
#SBATCH --time=01:00:00
#SBATCH --output=live-%j.log
set -euo pipefail
: "${MOLMO_ROOT:?Set MOLMO_ROOT to the directory prepared by setup.sh}"
port=$((24000 + SLURM_JOB_ID % 18000))
export HF_HUB_CACHE="$MOLMO_ROOT/hub" HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
exec "$MOLMO_ROOT/env/bin/lerobot-policy-server" \
    --config_path="$MOLMO_ROOT/so101.yaml" \
    --zenoh.listen_endpoints="[tcp/127.0.0.1:$port]"
