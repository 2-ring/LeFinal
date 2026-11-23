#!/usr/bin/env bash
# Start from the Mac connected to the robot.
set -euo pipefail
cd "$(dirname "$0")/../.."
login="${OSCAR_LOGIN:?Set OSCAR_LOGIN to your Oscar SSH login (user@ssh.ccv.brown.edu)}"
socket="$HOME/.ssh/lefinal-oscar-$login.sock"
ssh_cmd=(ssh -S "$socket" "$login")
if ! ssh -S "$socket" -O check "$login" 2>/dev/null; then
    ssh -M -N -f -o ControlPersist=1h -o ServerAliveInterval=30 -S "$socket" "$login"
fi

job=$("${ssh_cmd[@]}" 'bash -s' <<'REMOTE'
set -euo pipefail
cd ~/lefinal-oscar
exec 9>.molmo-submit.lock
flock 9
jobs=$(squeue --me --name=lefinal-live --states=RUNNING,PENDING --noheader --format="%T %i")
job=$(awk '$1=="RUNNING" {print $2; exit}' <<< "$jobs")
if [[ -z "$job" ]]; then job=$(awk 'NR==1 {print $2}' <<< "$jobs"); fi
if [[ -n "$job" ]]; then
    echo "$job"
else
    export MOLMO_ROOT="/oscar/scratch/$USER/LeFinal/molmoact2"
    sbatch --account=default --parsable serve.sh
fi
REMOTE
)
job=${job%%;*}
[[ "$job" =~ ^[0-9]+$ ]] || { echo "Unexpected job ID: $job" >&2; exit 1; }
echo "Waiting for Oscar job $job to load Molmo..."
instance=$("${ssh_cmd[@]}" "bash -s -- $job" <<'REMOTE'
set -eu
cd ~/lefinal-oscar
log="live-$1.log"
while [[ -n "$(squeue -h -j "$1" -o %i)" ]]; do
    if [[ -f "$log" ]]; then
        id=$(sed -n 's/.*Policy server ready: deployment=lefinal-so101 instance=\([[:alnum:]]*\);.*/\1/p' "$log" | tail -1)
        if [[ -n "$id" ]]; then echo "$id"; exit 0; fi
    fi
    sleep 4
done
echo "Oscar job $1 ended during startup." >&2
tail -c 1500 "$log" >&2 || true
exit 1
REMOTE
)

# Only replace a relay owned by this account with the expected command line.
pid=$(lsof -nP -a -u "$(id -un)" -iTCP:17448 -sTCP:LISTEN -t || true)
if [[ -n "$pid" ]]; then
    args=$(ps -ww -p "$pid" -o command=)
    if [[ "$args" =~ [[:space:]]scripts/oscar/tunnel\.py[[:space:]]([0-9]+)[[:space:]]([^[:space:]]+)$ && "${BASH_REMATCH[2]}" == "$login" ]]; then
        if [[ "${BASH_REMATCH[1]}" != "$job" ]]; then
            kill "$pid"
            while kill -0 "$pid" 2>/dev/null; do sleep 0.1; done
            pid=""
        fi
    else
        echo "Port 17448 is occupied by another process (PID $pid)." >&2
        exit 1
    fi
fi
if [[ -z "$pid" ]]; then
    python3 scripts/oscar/tunnel.py "$job" "$login" &
    relay=$!
    trap 'kill "$relay" 2>/dev/null || true' EXIT
fi
.venv/bin/python - "$instance" <<'PY'
import sys
from lerobot.inference import RemoteInferenceConfig
from lerobot.remote_inference.client import RemoteClient

config = RemoteInferenceConfig(endpoint="tcp/127.0.0.1:17448", deployment="lefinal-so101",
                               instance=sys.argv[1], semantics="so101-degrees-gripper-percent-v1")
client = RemoteClient.connect(config)
client.close()
PY
echo "Molmo job $job is ready. Run .venv/bin/python scripts/rollout_molmo.py in another terminal."
if [[ -n "${relay:-}" ]]; then
    echo "Keep this terminal open for the tunnel. Ctrl+C closes it."
    wait "$relay"
fi
