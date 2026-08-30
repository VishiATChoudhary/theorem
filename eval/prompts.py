"""Prompt builders for both eval conditions.

Condition A: text2cypher, matching CypherBench's zero-shot setup (schema
in their JSON format plus the question).
Condition B: theorem, using the prompt the package ships. It used to live
here, which meant the benchmark measured a prompt no user had; it is now
`theorem.prompt` and this module re-exports it so the harness and the
product cannot drift apart.
Both prompts demand raw query text only, no markdown fences.
"""

from __future__ import annotations

import json

from theorem.prompt import TUTORIAL as GRAPHLANG_TUTORIAL
from theorem.prompt import agent_prompt as theorem_prompt
from theorem.prompt import repair_prompt

__all__ = ["GRAPHLANG_TUTORIAL", "cypher_prompt", "repair_prompt", "theorem_prompt"]


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
