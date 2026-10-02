"""Nightly CI's faithfulness gate. docs/DESIGN.md section 12: "faithfulness gate
>=0.90, activates only when a live-run baseline exists." Nightly CI has no secret
to call a live LLM with, so it can't compute a fresh faithfulness score itself --
instead this checks the STATIC, human-committed record at
`evals/baselines/live_faithfulness_baseline.json`, written by running
`evals/faithfulness_eval.py` by hand with `LLM_PROVIDER=anthropic` set
(`evals/faithfulness_eval.py`'s own `__main__` block writes it). If that file has
never been committed, the gate is simply not active yet -- this exits 0 either way,
printing which case it hit.
"""

from __future__ import annotations

import json
import os
import sys

THRESHOLD = 0.90
LIVE_BASELINE_PATH = os.path.join(os.path.dirname(__file__), "baselines", "live_faithfulness_baseline.json")


def check_gate(path: str = LIVE_BASELINE_PATH, threshold: float = THRESHOLD) -> bool:
    """True if the gate passes (including "not active yet"), False if a committed
    live baseline has dropped below `threshold`."""
    if not os.path.exists(path):
        print(f"No live faithfulness baseline committed at {path} -- gate not active yet.")
        return True

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    coach = float(data.get("coach_faithfulness", 0.0))
    match = float(data.get("match_faithfulness", 0.0))
    worst = min(coach, match)

    print(f"Live faithfulness baseline: coach={coach}, match={match} (threshold {threshold}).")
    if worst < threshold:
        print(f"FAIL: faithfulness {worst} is below the {threshold} gate.")
        return False
    print("PASS.")
    return True


if __name__ == "__main__":
    sys.exit(0 if check_gate() else 1)
