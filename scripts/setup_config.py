#!/usr/bin/env python3
"""Configure arm ports and cameras, save config.env, and calibrate arms missing calibration."""

import argparse
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
KEYS = ("FOLLOWER_PORT", "LEADER_PORT", "FOLLOWER_ID", "LEADER_ID", "ROBOT_CAMERAS")
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?(" + "|".join(KEYS) + r")\s*=")


def read_value(text, key):
    # Read simple shell assignments without executing the configuration file.
    for line in reversed(text.splitlines()):
        match = ASSIGNMENT.match(line)
        if match and match[1] == key:
            values = shlex.split(line[match.end():], comments=True)
            if len(values) == 1:
                return values[0]
    return ""


def arm_id(text, role, prompt=False):
    # Keep existing IDs, or infer the ID from a single calibration filename.
    key = role.upper() + "_ID"
    existing = read_value(text, key)
    if existing and not existing.startswith("REPLACE_WITH_"):
        return existing
    files = sorted((ROOT / "calibration" / role).glob("*.json"))
    if len(files) == 1:
        return files[0].stem
    if prompt:
        default = f"hiwonder_{role}_01"
        while True:
            value = input(f"{role.capitalize()} arm ID [{default}]: ").strip() or default
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
                return value
            print("Use a name containing letters, numbers, underscores, dots, or hyphens.")
    return "REPLACE_WITH_" + key


def find_port(role):
    # Let LeRobot run its normal interactive unplug-and-detect procedure.
    input(f"\nConnect both arms. Press Enter to identify the {role.upper()} arm. ")
    print(f"At the next prompt, unplug ONLY the {role.upper()} arm's USB cable.", flush=True)
    print("Leave the hub, camera, and other arm connected.", flush=True)
    ports = []
    command = [sys.executable, "-u", "-m", "lerobot.find_port"]
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, bufsize=1) as process:
        for line in process.stdout:
            print(line, end="", flush=True)
            match = re.search(r"The port of this Motors?Bus is\s+(.+)", line)
            if match:
                port = match[1].strip().strip("'\"")
                if re.fullmatch(r"(?:/dev/[^\s'\"]+|COM\d+)", port):
                    ports.append(port)
        if process.wait() != 0:
            raise RuntimeError(f"LeRobot could not identify the {role} port.")
    if len(ports) != 1:
        raise RuntimeError(f"Could not read one {role} port from LeRobot's output.")
    input(f"Reconnect the {role.upper()} USB cable to the same socket, then press Enter. ")
    return ports[0]


def discover_cameras(previews):
    """Keep the finder's detected profiles alongside its numbered preview images."""
    from PIL import Image
    from lerobot.find_cameras import find_and_print_cameras
    from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig

    print(f"\nCamera images: {previews}", flush=True)
    print(f"Open them with: open {shlex.quote(str(previews))}", flush=True)
    profiles = {}
    for info in find_and_print_cameras("opencv"):
        device = info["id"]
        camera = OpenCVCamera(OpenCVCameraConfig(index_or_path=device))
        try:
            camera.connect()
            safe_device = str(device).replace("/", "_").replace("\\", "_")
            Image.fromarray(camera.read()).save(previews / f"opencv_{safe_device}.png")
            profiles[device] = {"width": camera.width, "height": camera.height, "fps": camera.fps}
        except (OSError, RuntimeError, ValueError) as error:
            print(f"Could not capture camera {device}: {error}")
        finally:
            if camera.is_connected:
                camera.disconnect()
    if not profiles:
        raise RuntimeError("No camera previews were captured. Check camera connections and permissions.")
    print(f"\nCamera images: {previews}", flush=True)
    print(f"Open them with: open {shlex.quote(str(previews))}", flush=True)
    return profiles


def detected_camera_settings(device, profile):
    settings = {"type": "opencv", "index_or_path": device}
    for key in ("width", "height", "fps"):
        value = profile.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise RuntimeError(f"Camera {device} did not report a usable {key}. Check the camera and rerun setup.")
        # LeRobot's configuration expects integers; allow small reporting noise.
        if key == "fps" and not math.isclose(value, round(value), rel_tol=1e-3):
            # Keep a fractional native frame rate by letting LeRobot detect it on connect.
            continue
        settings[key] = max(1, round(value))
    return settings


