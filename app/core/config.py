from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações carregadas exclusivamente por variáveis de ambiente."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "VOLTA API"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: SecretStr | None = None
    groq_router_model: str = "llama-3.3-70b-versatile"

    postgres_dsn: SecretStr = SecretStr("postgresql://volta:volta@localhost:5432/volta")
    mongo_uri: SecretStr = SecretStr("mongodb://localhost:27017/volta_memory?replicaSet=rs0")

    rag_base_path: str = "./data/faiss"
    source_download_timeout_seconds: int = 20
    allowed_source_hosts: set[str] = {"sdgs.un.org", "www.gov.br", "jbsesg.com", "ambientaljbs.com.br"}

    cooperative_a2a_base_url: HttpUrl | None = None
    cooperative_a2a_hmac_secret: SecretStr | None = None
    a2a_timeout_seconds: int = 10
    ingestion_api_key: SecretStr | None = None

    # Estimativas configuráveis, para o painel acadêmico de custo/ROI.
    gemini_input_usd_per_million: float = 0.30
    gemini_output_usd_per_million: float = 2.50
    groq_input_usd_per_million: float = 0.59
    groq_output_usd_per_million: float = 0.79
    value_per_resolved_case_brl: float = 35.0

    @property
    def postgres_url(self) -> str:
        return self.postgres_dsn.get_secret_value()

    @property
    def mongodb_url(self) -> str:
        return self.mongo_uri.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
