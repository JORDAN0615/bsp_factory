from __future__ import annotations

from agent.graph import build_repair_graph


# LangGraph local server / Studio entrypoint.
# The CLI still uses agent.graph.run_repair_graph with a per-run SQLite checkpointer.
graph = build_repair_graph()
