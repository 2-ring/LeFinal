#!/usr/bin/env bash
# Stop if a command fails or a required variable is missing.
set -euo pipefail

# Find the project folder containing this scripts directory.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Use --no-cameras for arm-only testing without changing config.env.
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --no-cameras ) ]]; then
  echo "Usage: bash scripts/teleoperate.sh [--no-cameras]"
  exit 1
fi

# Make sure the local configuration file exists.
if [[ ! -f "$ROOT/config.env" ]]; then
  echo "Run python scripts/setup_config.py, or copy config.example.env to config.env and fill it in."
  exit 1
fi

# Read the arm IDs, USB ports, and cameras from the local configuration.
source "$ROOT/config.env"

# Check that all required settings have been filled in.
for name in FOLLOWER_PORT LEADER_PORT FOLLOWER_ID LEADER_ID; do
  value="${!name:-}"
  if [[ -z "$value" || "$value" == REPLACE_WITH_* ]]; then
    echo "Set $name in config.env."
    exit 1
  fi
done

# Use the configured cameras and show their live feeds in Rerun.
CAMERAS='{}'
DISPLAY_DATA=false
if [[ "${1:-}" != --no-cameras ]]; then
  if [[ -z "${ROBOT_CAMERAS:-}" || "$ROBOT_CAMERAS" == *REPLACE_WITH_* ]]; then
    echo "Run python scripts/setup_config.py --cameras-only to configure cameras, or use --no-cameras."
    exit 1
  fi
  CAMERAS="$(python - "$ROBOT_CAMERAS" <<'PY'
import json
import sys

try:
    cameras = json.loads(sys.argv[1])
except ValueError:
    sys.exit("ROBOT_CAMERAS must contain valid JSON in config.env.")
if not isinstance(cameras, dict):
    sys.exit("ROBOT_CAMERAS must be a JSON object in config.env.")
print(json.dumps(cameras, separators=(",", ":")))
PY
)"
  if [[ "$CAMERAS" != '{}' ]]; then
    DISPLAY_DATA=true
  fi
fi

# Check that both arms have saved calibration files.
for path in \
  "$ROOT/calibration/follower/$FOLLOWER_ID.json" \
  "$ROOT/calibration/leader/$LEADER_ID.json"; do
  if [[ ! -f "$path" ]]; then
    echo "Missing calibration: $path"
    exit 1
  fi
done

# Start teleoperation: move the leader to control the follower.
# Use the saved calibration files. Press Ctrl+C to stop.
exec python -m lerobot.teleoperate \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id="$FOLLOWER_ID" \
  --robot.calibration_dir="$ROOT/calibration/follower" \
  --robot.cameras="$CAMERAS" \
  --teleop.type=so101_leader \
  --teleop.port="$LEADER_PORT" \
  --teleop.id="$LEADER_ID" \
  --teleop.calibration_dir="$ROOT/calibration/leader" \
  --display_data="$DISPLAY_DATA"
