# theorem on CypherBench

[CypherBench](https://github.com/megagonlabs/cypherbench) (Feng, Papicchio and Rahman, ACL 2025, [arXiv:2412.18702](https://arxiv.org/abs/2412.18702)) is the standard public benchmark for natural-language retrieval over property graphs. It ships 11 Wikidata-derived graphs and a 2,348-question test set with gold Cypher and gold answers.

These are theorem's results on that benchmark, run under the published protocol. Nothing here is a custom slice, a custom metric, or a custom set of questions.

## Result

**theorem v0 scores 50.94% execution accuracy on the full test set. The same model writing Cypher scores 70.36%.** theorem is behind text2cypher by 19.4 points on this benchmark, and it is behind the 2024 baselines the paper published as well.

| System | Model | EX (%) | Executable (%) |
| --- | --- | --- | --- |
| text2cypher | claude-haiku-4-5-20251001 | 70.36 | 95.27 |
| text2cypher (published) | claude3.5-sonnet-20240620 | 61.58 | 96.34 |
| text2cypher (published) | gpt-4o-20240806 | 60.18 | 94.93 |
| theorem, set-valued `return` | claude-haiku-4-5-20251001 | 56.43 | 82.75 |
| **theorem, as it ships** | claude-haiku-4-5-20251001 | **50.94** | 82.75 |
| text2cypher (published) | qwen2.5-72b | 41.87 | 86.84 |
| text2cypher (published) | gemini1.5-pro-001 | 39.95 | 86.03 |
| text2cypher (published) | llama3.1-70b | 38.84 | 92.25 |
| text2cypher (published) | yi-large | 33.82 | 83.52 |
| text2cypher (published) | gpt-4o-mini-20240718 | 31.43 | 87.39 |
| text2cypher (published) | gemini1.5-flash-001 | 25.26 | 83.65 |
| text2cypher (published) | llama3.1-8b | 18.82 | 90.67 |
| text2cypher (published) | llama3.2-3b | 11.20 | 86.46 |

Excluding `nba`, the one graph theorem's prompt was written against, theorem scores 49.81% over 2078 questions. The gap is not an artifact of that graph.

The published baselines were run on 2024 models, so they cannot separate the query language from the model. The text2cypher row at the top is the control that can: official zero-shot prompt, same questions, same comparator, same model, graphs loaded from the same files.

## Where the gap comes from

theorem loses 1152 of 2348 questions. 57% of those losses are one bug and three missing features, not a broad inability to express the questions.

**Duplicate rows.** theorem's prompt tells the model "results are sets: duplicates do not matter", but neither the engine's rendering path nor its row output deduplicates. A correct query for "which airports have flights departed from" returns one row per accident rather than one per airport, and the benchmark's comparator rejects on row count before it compares anything. Re-scoring the same queries with `return` deduplicating on the bindings it projects lifts theorem from 50.94% to 56.43% and needs no change to any query. The language's documented semantics and its implementation disagree, and the implementation is the one that is wrong.

**No `union`.** 310 questions ask for one set or another. theorem v0 has no way to combine two result sets, and scores 9.35% on them against text2cypher's 68.71%.

**No optional match and no edge properties.** 268 questions need a left join and 60 need to filter on a relationship's own properties. v0 supports neither.

Where theorem is ahead, it is ahead on the shapes it was designed for: grouped counting and per-entity comparison.

## By graph

| Graph | Questions | theorem EX (%) | theorem, set `return` (%) | text2cypher EX (%) |
| --- | --- | --- | --- | --- |
| flight_accident | 189 | 76.72 | 80.42 | 76.19 |
| nba *(tuned on)* | 270 | 59.63 | 67.04 | 71.85 |
| fictional_character | 385 | 40.52 | 44.42 | 77.14 |
| company | 347 | 51.30 | 54.76 | 70.61 |
| geography | 366 | 53.55 | 60.38 | 62.57 |
| politics | 390 | 44.87 | 51.54 | 68.97 |
| movie | 401 | 46.13 | 52.12 | 68.33 |

## By question category

| Category | Questions | theorem EX (%) | text2cypher EX (%) | Delta |
| --- | --- | --- | --- | --- |
| `basic_(n)` | 61 | 90.16 | 90.16 | +0.0 |
| `basic_(n*)` | 59 | 89.83 | 84.75 | +5.1 |
| `basic_(n)-(m0)` | 71 | 18.31 | 63.38 | -45.1 |
| `basic_(n)-(m0*)` | 356 | 76.12 | 84.27 | -8.1 |
| `basic_(n)=(m0)` | 94 | 3.19 | 67.02 | -63.8 |
| `basic_(n)-(m0)-(m1*)` | 329 | 57.75 | 69.60 | -11.9 |
| `basic_(n)-(m0*),(n)-(m1*)` | 333 | 56.46 | 74.77 | -18.3 |
| `special_three-node-groupby` | 260 | 72.31 | 60.38 | +11.9 |
| `special_comparison` | 147 | 81.63 | 64.63 | +17.0 |
| `special_union` | 310 | 9.35 | 68.71 | -59.4 |
| `special_optional-match` | 268 | 23.51 | 53.73 | -30.2 |
| `special_time-sensitive` | 60 | 38.33 | 86.67 | -48.3 |

## Protocol

- **Questions**: the full published test set, all 2,348 questions across all 7 test graphs. No category was excluded, including the ones theorem v0 cannot express.
- **Graphs**: the full unsampled `simplekg` graphs, the same files the official Docker deployment loads, so the published gold answers apply unchanged.
- **Generation**: zero-shot, one generation per question, no repair retry, no self-consistency, no reranking.
- **Scoring**: execution accuracy using the comparator from `cypherbench/metrics/execution_accuracy.py`, vendored verbatim, against the published `answer_json`. Order is enforced exactly when the gold Cypher contains `order by`, as in the original.
- **text2cypher control**: `NL2CYPHER_PROMPT_DEFAULT` verbatim from the official baseline, schema string reproduced from `PropertyGraphSchema.to_sorted().to_str()`, queries executed against the official `megagonlabs/neo4j-with-loader` image with the official 120s timeout.

## What is not equal between the two arms

theorem's prompt contains a language tutorial, an EBNF grammar and nine worked examples, because theorem is a new language the model has never seen. The text2cypher prompt is the official zero-shot one, because Cypher is already in the model's training data. This is each system with its natural prompting, not a matched-prompt comparison, and the gap between the two arms therefore mixes the language with how it is taught.

Both prompts do carry comparable return discipline: the official Cypher prompt instructs the model not to return node objects and to avoid duplicate entities, and theorem's carries equivalent rules.

## Structural ceiling

135 of the 2348 scored questions (5.7%) cannot be answered by theorem v0 regardless of the query written:

- 75 have a list-valued gold cell, and v0 loads `list[str]` properties as comma-joined strings.
- 60 need edge properties (`r0.start_year` and similar), and v0 loads none.

Excluding them, execution accuracy is 53.00%. They are counted as failures in every other number on this page.

## Honest notes

- An earlier internal evaluation in this repo reported theorem at 98.3% against text2cypher's 73.3%. That number was measured on a hand-picked subset of the `nba` graph, with the categories theorem could not express removed, and with a prompt that had been iterated against those same questions. It does not survive contact with the full public benchmark and should not be quoted.
- Two bugs found while running this were fixed before the numbers above were taken: `count distinct` was quadratic, which made large graphs unqueryable, and the evaluation adapter collapsed relation labels that connect more than one pair of entity types, which alone was costing 36 points on `geography`.
- The set-valued `return` row is a measurement, not a shipped change. The engine still emits duplicates.

## Reproducing

```bash
# graphs and test set from the published HuggingFace dataset
#   https://huggingface.co/datasets/megagonlabs/cypherbench
uv run python -m eval.run_public all --model claude-haiku-4-5-20251001
uv run python -m eval.run_cypher_public all --model claude-haiku-4-5-20251001
uv run python -m eval.make_report
```

Per-question queries, results and errors for every arm are in `eval/out/public/`.
