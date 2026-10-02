"""The one swap-in point `pipeline/ingest.py` and `pipeline/pricing.py` call through,
so picking real vs. synthetic data is a single env var, not a code change -- the
promise recorded in docs/DECISIONS.md when `pipeline/synthetic_source.py` was built.
"""

from __future__ import annotations

import os

from pipeline import real_source, synthetic_source
from pipeline.synthetic_source import SyntheticWorld


def generate(seed: int | None = None) -> SyntheticWorld:
    if os.environ.get("DATA_SOURCE") == "real":
        return real_source.generate(seed=seed)
    return synthetic_source.generate(seed=seed)
