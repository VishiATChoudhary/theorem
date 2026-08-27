# X/Twitter thread (8 tweets)

*Attach to tweet 1: the demo GIF. Attach to tweet 4: the spider chart (eval/out/spider.png).*

---

**1/**
LLMs get ~40% of Cypher queries wrong on realistic schemas. Two years of model scaling hasn't moved that number.

So I built theorem: a graph language designed around the failure modes agents actually have.

Same small model. 56% → 96% on multi-hop queries.

Open source today. 🧵

**2/**
The failures are structural, not knowledge gaps:

• reversed arrows: (a)-[:X]->(b) flipped is valid Cypher for the wrong question
• hallucinated labels: your schema was never in the corpus
• implicit grouping: adding a return column silently changes GROUP BY
• long-range brackets

**3/**
theorem removes each one by construction:

find product where launch_year > 2024 as recent
follow recent uses component as parts
follow parts supplied_by source as sups
group by sups as g
count distinct g.parts as n_parts
return sups.name, n_parts order by n_parts desc

No arrows. No nesting. Grouping is its own line.

**4/**
The numbers (CypherBench slice, 60 questions, same model both sides, text2cypher executed live on Neo4j):

theorem + Haiku 4.5: 98.3% overall, 96% multi-hop
text2cypher + Haiku 4.5: 73.3% overall, 56% multi-hop

And Sonnet 5 writing Cypher? No better than Haiku writing Cypher. Scaling is flat. Language design isn't.

**5/**
Every query is verified WHOLE against the live schema before anything runs.

Typo a property name and you get:

error: unknown property "lunch_year" on class product. did you mean: launch_year?
nothing was executed.

The agent repairs and retries. Silent failures become loud ones.

**6/**
The half nobody builds: writes.

Every write returns a receipt with dedup candidates detected at write time. Merge is an explicit dialogue with full lineage. Granularity verbs, temporal retirement, and per-node health you can query:

find nodes where health.loss > 0.8

**7/**
Honest caveats: 60-question slice, one domain, union/optional/edge-property queries excluded (they're the roadmap). v0, single-process engine.

But the signal is strong enough that I'm building it in the open. Apache-2.0, spec-first language evolution, no CLA.

**8/**
It's a pip install:

pip install theorem

Repo, benchmark harness (one command to rerun on any model), 10-min tutorial:
github.com/VishiATChoudhary/theorem

If you're building agents on graphs, I want your failure cases. If you design query languages, I want your objections.
