# When a query is wrong, does anyone find out?

Execution accuracy counts the queries a model gets right. It says
nothing about the ones it gets wrong, and that is where the two
languages differ most. A Cypher query naming a label that does not
exist is legal Cypher: it matches nothing and returns an empty
result, which is exactly what a question whose true answer is empty
returns. theorem verifies the whole query against the live schema
before running any of it, so the same mistake is refused.

## Method

Start from a query known to be correct, break one token in a way
models actually break queries, run it, and record what the caller
sees. Each arm's own correct query is mutated: theorem's are the
generated queries that scored exactly right, Cypher's are
CypherBench's gold queries. Four mutations, each applied at most
once per query:

| mutation | theorem | Cypher |
|---|---|---|
| class | `find player` becomes `find players` | `:Player` becomes `:Players` |
| edge | `playsFor` becomes `playsFors` | `[:playsFor]` becomes `[:playsFors]` |
| property | `where name =` becomes `where name_x =` | `.name` becomes `.name_x` |
| direction | the arrival role is swapped for the other role | the arrow is reversed |

Outcomes:

- **rejected** &mdash; an error instead of an answer. The caller knows.
- **empty** &mdash; ran, returned nothing. Indistinguishable from a true empty answer.
- **wrong** &mdash; ran, returned rows that are not the right rows.
- **inert** &mdash; the mutation did not change the answer; not counted.

`empty` and `wrong` together are **undetectable**: the caller gets a
result and has no signal that it is not the answer.

## nba

| arm | mutation | mutants | rejected | empty | wrong | warned | undetectable |
|---|---|---:|---:|---:|---:|---:|---:|
| theorem | class | 235 | 235 | 0 | 0 | 0 | 0.0% |
| theorem | direction | 195 | 195 | 0 | 0 | 0 | 0.0% |
| theorem | edge | 195 | 195 | 0 | 0 | 0 | 0.0% |
| theorem | property | 218 | 218 | 0 | 0 | 0 | 0.0% |
| **theorem** | **all** | 843 | 843 | 0 | 0 | 0 | 0.0% |
| text2cypher | class | 262 | 0 | 219 | 43 | 262 | 100.0% |
| text2cypher | direction | 222 | 0 | 183 | 39 | 0 | 100.0% |
| text2cypher | edge | 222 | 0 | 184 | 38 | 222 | 100.0% |
| text2cypher | property | 234 | 0 | 31 | 203 | 234 | 100.0% |
| **text2cypher** | **all** | 940 | 0 | 617 | 323 | 718 | 100.0% |

## fictional_character

| arm | mutation | mutants | rejected | empty | wrong | warned | undetectable |
|---|---|---:|---:|---:|---:|---:|---:|
| theorem | class | 300 | 300 | 0 | 0 | 0 | 0.0% |
| theorem | direction | 238 | 121 | 69 | 48 | 0 | 49.2% |
| theorem | edge | 287 | 287 | 0 | 0 | 0 | 0.0% |
| theorem | property | 260 | 260 | 0 | 0 | 0 | 0.0% |
| **theorem** | **all** | 1085 | 968 | 69 | 48 | 0 | 10.8% |
| text2cypher | class | 282 | 0 | 243 | 39 | 282 | 100.0% |
| text2cypher | direction | 243 | 0 | 170 | 73 | 0 | 100.0% |
| text2cypher | edge | 266 | 0 | 229 | 37 | 266 | 100.0% |
| text2cypher | property | 266 | 0 | 22 | 244 | 266 | 100.0% |
| **text2cypher** | **all** | 1057 | 0 | 664 | 393 | 814 | 100.0% |

## Both graphs

| arm | mutants | rejected | undetectable |
|---|---:|---:|---:|
| theorem | 1928 | 1811 | 6.1% |
| text2cypher | 1997 | 0 | 100.0% |

## What this does and does not show

**The one case theorem does not catch is direction, and only when
both of an edge's roles hold the same class.** `hasFather(subj:
person, obj: person)` is type-correct whichever role you arrive at,
so swapping them is a different question rather than an invalid one,
and no schema check can tell. `nba` has no same-class edge and
theorem catches everything on it; `fictional_character` has five, and
half the direction mutants there survive. Cypher has the same blind
spot and reports none of the other three either.

**Neo4j does notify the driver.** A missing label, relationship type
or property raises a `01N42` notification alongside a successful
result. It is a warning on a call that succeeded, not an error, and
it never fires on a reversed arrow. The `warned` column counts them
so the comparison is not accused of hiding one. Every published
text2cypher pipeline, including CypherBench's own harness, reads the
rows and not the notifications.

**A mutation is not a model.** This measures what a language does
with a broken query, not how often a model breaks one. How often is
the execution-accuracy benchmark, which is a separate page.

Reproduce: `uv run python -m eval.run_silent --graph nba`.

