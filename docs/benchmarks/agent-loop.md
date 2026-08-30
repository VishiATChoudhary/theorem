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

## Reproducing

```bash
uv run python -m eval.run_agent run --graph terrorist_attack --n 120
uv run python -m eval.run_agent report
```
