# LeFinal: SO-101 Teleoperation

Setup and teleoperation for our SO-101 leader/follower arms, with wrist and
stand cameras. Run project commands from this repository's root folder.

## 1. Install

Create and activate the Conda environment:

```bash
conda env create -f environment.yml
conda activate so101
```

Extract the team's Hiwonder `lerobot.zip` into a separate folder. Inside that
folder (containing LeRobot's `pyproject.toml`), run:

```bash
python -m pip install -e ".[feetech]"
```

Keep that source folder in place, then return to this repository. Keep the
`so101` environment active when using the scripts.

## 2. Set Up the Hardware

Connect both arms' USB cables and power supplies, and connect the cameras.

```bash
python scripts/setup_config.py
```

Follow the prompts to name the arms and identify their ports. Unplug only the
arm requested, then reconnect it to the same USB socket.

For cameras, run the printed `open` command to inspect the preview images.
Assign the follower-mounted camera to `wrist` and the external task camera to
`stand`. Answer `n` to the camera question to run without cameras.

Setup saves `config.env` and starts guided calibration for any arm missing its
calibration file. Follow the prompts to position and manually move each arm.
Existing calibration files are reused.

## 3. Teleoperate

```bash
bash scripts/teleoperate.sh
```

Move the leader to control the follower. Camera feeds appear in Rerun when
configured. Press **Ctrl+C** to stop.

## Repeat Individual Steps

| Task | Command |
| --- | --- |
| Update cameras only | `python scripts/setup_config.py --cameras-only` |
| Create missing calibrations using saved ports | `python scripts/setup_config.py --calibration-only` |
| Recalibrate follower | `bash scripts/calibrate.sh follower` |
| Recalibrate leader | `bash scripts/calibrate.sh leader` |
| Teleoperate without cameras | `bash scripts/teleoperate.sh --no-cameras` |

The recalibration commands offer Enter to reuse an existing calibration or `c`
followed by Enter to redo it.

## Shared and Local Files

- Commit `calibration/follower/` and `calibration/leader/` JSON files for the
  team's physical arms. Each filename must match its arm ID in `config.env`.
- Keep `config.env` local; ports and camera indices differ between computers.

Original hardware notes are in [docs/setup-notes.md](docs/setup-notes.md).
