"""Cliente do LLM do chat. Dois provedores, escolhidos por LLM_PROVIDER no .env:

- ``openai``  -> servidor compatível com a API da OpenAI (vLLM, Ollama, LM Studio...).
                 Preencha LLM_BASE_URL, LLM_API_KEY e LLM_MODEL.
- ``bedrock`` -> Amazon Bedrock, pela Converse API. Preencha LLM_MODEL (id do modelo ou do perfil
                 de inferência) e, se preciso, LLM_AWS_REGION. Sem chave no .env: a autenticação
                 vem da role da instância (cadeia padrão de credenciais da AWS).
Sem configuração o cliente fica desligado e o chat responde com calculadoras e trechos citados.

Segurança:
- URL, região e modelo vêm só do .env do operador; nunca de body, query, PDF ou do próprio modelo.
- OpenAI-compatible: HTTPS obrigatório, exceto localhost (túnel SSH) ou LLM_ALLOW_HTTP=true.
- Sem ferramentas, sem navegação, sem retries automáticos; timeout total limitado.
- A chave (quando existe) nunca entra em prompt, log ou resposta.
"""
import logging
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from openai import OpenAI

from app.core.config import Settings, get_settings

log = logging.getLogger("raiz.llm")


@dataclass
class RespostaLLM:
    texto: str
    tokens: int


class ClienteLLM:
    def __init__(self, cfg: Settings) -> None:
        self.modelo = cfg.llm_model
        self.modelo_grande = cfg.llm_model_large or cfg.llm_model
        self.max_tokens = cfg.llm_max_tokens
        self.provedor = cfg.llm_provider
        self._cliente: OpenAI | None = None
        self._bedrock = None  # cliente boto3 "bedrock-runtime"
        if self.provedor == "bedrock":
            self._iniciar_bedrock(cfg)
        else:
            self._iniciar_openai(cfg)

    def _iniciar_openai(self, cfg: Settings) -> None:
        if not (cfg.llm_base_url and cfg.llm_model):
            return
        url = urlparse(cfg.llm_base_url)
        local = url.hostname in ("localhost", "127.0.0.1", "::1")
        if url.scheme != "https" and not (url.scheme == "http" and (local or cfg.llm_allow_http)):
            log.error("LLM_BASE_URL recusada: use HTTPS (ou localhost). LLM desligado.")
            return
        self._cliente = OpenAI(
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key or "sem-chave",
            timeout=cfg.llm_timeout_s,
            max_retries=0,
        )

    def _iniciar_bedrock(self, cfg: Settings) -> None:
        if not cfg.llm_model:
            return
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            log.error("LLM_PROVIDER=bedrock exige o pacote boto3. LLM desligado.")
            return
        try:
            self._bedrock = boto3.client(
                "bedrock-runtime",
                region_name=cfg.llm_aws_region or None,  # vazio: região padrão do ambiente
                config=Config(
                    read_timeout=cfg.llm_timeout_s,
                    connect_timeout=5,
                    retries={"max_attempts": 1, "mode": "standard"},
                ),
            )
        except Exception as erro:  # noqa: BLE001 - sem região/credencial o chat segue extrativo
            log.error("Bedrock indisponível (%s). LLM desligado.", type(erro).__name__)

    @property
    def ligado(self) -> bool:
        return self._cliente is not None or self._bedrock is not None

    def completar(self, sistema: str, usuario: str, grande: bool = False) -> RespostaLLM | None:
        """Devolve None em qualquer falha: quem chama cai no modo extrativo."""
        modelo = self.modelo_grande if grande else self.modelo
        try:
            if self._bedrock is not None:
                return self._completar_bedrock(modelo, sistema, usuario)
            if self._cliente is not None:
                return self._completar_openai(modelo, sistema, usuario)
        except Exception as erro:  # noqa: BLE001 - nunca derrubar o chat por causa do LLM
            log.warning("Falha no LLM (%s). Usando modo extrativo.", type(erro).__name__)
        return None

    def _completar_openai(self, modelo: str, sistema: str, usuario: str) -> RespostaLLM | None:
        assert self._cliente is not None
        r = self._cliente.chat.completions.create(
            model=modelo,
            messages=[{"role": "system", "content": sistema},
                      {"role": "user", "content": usuario}],
            temperature=0,
            max_tokens=self.max_tokens,
        )
        texto = (r.choices[0].message.content or "").strip() if r.choices else ""
        tokens = r.usage.total_tokens if r.usage else 0
        return RespostaLLM(texto, tokens) if texto else None

    def _completar_bedrock(self, modelo: str, sistema: str, usuario: str) -> RespostaLLM | None:
        assert self._bedrock is not None
        r = self._bedrock.converse(
            modelId=modelo,
            system=[{"text": sistema}],
            messages=[{"role": "user", "content": [{"text": usuario}]}],
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": 0},
        )
        blocos = r.get("output", {}).get("message", {}).get("content", [])
        texto = "".join(b.get("text", "") for b in blocos).strip()
        tokens = int(r.get("usage", {}).get("totalTokens", 0))
        return RespostaLLM(texto, tokens) if texto else None


@lru_cache
def get_llm() -> ClienteLLM:
    return ClienteLLM(get_settings())
