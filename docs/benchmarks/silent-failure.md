# What happens to a broken query

!!! warning "This is not a benchmark. Read this first."

    The headline anyone would want to pull from this page, *theorem refuses
    1,811 of 1,928 broken queries and Cypher refuses none of 1,997*, is
    **not a finding**. It is the design difference restated as a number.

    theorem checks a whole query against the live schema before executing
    any of it. Cypher has no such step. So a Cypher query naming a label
    that does not exist runs and returns nothing, and a theorem query
    naming a class that does not exist is refused. That is true by
    construction, and running 3,925 mutants to observe it taught nobody
    anything they could not have read off the two language definitions.

    The mutations are also **ours**. We chose four ways to break a query
    and applied them uniformly. We did not sample how models actually
    break queries, so the mix is a guess, and a different mix moves every
    number on this page. A comparison whose result is fixed by definition
    and whose inputs we picked is an argument, not evidence.

    What is worth reading here is the **other** column: what theorem does
    to theorem. That part is a self-audit, it was not guaranteed by the
    design, and it found a real blind spot.

## Why the page still exists

Two reasons.

The first is the blind spot. Verification catches a wrong class, a wrong
edge, a wrong property, and a wrong role, and we assumed for a long time
that it caught wrong direction too. It does not. **6.1% of our own broken
queries run and return an answer**, and every one of them is the same
case: an edge whose two roles hold the same class. `hasFather(subj:
person, obj: person)` is type-correct whichever role you arrive at, so
swapping them asks a different question rather than an invalid one, and
no schema check can tell. `nba` has no same-class edge and theorem
catches everything on it. `fictional_character` has five, and half the
direction mutants there survive.

That number is the honest ceiling on the "can't get wrong" claim, and it
is why [role naming as a checkable property](https://github.com/VishiATChoudhary/theorem/blob/main/ROADMAP.md)
is an open roadmap item rather than a solved one.

The second is that people ask what Neo4j does, and the answer deserves
to be written down accurately rather than argued from. It does notify:
a missing label, relationship type or property raises an `01N42`
notification alongside a successful result. It is a warning on a call
that succeeded, not an error, and it never fires on a reversed arrow.
The `warned` column below counts them so this page cannot be accused of
hiding one. Published text2cypher pipelines, including CypherBench's own
harness, read the rows and not the notifications, which is a fact about
those pipelines and not about Cypher.

## Method

Start from a query known to be correct, break one token, run it, record
what the caller sees. Each arm's own correct queries are mutated:
theorem's are the generated queries that scored exactly right, Cypher's
are CypherBench's gold queries. Four mutations, each applied at most once
per query:

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

The theorem row is the one to read. The text2cypher row is what "no
verification step" looks like when you write it as a percentage.

## What this does not show

**A mutation is not a model.** This measures what a language does with a
broken query, never how often a model breaks one. How often is
[execution accuracy](cypherbench.md), which is a real benchmark with a
real comparator, and it is where the case for this language should be
argued.

**Refusing a broken query is not the same as answering a question.** A
language that refused everything would score 0% undetectable here. The
number is only meaningful next to an accuracy figure, and it should
never be quoted alone.

Reproduce: `uv run python -m eval.run_silent --graph nba`.
