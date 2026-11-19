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
