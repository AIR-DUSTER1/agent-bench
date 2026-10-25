"""应用配置：所有可调参数集中于 .env / 环境变量，密钥不落代码。"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Agent-Bench"
    # 数据库：默认 SQLite 零配置；改 DATABASE_URL 即可切 MySQL（mysql+pymysql://user:pwd@host/db）
    DATABASE_URL: str = f"sqlite:///{(DATA_DIR / 'agent_bench.db').as_posix()}"

    # 被测内置 Agent 使用的 LLM（OpenAI 兼容）
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-chat"
    LLM_TEMPERATURE: float = 0.0

    # Judge 评分模型（可与被测模型不同，避免自我偏好）；缺省回落到 LLM_*
    JUDGE_BASE_URL: str = ""
    JUDGE_API_KEY: str = ""
    JUDGE_MODEL: str = ""

    # 评测流水线
    EXEC_CONCURRENCY: int = 4
    JUDGE_CONCURRENCY: int = 4
    PASS_THRESHOLD: int = 3          # 各维度得分 >= 该值视为通过（0-5 分制）
    AGENT_TIMEOUT_SECONDS: int = 300  # 单样本 Agent 执行超时
    JUDGE_MAX_RETRIES: int = 2       # Judge 结构化输出解析失败重试次数

    # Langfuse（可选；未配置时自动降级为本地 JSON Trace）
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    @property
    def judge_base_url(self) -> str:
        return self.JUDGE_BASE_URL or self.LLM_BASE_URL

    @property
    def judge_api_key(self) -> str:
        return self.JUDGE_API_KEY or self.LLM_API_KEY

    @property
    def judge_model(self) -> str:
        return self.JUDGE_MODEL or self.LLM_MODEL

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.LANGFUSE_PUBLIC_KEY and self.LANGFUSE_SECRET_KEY)

    @property
    def trace_dir(self) -> Path:
        return DATA_DIR / "traces"

    @property
    def report_dir(self) -> Path:
        return DATA_DIR / "reports"


settings = Settings()
for _d in (DATA_DIR, settings.trace_dir, settings.report_dir):
    _d.mkdir(parents=True, exist_ok=True)
