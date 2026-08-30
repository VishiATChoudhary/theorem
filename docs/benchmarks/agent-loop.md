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
| theorem | 120 | 75.8 | 85.8 | **89.2** | 1.19 | 2,220 | 3.0 |
| text2cypher | 120 | 76.7 | 85.8 | **87.5** | 1.14 | 884 | 66.8 |

theorem converges higher (89.2% against 87.5%) and executes 22x faster, and costs 2.5x the tokens per question, because a language the model has never seen has to carry its own tutorial in every prompt while Cypher arrives already known. That gap is the honest cost of a new language and the thing to keep shrinking.

## Reproducing

```bash
uv run python -m eval.run_agent run --graph terrorist_attack --n 120
uv run python -m eval.run_agent report
```
