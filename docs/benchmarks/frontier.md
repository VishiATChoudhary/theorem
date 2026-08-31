# Does the advantage survive a better model?

Every other number in these docs is one small model, Haiku 4.5. The
obvious objection is that theorem is scaffolding for weak models, and
that a frontier model writes Cypher well enough to make a new language
pointless. This is that objection, measured.

## Method

A seeded sample of 498 questions from the CypherBench test set,
stratified by graph and by match category across nba, flight_accident, fictional_character.
Both arms get the prompt they get everywhere else: theorem's shipped
tutorial, and the benchmark's own zero-shot Cypher prompt with its own
schema rendering. Same questions, same comparator, same stores. Zero-shot,
one generation, no retry.

## Result

| Model | theorem | text2cypher | gap |
|---|---:|---:|---:|
| Haiku 4.5 | 84.3% | 75.5% | **+8.8** |
| claude-sonnet-5 | 74.1% | 64.3% | **+9.8** |

Both rows are the same 498 questions, so the comparison is
paired across models as well as across languages.

## Is it real?

On claude-sonnet-5, theorem alone answers 96 of these questions and
text2cypher alone answers 47, so the verdict rests on the
143 they disagree about. Exact McNemar two-sided
**p = 0.0001**, so the difference is significant.

**The gap does not close.** It is as wide on the frontier model as on
the small one, which is the opposite of what the objection predicts.

## The finding nobody was looking for

Both arms score materially *worse* on the frontier model than on the
small one, by about ten points each, on identical questions. The drop
is roughly equal in the two languages, so it is a property of the task
rather than of either language. Why is not established here: the
obvious guess is that a benchmark rewarding terse literal translation
penalises a model that elaborates, but nothing in this run measures
that, and it should be treated as a question rather than an answer.

It is reported here because it is what the data says, and because it
matters for the economics argument elsewhere in these docs. Agent
fleets run small models because they issue thousands of queries. On
this evidence, that is not only the cheaper choice on this task.

Reproduce: `uv run python -m eval.run_frontier gen --model claude-sonnet-5`,
then `exec`, then `report`.

