#!/usr/bin/env bash
# Stop if a command fails or a required variable is missing.
set -euo pipefail

# Find the project folder containing this scripts directory.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Read which arm to calibrate from the first command argument.
ROLE="${1:-}"

# Accept only "follower" or "leader" as the arm choice.
case "$ROLE" in
  follower|leader) ;;
  *)
    echo "Usage: bash scripts/calibrate.sh follower|leader"
    exit 1
    ;;
esac

# Make sure the local configuration file exists.
if [[ ! -f "$ROOT/config.env" ]]; then
  echo "Copy config.example.env to config.env and fill it in first."
  exit 1
fi

# Read the arm IDs and USB ports from the local configuration.
source "$ROOT/config.env"

# Select this arm's settings and the matching LeRobot argument prefix.
if [[ "$ROLE" == follower ]]; then
  PORT="${FOLLOWER_PORT:-}"
  ARM_ID="${FOLLOWER_ID:-}"
  PREFIX=robot
else
  PORT="${LEADER_PORT:-}"
  ARM_ID="${LEADER_ID:-}"
  PREFIX=teleop
fi

# Check that this arm's port and ID have been filled in.
if [[ -z "$PORT" || "$PORT" == REPLACE_WITH_* ||
      -z "$ARM_ID" || "$ARM_ID" == REPLACE_WITH_* ]]; then
  echo "Set the $ROLE port and ID in config.env."
  exit 1
fi

# Start the guided calibration for the selected arm.
# Calibration files are stored in this arm's folder in the repository.
exec python -m lerobot.calibrate \
  "--$PREFIX.type=so101_$ROLE" \
  "--$PREFIX.port=$PORT" \
  "--$PREFIX.id=$ARM_ID" \
  "--$PREFIX.calibration_dir=$ROOT/calibration/$ROLE"
