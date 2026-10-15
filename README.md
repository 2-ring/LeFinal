# LeFinal

Imitation learning on a LeRobot SO-101 arm pair: record demonstrations with the
leader arm, train a policy, and run it on the follower.

Everything runs from one shared environment (`environment.yml`) and one script
(`run.py`). The script fills in each computer's ports and the group's shared
settings, so the commands are the same on every machine.

| File | What it's for | Committed? |
|---|---|---|
| `environment.yml` | Exact Python, LeRobot and ffmpeg versions | yes |
| `config.toml` | Settings the group shares: arm names, cameras, task, training | yes |
| `local.toml` | This computer's USB ports and camera numbers | no, each computer has its own |
| `calibration/` | Calibration of the physical arms | yes, see below |

## Set up a computer (once)

Works on Linux, Windows and Apple Silicon Macs. Intel Macs can't run current
PyTorch, so use a different computer. On Linux the environment takes about
7 GB, mostly NVIDIA libraries.

1. Install [Miniforge](https://conda-forge.org/download/). On Windows, use the
   **Miniforge Prompt** it adds to the Start menu for everything below.
2. Get the code and create the environment:
   ```bash
   git clone https://github.com/2-ring/LeFinal.git
   cd LeFinal
   conda env create -f environment.yml
   ```
3. Activate it. Do this in every new terminal:
   ```bash
   conda activate lefinal
   ```
4. Tell it this computer's ports and cameras. Copy `local.example.toml` to
   `local.toml`. Then plug in both arms (USB and power) and fill in the values
   these commands find:
   ```bash
   python run.py find-port      # run once per arm
   python run.py find-cameras
   ```
5. **Linux only:** give yourself access to the USB ports, then log out and back in:
   ```bash
   sudo usermod -aG dialout $USER
   ```
6. Log in to Hugging Face with a **write** token from
   <https://huggingface.co/settings/tokens>. Datasets and models are stored there.
   ```bash
   hf auth login
   ```
7. Check everything:
   ```bash
   python run.py check
   ```

## Commands

Run these from the `LeFinal` folder with the environment active.
`python run.py <command> --help` explains each one.

| Step | Command |
|---|---|
| Give each motor its ID (once per arm, one motor at a time) | `python run.py setup-motors follower` / `leader` |
| Calibrate an arm (once per arm) | `python run.py calibrate follower` / `leader` |
| Teleoperate | `python run.py teleop` |
| Record demonstrations | `python run.py record` |
| Add episodes to an earlier session (`num_episodes` then counts the new ones) | `python run.py record --resume <dataset>` |
| Replay an episode on the follower | `python run.py replay <dataset> <episode>` |
| Combine sessions for training | `python run.py merge <new name> <dataset> <dataset> ...` |
| Train | `python run.py train [<dataset>] [--name <run name>]` |
| Continue a training run | `python run.py train --resume outputs/train/<day>/<run>` |
| Run a trained policy and record the trials | `python run.py eval <model>` |
| Run a trained policy without recording | `python run.py eval <model> --no-record` |

Every command prints the full `lerobot-*` command it runs. Add `--dry-run` to
see the command without running it. You can add or override any LeRobot option
as `--key=value`, for example:

```bash
python run.py record --dataset.num_episodes=10
python run.py train --policy.push_to_hub=false
```

While recording: **→** ends the episode early, **←** re-records it, **Esc**
stops and uploads. The letters `n`, `r` and `q` do the same.

## Calibration lives in the repo

Calibration belongs to the physical arms, not to a computer. The first person
to calibrate each arm runs `python run.py calibrate follower` (and `leader`),
then commits the files it writes in `calibration/`. Every other computer just
needs `git pull`. If LeRobot ever asks whether to use the existing calibration
file, press **Enter**. Typing `c` recalibrates, which changes the arm's
calibration for everyone, so only do that on purpose and commit the new file.

## Datasets: one per recording session

Each `python run.py record` creates a new dataset named after `[record] name`
in `config.toml` plus the date and time, e.g. `so101_pickplace_20261015_140312`,
and uploads it to Hugging Face. Training uses one dataset, so combine sessions first:

```bash
python run.py merge so101_pickplace_v1 so101_pickplace_20261015_140312 so101_pickplace_20261016_101500
```

Then set `[train] dataset = "so101_pickplace_v1"` in `config.toml` and commit,
so everyone trains on the same data. Every computer must record with the same
cameras and camera settings, or the datasets can't be combined.

Browse any dataset at <https://huggingface.co/spaces/lerobot/visualize_dataset>.
To keep the group's datasets and models together, create a free Hugging Face
organization and set `[hub] namespace` in `config.toml`.

## Training

`python run.py train` uses an NVIDIA GPU automatically on Linux, or the GPU on an
Apple Silicon Mac. It falls back to the CPU otherwise, which is far too slow for
real runs. Runs are saved in `outputs/train/` and the finished model is uploaded
to Hugging Face. Set `wandb = true` in `config.toml` (after `wandb login`) to
get training curves for the report.

- **Windows:** the PyTorch this environment installs is CPU-only. Train on a
  Linux machine or Colab, or reinstall PyTorch with CUDA from
  <https://pytorch.org/get-started/locally/>.
- **Google Colab:** install the same version so the dataset and model formats
  match: `pip install 'lerobot[feetech,core-scripts,training,smolvla]==0.6.1'`.

## Changing the setup

- **Shared settings:** edit `config.toml` and commit.
- **Package versions:** edit `environment.yml` and commit. Everyone then runs
  `conda env update -f environment.yml --prune`. `python run.py check` warns
  when a computer's LeRobot doesn't match.

## Why not Docker?

The arms and cameras are USB devices. Docker Desktop on Mac can't pass them
through to a container, and on Windows it needs extra USB-forwarding tools.
A conda environment is the setup that works on everyone's computer.
