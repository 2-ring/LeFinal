"""Show local SO-101 camera streams in the session's Rerun viewer."""

import json
import logging
import os
import socket
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch
from threading import Event, Thread

from camera_ids import resolve_cameras
from setup_config import read_value


def configured_cameras(text):
    raw = read_value(text, "ROBOT_CAMERAS")
    if not raw or raw.startswith("REPLACE_WITH_"):
        return {}
    return resolve_cameras(json.loads(raw), json.loads(read_value(text, "MACOS_CAMERA_IDS") or "{}"))


def open_camera_viewer(session_name, names):
    """Connect this session to its own viewer and select the camera panels."""
    import rerun as rr
    import rerun.blueprint as rrb
    import rerun_cli

    # The recording and Molmo environments use incompatible Rerun protocols.
    # A viewer left on the default port may belong to the other environment.
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    rr.init(session_name)
    viewer_dir = Path(rerun_cli.__file__).parent
    with patch.dict(os.environ, {"PATH": os.pathsep.join((str(viewer_dir), os.environ.get("PATH", "")))}):
        rr.spawn(port=port, hide_welcome_screen=True, memory_limit="10%")
    panels = [
        rrb.Spatial2DView(name=name.title(), origin=f"/observation.{name}")
        for name in sorted(names)
    ]
    if panels:
        rr.send_blueprint(rrb.Blueprint(rrb.Horizontal(*panels)))
    return port


@contextmanager
def live_views(readers):
    """Read each view independently so a slow camera cannot stall robot control."""
    import rerun as rr

    stopped = Event()

    def stream(name, read):
        previous = None
        failed = False
        while not stopped.is_set():
            try:
                frame = read()
                if frame is not previous:
                    rr.log(f"observation.{name}", rr.Image(frame))
                    previous = frame
                failed = False
            except Exception as error:
                if not failed:
                    logging.warning("Preview unavailable for %s: %s", name, error)
                failed = True
            stopped.wait(0.1)

    with ExitStack() as workers:
        try:
            for name, read in readers.items():
                worker = Thread(target=stream, args=(name, read), name=f"preview-{name}", daemon=True)
                worker.start()
                workers.callback(worker.join)
            yield
        finally:
            stopped.set()
