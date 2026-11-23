"""Run a supervised MolmoAct2 rollout through the local Oscar SSH forward."""

import argparse
import csv
import os
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import patch

import cv2
from lerobot.cameras import CameraConfig
from lerobot.cameras.opencv import OpenCVCamera, OpenCVCameraConfig
from lerobot.inference import RemoteInferenceConfig
from lerobot.robots.so_follower import SO101FollowerConfig
from lerobot.rollout import RolloutConfig
from lerobot.rollout.configs import BaseStrategyConfig, RolloutStrategyConfig
from lerobot.rollout.strategies.base import BaseStrategy
from lerobot.scripts.lerobot_rollout import rollout

from camera_preview import configured_cameras, live_views, open_camera_viewer
from setup_config import ROOT, read_value
from molmo_preview import record_policy_views


@CameraConfig.register_subclass("molmo_opencv")
@dataclass
class MolmoCameraConfig(OpenCVCameraConfig):
    """Width and height describe the physical USB capture mode."""


def policy_image(rgb):
    """Resize the entire view to the 224-pixel square expected by this checkpoint."""
    return cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_AREA)


class MolmoCamera(OpenCVCamera):
    def _reset_connection_settings(self):
        super()._reset_connection_settings()
        if self.capture_width is None or self.capture_height is None:
            raise ValueError("Set native camera width and height in config.env")
        # LeRobot advertises width/height to the policy. The USB device uses
        # capture_width/capture_height, which stay at its native resolution.
        self.width = self.height = 224

    def _postprocess_image(self, image):
        return policy_image(super()._postprocess_image(image))


@RolloutStrategyConfig.register_subclass("measure_joint_limits")
@dataclass
class MeasuredRolloutConfig(BaseStrategyConfig):
    """Use the standard control loop and record each successful command."""


class MeasuredRollout(BaseStrategy):
    def setup(self, ctx):
        self.preview = ExitStack()
        super().setup(ctx)
        cameras = ctx.hardware.robot_wrapper.cameras
        open_camera_viewer("Molmo SO-101 cameras", cameras)
        self.preview.enter_context(live_views({name: camera.read_latest for name, camera in cameras.items()}))

    def teardown(self, ctx):
        try:
            self.preview.close()
        finally:
            super().teardown(ctx)

    def run(self, ctx):
        robot = ctx.hardware.robot_wrapper
        observe, send = robot.get_observation, robot.send_action
        joints = tuple(robot.action_features)
        rows = []
        clipped = dict.fromkeys(joints, 0)
        trimmed = dict.fromkeys(joints, 0.0)
        any_arm_clipped = 0
        measured = {}
        start = time.monotonic()
        folder = ROOT / "data" / "live_red_object" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        folder.mkdir(parents=True)

        def read_positions():
            observation = observe()
            measured.update((joint, observation[joint]) for joint in joints)
            return observation

        def record_command(requested):
            nonlocal any_arm_clipped
            applied = send(requested)
            limited = [j for j in joints if abs(requested[j] - applied[j]) > 1e-4]
            any_arm_clipped += any(j != "gripper.pos" for j in limited)
            for joint in limited:
                clipped[joint] += 1
                trimmed[joint] += abs(requested[joint] - applied[joint])
            rows.append([time.monotonic() - start] + [
                value for j in joints for value in (measured.get(j), requested[j], applied[j])
            ])
            return applied

        try:
            with (
                record_policy_views(ctx.policy.inference.client, folder),
                patch.object(robot, "get_observation", read_positions),
                patch.object(robot, "send_action", record_command),
            ):
                super().run(ctx)
        finally:
            with (folder / "joint_targets.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["time_s"] + [
                    f"{j}.{field}" for j in joints for field in ("measured", "requested", "sent")
                ])
                writer.writerows(rows)
            print(f"Driver altered an arm joint target on {any_arm_clipped}/{len(rows)} commands.", flush=True)
            for joint in joints:
                if clipped[joint]:
                    unit = "gripper percentage points" if joint == "gripper.pos" else "degrees"
                    print(f"{joint}: {clipped[joint] / len(rows):.1%} of commands clipped, "
                          f"mean {trimmed[joint] / clipped[joint]:.2f} {unit} removed when clipped.")
            print(f"Joint trace saved to {folder / 'joint_targets.csv'}", flush=True)


DEFAULT_TASK = "Pick up the red roll of tape."


def rollout_config(task=DEFAULT_TASK):
    settings = (ROOT / "config.env").read_text()
    cameras = {}
    for name, specification in configured_cameras(settings).items():
        if specification.pop("type") != "opencv":
            raise ValueError(f"Expected an OpenCV camera for {name}")
        cameras[name] = MolmoCameraConfig(**specification)
    if set(cameras) != {"stand", "wrist"}:
        raise ValueError("Set both stand and wrist cameras in config.env")
    return RolloutConfig(
        strategy=MeasuredRolloutConfig(),
        robot=SO101FollowerConfig(
            port=read_value(settings, "FOLLOWER_PORT"),
            id=read_value(settings, "FOLLOWER_ID"),
            calibration_dir=ROOT / "calibration" / "follower",
            use_degrees=True,
            max_relative_target=None,
            cameras=cameras,
        ),
        inference=RemoteInferenceConfig(
            endpoint=os.environ.get("MOLMO_ENDPOINT", "tcp/127.0.0.1:17448"),
            deployment="lefinal-so101",
            semantics="so101-degrees-gripper-percent-v1",
            encoding="jpeg",
        ),
        rename_map={
            "observation.images.stand": "observation.images.cam0",
            "observation.images.wrist": "observation.images.cam1",
        },
        task=task,
        fps=30,
        duration=30,
        interactive=True,
        return_to_initial_position=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=DEFAULT_TASK, help="Instruction sent to Molmo (default: %(default)s)")
    args = parser.parse_args()
    if not args.task.strip():
        parser.error("--task requires a nonempty instruction")
    config = rollout_config(args.task.strip())
    print(f"Task: {config.task}", flush=True)
    print(f"Duration: {config.duration}s | Max relative target: {config.robot.max_relative_target}", flush=True)
    rollout(config)
