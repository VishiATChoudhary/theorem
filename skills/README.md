# Skills

Agent skills that ship with theorem.

## `theorem`

Teaches an agent to build and query a graph with this language: which of
the three APIs to call, how to declare a schema, how to load data, how to
read an error, and what the language does not fix.

It deliberately does **not** restate the language. It tells the agent to
print the shipped tutorial instead, because the published benchmark
numbers belong to that exact text (prompt fingerprint `eb0f4010`). A
paraphrase here would drift from the prompt the numbers describe and
nothing would catch it. `tests/test_skill.py` fails if the fingerprint
moves without the skill being updated.

### Install

For Claude Code, link it into your skills directory:

```bash
mkdir -p ~/.claude/skills
ln -s "$(pwd)/skills/theorem" ~/.claude/skills/theorem
```

Then `/theorem`, or just describe a graph task and it will be picked up.

Other agent runners: point them at `skills/theorem/SKILL.md`.
