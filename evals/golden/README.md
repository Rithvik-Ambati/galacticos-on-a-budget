# Golden sets

CLAUDE.md: "Golden eval sets in `evals/golden/` are written by the human. Do not
generate or edit expected answers." These two files each ship with exactly 2
`"is_example": true` rows that show the schema -- illustrative only, not real
judged answers, and every runner that reads these files filters `is_example` rows
out before scoring. A file with only example rows (or none at all) is treated as
an empty golden set: `evals/retrieval_eval.py`, `evals/embedding_benchmark.py` and
`evals/run_all.py` all run correctly against it (they report 0 queries evaluated,
not an error), so the pipeline is exercised and tested even before the project
owner has written any real cases. Delete the example rows once you've added your
own -- they're skipped either way, so leaving them in is harmless too.

## retrieval_queries.jsonl

One JSON object per line:

```json
{"query": "left-sided defender good in the air", "relevant_doc_ids": ["player_profile:p_123", "player_profile:p_456"], "doc_type": "player_profile"}
```

`relevant_doc_ids` is the set of `documents.doc_id` values a human judge considers a
correct answer to `query`. `doc_type` is optional (narrows the search the same way
the UI's filters do).

~100 queries is the target in docs/DESIGN.md section 12.

## chat_questions.jsonl

One JSON object per line:

```json
{"question": "why did we concede twice down the left?", "expected_topic": "zone_mismatch left def"}
```

Used for a human's own manual grading pass (docs/DESIGN.md section 5's "Phase 5 manual
check: read 10 generated coach reports"); the runners do not score this file
automatically — there's no reference answer a machine can check a free-text response
against without an LLM judge, which is out of scope here.

~30 questions is the target in docs/DESIGN.md section 5.
