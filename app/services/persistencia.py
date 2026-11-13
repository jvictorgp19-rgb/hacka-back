"""Espelho do conteúdo do sistema no banco (Neon).

Grava no banco tudo o que o sistema extrai e usa:
- cada arquivo do acervo: metadados do manifesto e do cabeçalho, link no repositório e o texto
  completo extraído do PDF;
- os trechos (um por item numerado), com nível de acesso e vigência;
- as regras das calculadoras (prazos de férias, alçadas, contrato), com documento e item de origem;
- as relações do grafo (substitui, vinculado_a, referencia);
- o conteúdo curado (seed do front), as personas e os pedidos de acesso;
- cada execução da ingestão e a quarentena.

O chat e a busca da API continuam lendo dos arquivos: o banco é cópia, não a fonte.
A cópia é refeita inteira, numa transação, só quando a assinatura do conteúdo muda.

Toda linha com conteúdo do acervo leva a coluna `nivel`. Quem um dia ler estas tabelas para
servir alguém precisa filtrar por ela, como a API faz.
"""

import hashlib
import json
import logging
import threading
from datetime import UTC, datetime
from functools import lru_cache
from urllib.parse import quote

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    delete,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from app.core import banco
from app.core.acl import maior_nivel
from app.core.banco import criar_engine, url_configurada
from app.core.config import get_settings
from app.core.personas import PERSONAS
from app.services.acervo import NOMES_DOMINIO, Acervo
from app.services.calculators import alcadas, contrato, ferias
from app.services.front import PEDIDOS_SEMENTE
from app.services.grafo import CODIGO, Grafo
from app.services.ingest import pipeline

log = logging.getLogger("raiz.persistencia")

VERSAO_ESPELHO = "2"  # 2: setores e motivo da classificação BBTS
_ID = BigInteger().with_variant(Integer, "sqlite")
_JSON = JSON().with_variant(JSONB(), "postgresql")
_NIVEL = String(20)

