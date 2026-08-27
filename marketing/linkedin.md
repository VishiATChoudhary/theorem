# LinkedIn founder post

*Attach: spider chart image. Post from personal account.*

---

I open-sourced a programming language this week. Here's why a language, of all things.

For two years, the entire industry has been waiting for better models to fix LLM database access. The benchmark record now says clearly: they won't. Frontier models score 51-58% execution accuracy generating Cypher for graph databases. That's roughly where models two generations older scored. On hard queries it drops below 45%. Scaling is flat on this task.

The reason is structural. Query-language accuracy tracks training-corpus familiarity, not model capacity. A fine-tuned 8B model beats frontier models at this. And even a model that memorized every public Cypher query has never seen YOUR schema, because production schemas are not in any corpus.

So instead of waiting for models to get better at a language built for humans in 2011, I designed a language for the failure modes agents actually have, and it went open source this week: theorem.

The result that matters: with theorem, a small, cheap model (Claude Haiku) reaches 98.3% execution accuracy where the same model writing Cypher reaches 73.3%. On multi-hop queries: 96% vs 56%.

Read that again from a unit-economics angle. Agent fleets run on small models because they issue thousands of queries a day. A language that makes the cheap model reliable beats a frontier model that stays unreliable, at a fraction of the cost.

Three design decisions did most of the work:
- Edges traverse by named role, not by direction arrows. There is nothing to reverse.
- Every query is verified whole against the live schema before anything executes. Errors name the line, suggest the fix, and guarantee nothing ran.
- Aggregation is explicitly staged. Adding an output column can never silently change the grouping.

theorem is Apache-2.0, community-governed, spec-first: language changes are argued as proposals before syntax lands. The benchmark harness reruns on any model with one command, and I'd genuinely like to see it run on models I don't have access to.

Repo: github.com/VishiATChoudhary/theorem

If your team is building agents over knowledge graphs and hitting the reliability wall, the tutorial takes ten minutes. And if you think I'm wrong that scaling won't fix this, the strongest counterargument I know is in the docs under "Why not Cypher?", steelmanned as best I could before I answer it.
