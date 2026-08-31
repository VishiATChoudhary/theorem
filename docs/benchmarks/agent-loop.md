# theorem in an agent loop

CypherBench measures one-shot translation. An agent does not work that way: it writes a query, reads the error or the result, and tries again. What it pays for is whether it converges, how many turns that takes, and how many tokens the whole loop burns.

## Held out by construction

Questions and graphs come from CypherBench's **train** split, whose four graphs (art, biology, soccer, terrorist_attack) share no schema, no question and no qid with the test split every other number in these docs uses. theorem's prompt was written against `nba`, which is not among them. Nothing here was tuned on these graphs.

## Fair by construction

Both arms run the identical loop: same questions, same retry budget (3 turns), same error-feedback mechanics, same comparator, same model. Token accounting covers the whole loop including the prompt on every turn, so theorem's larger tutorial is charged against it rather than hidden.

Graphs: soccer, terrorist_attack. Prompt fingerprint `eb0f4010`.

## Results

| Arm | n | solve@1 | solve@2 | solve@3 | Turns when solved | Tokens/question | Exec ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| theorem | 240 | 82.9 | 86.7 | **87.9** | 1.07 | 2,064 | 110.5 |
| text2cypher | 240 | 72.1 | 82.1 | **85.0** | 1.19 | 1,068 | 101.7 |

### Is the accuracy difference real?

Both arms answer the same questions, so the honest test is the paired one. Of 240 questions, 183 were solved by both and 8 by neither. The verdict rests entirely on the 49 they disagree on: theorem alone solved 28, text2cypher alone solved 21.

McNemar exact two-sided p = 0.392. **The accuracy difference is not statistically significant: on this task the two are tied.** Reading a winner into the point estimates would be reading noise.

What the tie does not cover is the first attempt. theorem solves 82.9% of these questions without a retry against 72.1%, a gap of 10.8 points that the retries then close, and it converges in 1.07 turns against 1.19. An agent that can retry pays for the difference in turns rather than in answers; one that cannot pays for it in answers.

The token cost is 1.9x per question, because a language the model has never seen carries its own tutorial in every prompt while Cypher arrives already known. That is the honest price of a new language, and the next section is where it stops being one.

Execution time is not a useful comparison on this benchmark. The means are 110 ms and 102 ms, but they are dominated by a handful of wide queries over `soccer`, and theorem runs in-process while Cypher goes over bolt to a container. The CypherBench page has the median, where the difference is real and large.

At n=240 the 95% interval on either solve rate is about 6 points wide, so this benchmark can only detect large differences. Narrowing it means more questions and more graphs, not more retries.

## Why the token gap, and when it closes

The gap is one thing and it is not the data. Per turn on this graph, theorem spends 1,241 tokens stating its language against roughly 146 for the Cypher prompt's instructions, because Cypher arrives already known and theorem has to be taught in context every time. On the schema theorem is the cheaper of the two: 119 tokens against 333.

That matters because the two costs scale differently. The rules are a fixed cost per turn no matter how big the graph is; the schema grows with it. Measured on the seven test schemas and on their union, each additional class costs theorem 39 tokens and text2cypher 85, and the two lines cross at 31 classes. That crossing is inside the measured range rather than past it: on the union, 40 classes, theorem's prompt is the smaller of the two. See [prompt cost](prompt-cost.md) for the method and the table.

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
