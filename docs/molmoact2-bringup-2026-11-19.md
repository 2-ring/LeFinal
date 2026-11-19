# MolmoAct2 on the SO-101: bring-up log and handoff (2026-11-19)

Audience: teammates and their coding agents picking this up cold. Everything below was observed directly on Nov 19, 2026 unless marked **(hypothesis)**. LeRobot file:line references are for tag `v0.7.0`.

## 1. TL;DR

- **Goal:** run MolmoAct2 zero-shot on our SO-101 follower. This is step 1 of the plan: get a VLA working, then add a VLM on top.
- **Status:** all the plumbing works end to end. The model loads on a GPU server, the robot computer connects, and the session is admitted. No full rollout yet: both attempts faulted on the **second** inference request with `ProtocolError: Invalid RTC delay`.
- **Root cause:** the **first** request of a session is slow (round trip 1.2–1.8 s). Each action chunk is 1.0 s (30 steps at 30 Hz). The client sizes the next request's "delay" from that first round trip, giving 36–55 steps. The server rejects any delay above 30.
- **Steady-state inference is fast:** 0.17 s per chunk on a 32 GB Ada-generation GPU in bf16, measured over repeated calls. The GPU is not the bottleneck; the first-request outlier is.
- **Next:** (a) try the stop-and-go launcher, which is ready but untested on the arm; (b) fix smooth mode by absorbing the slow first request; (c) the simplest alternative is to plug the arm into any local NVIDIA machine with ≥16 GB and run LeRobot's local synchronous mode, which avoids the remote path entirely.

## 2. Architecture used

```
 SO-101 follower + 2 USB cams                         GPU server (NVIDIA)
 ┌──────────────────────────────┐   SSH tunnel    ┌──────────────────────────────────┐
 │ Robot computer (Zyad's Mac)  │  localhost:7447 │ lerobot-policy-server (Zenoh)    │
 │ lerobot-rollout              │ ──────────────▶ │ MolmoAct2-SO100_101, bf16, GPU 0 │
 │  --inference.type=remote     │ ◀────────────── │ returns 30-action chunks (1.0 s) │
 │ sends: 2 JPEG frames + state │   action chunk  └──────────────────────────────────┘
 │        + task text           │
 └──────────────────────────────┘
```

