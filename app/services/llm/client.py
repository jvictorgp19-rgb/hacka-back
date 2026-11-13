"""Cliente do LLM local na VM (API OpenAI-compatible: vLLM, Ollama, LM Studio...).

Para ligar, basta preencher LLM_BASE_URL, LLM_API_KEY e LLM_MODEL no .env.
Sem isso o cliente fica desligado e o chat responde com calculadoras e trechos citados.

Segurança:
- A URL vem só do .env do operador; nunca de body, query, PDF ou do próprio modelo.
- HTTPS obrigatório, exceto localhost (túnel SSH) ou LLM_ALLOW_HTTP=true.
- Sem ferramentas, sem navegação, sem retries automáticos; timeout total limitado.
- A chave nunca entra em prompt, log ou resposta.
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
        self._cliente: OpenAI | None = None
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

    @property
    def ligado(self) -> bool:
        return self._cliente is not None

    def completar(self, sistema: str, usuario: str, grande: bool = False) -> RespostaLLM | None:
        """Devolve None em qualquer falha: quem chama cai no modo extrativo."""
        if self._cliente is None:
            return None
        try:
            r = self._cliente.chat.completions.create(
                model=self.modelo_grande if grande else self.modelo,
                messages=[{"role": "system", "content": sistema},
                          {"role": "user", "content": usuario}],
                temperature=0,
                max_tokens=self.max_tokens,
            )
        except Exception as erro:  # noqa: BLE001 - nunca derrubar o chat por causa da VM
            log.warning("Falha no LLM (%s). Usando modo extrativo.", type(erro).__name__)
            return None
        texto = (r.choices[0].message.content or "").strip() if r.choices else ""
        tokens = r.usage.total_tokens if r.usage else 0
        return RespostaLLM(texto, tokens) if texto else None


@lru_cache
def get_llm() -> ClienteLLM:
    return ClienteLLM(get_settings())