_meta = MetaData()
ingestao = Table(
    "acervo_ingestao", _meta,
    Column("id", _ID, primary_key=True),
    Column("assinatura", String(64), nullable=False, unique=True),
    Column("versao_parser", String(10), nullable=False),
    Column("momento", DateTime(timezone=True), nullable=False),
    Column("documentos", Integer, nullable=False),
    Column("trechos", Integer, nullable=False),
    Column("relacoes", Integer, nullable=False),
    Column("quarentena", Integer, nullable=False),
)
documento = Table(
    "acervo_documento", _meta,
    Column("codigo", String(40), primary_key=True),
    Column("versao", String(20), primary_key=True),
    Column("titulo", Text, nullable=False),
    Column("tipo", String(10), nullable=False),  # prefixo do código: NG, PX, CTR...
    Column("categoria", Text),  # campo "Documento" do cabeçalho: Norma Geral, Procedimento...
    Column("tema", String(20), nullable=False),
    Column("dominio", String(10), nullable=False),
    Column("dominio_nome", Text, nullable=False),
    Column("nivel", _NIVEL, nullable=False),
    # Setores com necessidade de conhecer (docs/CLASSIFICACAO_BBTS.md). Quem ler esta tabela para
    # servir alguém filtra por nivel E por setores, como app/core/acl.py.
    Column("setores", _JSON),
    Column("motivo_classificacao", Text),
    Column("classificacao_pdf", _NIVEL),
    Column("vigente", Boolean, nullable=False),
    Column("fase", Text),
    Column("arquivo", Text),
    Column("link_repositorio", Text),
    Column("sha256", String(64)),
    Column("elaborado_por", Text),
    Column("aprovado_por", Text),
    Column("vinculado_a", String(40)),
    Column("vigencia_inicio", String(10)),
    Column("vigencia_fim", String(10)),
    Column("data_referencia", String(10)),
    Column("texto_completo", Text),
    Column("trechos", Integer, nullable=False),
)
trecho = Table(
    "acervo_trecho", _meta,
    Column("id", _ID, primary_key=True),
    Column("codigo", String(40), nullable=False),
    Column("versao", String(20), nullable=False),
    Column("ordem", Integer, nullable=False),
    Column("item", Text, nullable=False),
    Column("texto", Text, nullable=False),
    Column("nivel", _NIVEL, nullable=False),
    Column("vigente", Boolean, nullable=False),
    Column("tema", String(20), nullable=False),
    Column("dominio", String(10), nullable=False),
    ForeignKeyConstraint(["codigo", "versao"],
                         ["acervo_documento.codigo", "acervo_documento.versao"],
                         ondelete="CASCADE"),
    UniqueConstraint("codigo", "versao", "ordem"),
)
relacao = Table(
    "acervo_relacao", _meta,
    Column("id", _ID, primary_key=True),
    Column("origem", String(70), nullable=False),  # CODIGO@VERSAO
    Column("alvo", String(70), nullable=False),  # código citado ou CODIGO@VERSAO
    Column("tipo", String(20), nullable=False),
    Column("itens", _JSON, nullable=False),  # onde a evidência aparece na origem
    Column("nivel", _NIVEL, nullable=False),  # nível do documento de origem
)
regra = Table(
    "acervo_regra", _meta,
    Column("chave", String(60), primary_key=True),
    Column("tema", String(20), nullable=False),
    Column("descricao", Text, nullable=False),
    Column("valor", Text, nullable=False),
    Column("unidade", String(20)),
    Column("documento", String(40), nullable=False),
    Column("item", Text),
    Column("nivel", _NIVEL, nullable=False),
)
curado = Table(
    "acervo_curado", _meta,
    Column("secao", String(60), primary_key=True),
    Column("conteudo", _JSON, nullable=False),
    Column("nivel", _NIVEL, nullable=False),  # maior nível entre os documentos citados
)
quarentena = Table(
    "acervo_quarentena", _meta,
    Column("id", _ID, primary_key=True),
    Column("ingestao_id", _ID, ForeignKey("acervo_ingestao.id"), nullable=False),
    Column("documento", Text, nullable=False),
    Column("motivo", Text, nullable=False),
)
persona = Table(
    "sistema_persona", _meta,
    Column("id", String(40), primary_key=True),
    Column("nome", Text, nullable=False),
    Column("papel", Text, nullable=False),
    Column("unidade", Text, nullable=False),
    Column("nivel", _NIVEL, nullable=False),
    Column("cura_dominios", _JSON, nullable=False),
    Column("setor", String(10)),
    Column("senioridade", String(10)),
)
pedido_acesso = Table(
    "sistema_pedido_acesso", _meta,
    Column("id", String(40), primary_key=True),
    Column("solicitante_id", String(40), nullable=False),
    Column("dominio", String(10), nullable=False),
    Column("nivel_exigido", _NIVEL, nullable=False),
    Column("status", Text, nullable=False),
    Column("conteudo", _JSON, nullable=False),
)
# Ordem de limpeza respeita as chaves estrangeiras (filhos primeiro).
_ESPELHADAS = (trecho, documento, relacao, regra, curado, persona, pedido_acesso)


