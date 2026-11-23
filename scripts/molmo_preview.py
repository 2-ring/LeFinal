"""Archive decoded camera pairs from the same JPEG messages Oscar receives."""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch

import cv2
import numpy as np
from lerobot.inference.contracts import ExecutionMode
from lerobot.remote_inference.codec import decode_message


@contextmanager
def record_policy_views(client, folder):
    frames = folder / "camera_pairs"
    frames.mkdir()
    live = folder.parent / "policy_view.png"
    send = client.transport.publish
    infer = client.infer
    last_observation = None

    def publish(key, data):
        nonlocal last_observation
        send(key, data)
        if key.endswith("/obs"):
            last_observation = data

    def save(payload, record, elbow):
        try:
            if payload is None or elbow is None:
                return
            message = decode_message(payload)
            if message.request_id != record["request_id"]:
                raise ValueError("Observation and action request IDs differ")
            obs = message.body
            features = obs["features"]
            rgb = np.concatenate([features[f"observation.images.cam{i}"] for i in (0, 1)], axis=1)
            pair = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            seq = obs["sequence"]
            name = f"pair-{seq:04d}.png"
            if not cv2.imwrite(str(frames / name), pair):
                raise OSError(f"Could not write {name}")
            measured = float(features["observation.state"][2])
            record.update(file=name, measured_elbow=measured, elbow_targets=elbow)
            caption = f"Request {seq}   Elbow {measured:.1f} deg   First target {elbow[0]:.1f} deg"
            display = cv2.copyMakeBorder(pair, 0, 26, 0, 0, cv2.BORDER_CONSTANT)
            cv2.putText(display, caption, (6, 242), cv2.FONT_HERSHEY_SIMPLEX, .46,
                        (240, 240, 240), 1, cv2.LINE_AA)
            tmp = frames / "preview.tmp.png"
            if cv2.imwrite(str(tmp), display):
                os.replace(tmp, live)
        except Exception:
            logging.exception("Could not save policy camera pair")
        finally:
            try:
                with (frames / "requests.jsonl").open("a") as log:
                    log.write(json.dumps(record) + "\n")
            except OSError:
                logging.exception("Could not log policy request")

    with ThreadPoolExecutor(max_workers=1) as writer:
        def infer_with_preview(request, **kwargs):
            nonlocal last_observation
            last_observation = None
            # LeRobot 0.7 estimates delay from the previous turnaround. Its
            # wire protocol bounds that field even for plain action chunks.
            if request.mode is ExecutionMode.CHUNK and request.delay > client.capabilities.prediction_steps:
                request = replace(request, delay=client.capabilities.prediction_steps)
            record = dict(request_id=request.request_id, task=request.observation.task,
                          capture_time=request.observation.capture_time)
            started = time.perf_counter()
            try:
                result = infer(request, **kwargs)
            except Exception as exc:
                record.update(duration_ms=(time.perf_counter() - started) * 1000,
                              status="error", error=type(exc).__name__)
                writer.submit(save, last_observation, record, None)
                raise
            record.update(duration_ms=(time.perf_counter() - started) * 1000, status="ok")
            writer.submit(save, last_observation, record, result.canonical_actions[:, 2].tolist())
            return result

        with patch.object(client.transport, "publish", publish), patch.object(client, "infer", infer_with_preview):
            yield