- **Why remote:** MolmoAct2 needs an NVIDIA GPU (LeRobot docs). Our Macs can't run it, and there's an open third-party report (issue #5375) that bf16 on Apple MPS silently returns wrong actions.
- **The GPU server is one Zyad has access to.** Only Zyad can reach it for now. It has two 32 GB NVIDIA GPUs (Ada generation).
- **Brown CS cluster (`ssh.cs.brown.edu`, Slurm partition `gpus`):** checked as an alternative. Only the RTX A6000, L40 and L40S nodes (48 GB) are comfortable. All were fully allocated at ~16:15. GTX 1080/1080 Ti/2080 Ti (8–11 GB) are too small. Titan RTX (24 GB, Turing) has no native bf16, and fp32 needs ~24–26 GB, so it's borderline.

## 3. Components and versions

| Item | Value |
|---|---|
| LeRobot | `v0.7.0` (git tag), separate clone + uv venv on each machine |
| Robot side install | `uv sync --locked --extra remote --extra core_scripts --extra feetech` (Python 3.12, macOS, arm64) |
| Server side install | `uv sync --locked --extra remote --extra core_scripts --extra molmoact2` (uv-managed Python 3.13, Ubuntu) |
| Checkpoint | `lerobot/MolmoAct2-SO100_101-LeRobot`, revision `9adadbdf2ef15c9993161d61569c8ab0cf84417f`, ~21 GB |
| Checkpoint contract | inputs `observation.images.cam0`, `observation.images.cam1` (nominal 3×224×224), `observation.state` (6); output `action` (6); `chunk_size=30`, `n_action_steps=30`; continuous actions (flow matching); `enable_inference_cuda_graph=true` |
| Joint-frame fix | built into this LeRobot-format checkpoint's processor (`joint_signs [1,-1,1,1,1,1]`, `joint_offsets [0,90,90,0,0,0]`). Don't use `allenai/MolmoAct2-SO100_101` without setting these; LeRobot warns the arm "may move in the wrong direction". |
| GPU memory | fp32 ≈ 25 GB, bf16 ≈ 13.6 GB (server process on one 32 GB GPU) |
| Robot | HiWonder SO-ARM101 follower, port `/dev/tty.usbmodem5C4C1243751` on Zyad's Mac (matches `docs/setup-notes.md` in the team repo) |
| Calibration | `calibration/follower/hiwonder_follower_01.json` from https://github.com/2-ring/LeFinal, robot id `hiwonder_follower_01` |
| Cameras | two "icspring" UVC cameras. On Zyad's Mac: **wrist = OpenCV index 0** (native 640×480), **stand = index 1** (native 1920×1080, very wide/fisheye). Captured at 640×480 @ 30 fps. Indices change when devices are replugged or an iPhone Continuity Camera appears. |

## 4. What was done, in order (times ET, approximate)

1. **~16:05** SSH access to Brown CS set up; checked `sinfo -p gpus`. No free 48 GB GPU, so we switched to the other GPU server.
2. **~16:20** Server: cloned LeRobot v0.7.0, `uv sync` with the `molmoact2` extra, downloaded the checkpoint (~3 min) into a project-local `HF_HOME`.
3. **~16:22** Mac: cloned LeRobot v0.7.0, `uv sync` with `remote`, `core_scripts`, `feetech`.
4. **16:29** First server start **failed**: `ValueError: RGB feature shape differs from checkpoint: observation.images.cam0` (see §5.2). Fixed with a launcher; **16:34** server ready ("Deployment warmed … horizon=1.000s").
5. **~16:35** Camera indices found with `lerobot-find-cameras opencv` after granting macOS camera permission to the terminal app. A USB-hub disconnect briefly removed the arm and cameras.
6. **~16:41** Rollout asked to **calibrate** although the arm is calibrated. Cause: wrong calibration folder for v0.7.0 (§5.3). Fixed by copying the file; no recalibration done.
7. **16:44** Run 1 (fp32 server): admitted, then `Invalid RTC delay` on the second request.
8. **16:47** Server restarted in bf16 (local config copy, §5.4). **16:48** Run 2: same fault, smaller numbers.
9. **16:52** Benchmark on the idle second GPU (§6). Then everything was shut down: server stopped, tunnel closed, GPUs free.

The robot side was healthy in both runs. It held 29.97 Hz with 0/79 and 0/42 ticks over budget. At most one 1-second chunk was executed per run before the fault, after which the rollout returned the arm to its initial position and disabled torque. **We have not evaluated task behavior yet.**

## 5. Problems hit and fixes

### 5.1 No suitable free GPU on the Brown CS cluster
See §2. If you use it later, request a 48 GB card and wait in the queue:
```bash
srun -p gpus --gres=gpu:nvidia_rtx_a6000:1 --mem=48G --cpus-per-task=8 --time=3:00:00 --pty bash
```
Use `gpu:nvidia_l40:1` or `gpu:nvidia_l40s:1` as alternatives. Check when jobs end with `squeue -p gpus -o "%.10i %.10u %.14b %.10L %R"`.

### 5.2 Server rejects 640×480 frames (MolmoAct2 is only a "candidate" for remote serving)
- **Symptom:** `ValueError: RGB feature shape differs from checkpoint: observation.images.cam0.` at server start.
- **Cause:** `PreTrainedPolicy.validate_chunk_input_features` (`src/lerobot/policies/pretrained.py:284`) requires wire image shapes to equal the config's nominal `3×224×224`. SmolVLA, XVLA, LaWAM and VLA-JEPA override this; MolmoAct2 doesn't. `src/lerobot/remote_inference/README.md:157` lists MolmoAct2 as "Candidate; full checkpoint/processor acceptance pending".
- **Why it's safe to relax:** MolmoAct2's own image processor resizes any H×W×3 frame, and LeRobot's local rollout example uses 640×480 cameras.
- **Fix:** launcher `serve_molmoact2.py` (Appendix A) monkeypatches `MolmoAct2Policy.validate_chunk_input_features` to accept any H×W×3 RGB. Names, kinds and tensor shapes are still checked exactly. Server warm-up then ran fine at 480×640.

### 5.3 Rollout asks to calibrate an already-calibrated arm
- **Cause:** in v0.7.0 the SO follower class is `so_follower` (`src/lerobot/robots/so_follower/so_follower.py:61`, `name = "so_follower"`). The calibration path is `HF_LEROBOT_CALIBRATION/robots/<name>/<id>.json` (`src/lerobot/robots/robot.py:62-65`). The team's older install keeps files under `.../robots/so101_follower/`.
- **Fix:** put the repo file at `~/.cache/huggingface/lerobot/calibration/robots/so_follower/hiwonder_follower_01.json`, or pass `--robot.calibration_dir=<repo>/calibration/follower`. If prompted "Press ENTER to use provided calibration file…", press Enter. **Never type `c`**: recalibrating writes new offsets to the motors and desyncs everyone else's file.
- The repo's calibration already uses LeRobot's mid-range convention (it postdates the PR #777 calibration redesign; the team's scripts use `python -m lerobot.teleoperate`).

### 5.4 Server config has no precision setting
- The server YAML (`ModelConfig`: `repo_or_path`, `revision`, `device`, `tf32`) can't set dtype, so the checkpoint loads in its saved `float32`.
- **Fix:** a folder `ckpt-bf16/` with symlinks to the snapshot files plus a copied `config.json` with `"dtype": "bfloat16"`, and `model.repo_or_path` pointed at it. GPU memory dropped from ~25 GB to ~13.6 GB.

### 5.5 macOS camera access
- OpenCV prints `not authorized to capture video` until the terminal app is allowed under System Settings → Privacy & Security → Camera. Quit and reopen the app afterwards.
- Processes started by an agent's shell inside the Claude desktop app also can't use the cameras, so a human runs camera commands in their own terminal.

### 5.6 MAIN BLOCKER: `ProtocolError: Invalid RTC delay` on the second request

**Mechanism (code, v0.7.0):**
- The client estimates the latency as `turnaround = max(self.turnarounds, default=self._initial_turnaround)` (`src/lerobot/inference/execution.py:225`). Until steady-state samples exist, the **first** request's round trip is the estimate.
- The refill threshold is `effective_refill = max(refill_seconds, turnaround + interval)` (`execution.py:228-230`). With turnaround above the 1.0 s chunk, the client re-requests as soon as a chunk arrives, while actions are still queued.
- The delay sent is `ceil(turnaround / interval)` whenever actions are queued (`estimate_delay`, `execution.py:120-135`).
- The server requires `0 <= delay <= prediction_steps` (= 30), else `Invalid RTC delay` (`src/lerobot/remote_inference/server.py:497-498`). This applies in plain chunk mode too.

**Observed numbers:**

| Run | Server precision | Client round trip (max) | Server compute for that request | Delay sent | Outcome |
|---|---|---|---|---|---|
| 1 (16:44) | fp32 | 1.809 s | 0.992 s | ceil(1.809×30) = 55 | rejected |
| 2 (16:48) | bf16 | 1.199 s | 1.126 s | ceil(1.199×30) = 36 | rejected |

- Network ping from the lab to the server was ~40–95 ms (mean 62 ms). In run 2, transport added only ~0.07 s; the first request's compute is the issue.
- Server log: each session performed `resets=3` and completed `actions=1` before the fault.

## 6. Benchmark (same runner path as the server)

**Setup:** the server's second, idle 32 GB GPU, bf16, CUDA graphs on, `PolicyRunner.predict(mode=CHUNK)` via `load_deployment` (the server's own loader, including its 2 warm-up calls). Random 480×640 images and random state, task "pick up the red tape roll". 8 calls per setting; median of calls 2–8. Script: Appendix C.

| Setting | First call | Median after first | Min | Max |
|---|---|---|---|---|
| Default flow steps (backbone default; the paper uses 10 Euler steps) | 0.830 s | **0.173 s** | 0.168 s | 0.174 s |
| New instruction string (default steps, 3 calls) | 0.347 s | 0.172 s | 0.172 s | 0.172 s |
| `num_inference_steps = 5` | 0.430 s | 0.128 s | 0.125 s | 0.129 s |
| `num_inference_steps = 3` | 0.312 s | 0.106 s | 0.104 s | 0.109 s |

**Reading:**
- Steady state is ~6× faster than one chunk's duration, so smooth async control is feasible.
- The first call after load is slow even after the server's warm-up, which uses zero images and the task string "warmup" (`remote_inference/deployment.py`, `load_deployment`). A new instruction string also costs extra on its first call.
- **(hypothesis)** Per-session `reset` may discard warm state, making every session's first call slow. Not verified.
- Fewer flow steps are not needed for speed. Their effect on action quality is untested.

## 7. Options to unblock, ranked

1. **Stop-and-go launcher. Ready, untested on the arm.** `rollout_stopgo.py` (Appendix B) patches `ChunkRuntime.effective_refill` to drop the latency floor. Run it with `--inference.refill_seconds=0 --inference.action_starvation_grace_s=3.0`. The arm plays a full 1 s chunk, holds while the next is computed (requested with delay 0 because the queue is empty), then continues.
   - Expected pause per chunk: ~0.2–0.4 s at steady state, longer for the first.
   - **(hypothesis)** When the queue empties, the starvation path invalidates any in-flight request (`execution.py`, `_wait_for_actions` → `invalidate`). That can cost one extra round trip per cycle; still within the 3 s grace.
2. **Absorb the slow first request (smooth mode).** Either:
   - pre-warm with a realistic dummy prediction (real-size images plus the actual task string) after startup and, if resets clear it, after each session admission; or
   - cap the client's initial turnaround estimate, e.g. ignore the first sample.

   Needs a small patch in the same launcher style; test on hardware.
3. **Local synchronous inference, no remote at all.** Plug the arm into any Linux machine with an NVIDIA GPU (≥16 GB for bf16) and run LeRobot's documented local command. The robot simply pauses during each ~0.2 s inference:
   ```bash
   lerobot-rollout --policy.path=lerobot/MolmoAct2-SO100_101-LeRobot --policy.dtype=bfloat16 \
     --rename_map='{"observation.images.stand": "observation.images.cam0", "observation.images.wrist": "observation.images.cam1"}' \
     --robot.type=so101_follower --robot.port=<port> --robot.id=hiwonder_follower_01 \
     --robot.cameras='{stand: {type: opencv, index_or_path: <i>, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: <j>, width: 640, height: 480, fps: 30}}' \
     --task="pick up the red tape roll" --interactive=true
   ```
4. **Fewer flow steps** (`num_inference_steps` 5 or 3). Only if quality holds; not required for speed.
5. **Upstream:** worth an issue or PR to LeRobot for (a) a MolmoAct2 `validate_chunk_input_features` override and (b) handling a first round trip longer than one chunk.

## 8. Exact commands that were used

**Server** (from `<project>/lerobot` on the GPU server, inside tmux session `csci2470-server`):
```bash
export HF_HOME=<project>/hf CUDA_VISIBLE_DEVICES=0
~/.local/bin/uv run --no-sync python ../serve_molmoact2.py --config_path=../server.yaml
```
Wait for `Policy server ready: deployment=csci2470-molmo …`.

**Tunnel** (robot computer; server listens on 127.0.0.1 only, which is deliberate because Zenoh TCP has no authentication):
```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -L 7447:127.0.0.1:7447 <gpu-server>
```

**Robot client** (robot computer, from `~/Projects/csci2470-lerobot`). This is the version that faulted; for stop-and-go, see §7.1.
```bash
uv run --no-sync lerobot-rollout \
  --inference.type=remote \
  --inference.endpoint=tcp/127.0.0.1:7447 \
  --inference.deployment=csci2470-molmo \
  --inference.mode=chunk \
  --inference.chunk_merge=aligned \
  --inference.semantics=so101-degrees-gripper-percent-v1 \
  --inference.encoding=jpeg --inference.jpeg_quality=90 \
  --rename_map='{"observation.images.stand": "observation.images.cam0", "observation.images.wrist": "observation.images.cam1"}' \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem5C4C1243751 \
  --robot.id=hiwonder_follower_01 \
  --robot.use_degrees=true \
  --robot.cameras='{stand: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}}' \
  --fps=30 \
  --task="pick up the red tape roll" \
  --interactive=true
```
Then type `/start`; `/stop` ends the run, `/subtask <text>` changes the instruction, `/reset` returns home.

**Stop-and-go variant:** replace `lerobot-rollout` with `python rollout_stopgo.py` and add `--inference.refill_seconds=0 --inference.action_starvation_grace_s=3.0`.

## 9. Safety and hardware notes

- On disconnect the rollout disables torque (`disable_torque_on_disconnect=True`), so the arm goes limp. Support it if it's in a raised pose.
- Each chunk is 1 s of open-loop motion; keep a hand near the arm's power.
- Keep the leader arm unplugged during policy runs (only the follower is used).
- Team notes: keep slack on the wrist-camera cable, don't rotate the cameras, and put the caps back on afterwards.
- The stand camera is very wide; the arm and workspace occupy a small part of the frame. Ai2 recommends "a third-person camera" plus the standard wrist camera. **(hypothesis)** A tighter third-person view may help zero-shot performance; discuss before moving the cameras.

## 10. Open questions

1. Is every session's first call slow (per-session reset), or only the first after load?
2. Does MolmoAct2 zero-shot do anything useful on our SO-101 with this camera framing? Ai2 reports SO-100 only (56.7% average partial credit over 5 tasks); SO-101 evidence is community-only.
3. Does it follow changed instructions via `/subtask`? This is the key question for the VLM-over-VLA plan.
4. Which machine will the team use long-term: a Brown cluster 48 GB GPU (queue), a local NVIDIA box (sync mode), or the current server (only Zyad can reach it)?

## 11. File index

Repo copies of the scripts and an example server config are in `scripts/molmoact2/` (`serve_molmoact2.py`, `rollout_stopgo.py`, `bench_molmo.py`, `server.example.yaml`). The machine paths below are where they were run on Nov 19.

**Robot computer (Zyad's Mac)**
- `~/Projects/csci2470-lerobot/`: LeRobot v0.7.0 clone + `.venv`
- `~/Projects/csci2470-lerobot/rollout_stopgo.py`: stop-and-go launcher (Appendix B)
- `~/.cache/huggingface/lerobot/calibration/robots/so_follower/hiwonder_follower_01.json`

**GPU server**, project folder `<project>/`:
- `lerobot/`: v0.7.0 clone + `.venv`
- `hf/`: HF cache with the checkpoint
- `ckpt-bf16/`: bf16 config + symlinked weights
- `server.yaml` (bf16, current) and `server.fp32.yaml`
- `serve_molmoact2.py`: Appendix A
- `bench_molmo.py`: Appendix C
- logs: `setup.log`, `server.fail1.log` (shape error), `server.fp32.log` (run 1), `server.log` (run 2), `bench.log`

---

## Appendix A: `serve_molmoact2.py` (server launcher)

```python
"""Start lerobot-policy-server with MolmoAct2 accepting full-size camera frames.

LeRobot 0.7.0 lists MolmoAct2 as an untested remote-inference candidate. Its
generic check requires wire images to equal the nominal 224x224 config shape,
but the MolmoAct2 image processor resizes any HxWx3 frame (local rollout uses
640x480). This relaxes only the image-size check; names, kinds and tensor
shapes are still enforced exactly.
"""
import sys

from lerobot.configs.types import FeatureType
from lerobot.policies.molmoact2.modeling_molmoact2 import MolmoAct2Policy


def _validate(self, features):
    expected = self.config.input_features or {}
    supplied = {feature.name: feature for feature in features}
    if supplied.keys() != expected.keys():
        raise ValueError("Canonical feature names must exactly match policy input_features.")
    for name, policy_feature in expected.items():
        feature = supplied[name]
        if policy_feature.type == FeatureType.VISUAL:
            if feature.kind != "rgb" or len(feature.shape) != 3 or feature.shape[2] != 3:
                raise ValueError(f"MolmoAct2 needs HxWx3 RGB input: {name}.")
        elif feature.kind != "tensor" or tuple(feature.shape) != tuple(policy_feature.shape):
            raise ValueError(f"Tensor feature shape differs from checkpoint: {name}.")


MolmoAct2Policy.validate_chunk_input_features = _validate

from lerobot.scripts.lerobot_policy_server import main  # noqa: E402

sys.exit(main())
```

## Appendix B: `rollout_stopgo.py` (robot-side launcher)

```python
"""Run lerobot-rollout with remote inference in stop-and-go mode.

LeRobot 0.7.0 normally asks for the next action chunk early, using the measured
round trip as a floor for the refill threshold. When that round trip is longer than
one chunk of motion (on Nov 19 the first request of a session took 1.2-1.8 s for
a 1.0 s chunk), the next request carries a delay longer than the chunk and the
server rejects it ("Invalid RTC delay").

This launcher removes that floor so the refill threshold is exactly
--inference.refill_seconds. With --inference.refill_seconds=0 the robot plays a
full chunk, holds position while the next one is computed, then continues. Pass
a starvation grace longer than one round trip, e.g.
--inference.action_starvation_grace_s=3.0. All other flags are lerobot-rollout's.
"""
import sys

from lerobot.inference.execution import ChunkRuntime


def _refill_without_latency_floor(self):
    return self.refill_seconds


ChunkRuntime.effective_refill = property(_refill_without_latency_floor)

from lerobot.scripts.lerobot_rollout import main  # noqa: E402

sys.exit(main())
```

(Steady-state inference is 0.17 s per chunk; the slow call is the first one of a session. The launcher is still valid.)

## Appendix C: `bench_molmo.py` (benchmark)

```python
"""Time MolmoAct2 chunk inference through the same runner the policy server uses."""
import statistics
import sys
import time

import draccus
import numpy as np
import torch

from lerobot.configs.types import FeatureType
from lerobot.inference import ExecutionMode, ObservationSnapshot
from lerobot.policies.molmoact2.modeling_molmoact2 import MolmoAct2Policy
from lerobot.remote_inference.configs import ServerConfig
from lerobot.remote_inference.deployment import load_deployment


def _validate(self, features):
    expected = self.config.input_features or {}
    supplied = {feature.name: feature for feature in features}
    if supplied.keys() != expected.keys():
        raise ValueError("feature names differ")
    for name, policy_feature in expected.items():
        feature = supplied[name]
        if policy_feature.type == FeatureType.VISUAL:
            if feature.kind != "rgb" or len(feature.shape) != 3 or feature.shape[2] != 3:
                raise ValueError(name)
        elif feature.kind != "tensor" or tuple(feature.shape) != tuple(policy_feature.shape):
            raise ValueError(name)


MolmoAct2Policy.validate_chunk_input_features = _validate

cfg = draccus.parse(config_class=ServerConfig, config_path=sys.argv[1], args=[])
runner, _ = load_deployment(cfg)
policy = getattr(runner, "policy", None)
if not isinstance(policy, MolmoAct2Policy):
    policy = next(v for v in vars(runner).values() if isinstance(v, MolmoAct2Policy))
rng = np.random.default_rng(0)


def observation(i, task):
    values = {}
    for feature in cfg.features:
        if feature.kind == "rgb":
            values[feature.name] = rng.integers(0, 256, size=feature.shape, dtype=np.uint8)
        else:
            values[feature.name] = rng.normal(size=feature.shape).astype(np.float32)
    return ObservationSnapshot(values, 0.0, task, observation_id=f"b{i}")


def bench(label, n=8, task="pick up the red tape roll"):
    times = []
    for i in range(n):
        obs = observation(i, task)
        torch.cuda.synchronize()
        start = time.perf_counter()
        runner.predict(obs, mode=ExecutionMode.CHUNK, inference_delay=0,
                       model_continuation=None, canonical_continuation=None)
        torch.cuda.synchronize()
        times.append(time.perf_counter() - start)
    rest = times[1:]
    print(f"{label}: first={times[0]:.3f}s median={statistics.median(rest):.3f}s "
          f"min={min(rest):.3f}s max={max(rest):.3f}s", flush=True)


bench("default steps")
bench("new task string", n=3, task="put the red tape roll in the box")
for steps in (5, 3):
    policy.config.num_inference_steps = steps
    bench(f"{steps} flow steps")
```

Run: `CUDA_VISIBLE_DEVICES=1 HF_HOME=<hf> uv run --no-sync python ../bench_molmo.py ../server.yaml` from the server's `lerobot/` folder.

## Appendix D: `server.yaml`

```yaml
# MolmoAct2 SO-100/101 checkpoint served to an SO-101 with a front and a wrist camera.
deployment: csci2470-molmo
model:
  repo_or_path: <abs path to ckpt-bf16>   # fp32 variant: lerobot/MolmoAct2-SO100_101-LeRobot @ 9adadbdf2ef15c9993161d61569c8ab0cf84417f
  revision: null
  device: cuda
execution:
  supported_modes: [chunk]
  action_fps: 30.0
  action_deadline_s: 5.0
  idle_timeout_s: 10.0
  warmup_calls: 2
language:
  enabled: false
  deadline_s: 60.0
zenoh:
  mode: peer
  listen_endpoints: [tcp/127.0.0.1:7447]
semantics: so101-degrees-gripper-percent-v1
robot_type: so101_follower
features:
  - name: observation.state
    shape: [6]
    dtype: float32
    names: [shoulder_pan.pos, shoulder_lift.pos, elbow_flex.pos, wrist_flex.pos, wrist_roll.pos, gripper.pos]
    semantics: so101-degrees-gripper-percent-v1
  - name: observation.images.cam0
    shape: [480, 640, 3]
    dtype: uint8
    kind: rgb
    semantics: rgb-front-table-v1
  - name: observation.images.cam1
    shape: [480, 640, 3]
    dtype: uint8
    kind: rgb
    semantics: rgb-wrist-v1
action_feature:
  name: action
  shape: [6]
  dtype: float32
  names: [shoulder_pan.pos, shoulder_lift.pos, elbow_flex.pos, wrist_flex.pos, wrist_roll.pos, gripper.pos]
  semantics: so101-degrees-gripper-percent-v1
```

`semantics` strings are free-form labels that must match between client and server. `features` must use the checkpoint-facing names (`cam0`, `cam1`); the client's `--rename_map` maps the robot's camera names onto them.
