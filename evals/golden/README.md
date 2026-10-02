# Golden sets

CLAUDE.md: "Golden eval sets in `evals/golden/` are written by the human. Do not
generate or edit expected answers." These two files are empty templates, left for
the project owner to fill in — `evals/retrieval_eval.py` and `run_all.py` both run
correctly against an empty file (they report 0 queries evaluated, not an error), so
the pipeline is exercised and tested even before anyone writes real cases.

## retrieval.jsonl

One JSON object per line:

```json
{"query": "left-sided defender good in the air", "relevant_doc_ids": ["player_profile:p_123", "player_profile:p_456"], "doc_type": "player_profile"}
```

`relevant_doc_ids` is the set of `documents.doc_id` values a human judge considers a
correct answer to `query`. `doc_type` is optional (narrows the search the same way
the UI's filters do).

~100 queries is the target in docs/DESIGN.md section 12.

## chat.jsonl

One JSON object per line:

```json
{"question": "why did we concede twice down the left?", "expected_topic": "zone_mismatch left def"}
```

Used for a human's own manual grading pass (docs/DESIGN.md section 5's "Phase 5 manual
check: read 10 generated coach reports"); `evals/run_all.py` does not score this file
automatically — there's no reference answer a machine can check a free-text response
against without an LLM judge, which is out of scope here.

~30 questions is the target in docs/DESIGN.md section 5.