# ---------- regras das calculadoras ----------
def _regras() -> list[dict]:
    """Parâmetros que respondem "quando posso tirar férias", alçadas e contrato.

    Os valores vêm das constantes das calculadoras: o banco nunca diverge do que o chat calcula.
    """
    def r(chave, tema, descricao, valor, unidade, doc, item):
        return {"chave": chave, "tema": tema, "descricao": descricao, "valor": str(valor),
                "unidade": unidade, "documento": doc, "item": item}

    faltas = json.dumps([{"faltas_de": a, "faltas_ate": b, "dias_de_ferias": d}
                         for a, b, d in ferias.TABELA_FALTAS])
    return [
        r("ferias.antecedencia_solicitacao", "ferias", "Pedir as férias com antecedência mínima "
          "em relação ao início.", ferias.ANTECEDENCIA_SOLICITACAO, "dias", "NG_111", "4.5.1"),
        r("ferias.antecedencia_aviso", "ferias", "Aviso de férias emitido antes do início.",
          ferias.ANTECEDENCIA_AVISO, "dias", "NG_111", "4.5.3"),
        r("ferias.antecedencia_assinatura", "ferias", "Aviso assinado pelo empregado antes do "
          "início.", ferias.ANTECEDENCIA_ASSINATURA, "dias", "NG_111", "4.5.4"),
        r("ferias.antecedencia_alteracao", "ferias", "Alteração ou cancelamento das férias até "
          "esta antecedência.", ferias.ANTECEDENCIA_ALTERACAO, "dias", "NG_111", "4.9.1"),
        r("ferias.antecedencia_pagamento", "ferias", "Pagamento das férias antes do início, "
          "antecipado para dia útil.", ferias.ANTECEDENCIA_PAGAMENTO, "dias", "NG_111", "4.5.5"),
        r("ferias.inicio_vedado", "ferias", "Início vedado nos dias úteis que antecedem feriado "
          "ou descanso semanal (domingo); o início deve ser dia útil.", 2, "dias úteis",
          "NG_111", "4.3.2"),
        r("ferias.limite_equipe", "ferias", "Máximo da equipe ausente ao mesmo tempo, "
          "arredondado para baixo, mínimo de 1 pessoa.", 30, "%", "NG_111", "4.6.3"),
        r("ferias.fracionamento", "ferias", "Até 3 períodos; um com 14 dias corridos ou mais; "
          "os demais com 5 ou mais.", "14+5+5", "dias", "NG_111", "4.4"),
        r("ferias.dias_por_faltas", "ferias", "Dias de férias conforme as faltas injustificadas "
          "no período aquisitivo.", faltas, "tabela", "TB_1111-001", "Tabela 1"),
        r("ferias.teto_ressarcimento", "ferias", "Teto de ressarcimento de despesas quando a "
          "empresa cancela as férias.", ferias.TETO_RESSARCIMENTO, "BRL", "NG_111", "4.9.3"),
        r("inovacao.alcada_gerente", "inovacao", "Gasto com protótipo até este valor: aprova o "
          "Gerente do NIN.", alcadas.LIMITE_GERENTE, "BRL", "NT_2026-021", "4.2 a 4.4"),
        r("inovacao.alcada_diretor", "inovacao", "Gasto com protótipo até este valor: aprova o "
          "Diretor da DIRTEC; acima, o Comitê de Alçadas.", alcadas.LIMITE_DIRETOR, "BRL",
          "NT_2026-021", "4.2 a 4.4"),
        r("contrato.inicio", "locacao", "Início da vigência do contrato.", contrato.INICIO,
          "data", contrato.CODIGO, "Cláusula 2ª"),
        r("contrato.fim", "locacao", "Fim da vigência do contrato.", contrato.FIM, "data",
          contrato.CODIGO, None),
        r("contrato.aluguel", "locacao", "Aluguel mensal.", contrato.ALUGUEL, "BRL",
          contrato.CODIGO, "Cláusula 7ª"),
        r("contrato.valor_global", "locacao", "Valor global do contrato.", contrato.VALOR_GLOBAL,
          "BRL", contrato.CODIGO, None),
        r("contrato.prazo_maximo", "locacao", "Prazo máximo com prorrogações.",
          contrato.PRAZO_MAXIMO_MESES, "meses", contrato.CODIGO, None),
        r("contrato.vistoria_ate", "locacao", "Vistoria do espaço até esta data.",
          contrato.VISTORIA_ATE, "data", contrato.CODIGO, "Cláusula 6ª"),
        r("contrato.prorrogacao_ate", "locacao", "Pedido de prorrogação até esta data.",
          contrato.PRORROGACAO_ATE, "data", contrato.CODIGO, "Cláusula 3ª"),
        r("contrato.ultimo_dia_com_multa", "locacao", "Rescisão até esta data (90º dia) paga "
          "multa de um aluguel; a partir do dia seguinte, sem multa.",
          contrato.ULTIMO_DIA_COM_MULTA, "data", contrato.CODIGO, "Cláusula 13ª"),
        r("contrato.aditivo_maximo", "locacao", "Aditivo máximo (20% do valor global).",
          contrato.ADITIVO_MAXIMO, "BRL", contrato.CODIGO, "Cláusula 3ª"),
        r("contrato.multa_inexecucao", "locacao", "Multa por inexecução (5% do valor global).",
          contrato.MULTA_INEXECUCAO, "BRL", contrato.CODIGO, "Cláusula 15ª"),
        r("contrato.glosa_diaria", "locacao", "Desconto por dia com internet interrompida por "
          "mais de 4 horas (1/30 do aluguel).", contrato.GLOSA_DIARIA, "BRL", contrato.CODIGO,
          "Anexo, item 11"),
        r("contrato.aviso_rescisao", "locacao", "Aviso prévio para rescindir.",
          contrato.AVISO_RESCISAO_DIAS, "dias", contrato.CODIGO, None),
    ]


# ---------- montagem das linhas ----------
def _texto_completo(item_manifesto: dict) -> str | None:
    if item_manifesto["arquivo"] is None:
        return item_manifesto.get("texto")
    return _texto_do_pdf(item_manifesto["arquivo"], item_manifesto["sha256"])


