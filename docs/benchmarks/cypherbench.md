# theorem on CypherBench

[CypherBench](https://github.com/megagonlabs/cypherbench) (Feng, Papicchio and Rahman, ACL 2025, [arXiv:2412.18702](https://arxiv.org/abs/2412.18702)) is the standard public benchmark for natural-language retrieval over property graphs. It ships 11 Wikidata-derived graphs and a 2,348-question test set with gold Cypher and gold answers.

These are theorem's results on that benchmark, run under the published protocol. Nothing here is a custom slice, a custom metric, or a custom set of questions.

## Result

**theorem scores 77.98% execution accuracy on the full test set. The same model writing Cypher scores 70.36%.** theorem is ahead by 7.6 points, and ahead of every baseline the paper published.

| System | Model | EX (%) | Executable (%) |
| --- | --- | --- | --- |
| **theorem** | claude-haiku-4-5-20251001 | **77.98** | 96.59 |
| text2cypher (control) | claude-haiku-4-5-20251001 | 70.36 | 95.27 |
| text2cypher (published) | claude3.5-sonnet-20240620 | 61.58 | 96.34 |
| text2cypher (published) | gpt-4o-20240806 | 60.18 | 94.93 |
| text2cypher (published) | qwen2.5-72b | 41.87 | 86.84 |
| text2cypher (published) | gemini1.5-pro-001 | 39.95 | 86.03 |
| text2cypher (published) | llama3.1-70b | 38.84 | 92.25 |
| text2cypher (published) | yi-large | 33.82 | 83.52 |
| text2cypher (published) | gpt-4o-mini-20240718 | 31.43 | 87.39 |
| text2cypher (published) | gemini1.5-flash-001 | 25.26 | 83.65 |
| text2cypher (published) | llama3.1-8b | 18.82 | 90.67 |
| text2cypher (published) | llama3.2-3b | 11.20 | 86.46 |

Excluding `nba`, the one graph theorem's prompt was written against, theorem scores 76.85% over 2078 questions, so the result is not an artifact of that graph.

theorem is ahead on 7 of 7 graphs.

The published baselines were run on 2024 models, so they cannot separate the query language from the model. The control row is the one that can: official zero-shot prompt, same questions, same comparator, same model, graphs loaded from the same files.

## Cost per answered question

Accuracy is not the only axis an agent pays for. These are measured on the same runs: tokens are counted with the same estimator on the text each system hands back, and latency is wall-clock for executing the query.

| Measure | theorem | text2cypher |
| --- | --- | --- |
| Result tokens returned, median | 19.0 | 20.0 |
| Result tokens returned, mean | 167.4 | 241.9 |
| Query tokens written, mean | 42.7 | 35.7 |
| Execution latency, median | 0.2 ms | 67.2 ms |
| Execution latency, mean | 51.0 ms | 95.9 ms |

Counted over the questions each system answered correctly, so the comparison is between two right answers rather than between a right answer and an empty one.

Two caveats worth stating. theorem's renderer applies a token budget and hands back a resume handle when a result exceeds it, so its result tokens are capped by design where Cypher's are not; that is a real property of the system, not a measurement artifact, but it means the two numbers answer slightly different questions on large results. And theorem executes in-process while Cypher goes over bolt to a container, so the latency gap includes transport that a co-located Neo4j would not pay.

## What moved the number

An earlier run of this same protocol scored 50.94%. The gain did not come from prompt tuning: it came from the language accepting shapes it used to reject, and from two data-model gaps being closed. Categories that were near zero before are the ones that moved.

| Change | Category it unblocked | Before | Now |
| --- | --- | --- | --- |
| `or` branches for union | `special_union` | 9.35 | 84.19 |
| edge properties and `none` | `special_time-sensitive` | 38.33 | 90.00 |
| `or none` for optional match | `special_optional-match` | 23.51 | 63.43 |
| name reuse means the same node | `basic_(n)=(m0)` | 3.19 | 57.45 |

Executable queries went from 82.75% to 96.59%, which is the clearest single sign: the language now accepts what the model writes without being taught to write differently.

## Where it still loses

- `basic_(n)=(m0)`: 57.45% over 94 questions, against text2cypher's 67.02%.
- `basic_(n)-(m0)`: 60.56% over 71 questions, against text2cypher's 63.38%.
- `special_optional-match`: 63.43% over 268 questions, against text2cypher's 53.73%.

80 queries of 2348 still fail to run at all. The rest are queries that execute and return the wrong rows, which is the harder half to fix.

## By graph

| Graph | Questions | theorem EX (%) | text2cypher EX (%) |
| --- | --- | --- | --- |
| flight_accident | 189 | 88.36 | 76.19 |
| nba *(tuned on)* | 270 | 86.67 | 71.85 |
| fictional_character | 385 | 80.00 | 77.14 |
| company | 347 | 78.10 | 70.61 |
| geography | 366 | 74.59 | 62.57 |
| politics | 390 | 73.85 | 68.97 |
| movie | 401 | 72.32 | 68.33 |

## By question category

| Category | Questions | theorem EX (%) | text2cypher EX (%) | Delta |
| --- | --- | --- | --- | --- |
| `basic_(n)` | 61 | 91.80 | 90.16 | +1.6 |
| `basic_(n*)` | 59 | 96.61 | 84.75 | +11.9 |
| `basic_(n)-(m0)` | 71 | 60.56 | 63.38 | -2.8 |
| `basic_(n)-(m0*)` | 356 | 87.64 | 84.27 | +3.4 |
| `basic_(n)=(m0)` | 94 | 57.45 | 67.02 | -9.6 |
| `basic_(n)-(m0)-(m1*)` | 329 | 78.72 | 69.60 | +9.1 |
| `basic_(n)-(m0*),(n)-(m1*)` | 333 | 76.88 | 74.77 | +2.1 |
| `special_three-node-groupby` | 260 | 76.54 | 60.38 | +16.2 |
| `special_comparison` | 147 | 74.83 | 64.63 | +10.2 |
| `special_union` | 310 | 84.19 | 68.71 | +15.5 |
| `special_optional-match` | 268 | 63.43 | 53.73 | +9.7 |
| `special_time-sensitive` | 60 | 90.00 | 86.67 | +3.3 |

## Protocol

- **Prompt version**: fingerprint `eb0f4010`, read from the name of the frozen query file these results were scored from. Recomputing it here instead would print the tutorial that happens to be checked out, which is how a report comes to claim a prompt it never ran.
- **Questions**: the full published test set, all 2,348 questions across all 7 test graphs. No category was excluded, including the ones theorem v0 cannot express.
- **Graphs**: the full unsampled `simplekg` graphs, the same files the official Docker deployment loads, so the published gold answers apply unchanged.
- **Generation**: zero-shot, one generation per question, no repair retry, no self-consistency, no reranking.
- **Scoring**: execution accuracy using the comparator from `cypherbench/metrics/execution_accuracy.py`, vendored verbatim, against the published `answer_json`. Order is enforced exactly when the gold Cypher contains `order by`, as in the original.
- **text2cypher control**: `NL2CYPHER_PROMPT_DEFAULT` verbatim from the official baseline, schema string reproduced from `PropertyGraphSchema.to_sorted().to_str()`, queries executed against the official `megagonlabs/neo4j-with-loader` image with the official 120s timeout.

## What is not equal between the two arms

theorem's prompt contains a language tutorial, an EBNF grammar and nine worked examples, because theorem is a new language the model has never seen. The text2cypher prompt is the official zero-shot one, because Cypher is already in the model's training data. This is each system with its natural prompting, not a matched-prompt comparison, and the gap between the two arms therefore mixes the language with how it is taught.

Both prompts do carry comparable return discipline: the official Cypher prompt instructs the model not to return node objects and to avoid duplicate entities, and theorem's carries equivalent rules.

## Two data shapes worth calling out

Both of these were unanswerable at any prompt until the data model supported them, and both are the norm rather than the exception in graphs built from technical sources.

- **Multi-valued properties** (75 questions): a person with two citizenships. Flattening them into one string made the value unreturnable. Now 86.67%.
- **Properties on the relationship** (60 questions): when a spell started and ended, which is what makes a question about a particular year answerable at all. Now 90.00%.

## Honest notes

- An earlier internal evaluation in this repo reported theorem at 98.3% against text2cypher's 73.3%. That number was measured on a hand-picked subset of the `nba` graph, with the categories theorem could not express removed, and with a prompt that had been iterated against those same questions. It does not survive contact with the full public benchmark and should not be quoted.
- Several engine and adapter bugs were found by running this and fixed before these numbers were taken: `count distinct` was quadratic, the adapter collapsed relation labels connecting more than one pair of entity types (36 points on `geography` alone), and an optional follow wrongly inherited the path's edge trail, which undercounted every "and how many each" question by one.
- The nba graph is the one theorem's prompt was written against; its number is reported but the held-out figure is the one to quote.

## Reproducing

```bash
# graphs and test set from the published HuggingFace dataset
#   https://huggingface.co/datasets/megagonlabs/cypherbench
uv run python -m eval.run_public all --model claude-haiku-4-5-20251001
uv run python -m eval.run_cypher_public all --model claude-haiku-4-5-20251001
uv run python -m eval.make_report
```

Per-question queries, results and errors for every arm are in `eval/out/public/`.

This page measures one-shot translation. For what an agent actually pays, convergence under retry and tokens across the whole loop on graphs nothing here was tuned on, see [agent-loop.md](agent-loop.md).
