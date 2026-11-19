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
print("dtype", policy.config.dtype, "cuda_graph", policy.config.enable_inference_cuda_graph,
      "default flow steps", policy.config.num_inference_steps, flush=True)
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
print("BENCH_DONE", flush=True)