@lru_cache(maxsize=64)
def _texto_do_pdf(arquivo: str, sha256: str) -> str | None:
    """Texto inteiro do PDF, com as mesmas checagens da ingestão (caminho e hash).

    Cache por arquivo + hash do manifesto: extrair todos os PDFs leva alguns segundos.
    """
    try:
        caminho = pipeline._caminho_seguro(arquivo)
        if hashlib.sha256(caminho.read_bytes()).hexdigest() != sha256:
            return None
        return pipeline.extrair_texto(caminho)
    except Exception:  # noqa: BLE001 - arquivo problemático já está na quarentena
        return None


def _link(arquivo: str | None) -> str | None:
    base = get_settings().acervo_repo_url.rstrip("/")
    if not arquivo or not base.startswith("https://"):
        return None
    return f"{base}/acervo/bronze/{quote(arquivo)}"


def _nivel_por_codigo(acervo: Acervo) -> dict[str, str]:
    niveis: dict[str, list[str]] = {}
    for d in acervo.documentos:
        niveis.setdefault(d.codigo, []).append(d.nivel)
    return {codigo: maior_nivel(lista) for codigo, lista in niveis.items()}


def _nivel_do_conteudo(conteudo, por_codigo: dict[str, str]) -> str:
    """Maior nível entre os documentos citados no trecho de JSON; sem citação, Interna."""
    citados = set(CODIGO.findall(json.dumps(conteudo, ensure_ascii=False)))
    return maior_nivel(["Interna"] + [por_codigo[c] for c in citados if c in por_codigo])


def montar(acervo: Acervo, grafo: Grafo) -> dict[str, list[dict]]:
    manifesto = {f"{m['codigo']}@{m['versao']}": m
                 for m in json.loads(pipeline.MANIFESTO.read_text(encoding="utf-8"))["documentos"]}
    por_codigo = _nivel_por_codigo(acervo)

    ordens: dict[str, int] = {}
    trechos = []
    for c in acervo.chunks:
        chave = f"{c.codigo}@{c.versao}"
        ordens[chave] = ordens.get(chave, 0) + 1
        trechos.append({"codigo": c.codigo, "versao": c.versao, "ordem": ordens[chave],
                        "item": c.item, "texto": c.texto, "nivel": c.nivel,
                        "vigente": c.vigente, "tema": c.tema, "dominio": c.dominio})

    documentos = []
    for d in acervo.documentos:
        chave = f"{d.codigo}@{d.versao}"
        cab = acervo.cabecalhos.get(chave, {})
        m = manifesto.get(chave, {"arquivo": d.arquivo, "sha256": None})
        documentos.append({
            "codigo": d.codigo, "versao": d.versao, "titulo": d.titulo, "tipo": d.tipo,
            "categoria": cab.get("tipo"), "tema": d.tema, "dominio": d.dominio,
            "dominio_nome": NOMES_DOMINIO.get(d.dominio, d.dominio), "nivel": d.nivel,
            "setores": list(d.setores), "motivo_classificacao": d.motivo,
            "classificacao_pdf": cab.get("classificacao"), "vigente": d.vigente,
            "fase": d.fase, "arquivo": d.arquivo, "link_repositorio": _link(d.arquivo),
            "sha256": m.get("sha256"), "elaborado_por": cab.get("elaborado_por"),
            "aprovado_por": cab.get("aprovado_por"), "vinculado_a": d.vinculado_a,
            "vigencia_inicio": cab.get("vigencia_inicio"),
            "vigencia_fim": cab.get("vigencia_fim"), "data_referencia": d.data_referencia,
            "texto_completo": _texto_completo(m) if "codigo" in m else None,
            "trechos": ordens.get(chave, 0),
        })

    regras = [r | {"nivel": por_codigo.get(r["documento"], "Interna")} for r in _regras()]

    secoes: dict[str, object] = {}
    for chave, valor in acervo.seed.items():
        if chave == "jornadas_por_tema" and isinstance(valor, dict):
            secoes.update({f"jornadas_por_tema.{tema}": v for tema, v in valor.items()})
        else:
            secoes[chave] = valor
    curados = [{"secao": s, "conteudo": v, "nivel": _nivel_do_conteudo(v, por_codigo)}
               for s, v in secoes.items()]

    personas = [{"id": p.id, "nome": p.nome, "papel": p.papel, "unidade": p.unidade,
                 "nivel": p.nivel, "cura_dominios": list(p.cura_dominios),
                 "setor": p.setor, "senioridade": p.senioridade}
                for p in PERSONAS.values()]
    # Pedido de exemplo de GET /access-requests (o dossiê da folha é sigiloso da GEPEC).
    # Os pedidos criados no site ficam em registro_front (app/services/registros.py).
    pedidos = [{"id": p["id"], "solicitante_id": p["persona"], "dominio": p["owner"],
                "nivel_exigido": "Sigilosa", "status": p["status"], "conteudo": dict(p)}
               for p in PEDIDOS_SEMENTE]

    return {"documentos": documentos, "trechos": trechos, "relacoes": grafo.relacoes(),
            "regras": regras, "curados": curados, "personas": personas, "pedidos": pedidos,
            "quarentena": [{"documento": q["documento"], "motivo": str(q["motivo"])[:500]}
                           for q in acervo.quarentena]}


