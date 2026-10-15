"""Run the SO-101 workflow with the group's shared settings.

Builds the long lerobot-* commands from two files:
  config.toml  settings the whole group shares (committed)
  local.toml   this computer's USB ports and camera numbers (not committed)
Calibration files are kept in calibration/ so every computer drives the
arms with the same calibration.

Any extra --key=value goes straight to lerobot and replaces the generated
value, e.g.  python run.py record --dataset.num_episodes=10
Add --dry-run to print the lerobot command without running it.
"""

import sys

if sys.version_info < (3, 12):
    sys.exit("This needs the project environment. Run: conda activate lefinal")

import argparse
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CALIBRATION = ROOT / "calibration"
# arm -> (role on the lerobot command line, lerobot type, calibration folder)
ARMS = {
    "follower": ("robot", "so101_follower", CALIBRATION / "robots" / "so101_follower"),
    "leader": ("teleop", "so101_leader", CALIBRATION / "teleoperators" / "so101_leader"),
}


def load_toml(name, required=True):
    path = ROOT / name
    if not path.exists():
        if required:
            sys.exit(f"No {name} on this computer yet. Copy local.example.toml to {name} and fill it in.")
        return None
    with open(path, "rb") as f:
        return tomllib.load(f)


SHARED = load_toml("config.toml")
LOCAL = load_toml("local.toml", required=False)


def local():
    if LOCAL is None:
        load_toml("local.toml")  # exits with instructions
    return LOCAL


def arm_flags(arm):
    role, robot_type, calibration_dir = ARMS[arm]
    port = local().get(f"{arm}_port")
    if not port:
        sys.exit(f"Set {arm}_port in local.toml. Find it with: python run.py find-port")
    return {
        f"{role}.type": robot_type,
        f"{role}.port": port,
        f"{role}.id": SHARED["arms"][f"{arm}_id"],
        f"{role}.calibration_dir": calibration_dir.as_posix(),
    }


def camera_flags(required):
    """Combine the shared camera settings with this computer's camera numbers."""
    local_cameras = local().get("cameras", {})
    cameras, missing = {}, []
    for name, settings in SHARED.get("cameras", {}).items():
        if "index_or_path" not in local_cameras.get(name, {}):
            missing.append(name)
            continue
        cameras[name] = {
            "type": "opencv",
            "index_or_path": local_cameras[name]["index_or_path"],
            "fps": SHARED["record"]["fps"],
            **settings,
        }
    if required and not SHARED.get("cameras"):
        sys.exit("No cameras in config.toml. Add a [cameras.<name>] table first.")
    if missing:
        message = f"No camera number for {', '.join(missing)} in local.toml. Find it with: python run.py find-cameras"
        if required:
            sys.exit(message)
        print(f"Note: {message}")
    if not cameras:
        return {}
    return {"robot.cameras": json.dumps(cameras), "display_data": True}


def hub_repo(name):
    """Turn a dataset or model name into a Hub id under the group's namespace."""
    if "/" in name:
        return name
    namespace = SHARED["hub"].get("namespace")
    if not namespace:
        try:
            from huggingface_hub import whoami

            namespace = whoami()["name"]
        except Exception:
            sys.exit("Set [hub] namespace in config.toml, or log in with: hf auth login")
    return f"{namespace}/{name}"


