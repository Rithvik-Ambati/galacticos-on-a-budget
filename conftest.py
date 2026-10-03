"""Ensures the repo root (where engine/, config/, db/ live) is importable regardless
of which directory pytest is invoked from."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _no_real_langfuse_calls(monkeypatch):
    """The test suite must never depend on whether the machine running it happens
    to have real LANGFUSE_* keys in .env (e.g. from the docker-compose Langfuse
    instance docs/DECISIONS.md "Langfuse v4 self-host" documents) -- a real
    instance being reachable would otherwise make every graph/narrator test
    silently fire real network traces, which is slow, non-deterministic, and
    breaks the moment that instance isn't running. Tests exercising the
    "configured" path override this with their own monkeypatch.setattr call,
    which simply wins since it runs after this fixture within the same test."""
    import observability

    monkeypatch.setattr(observability, "_client", lambda: None)