def assinatura(linhas: dict[str, list[dict]]) -> str:
    """Muda quando muda qualquer conteúdo espelhado (inclusive o texto dos PDFs)."""
    corpo = json.dumps(linhas, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(f"{VERSAO_ESPELHO}|{pipeline.VERSAO_PARSER}|{corpo}".encode()).hexdigest()


# ---------- gravação ----------
@lru_cache
def _engine() -> Engine:
    engine = criar_engine(url_configurada())
    _meta.create_all(engine)  # com o papel restrito do Neon, só confere que as tabelas existem
    return engine


_trava = threading.Lock()


def migrar_colunas(engine: Engine) -> list[str]:
    return banco.migrar_colunas(engine, _meta)


def sincronizar(acervo: Acervo, grafo: Grafo) -> str:
    """Refaz o espelho se o conteúdo mudou. Devolve 'gravado' ou 'já atualizado'."""
    linhas = montar(acervo, grafo)
    sua_assinatura = assinatura(linhas)
    with _trava:
        engine = _engine()
        with engine.begin() as c:
            if engine.dialect.name == "postgresql":
                c.execute(text("SET LOCAL statement_timeout = '60s'"))
                c.execute(text("SET LOCAL lock_timeout = '5s'"))
            ultima = c.execute(select(ingestao.c.assinatura)
                               .order_by(ingestao.c.id.desc()).limit(1)).scalar()
            if ultima == sua_assinatura:
                return "já atualizado"
            for tabela in _ESPELHADAS:
                c.execute(delete(tabela))
            id_ingestao = c.execute(ingestao.insert().values(
                assinatura=sua_assinatura, versao_parser=pipeline.VERSAO_PARSER,
                momento=datetime.now(UTC), documentos=len(linhas["documentos"]),
                trechos=len(linhas["trechos"]), relacoes=len(linhas["relacoes"]),
                quarentena=len(linhas["quarentena"]))).inserted_primary_key[0]
            for tabela, chave in ((documento, "documentos"), (trecho, "trechos"),
                                  (relacao, "relacoes"), (regra, "regras"), (curado, "curados"),
                                  (persona, "personas"), (pedido_acesso, "pedidos")):
                if linhas[chave]:
                    c.execute(tabela.insert(), linhas[chave])
            if linhas["quarentena"]:
                c.execute(quarentena.insert(),
                          [q | {"ingestao_id": id_ingestao} for q in linhas["quarentena"]])
    log.info("Espelho no banco gravado: %d documentos, %d trechos, %d regras, %d relações.",
             len(linhas["documentos"]), len(linhas["trechos"]), len(linhas["regras"]),
             len(linhas["relacoes"]))
    return "gravado"


def sincronizar_em_segundo_plano(acervo: Acervo, grafo: Grafo) -> threading.Thread:
    """Startup não espera o Neon. Falha vira log; a próxima subida da API tenta de novo."""
    def tarefa() -> None:
        try:
            sincronizar(acervo, grafo)
        except Exception as erro:  # noqa: BLE001 - a mensagem do driver pode trazer host
            log.error("Falha ao gravar o espelho do acervo no banco: %s", type(erro).__name__)

    thread = threading.Thread(target=tarefa, name="espelho-acervo", daemon=True)
    thread.start()
    return thread


if __name__ == "__main__":
    # Com o papel DONO: cria as tabelas e grava o espelho uma vez.
    from app.services.acervo import get_acervo
    from app.services.grafo import get_grafo

    try:
        url = url_configurada()
    except ValueError as erro:
        raise SystemExit(f"Configuração recusada: {erro}") from None
    try:
        engine_dono = criar_engine(url)
        _meta.create_all(engine_dono)
        for coluna in migrar_colunas(engine_dono):
            print(f"coluna criada: {coluna}")
        print(sincronizar(get_acervo(), get_grafo()))
    except Exception as erro:  # noqa: BLE001
        raise SystemExit(f"Falha: {type(erro).__name__}.") from None