def configure_cameras(text):
    answer = input("\nUse cameras for teleoperation? [Y/n]: ").strip().lower()
    if answer not in ("", "y", "yes", "n", "no"):
        raise ValueError("Answer yes or no to the camera question.")
    if answer in ("n", "no"):
        return "{}"

    # Save previews, then let the user assign the physical camera views.
    previews = Path(tempfile.mkdtemp(prefix="lefinal-cameras-"))
    profiles = discover_cameras(previews)
    print(f"\nOpen the sample images in {previews} to identify the wrist and stand views.")
    print("Camera numbers can change after reconnecting devices or restarting the computer.")

    previous = read_value(text, "ROBOT_CAMERAS")
    previous = {} if not previous or previous.startswith("REPLACE_WITH_") else json.loads(previous)
    if not isinstance(previous, dict) or any(not isinstance(value, dict) for value in previous.values()):
        raise ValueError("ROBOT_CAMERAS must be a JSON object in config.env.")
    cameras = {}
    # Retain names and device choices, but refresh capture settings from detection.
    for name in previous or ("wrist", "stand"):
        defaults = previous.get(name, {})
        default = defaults.get("index_or_path", "")
        while True:
            answer = input(f"\n{name} camera index or /dev/video path (or 'skip') [{default}]: ").strip()
            answer = answer or str(default)
            if answer.lower() == "skip":
                break
            if not (answer.isdecimal() or answer.startswith("/dev/")):
                print("Enter a camera number, a /dev/video path, or 'skip'.")
                continue
            device = int(answer) if answer.isdecimal() else answer
            if device not in profiles:
                print("Select a camera with a captured preview, or 'skip'.")
                continue
            if any(camera["index_or_path"] == device for camera in cameras.values()):
                print("That device is already assigned to another view. Select a different camera.")
                continue
            cameras[name] = {
                **{key: value for key, value in defaults.items() if key not in ("width", "height", "fps")},
                **detected_camera_settings(device, profiles[device]),
            }
            profile = profiles[device]
            print(f"Using {name}: camera {device}, {profile['width']} x {profile['height']} "
                  f"at {profile['fps']:g} FPS (detected).")
            break

    # Validate the selected resolution/FPS with the same camera classes used by teleoperation.
    # Keep all selected cameras open together to check that the USB setup supports them.
    import draccus
    from PIL import Image
    from lerobot.cameras import CameraConfig
    from lerobot.cameras.opencv.camera_opencv import OpenCVCamera

    opened = []
    try:
        for name, settings in cameras.items():
            camera = OpenCVCamera(draccus.decode(CameraConfig, settings))
            opened.append(camera)
            camera.connect()
            safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", name)
            Image.fromarray(camera.async_read(timeout_ms=1000)).save(previews / f"selected_{safe_name}.png")
    finally:
        for camera in reversed(opened):
            if camera.is_connected:
                camera.disconnect()

    if cameras:
        print(f"\nCamera settings validated. Selected previews: {previews}")
    else:
        print("No cameras selected; teleoperation will run without images.")
    return json.dumps(cameras, separators=(",", ":"))


def update_config(text, settings):
    # Replace our settings and preserve other settings and comments.
    lines = []
    remaining = dict(settings)
    for line in text.splitlines():
        match = ASSIGNMENT.match(line)
        if match and match[1] in settings:
            key = match[1]
            if key in remaining:
                lines.append(f"{key}={shlex.quote(remaining.pop(key))}")
        else:
            lines.append(line)
    lines.extend(f"{key}={shlex.quote(value)}" for key, value in remaining.items())
    return "\n".join(lines) + "\n"


def calibrate_missing_arms(settings):
    for role, prefix in (("follower", "robot"), ("leader", "teleop")):
        arm = settings[role.upper() + "_ID"]
        port = settings[role.upper() + "_PORT"]
        if not arm or not port or arm.startswith("REPLACE_WITH_") or port.startswith("REPLACE_WITH_"):
            raise RuntimeError(f"Set the {role} port and ID in config.env before calibration.")
        directory = ROOT / "calibration" / role
        path = directory / f"{arm}.json"
        if path.is_file():
            print(f"Using existing {role} calibration: {path}", flush=True)
            continue
        directory.mkdir(parents=True, exist_ok=True)
        print(f"\nNo {role} calibration found. Follow LeRobot's prompts to calibrate the arm.", flush=True)
        result = subprocess.run([
            sys.executable, "-m", "lerobot.calibrate",
            f"--{prefix}.type=so101_{role}",
            f"--{prefix}.port={port}",
            f"--{prefix}.id={arm}",
            f"--{prefix}.calibration_dir={directory}",
        ])
        if result.returncode != 0 or not path.is_file():
            raise RuntimeError(f"{role.capitalize()} calibration did not finish. config.env has been saved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cameras-only", action="store_true", help="Keep existing arm ports and update cameras only.")
    mode.add_argument("--calibration-only", action="store_true",
                      help="Use saved arm ports and create missing calibration files; skip cameras and port discovery.")
    args = parser.parse_args()
    target = ROOT / "config.env"
    template = ROOT / "config.example.env"
    if args.calibration_only and not target.is_file():
        raise RuntimeError("Calibration-only setup needs config.env with both arm ports. Run full setup first.")
    text = target.read_text() if target.exists() else template.read_text()
    settings = {role.upper() + "_ID": arm_id(text, role, prompt=not args.cameras_only)
                for role in ("follower", "leader")}
    for role in ("follower", "leader"):
        key = role.upper() + "_PORT"
        if args.cameras_only or args.calibration_only:
            settings[key] = read_value(text, key) or "REPLACE_WITH_" + key
        else:
            settings[key] = find_port(role)
    if not args.cameras_only and settings["FOLLOWER_PORT"] == settings["LEADER_PORT"]:
        raise RuntimeError("The same port was detected twice. Repeat setup using a different arm each time.")
    if args.calibration_only:
        for key, value in settings.items():
            if not value or value.startswith("REPLACE_WITH_"):
                raise RuntimeError(f"Set {key} in config.env before calibration-only setup.")
    else:
        settings["ROBOT_CAMERAS"] = configure_cameras(text)

    # Save only after arm detection and camera checks succeed, replacing the file atomically.
    updated = update_config(text, settings)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=ROOT, delete=False) as file:
            temporary = Path(file.name)
            file.write(updated)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"\nSaved {target}")
    for key in KEYS:
        if key in settings:
            print(f"{key}={shlex.quote(settings[key])}")
    if any(value.startswith("REPLACE_WITH_") for value in settings.values()):
        print("\nFill in missing arm ports/IDs in config.env before teleoperating.")
    print("config.env stays out of Git.")
    if not args.cameras_only:
        calibrate_missing_arms(settings)
        print("\nSetup complete. Start teleoperation with: bash scripts/teleoperate.sh")


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nSetup cancelled. Any files already saved have been kept.")
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        sys.exit(f"\n{error}\nSetup failed. Any files already saved have been kept.")
