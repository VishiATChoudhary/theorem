"""How much of the test set has a query for the prompt that ships now.

Counting files in the cache directory counts every prompt version that
has ever run against it, which is how a half-finished generation looks
finished. This asks the same question the harness asks: does this
question have a cached answer for this prompt?

    uv run python -m eval._progress
"""

import json

from eval.load_graph import derive_schema
from eval.run_public import DATA, TEST_GRAPHS, cache_path_for, questions_for

MODEL = "claude-haiku-4-5-20251001"


def main() -> int:
    schemas = {
        g: derive_schema(json.loads((DATA / f"{g}_schema.json").read_text()))
        for g in TEST_GRAPHS
    }
    qs = questions_for()
    have = sum(cache_path_for(q, MODEL, schemas).exists() for q in qs)
    print(
        f"{have}/{len(qs)} generated for the current prompt ({len(qs) - have} missing)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
