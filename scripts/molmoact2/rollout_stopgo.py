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
