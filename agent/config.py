from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = Field(default="http://172.17.5.206:8000/v1", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="EMPTY", alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-oss-120b", alias="LLM_MODEL")
    llm_timeout_sec: int = Field(default=180, alias="LLM_TIMEOUT_SEC")
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
    llm_failure_node_retries: int = Field(default=1, alias="LLM_FAILURE_NODE_RETRIES")
    llm_failure_retry_delay_sec: int = Field(default=60, alias="LLM_FAILURE_RETRY_DELAY_SEC")
    runs_dir: Path = Path("runs")
    skills_dir: Path = Path("skills")
    validation_dir: Path = Path("tests/validation")
    max_selected_skills: int = 3
    max_loops: int = 3
    code_review_enabled: bool = Field(default=True, alias="CODE_REVIEW_ENABLED")
    react_evidence_enabled: bool = Field(default=False, alias="REACT_EVIDENCE_ENABLED")
    patch_agent_agentic: bool = Field(default=False, alias="PATCH_AGENT_AGENTIC")
    deep_agent_enabled: bool = Field(default=True, alias="DEEP_AGENT_ENABLED")
    evidence_recursion_limit: int = Field(default=12, alias="EVIDENCE_RECURSION_LIMIT")
    patch_agent_recursion_limit: int = Field(default=40, alias="PATCH_AGENT_RECURSION_LIMIT")
    deep_agent_recursion_limit: int = Field(default=60, alias="DEEP_AGENT_RECURSION_LIMIT")
    planner_enabled: bool = Field(default=False, alias="PLANNER_ENABLED")
    planner_llm_base_url: str = Field(default="", alias="PLANNER_LLM_BASE_URL")
    planner_llm_api_key: str = Field(default="", alias="PLANNER_LLM_API_KEY")
    planner_llm_model: str = Field(default="", alias="PLANNER_LLM_MODEL")
    planner_llm_timeout_sec: int = Field(default=180, alias="PLANNER_LLM_TIMEOUT_SEC")
    planner_recursion_limit: int = Field(default=40, alias="PLANNER_RECURSION_LIMIT")
    target_build_enabled: bool = Field(default=False, alias="TARGET_BUILD_ENABLED")
    build_entrypoint: str = Field(default="scripts/build_bsp.sh", alias="BUILD_ENTRYPOINT")
    build_timeout_sec: int = Field(default=3600, alias="BUILD_TIMEOUT_SEC")
    build_default_scope: str = Field(default="full", alias="BUILD_DEFAULT_SCOPE")
    mic741_knowledge_enabled: bool = Field(default=False, alias="MIC741_KNOWLEDGE_ENABLED")
    mic741_knowledge_db_url: str = Field(default="", alias="MIC741_KNOWLEDGE_DB_URL")
    mic741_knowledge_source_dir: Path = Field(
        default=Path("RAG_DOCS/MIC-741_KnowledgeBase"),
        alias="MIC741_KNOWLEDGE_SOURCE_DIR",
    )
    mic741_knowledge_query_limit: int = Field(default=10, alias="MIC741_KNOWLEDGE_QUERY_LIMIT")
    mic741_knowledge_hunk_budget_chars: int = Field(
        default=16000,
        alias="MIC741_KNOWLEDGE_HUNK_BUDGET_CHARS",
    )
    mic741_rerank_enabled: bool = Field(default=True, alias="MIC741_RERANK_ENABLED")
    mic741_rerank_top_k: int = Field(default=3, alias="MIC741_RERANK_TOP_K")
    auto_push_enabled: bool = Field(default=False, alias="AUTO_PUSH_ENABLED")
    git_remote: str = Field(default="origin", alias="GIT_REMOTE")
    bsp_base_branch: str = Field(default="", alias="BSP_BASE_BRANCH")
    gitlab_webhook_token: str = Field(default="", alias="GITLAB_WEBHOOK_TOKEN")
    gitlab_token: str = Field(default="", alias="GITLAB_TOKEN")
    gitlab_api_url: str = Field(default="https://gitlab.com/api/v4", alias="GITLAB_API_URL")
    bsp_repo_path: Path = Field(default=Path("."), alias="BSP_REPO_PATH")


def get_settings() -> Settings:
    return Settings()
