# r/MachineLearning

*Text post, [P] tag. Angle: benchmark and eval methodology. This sub hates marketing; keep it a research writeup.*

## Title

[P] Language design beats model scaling for text-to-graph-query: 56% → 96% multi-hop EX with the same 
small model (CypherBench slice, harness included)

## Body

**Claim being tested:** LLM graph-query generation accuracy is corpus-limited, not capacity-limited, so redesigning the target language should outperform scaling the model.

**Background:** CypherBench (arXiv 2412.18702) put Claude 3.5 Sonnet at 61.6% EX, GPT-4o at 60.2%. Text2GraphQuery-Bench (arXiv 2602.11745, Feb 2026) shows frontier models two generations later at 51-58% EX, 19-44% on hard tiers, and a fine-tuned 8B matching frontier zero-shot, which points at corpus familiarity rather than capacity. GQL (cleaner language, smaller corpus) benchmarks worse than Cypher, same signal.

**Intervention:** a purpose-built graph language (theorem) that makes the dominant error classes unrepresentable: role-named traversal instead of direction glyphs, mandatory staged aggregation, schema-closed vocabulary with whole-program verification before execution, canonical single spelling per operation. Verification errors are corrective (line number, did-you-mean, "nothing was executed") so the single repair retry is well-targeted.

**Setup:** CypherBench NBA slice, 60 questions stratified over expressible categories (union, optional-match, edge-property questions excluded; the language can't express them yet). Both conditions: same model, same one-retry repair budget. Baseline executes generated Cypher live on Neo4j against gold answers; theorem executes on its own engine over the same graph loaded from CypherBench JSON. Metric: execution accuracy, set comparison, order-sensitive only for explicit order-by questions.

**Results:**

| Condition | Overall EX | Multi-hop | 1-hop | Syntax valid |
|---|---|---|---|---|
| theorem + Haiku 4.5 | 98.3 | 96.0 | 100 | 100 |
| text2cypher + Haiku 4.5 | 73.3 | 56.0 | 85.7 | 98.3 |
| theorem + Sonnet 5 | 95.0 | 92.0 | 97.1 | 100 |
| text2cypher + Sonnet 5 | 71.7 | 60.0 | 80.0 | 96.7 |

The within-experiment scaling control is the part I find most interesting: Sonnet 5 → Haiku 4.5 on text2cypher is flat (71.7 vs 73.3), while the language switch moves both models 20+ points overall, 30+ multi-hop.

**Limitations:** n=60, one domain graph, category exclusions favor the new language by construction (excluded categories are ones it can't do at all; reported numbers are over the expressible set for both conditions), token-count heuristic is len/4, engine is single-process Python. Three language changes (global aggregates, trail semantics, a compute verb) came out of eval failures, so the language partially fit the benchmark distribution; the spec documents each.

**Repro:** `uv run python -m eval.run_eval --n 60` in the repo (needs a claude CLI key; docker for the Neo4j baseline). I'd particularly value runs on non-Anthropic models; the harness prompt is model-agnostic.

Repo: github.com/VishiATChoudhary/theorem (Apache-2.0; technical report with the full scaling argument in docs/)
