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
    runs_dir: Path = Path("runs")
    skills_dir: Path = Path("skills")
    validation_dir: Path = Path("tests/validation")
    max_selected_skills: int = 3
    max_loops: int = 3
    code_review_enabled: bool = Field(default=True, alias="CODE_REVIEW_ENABLED")
    auto_push_enabled: bool = Field(default=False, alias="AUTO_PUSH_ENABLED")
    git_remote: str = Field(default="origin", alias="GIT_REMOTE")


def get_settings() -> Settings:
    return Settings()
