"""Pedidos de acesso (STUB somente leitura, com dados sintéticos).

Regra de visibilidade, já aplicada aqui:
- quem pediu vê os próprios pedidos;
- a curadora vê os pedidos do domínio que administra;
- ninguém mais vê nada.

A decisão (conceder, responder com resposta curada, negar) ainda não foi implementada: é
escopo do Victor. Nenhuma saída de LLM pode mudar status ou permissão.
"""

from dataclasses import dataclass

from app.core.auth import Sujeito
from app.schemas.api import AccessRequestItem
from app.services.acervo import NOMES_DOMINIO


@dataclass
class _Pedido:
    solicitante_id: str
    dominio: str
    item: AccessRequestItem


_PEDIDOS = [
    _Pedido("ana", "GGC", AccessRequestItem(
        id="REQ-2026-089",
        solicitante="Ana (Analista / Empregada)",
        papelSolicitante="Empregada - RBAC Interna",
        dominioDono=NOMES_DOMINIO["GGC"],
        documentoAlvo="Conteúdo restrito do domínio GGC",
        perguntaOriginal="Qual o detalhamento de auditoria da folha para ressarcimento de "
                         "despesas em cancelamento de férias?",
        nivelExigido="Restrita",
        status="Pendente",
        timestampSolicitacao="12/11/2026 11:42:10",
    )),
]


def listar_pedidos(sujeito: Sujeito) -> list[AccessRequestItem]:
    if sujeito.persona is None:
        return []
    return [p.item for p in _PEDIDOS
            if p.solicitante_id == sujeito.id or p.dominio in sujeito.persona.cura_dominios]
