import os
import tempfile

import pytest

# Banco de auditoria isolado e sem LLM: os testes não dependem de rede nem de .env local.
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/teste.db"
for _var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_AWS_REGION",
             "DEMO_DEFAULT_PERSONA", "API_PUBLIC_URL"):
    os.environ[_var] = ""
os.environ["LLM_PROVIDER"] = "openai"  # um .env com bedrock não pode ligar o LLM real nos testes
os.environ["AUTH_MODE"] = "demo"
os.environ["TRIAGEM_ISOLAR"] = "false"  # o processo isolado tem teste próprio (test_triagem)

from fastapi.testclient import TestClient  # noqa: E402

from app.core.limites import zerar_taxas  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _sem_limite_entre_testes():
    zerar_taxas()


@pytest.fixture
def perguntar(client):
    """Motor do chat (o mesmo de POST /conversations/messages), com a resposta completa:
    rbacBlock, revokedAlert e honestAbstention aparecem como o agente decidiu."""
    from app.core.auth import ANONIMO, Sujeito
    from app.core.personas import PERSONAS
    from app.schemas.api import ChatRequest
    from app.services.agent.router import responder

    def _perguntar(mensagem: str, persona: str | None = "ana", tema: str = "ferias") -> dict:
        p = PERSONAS.get(persona or "")
        sujeito = Sujeito(p, p.nivel) if p else ANONIMO
        resposta = responder(ChatRequest(message=mensagem, tema=tema), sujeito)
        return resposta.model_dump(exclude_none=True)
    return _perguntar
