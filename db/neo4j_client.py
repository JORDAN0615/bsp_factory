"""Neo4j client — schema constraints, ingestion helpers, and graph_hints retrieval.

Graph schema (Component-centric):
  (Machine)-[:USES_BSP]->(BSP)-[:INCLUDES]->(Driver)-[:BELONGS_TO]->(Component)
  (Driver)-[:HAS_ISSUE]->(Error)-[:FIXED_BY]->(Fix)-[:VERIFIED_ON]->(Machine)
  (Component)-[:DEPENDS_ON]->(Component)
"""

from __future__ import annotations

import os
from typing import Any

from rag.models import Chunk

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

_driver = None


def _get_driver():
    global _driver
    if _driver is None:
        from neo4j import GraphDatabase
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _driver


def is_available() -> bool:
    try:
        _get_driver().verify_connectivity()
        return True
    except Exception:
        return False


# ── Schema ────────────────────────────────────────────────────────────────────

def init_schema() -> None:
    """Create uniqueness constraints (idempotent)."""
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Machine)   REQUIRE m.name    IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (b:BSP)       REQUIRE b.version IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Component) REQUIRE c.name    IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Driver)    REQUIRE d.name    IS UNIQUE",
    ]
    with _get_driver().session() as session:
        for cql in constraints:
            session.run(cql)


# ── Ingestion ─────────────────────────────────────────────────────────────────

def ingest_case(
    model: str,
    bsp_version: str,
    driver_name: str,
    component_name: str,
    error_msg: str,
    fix_description: str,
    fix_steps: list[str],
    verified: bool = False,
) -> None:
    """MERGE all nodes and relationships for one BSP case."""
    cql = """
    MERGE (m:Machine  {name: $model})
    MERGE (b:BSP      {version: $bsp_version})
    MERGE (c:Component{name: $component})
    MERGE (d:Driver   {name: $driver})
    MERGE (e:Error    {message: $error_msg})
    MERGE (f:Fix      {description: $fix_description})

    MERGE (m)-[:USES_BSP]->(b)
    MERGE (b)-[:INCLUDES]->(d)
    MERGE (d)-[:BELONGS_TO]->(c)
    MERGE (d)-[:HAS_ISSUE]->(e)
    MERGE (e)-[:FIXED_BY]->(f)

    SET f.steps    = $fix_steps
    SET f.verified = $verified

    WITH m, f
    WHERE $verified
    MERGE (f)-[:VERIFIED_ON]->(m)
    """
    with _get_driver().session() as session:
        session.run(cql, {
            "model": model,
            "bsp_version": bsp_version,
            "driver": driver_name,
            "component": component_name,
            "error_msg": error_msg,
            "fix_description": fix_description,
            "fix_steps": fix_steps,
            "verified": verified,
        })


# ── Retrieval ─────────────────────────────────────────────────────────────────

def query_by_error_keywords(keywords: list[str], limit: int = 15) -> list[Chunk]:
    """Search Error nodes whose message contains any of the given keywords."""
    if not keywords:
        return []
    # Build WHERE clause: any keyword substring match
    conditions = " OR ".join(
        f"toLower(e.message) CONTAINS toLower('{kw.replace(chr(39), '')}')"
        for kw in keywords[:10]
    )
    cql = f"""
    MATCH (e:Error)-[:FIXED_BY]->(f:Fix)
    WHERE {conditions}
    MATCH (d:Driver)-[:HAS_ISSUE]->(e)
    MATCH (d)-[:BELONGS_TO]->(c:Component)
    RETURN
        c.name        AS component,
        d.name        AS driver,
        e.message     AS error_message,
        f.description AS fix_description,
        f.steps       AS fix_steps
    LIMIT $limit
    """
    try:
        with _get_driver().session() as session:
            records = session.run(cql, {"limit": limit})
            return [_record_to_chunk(r.data()) for r in records]
    except Exception as e:
        print(f"[NEO4J] query_by_error_keywords error: {e}")
        return []


def query_by_hints(graph_hints: list[str], limit: int = 15) -> list[Chunk]:
    """
    Given a list of component names, traverse the graph to find related Errors + Fixes.
    Returns serialised Chunk objects suitable for the Reranker.
    """
    if not graph_hints:
        return []

    cql = """
    MATCH (c:Component)
    WHERE c.name IN $hints
    MATCH (d:Driver)-[:BELONGS_TO]->(c)
    MATCH (d)-[:HAS_ISSUE]->(e:Error)-[:FIXED_BY]->(f:Fix)
    RETURN
        c.name  AS component,
        d.name  AS driver,
        e.message  AS error_message,
        f.description AS fix_description,
        f.steps       AS fix_steps
    LIMIT $limit
    """
    try:
        with _get_driver().session() as session:
            records = session.run(cql, {"hints": graph_hints, "limit": limit})
            return [_record_to_chunk(r.data()) for r in records]
    except Exception as e:
        print(f"[NEO4J] query_by_hints error: {e}")
        return []


def _record_to_chunk(rec: dict) -> Chunk:
    """Serialize a Neo4j record to a text Chunk for the Reranker."""
    steps_text = ""
    steps = rec.get("fix_steps") or []
    if steps:
        steps_text = " → ".join(str(s) for s in steps)

    text = (
        f"Component: {rec.get('component', '')} | Driver: {rec.get('driver', '')}\n"
        f"Error: {rec.get('error_message', '')}\n"
        f"Fix: {rec.get('fix_description', '')}"
    )
    if steps_text:
        text += f"\nSteps: {steps_text}"

    import hashlib
    chunk_id = "neo4j_" + hashlib.md5(text.encode()).hexdigest()[:12]
    return Chunk(
        id=chunk_id,
        text=text,
        source="neo4j",
        section=rec.get("component", ""),
    )
