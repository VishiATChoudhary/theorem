# theorem in an agent loop

CypherBench measures one-shot translation. An agent does not work that way: it writes a query, reads the error or the result, and tries again. What it pays for is whether it converges, how many turns that takes, and how many tokens the whole loop burns.

## Held out by construction

Questions and graphs come from CypherBench's **train** split, whose four graphs (art, biology, soccer, terrorist_attack) share no schema, no question and no qid with the test split every other number in these docs uses. theorem's prompt was written against `nba`, which is not among them. Nothing here was tuned on these graphs.

## Fair by construction

Both arms run the identical loop: same questions, same retry budget (3 turns), same error-feedback mechanics, same comparator, same model. Token accounting covers the whole loop including the prompt on every turn, so theorem's larger tutorial is charged against it rather than hidden.

Graphs: terrorist_attack. Prompt fingerprint `eb0f4010`.

## Results

| Arm | n | solve@1 | solve@2 | solve@3 | Turns when solved | Tokens/question | Exec ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| text2cypher | 120 | 76.7 | 85.8 | **87.5** | 1.14 | 884 | 66.8 |
| theorem | 120 | 77.5 | 84.2 | **87.5** | 1.15 | 2,168 | 3.5 |

### Is the accuracy difference real?

Both arms answer the same questions, so the honest test is the paired one. Of 120 questions, 96 were solved by both and 6 by neither. The verdict rests entirely on the 18 they disagree on: theorem alone solved 9, text2cypher alone solved 9.

McNemar exact two-sided p = 1.000. **The accuracy difference is not statistically significant: on this task the two are tied.** Reading a winner into the point estimates would be reading noise.

What is not in doubt is the cost. theorem executes 19x faster, and costs 2.5x the tokens per question, because a language the model has never seen carries its own tutorial in every prompt while Cypher arrives already known. Both gaps are large enough not to be noise, and the token one is the honest cost of a new language.

At n=120 the 95% interval on either solve rate is about 6 points wide, so this benchmark can only detect large differences. Narrowing it means more questions and more graphs, not more retries.

## Why the token gap, and when it closes

The gap is one thing and it is not the data. Per turn on this graph, theorem spends 1,241 tokens stating its language against roughly 146 for the Cypher prompt's instructions, because Cypher arrives already known and theorem has to be taught in context every time. On the schema theorem is the cheaper of the two: 119 tokens against 333.

That matters because the two costs scale differently. The rules are a fixed cost per turn no matter how big the graph is; the schema grows with it. Measured over merged CypherBench schemas, each additional class costs theorem about 42 tokens and Cypher about 104, so theorem's fixed overhead is repaid at roughly 18 to 20 classes and is pure profit above that.

| Schema | Classes | theorem | text2cypher |
| --- | ---: | ---: | ---: |
| terrorist_attack (this benchmark) | 5 | 1,405 | 476 |
| three graphs merged | 15 | 1,698 | 1,352 |
| four graphs merged | 20 | 1,879 | 1,797 |
| six graphs merged | 28 | 2,266 | 2,771 |
| all eight merged | 39 | 2,837 | 4,001 |

The benchmark graphs have five to eleven classes, which is the region where theorem looks most expensive. A schema of the size this language is built for, a bill of materials or a standards corpus, sits the other side of the crossover. Two caveats: the Cypher figure uses the benchmark's official JSON schema format, and a terser serialisation would push the crossover out; and none of this changes the small-schema result measured above, which is what the table at the top reports.

## Reproducing

```bash
uv run python -m eval.run_agent run --graph terrorist_attack --n 120
uv run python -m eval.run_agent report
```
