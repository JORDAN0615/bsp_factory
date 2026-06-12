# Use the Specified Working Tree for MVP Repairs

The MVP agent applies patches directly to the clean BSP source working tree passed by the user instead of creating its own branch or Git worktree. This keeps human review, commit, publish, build, and flash workflows in the repository people already use, while the clean-source requirement keeps patch review and reject rollback unambiguous.

**Considered Options**

- Create an agent branch for each run.
- Create an isolated Git worktree under the run artifacts.
- Apply patches directly to the specified working tree.

**Consequences**

The MVP agent must refuse dirty source by default and must not commit or push. A later version can introduce agent-managed branches or worktrees when publish automation becomes part of the agent boundary.
