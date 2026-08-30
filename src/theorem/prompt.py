"""The prompt an agent is given to write theorem.

This is the product, not a benchmark fixture. It lived in `eval/prompts.py`
for as long as the only thing writing theorem was the benchmark, which
meant an application wanting an agent to use the language had to copy the
tutorial out of the harness, and the published numbers described a prompt
users did not have.

The text is versioned by its own hash: the benchmark's frozen query files
are keyed by it, so a run cannot silently score queries generated from a
different tutorial. Editing anything below changes that hash on purpose.
"""

from __future__ import annotations

import hashlib

from .schema import Schema

TUTORIAL = """\
theorem is a line-oriented graph query language. One operation per line,
each binding its result with `as`.

Grammar:
  query   := branch ("or" branch)* (group | agg | compute | keep)* return
  branch  := (find | follow)+
  find    := "find" CLASS ["where" cond] "as" NAME
  follow  := "follow" NAME EDGE ROLE ["upto" (INT|"any")] ["where" cond]
             "as" NAME ["where" cond] ["or" "none"]
  group   := "group" "by" NAME["." PROP] "as" NAME
  agg     := ("count"|"sum"|"avg"|"min"|"max") ["distinct"] COL "as" NAME
  keep    := "keep" NAME "where" cond
  compute := "compute" col ("plus"|"minus"|"times"|"over"|"same") col "as" NAME
  return  := "return" ["distinct"] col ("," col)*
             ["order" "by" col ["desc"]] ["limit" INT]
  cond    := clause (("and"|"or") clause)*   ; and binds tighter, no parens
  clause  := PROP OP literal                 ; OP: = != > >= < <= contains

Traversal
- `follow` names the ROLE you arrive at, never a direction. Roles are in
  the schema below. You cannot arrive at the role your binding occupies.
- Edges between two nodes of the same class use roles `subj` and `obj`.
  `follow c hasFather obj as dad` goes to the father, `subj` to the child.
- `upto N` walks the edge 1..N times, `upto any` until exhausted. Use for
  "transitively", "at any depth", "all the way down".
- `or none` keeps rows that matched nothing, so a per-thing count can come
  out 0. Use whenever some things may have none.
- An edge instance is used once per row, so "other teams in X's division"
  excludes X by itself.
- Reusing an `as` name means THE SAME NODE, which is how you say "both,
  and the same one".

Conditions
- Strings double-quoted, numbers bare. Matching is case- and
  accent-insensitive.
- A property holding several values matches if any one matches.
- `via.<prop>` reads a property of the EDGE, inside a follow's `where`.
- `none` is a missing value: `via.end_year = none` has not ended.
  For "in year Y" repeat the shared part across the or-groups:
  `where via.start_year <= Y and via.end_year >= Y
      or via.start_year <= Y and via.end_year = none`
- Dates are ISO strings: `where date_of_death < "2019"`.
- Use the full entity name as the question states it.

Aggregation
- One step over everything: `count distinct p as n`, `avg p.height_cm as h`.
  Collapses to one row.
- Per group is two steps: `group by p as g` (by identity) or
  `group by p.prop as g` (by value), then `count distinct g.p as n`.
  `g.key` is the key; the grouped binding stays usable in `return`.
- `keep g where n > 3` filters AFTER counting. `keep p where ...` filters
  plain rows.

Return
- Return properties (`t.name`), never bare bindings, and return exactly
  what is asked. A column used only for ordering goes in `order by`.
- Rows are a set: reaching a node twice answers once. `count distinct`
  when a node is reachable by several paths.
- `return distinct` collapses repeated VALUES; plain `return` collapses
  repeated nodes. Two people sharing a name are two rows under `return`,
  one under `return distinct`.
- "Who is taller, X or Y?" wants a name: find both with `or`, then
  `return p.name order by p.height_cm desc limit 1`. `compute` is only for
  a numeric difference or an explicit yes/no.

Examples (player/team/award; playsFor(player,team), receivesAward(player,award)):

Q: Which teams has LeBron James played for?
find player where name = "LeBron James" as p
follow p playsFor team as t
return t.name

Q: For each team founded after 1960, how many distinct players played for it?
find team where inception_year > 1960 as t
follow t playsFor player as p
group by t as g
count distinct g.p as n
return t.name, n

Q: How many players have played for either the Bulls or the Kings?
find team where name = "Chicago Bulls" as t
follow t playsFor player as p
or
find team where name = "Sacramento Kings" as t
follow t playsFor player as p
count distinct p as n
return n

Q: Every team, and how many players it has had, counting teams with none?
find team as t
follow t playsFor player as p or none
group by t as g
count distinct g.p as n
return t.name, n

Q: Which players received both the MVP and the Finals MVP award?
find player as p
follow p receivesAward award where name = "MVP" as mvp
follow p receivesAward award where name = "Finals MVP" as finals
return p.name

Q: Which teams did Robert Reid play for during 1983?
find player where name = "Robert Reid" as p
follow p playsFor team as t where via.start_year <= 1983
  and via.end_year >= 1983
  or via.start_year <= 1983 and via.end_year = none
return t.name

Q: Which awards have more than 20 distinct recipients?
find award as a
follow a receivesAward player as p
group by a as g
count distinct g.p as n
keep g where n > 20
return a.name, n order by n desc

Q: How much taller is Alice Doe than Bob Roe?
find player where name = "Alice Doe" as p1
find player where name = "Bob Roe" as p2
compute p1.height_cm minus p2.height_cm as diff
return diff
"""


def fingerprint() -> str:
    """Short hash of the tutorial, identifying the prompt version."""
    return hashlib.sha1(TUTORIAL.encode()).hexdigest()[:8]


def agent_prompt(schema: Schema, question: str, store=None) -> str:
    """What to send a model that should answer `question` in theorem.

    Passing the store renders only the classes that hold data, which is
    both cheaper and less of an invitation to traverse somewhere nothing
    lives. Leave it out when the agent is going to write as well as read.
    """
    return (
        f"{TUTORIAL}\\n"
        f"Live schema (classes with properties, edges with roles):\\n"
        f"{schema.render(store)}\\n\\n"
        f"Write a single theorem query answering the question.\\n"
        f"Output ONLY the query text, no explanation, no code fences.\\n\\n"
        f"Question: {question}\\n"
    )


def repair_prompt(previous_query: str, error: str) -> str:
    """What to send after a query failed, given the error it produced."""
    return (
        "Your previous query failed.\\n\\n"
        f"Query:\\n{previous_query}\\n\\n"
        f"Error:\\n{error}\\n\\n"
        "Write a corrected query. Output ONLY the query text, no "
        "explanation, no code fences.\\n"
    )
