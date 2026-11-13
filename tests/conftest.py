import os
import tempfile

import pytest

# Banco de auditoria isolado e sem LLM: os testes não dependem de rede nem de .env local.
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/teste.db"
for _var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "DEMO_DEFAULT_PERSONA"):
    os.environ[_var] = ""
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
    def _perguntar(mensagem: str, persona: str | None = "ana", tema: str = "ferias") -> dict:
        r = client.post("/chat", json={"message": mensagem, "tema": tema, "perfil": "",
                                       "personaId": persona})
        assert r.status_code == 200, r.text
        return r.json()
    return _perguntar
