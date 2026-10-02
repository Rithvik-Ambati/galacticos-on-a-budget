"""The one swap-in point `pipeline/ingest.py` and `pipeline/pricing.py` call through,
so picking real vs. synthetic data is a single env var, not a code change -- the
promise recorded in docs/DECISIONS.md when `pipeline/synthetic_source.py` was built.

docs/DECISIONS.md "Synthetic data is no longer the silent default": DATA_SOURCE
defaults to "real" now, not "synthetic" -- a player must opt INTO fictional data
(`DATA_SOURCE=synthetic`), never opt out of it by omission. CI and the test suite
must set DATA_SOURCE=synthetic explicitly wherever they seed a database; nothing
may rely on this default.
"""

from __future__ import annotations

import os

from pipeline import real_source, synthetic_source
from pipeline.synthetic_source import SyntheticWorld

VALID_SOURCES = ("real", "synthetic")


def resolve_source_name() -> str:
    source = os.environ.get("DATA_SOURCE", "real")
    if source not in VALID_SOURCES:
        raise ValueError(f"DATA_SOURCE must be one of {VALID_SOURCES}, got {source!r}")
    return source


def generate(seed: int | None = None) -> SyntheticWorld:
    if resolve_source_name() == "synthetic":
        return synthetic_source.generate(seed=seed)
    return real_source.generate(seed=seed)
