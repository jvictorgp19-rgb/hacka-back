"""Grafo do acervo: estrutura, projeção por nível e testes negativos.

Os testes negativos seguem docs/SEGURANCA_GRAFO_CODEX.md (ids GRAFO-xx nas docstrings).
"""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.acervo import Documento
from app.services.grafo import Grafo, get_grafo, para_mermaid
from app.services.ingest.pipeline import Chunk

P = {"ana": {"X-Persona-Id": "ana"}, "rafael": {"X-Persona-Id": "rafael"}}


def _ids(projecao, tipo=None):
    return {n.id for n in projecao.nos if tipo is None or n.tipo == tipo}


def _arestas(projecao, tipo):
    return {(a.origem, a.destino) for a in projecao.arestas if a.tipo == tipo}


# ---------- estrutura do acervo real ----------
def test_substituicao_de_versoes():
    p = get_grafo().projetar("Interna")
    assert _arestas(p, "substitui") == {("NG_111@3.0.0", "NG_111@2.0.0"),
                                        ("FM_1111-001@2.0.0", "FM_1111-001@1.0.0")}


def test_vinculos_do_cabecalho():
    v = _arestas(get_grafo().projetar("Restrita"), "vinculado_a")
    assert ("PX_1111-001@1.0.0", "NG_111@3.0.0") in v
    assert ("FL_1111-001@1.0.0", "PX_1111-001@1.0.0") in v
    assert ("NT_2026-021@1.0.0", "RG_1100@2.0.0") in v


def test_referencia_aponta_para_a_versao_vigente_e_guarda_os_itens():
    p = get_grafo().projetar("Interna")
    ref = next(a for a in p.arestas
               if a.tipo == "referencia" and a.origem == "NG_1130@1.0.0"
               and a.destino == "NT_2026-021@1.0.0")
    assert ref.itens  # proveniência: onde a menção aparece na origem
    assert all(a.destino != "NG_111@2.0.0" for a in p.arestas if a.tipo != "substitui")


def test_documentos_citados_fora_do_acervo_viram_referencia_neutra():
    p = get_grafo().projetar("Interna")
    refs = [n for n in p.nos if n.tipo == "referencia"]
    assert {n.id for n in refs} == {"ref:NG_010", "ref:NG_012"}
    assert all(n.titulo is None and n.nivel is None and n.dominio is None for n in refs)


# ---------- projeção por nível ----------
def test_publica_nao_ve_nada():
    p = get_grafo().projetar("Pública")
    assert p.nos == [] and p.arestas == []


def test_interna_nao_ve_contrato_restrito_nem_area_dona_dele():
    p = get_grafo().projetar("Interna")
    corpo = p.model_dump_json()
    assert "CTR_2026-012" not in corpo and "NT_2026-018" not in corpo
    assert "dominio:GCO" not in _ids(p)  # área só aparece se houver documento visível dela


def test_restrita_ve_contrato():
    p = get_grafo().projetar("Restrita", "locacao")
    assert _ids(p, "documento") == {"CTR_2026-012@1.0.0", "NT_2026-018@1.0.0"}
    assert _ids(p, "dominio") == {"dominio:GCO"}


def test_toda_aresta_liga_nos_presentes():
    for nivel in ("Interna", "Restrita", "Sigilosa"):
        p = get_grafo().projetar(nivel)
        ids = _ids(p)
        assert all(a.origem in ids and a.destino in ids for a in p.arestas)


def test_versao_anterior_exige_as_duas_versoes_visiveis():
    g = get_grafo()
    atual, antiga = g.versao_anterior("NG_111", "Interna")
    assert (atual.versao, antiga.versao) == ("3.0.0", "2.0.0")
    assert g.versao_anterior("NG_111", "Pública") is None


# ---------- grafo sintético para testes negativos ----------
def _doc(codigo, versao, nivel, vigente=True, vinculado=None, tema="ferias"):
    return Documento(codigo=codigo, versao=versao, titulo=f"Título {codigo}", tema=tema,
                     dominio="GGC", nivel=nivel, vigente=vigente,
                     fase="Vigente" if vigente else "Versão anterior", arquivo="x.pdf",
                     data_referencia=None, vinculado_a=vinculado)


def _chunk(codigo, versao, nivel, texto, item="1.1"):
    return Chunk(codigo=codigo, versao=versao, item=item, texto=texto, nivel=nivel, vigente=True,
                 tema="ferias", dominio="GGC")


def _grafo(documentos, chunks):
    return Grafo(SimpleNamespace(documentos=documentos, chunks=chunks))


