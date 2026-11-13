"""Configuração central. Tudo vem de variáveis de ambiente (.env); nenhum segredo no código."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    cors_origins: str = "http://localhost:3000"
    # Neon (PostgreSQL); vazio = SQLite local, só testes/offline. Segredos fora do repr.
    database_url: str = Field(default="", repr=False)
    # Base dos links "ver no repositório" gravados no banco para cada arquivo do acervo.
    acervo_repo_url: str = "https://github.com/jvictorgp19-rgb/hacka-back/blob/main"

    auth_mode: Literal["demo", "token"] = "demo"  # valor desconhecido derruba o startup
    auth_token_secret: str = Field(default="", repr=False)
    auth_token_ttl_min: int = 30
    demo_default_persona: str = ""

    llm_base_url: str = ""
    llm_api_key: str = Field(default="", repr=False)
    llm_model: str = ""
    llm_model_large: str = ""
    llm_timeout_s: float = 20
    llm_max_tokens: int = 500
    llm_allow_http: bool = False
    llm_cost_per_1k_brl: float = 0

    max_message_chars: int = 2000
    max_body_bytes: int = 16384
    rate_chat_per_min: int = 30
    rate_reports_per_min: int = 3
    rate_grafo_per_min: int = 30

    # Envio de arquivos (/document-jobs). O front manda um arquivo por requisição.
    max_upload_bytes: int = 20 * 1024 * 1024  # por arquivo, igual ao front
    max_upload_files: int = 10
    rate_upload_per_min: int = 20
    triagem_isolar: bool = True  # parser em processo separado; False só em teste
    triagem_workers: int = 2
    triagem_fila_max: int = 20

    @property
    def origens_cors(self) -> list[str]:
        origens = [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]
        if "*" in origens:
            raise ValueError("CORS_ORIGINS não aceita '*'; informe as origens exatas.")
        return origens


@lru_cache
def get_settings() -> Settings:
    return Settings()
