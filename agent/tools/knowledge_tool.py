from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.tools import tool

if TYPE_CHECKING:
    from agent.config import Settings


def build_bsp_knowledge_tool(settings: "Settings"):
    """Build the shared case/document/pinmux retrieval tool for both agents.

    Results are memoised per built tool — i.e. per agent run. An observed run
    issued the identical query twice and paid 73k characters of context for the
    second copy, which contributed nothing but pushed the answer further from
    the model's attention.
    """
    cache: dict[str, str] = {}

    @tool
    def search_bsp_knowledge(query: str) -> str:
        """Search BSP knowledge for past MIC-741 repairs, Git patch excerpts,
        vendor design guides, datasheets, and pinmux records relevant to `query`.
        Reformulate and call again as concrete files, symbols, or interfaces emerge."""
        cleaned = query.strip()
        if not cleaned:
            return "(BSP knowledge query is empty)"
        if not settings.mic741_knowledge_enabled and not settings.doc_retrieval_enabled:
            return "(BSP knowledge retrieval is disabled)"

        cache_key = " ".join(cleaned.lower().split())
        if cache_key in cache:
            return cache[cache_key]

        from agent.tools.mic741_knowledge import KnowledgeDBError

        try:
            if settings.mic741_knowledge_enabled and settings.doc_retrieval_enabled:
                from agent.tools.doc_knowledge import query_all_knowledge

                result = query_all_knowledge(cleaned, [], settings)
            elif settings.doc_retrieval_enabled:
                from agent.tools.doc_knowledge import query_doc_knowledge

                result = query_doc_knowledge(cleaned, [], settings)
            else:
                from agent.tools.mic741_knowledge import query_mic741_knowledge

                result = query_mic741_knowledge(cleaned, [], settings, subsystem=None)
        except KnowledgeDBError as exc:
            # Not cached: a transient DB failure should not poison the run.
            return f"(BSP knowledge unavailable: {exc})"
        rendered = result or "(no matching BSP knowledge)"
        cache[cache_key] = rendered
        return rendered

    return search_bsp_knowledge
