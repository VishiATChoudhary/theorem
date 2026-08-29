"""Prompt builders for both eval conditions.

Condition A: text2cypher, matching CypherBench's zero-shot setup (schema
in their JSON format plus the question).
Condition B: theorem grammar prompting (compact grammar, worked
examples, live schema render).
Both prompts demand raw query text only, no markdown fences.
"""

from __future__ import annotations

import json

from theorem.schema import Schema

GRAPHLANG_TUTORIAL = """\
You write queries in theorem, a line-oriented graph query language.

Rules:
- One operation per line. Every line binds its result to a name with `as`.
- `find <class> [where <cond>] as <name>` seeds the working set.
- `follow <binding> <edge_type> <arrival_role> [where <cond>] as <name>`
  walks an edge type. You name the ROLE you arrive at, never a direction.
  The role names and their classes are listed in the schema below.
  You cannot arrive at the role your binding already occupies.
- Conditions: `prop = value`, `!=`, `>`, `>=`, `<`, `<=`,
  `prop contains "text"`, joined with `and` / `or` (and binds tighter).
  Strings in double quotes. Numbers bare.
- Aggregation over the whole result is one step:
  `count distinct <binding> as <name>`, or over a property
  `avg <binding>.<prop> as <name>` (also sum/min/max). It collapses
  the result to a single row.
- Per-group aggregation is two explicit steps:
  `group by <binding> as <g>` groups by node identity;
  `group by <binding>.<prop> as <g>` groups by a property value.
  Then `count [distinct] <g>.<column> as <name>` (also sum/avg/min/max,
  e.g. `avg g.p.height_cm as h`). The grouped binding stays available
  in `return`; `<g>.key` is the group key value.
- The same edge instance is never used twice in one result row, so
  "other teams in the same division as X" naturally excludes X.
- REUSING A NAME MEANS THE SAME NODE. Give two steps the same `as` name
  and only rows where they land on the same node survive. That is how you
  say "both ... and the same one":
    find flightaccident as f
    follow f departsFrom airport as a
    follow f destinedFor airport as a
  keeps only accidents whose departure and destination airport are one
  and the same. Use different names when you mean different nodes.
- A LINE CONTAINING ONLY `or` STARTS AN ALTERNATIVE BRANCH. Everything
  after it is a separate way of reaching the answer, and the results are
  combined. Use it for "either ... or ...":
    find team where name = "Chicago Bulls" as t
    follow t playsFor player as p
    or
    find team where name = "Sacramento Kings" as t
    follow t playsFor player as p
    count distinct p as n
    return n
  Give the branches the same names for the things you want combined.
  `group`, the aggregates and `return` all see the combined result.
- `where` may come before or after `as`; both read the same.
- Scalar math and equality between two bound values:
  `compute <col> plus|minus|times|over|same <col> as <name>`.
  `same` yields true/false. Use for "how much taller", "do X and Y share".
- String matching (`=`, `contains`) is case- and accent-insensitive.
- RETURN DISCIPLINE: return exactly the values the question asks for,
  nothing extra. A column used only for ordering goes in `order by`,
  not in `return`. "Which X is biggest?" returns only the name:
  `return t.name order by t.inception_year limit 1`.
- "Who is taller / heavier / died later, X or Y?" asks for a NAME:
  find both with `or`, then `return p.name order by p.<prop> desc limit 1`.
  Use `compute` only when the question asks for the numeric difference
  or an explicit yes/no.
- Entity names: use the FULL name as stated in the question
  ("Southeast Division", not "Southeast").
- Date properties are ISO strings: compare with quoted strings,
  e.g. `where date_of_death < "2019"`.
- `return <col>, ... [order by <col> [desc]] [limit N]` ends the query.
  Return properties (like `t.name`), never bare bindings.
- Results are sets: duplicates do not matter, except counts must be exact,
  so use `count distinct` when the same node can be reached twice.

- Results are a set of rows: reaching the same node twice answers once.
  For a count, use `count distinct` when the same node can be reached by
  more than one path.
- Some edges join two nodes of the SAME class (hasSpouse between two
  characters, subsidiaryOf between two companies). Their roles are named
  `subj` and `obj`, not the class name, because the class cannot tell the
  two ends apart. `follow c hasFather obj as dad` goes from a character
  to their father; `follow c hasFather subj as kid` goes the other way.
  When the relation reads both ways, use `or` to take both.

Grammar (EBNF):
  query   := branch ("or" branch)* (group | agg | compute)* return
  branch  := (find | follow)+
  find    := "find" CLASS ["where" cond] "as" NAME
  follow  := "follow" NAME EDGE ROLE ["where" cond] "as" NAME
            ; where comes BEFORE as: follow p playsFor team where name = "X" as t
  group   := "group" "by" NAME["." PROP] "as" NAME
  agg     := ("count"|"sum"|"avg"|"min"|"max") ["distinct"] NAME "." COL ["." PROP] "as" NAME
  compute := "compute" col ("plus"|"minus"|"times"|"over"|"same") col "as" NAME
  return  := "return" col ("," col)* ["order" "by" col ["desc"]] ["limit" INT]
  cond    := clause (("and"|"or") clause)*
  clause  := PROP OP literal ; OP: = != > >= < <= contains

Worked examples (schema: player/team/award, edges playsFor(player, team),
receivesAward(player, award)):

Q: Which teams has LeBron James played for?
find player where name = "LeBron James" as p
follow p playsFor team as t
return t.name

Q: How many distinct players have played for the Lakers?
find team where name = "Los Angeles Lakers" as t
follow t playsFor player as p
group by t as g
count distinct g.p as n
return n

Q: For each team founded after 1960, how many distinct players played for it?
find team where inception_year > 1960 as t
follow t playsFor player as p
group by t as g
count distinct g.p as n
return t.name, n

Q: Which players taller than 210 cm received an award?
find player where height_cm > 210 as p
follow p receivesAward award as a
return p.name

Q: What is the average height of players who played for the Bulls?
find team where name = "Chicago Bulls" as t
follow t playsFor player as p
group by t as g
avg distinct g.p.height_cm as h
return h

Q: Which award has the most distinct recipients?
find award as a
follow a receivesAward player as p
group by a as g
count distinct g.p as n
return a.name, n order by n desc limit 1

Q: How much taller is Alice Doe than Bob Roe in centimeters?
find player where name = "Alice Doe" as p1
find player where name = "Bob Roe" as p2
compute p1.height_cm minus p2.height_cm as diff
return diff

Q: Do Alice Doe and Bob Roe have the same handedness?
find player where name = "Alice Doe" as p1
find player where name = "Bob Roe" as p2
compute p1.handedness same p2.handedness as answer
return answer

Q: Which players played for teams that LeBron James also played for?
find player where name = "LeBron James" as lj
follow lj playsFor team as t
follow t playsFor player as others
return others.name

Q: How many players have played for either the Bulls or the Kings?
find team where name = "Chicago Bulls" as t
follow t playsFor player as p
or
find team where name = "Sacramento Kings" as t
follow t playsFor player as p
count distinct p as n
return n

Q: Which players received both the MVP award and the Finals MVP award?
find player as p
follow p receivesAward award where name = "MVP" as mvp
follow p receivesAward award where name = "Finals MVP" as finals
return p.name

Q: Which players played for a team whose head coach they also played
   under at another team? (same node reached two ways)
find player as p
follow p playsFor team as t
follow p coachedBy team as t
return p.name
"""


def theorem_prompt(schema: Schema, question: str) -> str:
    return (
        f"{GRAPHLANG_TUTORIAL}\n"
        f"Live schema (classes with properties, edges with roles):\n"
        f"{schema.render()}\n\n"
        f"Write a single theorem query answering the question.\n"
        f"Output ONLY the query text, no explanation, no code fences.\n\n"
        f"Question: {question}\n"
    )


def cypher_prompt(cb_schema: dict, question: str) -> str:
    return (
        "You are an expert in writing Cypher queries for Neo4j.\n"
        "Given the graph schema below (entities with properties, and "
        "relations as (subject)-[relation]->(object)), write a Cypher "
        "query answering the question.\n"
        "Output ONLY the Cypher query, no explanation, no code fences.\n\n"
        f"Schema:\n{json.dumps(cb_schema, indent=1)}\n\n"
        f"Question: {question}\n"
    )


def repair_prompt(previous_query: str, error: str) -> str:
    return (
        "Your previous query failed.\n\n"
        f"Query:\n{previous_query}\n\n"
        f"Error:\n{error}\n\n"
        "Write a corrected query. Output ONLY the query text, no "
        "explanation, no code fences.\n"
    )
