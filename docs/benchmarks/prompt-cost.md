# What the prompt costs, and where that reverses

theorem carries a tutorial in every prompt, because the model has
never seen the language. Cypher carries none, because it has. That
is a fixed cost, and on the benchmark graphs it makes theorem's
prompt about 2.4 to 3.6 times larger.

Against it, theorem's schema render is much cheaper per class than
the JSON schema a text2cypher prompt sends. So the two costs are
lines with different slopes, and they cross.

## Measured

| schema | classes | edges | theorem | text2cypher | ratio |
|---|---:|---:|---:|---:|---:|
| fictional_character | 9 | 12 | 1,570 | 561 | 2.80x |
| company | 9 | 7 | 1,479 | 416 | 3.56x |
| flight_accident | 10 | 6 | 1,538 | 497 | 3.09x |
| politics | 11 | 12 | 1,663 | 700 | 2.38x |
| nba | 12 | 8 | 1,532 | 567 | 2.70x |
| movie | 12 | 10 | 1,546 | 593 | 2.61x |
| geography | 13 | 13 | 1,622 | 671 | 2.42x |
| all seven, unioned | 40 | 62 | **2,793** | 3,186 | 0.88x |

- theorem: **39 tokens per class**, on top of 1,357 tokens of tutorial and instructions that never grow.
- text2cypher: **85 tokens per class**, on top of 99.
- The lines cross at **31 classes**.

The crossing is inside the measured range rather than past it: theorem's prompt is smaller at 40 classes (all seven, unioned) and larger at 13. The seven benchmark graphs have 9 to 13 classes each, which is the region where theorem is most expensive; a schema of the size real deployments have is the region where it is cheapest.

## What this is not

This is prompt size, not accuracy. It says what a question costs to
ask, not how often the answer is right. The unioned schema is assembled from real ones and has 40 classes and 62 edge types, but no data was loaded behind it and no query was run against it, so nothing here is a claim about how a model performs at that size.

Counts use the same `len(text) // 4` heuristic as every other number
in these docs. Prompt fingerprint `eb0f4010`.

Reproduce: `uv run python -m eval.token_crossover --report`.