def test_alvo_invisivel_e_inexistente_sao_indistinguiveis():
    """GRAFO-01: Ana não pode saber se NG_999 existe e é Sigilosa ou se nem existe."""
    base_docs = [_doc("NG_100", "1.0.0", "Interna")]
    base_chunks = [_chunk("NG_100", "1.0.0", "Interna", "Ver também a NG_999.")]
    sem_alvo = _grafo(base_docs, base_chunks).projetar("Interna")
    com_alvo_sigiloso = _grafo(base_docs + [_doc("NG_999", "1.0.0", "Sigilosa")],
                               base_chunks).projetar("Interna")
    assert sem_alvo.model_dump() == com_alvo_sigiloso.model_dump()


def test_mencao_feita_em_documento_invisivel_nao_aparece():
    """GRAFO-02: referência que só existe em texto Restrito não gera nó nem aresta para Ana."""
    docs = [_doc("NG_100", "1.0.0", "Interna"), _doc("NG_200", "1.0.0", "Restrita")]
    chunks = [_chunk("NG_200", "1.0.0", "Restrita", "Aplica-se a NG_100 e ao anexo NG_777.")]
    p = _grafo(docs, chunks).projetar("Interna")
    assert _ids(p) == {"NG_100@1.0.0", "dominio:GGC"}
    assert _arestas(p, "referencia") == set()
    assert "NG_777" not in p.model_dump_json() and "NG_200" not in p.model_dump_json()


def test_substituicao_ambigua_nao_e_inventada():
    """GRAFO-07: duas versões vigentes do mesmo código -> nenhuma aresta substitui."""
    docs = [_doc("NG_100", "1.0.0", "Interna"), _doc("NG_100", "2.0.0", "Interna")]
    assert _arestas(_grafo(docs, []).projetar("Interna"), "substitui") == set()


def test_versao_anterior_sigilosa_nao_aparece_para_interna():
    """GRAFO-04/06: a sucessão só aparece se as duas versões forem visíveis."""
    docs = [_doc("NG_100", "2.0.0", "Interna"), _doc("NG_100", "1.0.0", "Sigilosa", False)]
    g = _grafo(docs, [])
    p = g.projetar("Interna")
    assert _arestas(p, "substitui") == set() and "NG_100@1.0.0" not in _ids(p)
    assert g.versao_anterior("NG_100", "Interna") is None


def test_codigos_forjados_no_texto_nao_viram_no():
    """GRAFO-09: só código com gramática completa vira referência."""
    docs = [_doc("NG_100", "1.0.0", "Interna")]
    chunks = [_chunk("NG_100", "1.0.0", "Interna",
                     'XNG_123 NG_12 NG_1234567 <script>NG_</script> "NG_300"]')]
    p = _grafo(docs, chunks).projetar("Interna")
    assert _ids(p, "referencia") == {"ref:NG_300"}


def test_mermaid_nao_aceita_injecao_pelo_titulo():
    """GRAFO-13: rótulos com sintaxe Mermaid/HTML viram texto inerte."""
    p = _grafo([_doc("NG_100", "1.0.0", "Interna")], []).projetar("Interna")
    p.nos[0].rotulo = 'X"] --> n9[click n9 "javascript:alert(1)"]\n%%{init: {}}%%<img src=x>'
    texto = para_mermaid(p)
    assert '"javascript' not in texto and "<img" not in texto and "%%{" not in texto
    assert texto.count("\n") == len(p.nos) + len(p.arestas)  # uma linha por nó e por aresta


# ---------- rota ----------
def test_rota_grafo_respeita_persona_e_nao_faz_cache(client):
    anon = client.get("/grafo")
    assert anon.json() == {"nos": [], "arestas": []}
    assert "no-store" in anon.headers["cache-control"]
    ana = client.get("/grafo", headers=P["ana"]).json()
    assert "CTR_2026-012" not in json.dumps(ana)
    rafael = client.get("/grafo?tema=locacao", headers=P["rafael"]).json()
    assert {n["id"] for n in rafael["nos"] if n["tipo"] == "documento"} == \
        {"CTR_2026-012@1.0.0", "NT_2026-018@1.0.0"}


def test_rota_grafo_recusa_tema_invalido(client):
    assert client.get("/grafo?tema=todos", headers=P["ana"]).status_code == 422
    assert client.get("/grafo?tema=../x", headers=P["ana"]).status_code == 422


def test_auth_mode_desconhecido_derruba_o_startup():
    """GRAFO-20: erro de digitação não pode cair num modo permissivo."""
    with pytest.raises(ValidationError):
        Settings(auth_mode="tokn")
