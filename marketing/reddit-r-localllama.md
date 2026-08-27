# r/LocalLLaMA

*Text post. Angle: small models win with the right target language. This crowd cares about running cheap/local.*

## Title

The query language matters more than the model: Haiku 4.5 hits 98.3% on graph queries where frontier models writing Cypher sit at ~52-72%

## Body

Interesting result from a benchmark I ran while building an agent-first graph query language, relevant here because it's about making SMALL models reliable instead of paying for frontier ones.

Setup: CypherBench slice (60 questions, stratified by hops), execution accuracy against gold answers, one repair retry per question, baseline Cypher executed live on Neo4j.

- Haiku 4.5 writing Cypher: 73.3% overall, 56% multi-hop
- Sonnet 5 writing Cypher: 71.7% overall, 60% multi-hop (yes, the bigger model is not better)
- Published numbers for Opus 4.8 / GPT-5.5 on the newest text2graph benchmark: 51-58%, dropping to 19-44% on hard queries
- Haiku 4.5 writing theorem (the new language): **98.3% overall, 96% multi-hop**

The mechanism is boring and that's the point: the language has no direction arrows to reverse (edges traverse by named role), no implicit grouping, and the whole query is verified against the live schema before execution, with did-you-mean errors the model can act on in its retry. Most of what kills small models on Cypher is notation, not reasoning.

Why this might matter for local setups: if the pattern holds, a 7-8B local model with a schema-verified language should beat API frontier models writing Cypher, at zero marginal cost. The fine-tuning literature already hints at this (a fine-tuned 8B matches frontier zero-shot on graph query gen). I haven't run local models through the harness yet; it's one command (`uv run python -m eval.run_eval`) and the prompting is plain text, so if anyone wants to try Llama/Qwen/Mistral variants I'd love to see numbers. The harness currently shells out to the claude CLI, so wiring in a local endpoint is a small patch (good first issue in the repo).

Caveats: 60 questions, one domain, some Cypher query categories excluded because v0 can't express them yet, engine is a single-process Python thing not a production DB.

Repo (Apache-2.0): github.com/VishiATChoudhary/theorem