def run(script, positional=(), flags=None, extra=(), dry_run=False):
    flags = dict(flags or {})
    for arg in extra:
        key, sep, value = arg.removeprefix("--").partition("=")
        if not arg.startswith("--") or not sep:
            sys.exit(f"Extra arguments must look like --key=value, got: {arg}")
        flags[key] = value
    cli = [*positional] + [f"--{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in flags.items()]
    print("$", shlex.join([script.replace("_", "-"), *cli]), flush=True)
    if dry_run:
        return 0
    if importlib.util.find_spec("lerobot") is None:
        sys.exit("LeRobot isn't installed in this Python. Run: conda activate lefinal")
    proc = subprocess.Popen([sys.executable, "-m", f"lerobot.scripts.{script}", *cli])
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            # lerobot gets the Ctrl-C too; wait so it can save and shut down cleanly.
            pass


def cmd_check(args, extra):
    problems = 0

    def report(ok, message, fix=""):
        nonlocal problems
        problems += not ok
        print(f"[{'ok' if ok else '!!'}] {message}" + ("" if ok or not fix else f"\n     fix: {fix}"))

    pinned = re.search(r"lerobot\[[^\]]*\]==([\w.]+)", (ROOT / "environment.yml").read_text()).group(1)
    try:
        installed = version("lerobot")
        report(installed == pinned, f"lerobot {installed} (environment.yml pins {pinned})",
               "conda env update -f environment.yml --prune")
    except PackageNotFoundError:
        report(False, "lerobot is not installed in this Python",
               "conda activate lefinal  (first time: conda env create -f environment.yml)")
    report(shutil.which("ffmpeg") is not None, "ffmpeg found", "conda env update -f environment.yml --prune")
    try:
        import torch

        device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        print(f"[ok] torch {torch.__version__}, training device: {device}")
    except ImportError:
        pass

    if LOCAL is None:
        report(False, "local.toml exists", "copy local.example.toml to local.toml and fill it in")
    else:
        for arm in ARMS:
            port = LOCAL.get(f"{arm}_port", "")
            if os.name == "nt":
                from serial.tools import list_ports

                found = port in {p.device for p in list_ports.comports()}
            else:
                found = Path(port).exists()
            if not found:
                report(False, f"{arm} port {port!r} not found",
                       "plug the arm in (USB and power) and run: python run.py find-port")
            elif os.name != "nt" and not os.access(port, os.R_OK | os.W_OK):
                report(False, f"{arm} port {port} found but not accessible",
                       "sudo usermod -aG dialout $USER, then log out and back in")
            else:
                report(True, f"{arm} port {port}")
        for name in SHARED.get("cameras", {}):
            report("index_or_path" in LOCAL.get("cameras", {}).get(name, {}), f"camera '{name}' has a number in local.toml",
                   "python run.py find-cameras, then add it under [cameras." + name + "] in local.toml")

    for arm, (_, _, calibration_dir) in ARMS.items():
        path = calibration_dir / f"{SHARED['arms'][f'{arm}_id']}.json"
        report(path.exists(), f"{arm} calibration {path.relative_to(ROOT).as_posix()}",
               f"git pull, or if nobody has calibrated yet: python run.py calibrate {arm}")

    try:
        from huggingface_hub import whoami

        print(f"[ok] logged in to Hugging Face as {whoami()['name']}")
    except ImportError:
        pass
    except Exception:
        report(False, "logged in to Hugging Face", "hf auth login  (with a write token)")

    print("All good." if not problems else f"{problems} thing(s) to fix.")
    return 1 if problems else 0


def cmd_find_port(args, extra):
    return run("lerobot_find_port", extra=extra, dry_run=args.dry_run)


def cmd_find_cameras(args, extra):
    return run("lerobot_find_cameras", ["opencv"], extra=extra, dry_run=args.dry_run)


def cmd_setup_motors(args, extra):
    role = ARMS[args.arm][0]
    flags = {k: v for k, v in arm_flags(args.arm).items() if k in (f"{role}.type", f"{role}.port")}
    return run("lerobot_setup_motors", flags=flags, extra=extra, dry_run=args.dry_run)


def cmd_calibrate(args, extra):
    return run("lerobot_calibrate", flags=arm_flags(args.arm), extra=extra, dry_run=args.dry_run)


def cmd_teleop(args, extra):
    flags = {**arm_flags("follower"), **arm_flags("leader"), **camera_flags(required=False)}
    return run("lerobot_teleoperate", flags=flags, extra=extra, dry_run=args.dry_run)


def cmd_record(args, extra):
    rec = SHARED["record"]
    flags = {
        **arm_flags("follower"),
        **arm_flags("leader"),
        **camera_flags(required=True),
        "dataset.repo_id": hub_repo(args.resume or rec["name"]),
        "dataset.single_task": rec["task"],
        "dataset.fps": rec["fps"],
        "dataset.num_episodes": rec["num_episodes"],
        "dataset.episode_time_s": rec["episode_time_s"],
        "dataset.reset_time_s": rec["reset_time_s"],
        "dataset.streaming_encoding": True,
        "dataset.encoder_threads": 2,
    }
    if args.resume:
        from lerobot.utils.constants import HF_LEROBOT_HOME

        # num_episodes now counts the episodes to add. Resuming needs an explicit
        # folder; this is where lerobot-record created it (or downloads it to).
        flags["dataset.root"] = (HF_LEROBOT_HOME / flags["dataset.repo_id"]).as_posix()
        flags["resume"] = True
    return run("lerobot_record", flags=flags, extra=extra, dry_run=args.dry_run)


def cmd_replay(args, extra):
    flags = {
        **arm_flags("follower"),
        "dataset.repo_id": hub_repo(args.dataset),
        "dataset.episode": args.episode,
        "dataset.fps": SHARED["record"]["fps"],
    }
    return run("lerobot_replay", flags=flags, extra=extra, dry_run=args.dry_run)


def cmd_merge(args, extra):
    flags = {
        "new_repo_id": hub_repo(args.name),
        "operation.type": "merge",
        "operation.repo_ids": json.dumps([hub_repo(d) for d in args.datasets]),
        "push_to_hub": True,
    }
    return run("lerobot_edit_dataset", flags=flags, extra=extra, dry_run=args.dry_run)


def cmd_train(args, extra):
    if args.resume:
        config_path = Path(args.resume) / "checkpoints" / "last" / "pretrained_model" / "train_config.json"
        flags = {"config_path": config_path.as_posix(), "resume": True}
        return run("lerobot_train", flags=flags, extra=extra, dry_run=args.dry_run)
    train = SHARED["train"]
    dataset = args.dataset or train["dataset"]
    if not dataset:
        sys.exit("Set [train] dataset in config.toml, or pass one: python run.py train <dataset>")
    name = args.name or f"{train['policy']}_{dataset.split('/')[-1]}"
    flags = {
        "dataset.repo_id": hub_repo(dataset),
        "policy.type": train["policy"],
        "policy.repo_id": hub_repo(name),
        "job_name": name,
        "steps": train["steps"],
        "batch_size": train["batch_size"],
        "wandb.enable": train["wandb"],
    }
    return run("lerobot_train", flags=flags, extra=extra, dry_run=args.dry_run)


def cmd_eval(args, extra):
    local_path = Path(args.policy)
    policy = local_path.as_posix() if local_path.exists() else hub_repo(args.policy)
    ev = SHARED["eval"]
    flags = {
        "policy.path": policy,
        **arm_flags("follower"),
        **camera_flags(required=True),
        "fps": SHARED["record"]["fps"],
    }
    if args.no_record:
        flags |= {"strategy.type": "base", "task": SHARED["record"]["task"], "duration": ev["episode_time_s"]}
    else:
        # outputs/train/<day>/<run>/checkpoints/<step>/pretrained_model -> <run>
        parts = local_path.parts
        policy_name = parts[parts.index("checkpoints") - 1] if "checkpoints" in parts[1:] else local_path.name
        name = args.name or f"eval_{policy_name}"
        flags |= {
            "strategy.type": "episodic",
            "dataset.repo_id": hub_repo(name),
            "dataset.single_task": SHARED["record"]["task"],
            "dataset.fps": SHARED["record"]["fps"],
            "dataset.num_episodes": ev["num_episodes"],
            "dataset.episode_time_s": ev["episode_time_s"],
            "dataset.reset_time_s": ev["reset_time_s"],
        }
    return run("lerobot_rollout", flags=flags, extra=extra, dry_run=args.dry_run)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    def command(name, func, help):
        p = sub.add_parser(name, help=help, description=help, allow_abbrev=False)
        p.add_argument("--dry-run", action="store_true", help="print the lerobot command without running it")
        p.set_defaults(func=func)
        return p

    command("check", cmd_check, "check this computer is set up correctly")
    command("find-port", cmd_find_port, "find which USB port an arm is on")
    command("find-cameras", cmd_find_cameras, "list cameras and their numbers")
    command("setup-motors", cmd_setup_motors, "give each motor its ID (once per arm, one motor at a time)") \
        .add_argument("arm", choices=ARMS)
    command("calibrate", cmd_calibrate, "calibrate an arm (once per arm, then commit the file)") \
        .add_argument("arm", choices=ARMS)
    command("teleop", cmd_teleop, "control the follower with the leader")
    p = command("record", cmd_record, "record demonstrations into a new dataset")
    p.add_argument("--resume", metavar="DATASET",
                   help="add episodes to an earlier session's dataset (num_episodes then counts the new ones)")
    p = command("replay", cmd_replay, "replay a recorded episode on the follower")
    p.add_argument("dataset", help="dataset name, e.g. so101_pickplace_20261015_140312")
    p.add_argument("episode", type=int)
    p = command("merge", cmd_merge, "combine recording sessions into one dataset for training")
    p.add_argument("name", help="name for the combined dataset")
    p.add_argument("datasets", nargs="+", help="session datasets to combine")
    p = command("train", cmd_train, "train a policy")
    p.add_argument("dataset", nargs="?", help="dataset to train on (default: [train] dataset in config.toml)")
    p.add_argument("--name", help="run and model name (default: <policy>_<dataset>)")
    p.add_argument("--resume", metavar="RUN_DIR", help="continue a run, e.g. outputs/train/2026-10-15/14-03-12_act_x")
    p = command("eval", cmd_eval, "run a trained policy on the robot and record the trials")
    p.add_argument("policy", help="model name on the Hub, or a local pretrained_model folder")
    p.add_argument("--name", help="name for the recorded eval dataset (default: eval_<policy>)")
    p.add_argument("--no-record", action="store_true", help="just run the policy once, without recording")

    args, extra = parser.parse_known_args()
    sys.exit(args.func(args, extra))


if __name__ == "__main__":
    main()
