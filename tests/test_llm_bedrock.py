"""Provedor Amazon Bedrock do LLM (app/services/llm/client.py). Sem rede: cliente boto3 falso."""
import pytest

from app.core.config import Settings
from app.services.llm.client import ClienteLLM

MODELO = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def _cfg(**extra) -> Settings:
    base = {"llm_provider": "bedrock", "llm_model": MODELO, "llm_aws_region": "us-east-1"}
    return Settings(_env_file=None, **{**base, **extra})


class _BedrockFalso:
    def __init__(self, resposta=None, erro: Exception | None = None) -> None:
        self.resposta, self.erro, self.chamadas = resposta, erro, []

    def converse(self, **kwargs):
        self.chamadas.append(kwargs)
        if self.erro:
            raise self.erro
        return self.resposta


def _com_falso(falso: _BedrockFalso, **extra) -> ClienteLLM:
    cliente = ClienteLLM(_cfg(**extra))
    cliente._bedrock = falso  # troca o transporte; o resto do cliente é o de produção
    return cliente


def _ok(texto: str, tokens: int = 42) -> dict:
    return {"output": {"message": {"role": "assistant", "content": [{"text": texto}]}},
            "usage": {"totalTokens": tokens}}


def test_bedrock_desligado_sem_modelo():
    cliente = ClienteLLM(_cfg(llm_model=""))
    assert not cliente.ligado
    assert cliente.completar("sistema", "pergunta") is None


def test_bedrock_liga_com_modelo_e_regiao():
    assert ClienteLLM(_cfg()).ligado  # só cria o cliente; nenhuma chamada de rede


def test_bedrock_envia_sistema_e_pergunta_separados_e_devolve_texto():
    falso = _BedrockFalso(_ok("Resposta [1]", 99))
    r = _com_falso(falso).completar("REGRAS", "TRECHOS e PERGUNTA")
    assert r is not None and r.texto == "Resposta [1]" and r.tokens == 99
    envio = falso.chamadas[0]
    assert envio["modelId"] == MODELO
    assert envio["system"] == [{"text": "REGRAS"}]
    assert envio["messages"] == [{"role": "user", "content": [{"text": "TRECHOS e PERGUNTA"}]}]
    assert envio["inferenceConfig"]["temperature"] == 0
    assert 0 < envio["inferenceConfig"]["maxTokens"] <= 2000  # nunca deixa o teto do modelo


def test_bedrock_usa_modelo_grande_quando_pedido():
    falso = _BedrockFalso(_ok("ok"))
    cliente = _com_falso(falso, llm_model_large="us.anthropic.claude-sonnet-5")
    cliente.completar("s", "u", grande=True)
    assert falso.chamadas[0]["modelId"] == "us.anthropic.claude-sonnet-5"


def test_bedrock_junta_blocos_de_texto():
    resposta = {"output": {"message": {"content": [{"text": "Parte 1. "}, {"text": "Parte 2."}]}},
                "usage": {"totalTokens": 7}}
    r = _com_falso(_BedrockFalso(resposta)).completar("s", "u")
    assert r is not None and r.texto == "Parte 1. Parte 2."


def test_bedrock_resposta_vazia_vira_none():
    assert _com_falso(_BedrockFalso(_ok("   "))).completar("s", "u") is None


@pytest.mark.parametrize("erro", [RuntimeError("cota"), TimeoutError("lento"),
                                  PermissionError("AccessDenied")])
def test_bedrock_qualquer_falha_vira_none_e_chat_cai_no_extrativo(erro):
    assert _com_falso(_BedrockFalso(erro=erro)).completar("s", "u") is None


def test_rotulo_de_custo_nomeia_o_provedor(perguntar, monkeypatch):
    from app.services.agent import router as agente
    from app.services.llm.client import RespostaLLM

    class _Falso:
        ligado = True

        def completar(self, sistema, usuario, grande=False):
            return RespostaLLM("O empregado pode converter até 10 dias em abono [1].", 500)

    monkeypatch.setattr(agente, "get_llm", lambda: _Falso())
    monkeypatch.setattr(agente, "get_settings", lambda: _cfg(llm_cost_per_1k_brl=0.02))
    d = perguntar("Posso converter férias em abono pecuniário?")
    assert d["costBadge"]["type"] == "rag_llm"
    assert "Amazon Bedrock" in d["costBadge"]["label"] and "0,0100" in d["costBadge"]["label"]
