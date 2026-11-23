"""Resolve saved macOS camera identities to the indices LeRobot opens."""

import json
import subprocess
import sys


def macos_camera_ids():
    # Match OpenCV's AVFoundation backend: video and muxed devices sorted by uniqueID.
    script = """
        ObjC.import("AVFoundation")
        const camera = $.NSClassFromString("AVCaptureDevice")
        const devices = camera.devicesWithMediaType($.AVMediaTypeVideo)
            .arrayByAddingObjectsFromArray(camera.devicesWithMediaType($.AVMediaTypeMuxed))
        const ids = ObjC.unwrap(devices).map(device => device.uniqueID)
        ids.sort((left, right) => left.compare(right))
        JSON.stringify(ids.map(id => ObjC.unwrap(id)))
    """
    result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", script],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Could not list macOS cameras: {result.stderr.strip()}")
    return json.loads(result.stdout)


def resolve_cameras(cameras, saved_ids):
    if not isinstance(cameras, dict) or not isinstance(saved_ids, dict):
        raise ValueError("Camera settings and saved camera IDs must be JSON objects.")
    if sys.platform != "darwin" or not saved_ids or not cameras:
        return cameras
    devices = macos_camera_ids()
    for name, uid in saved_ids.items():
        if name not in cameras:
            continue
        if uid not in devices:
            raise ValueError(f"Cannot find the saved {name} camera. Reconnect it to the same USB port "
                             "or run python scripts/setup_config.py --cameras-only.")
        cameras[name]["index_or_path"] = devices.index(uid)
    return cameras
