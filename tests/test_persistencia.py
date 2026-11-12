"""Espelho do conteúdo do sistema no banco (SQLite nos testes; Neon em produção)."""

from sqlalchemy import func, select

from app.services import persistencia as p
from app.services.acervo import get_acervo
from app.services.grafo import get_grafo


def _sincronizado() -> None:
    assert p.sincronizar(get_acervo(), get_grafo()) in ("gravado", "já atualizado")


def _contar(tabela) -> int:
    with p._engine().connect() as c:
        return c.execute(select(func.count()).select_from(tabela)).scalar()


def _linha(tabela, *condicoes) -> dict:
    with p._engine().connect() as c:
        return dict(c.execute(select(tabela).where(*condicoes)).mappings().one())


def test_cada_arquivo_vira_um_documento_com_texto_link_e_trechos(client):
    _sincronizado()
    acervo = get_acervo()
    assert _contar(p.documento) == len(acervo.documentos)
    assert _contar(p.trecho) == len(acervo.chunks)
    ng = _linha(p.documento, p.documento.c.codigo == "NG_111", p.documento.c.versao == "3.0.0")
    assert ng["link_repositorio"].startswith("https://github.com/")
    assert ng["link_repositorio"].endswith("acervo/bronze/ferias/NG_111__FERIAS__v3.0.0.pdf")
    assert "45" in ng["texto_completo"] and ng["sha256"] and ng["vigente"]
    assert ng["trechos"] > 10 and ng["categoria"]


def test_regras_de_ferias_tem_valor_e_fonte(client):
    _sincronizado()
    r = _linha(p.regra, p.regra.c.chave == "ferias.antecedencia_solicitacao")
    assert (r["valor"], r["unidade"], r["documento"], r["item"]) == ("45", "dias", "NG_111",
                                                                     "4.5.1")
    assert _contar(p.regra) >= 20


def test_nivel_de_acesso_acompanha_o_conteudo(client):
    _sincronizado()
    ctr = _linha(p.documento, p.documento.c.codigo == "CTR_2026-012")
    assert ctr["nivel"] == "Restrita"
    with p._engine().connect() as c:
        niveis = set(c.execute(select(p.trecho.c.nivel)
                               .where(p.trecho.c.codigo == "CTR_2026-012")).scalars())
    assert niveis == {"Restrita"}
    assert _linha(p.regra, p.regra.c.chave == "contrato.aluguel")["nivel"] == "Restrita"
    assert _linha(p.curado, p.curado.c.secao == "jornadas_por_tema.locacao")["nivel"] == \
        "Restrita"


def test_relacoes_curado_personas_e_pedidos(client):
    _sincronizado()
    assert _contar(p.relacao) == len(get_grafo().relacoes())
    assert _contar(p.persona) == 6
    assert _linha(p.pedido_acesso, p.pedido_acesso.c.id == "REQ-2026-089")["status"] == "Pendente"
    assert _contar(p.curado) >= 6


def test_mesmo_conteudo_nao_regrava_e_mudanca_refaz_sem_duplicar(client, monkeypatch):
    _sincronizado()
    assert p.sincronizar(get_acervo(), get_grafo()) == "já atualizado"
    execucoes, trechos = _contar(p.ingestao), _contar(p.trecho)
    monkeypatch.setattr(p, "VERSAO_ESPELHO", "teste")
    assert p.sincronizar(get_acervo(), get_grafo()) == "gravado"
    assert _contar(p.ingestao) == execucoes + 1
    assert _contar(p.trecho) == trechos  # refeito por inteiro, sem duplicar
