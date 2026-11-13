"""Relações do acervo que vão para o espelho no Neon: estrutura e testes negativos.

Os testes negativos seguem docs/SEGURANCA_GRAFO_CODEX.md (ids GRAFO-xx nas docstrings).
"""

from types import SimpleNamespace

from app.services.acervo import Documento
from app.services.grafo import Grafo, get_grafo
from app.services.ingest.pipeline import Chunk


def _relacoes(grafo, tipo):
    return {(r["origem"], r["alvo"]) for r in grafo.relacoes() if r["tipo"] == tipo}


# ---------- estrutura do acervo real ----------
def test_substituicao_de_versoes():
    assert _relacoes(get_grafo(), "substitui") == {("NG_111@3.0.0", "NG_111@2.0.0"),
                                                   ("FM_1111-001@2.0.0", "FM_1111-001@1.0.0")}


def test_vinculos_do_cabecalho():
    v = _relacoes(get_grafo(), "vinculado_a")
    assert ("PX_1111-001@1.0.0", "NG_111") in v
    assert ("FL_1111-001@1.0.0", "PX_1111-001") in v
    assert ("NT_2026-021@1.0.0", "RG_1100") in v


def test_referencia_guarda_os_itens_e_o_nivel_da_origem():
    ref = next(r for r in get_grafo().relacoes()
               if r["tipo"] == "referencia" and r["origem"] == "NG_1130@1.0.0"
               and r["alvo"] == "NT_2026-021")
    assert ref["itens"]  # proveniência: onde a menção aparece na origem
    assert ref["nivel"] == get_grafo()._docs["NG_1130@1.0.0"].nivel


# ---------- grafo sintético para testes negativos ----------
def _doc(codigo, versao, nivel, vigente=True, vinculado=None, tema="ferias"):
    return Documento(codigo=codigo, versao=versao, titulo=f"Título {codigo}", tema=tema,
                     dominio="GEPEC", nivel=nivel, vigente=vigente,
                     fase="Vigente" if vigente else "Versão anterior", arquivo="x.pdf",
                     data_referencia=None, vinculado_a=vinculado, setores=("GEPEC",))


def _chunk(codigo, versao, nivel, texto, item="1.1"):
    return Chunk(codigo=codigo, versao=versao, item=item, texto=texto, nivel=nivel, vigente=True,
                 tema="ferias", dominio="GEPEC")


def _grafo(documentos, chunks):
    return Grafo(SimpleNamespace(documentos=documentos, chunks=chunks))


def test_substituicao_ambigua_nao_e_inventada():
    """GRAFO-07: duas versões vigentes do mesmo código -> nenhuma relação substitui."""
    docs = [_doc("NG_100", "1.0.0", "Interna"), _doc("NG_100", "2.0.0", "Interna")]
    assert _relacoes(_grafo(docs, []), "substitui") == set()


def test_codigos_forjados_no_texto_nao_viram_relacao():
    """GRAFO-09: só código com gramática completa vira referência; autocitação não conta."""
    docs = [_doc("NG_100", "1.0.0", "Interna")]
    chunks = [_chunk("NG_100", "1.0.0", "Interna",
                     'XNG_123 NG_12 NG_1234567 <script>NG_</script> "NG_300" NG_100')]
    assert _relacoes(_grafo(docs, chunks), "referencia") == {("NG_100@1.0.0", "NG_300")}


def test_vinculo_declarado_nao_duplica_a_mencao():
    docs = [_doc("NG_100", "1.0.0", "Interna", vinculado="NG_200")]
    chunks = [_chunk("NG_100", "1.0.0", "Interna", "Ver a NG_200.")]
    g = _grafo(docs, chunks)
    assert _relacoes(g, "vinculado_a") == {("NG_100@1.0.0", "NG_200")}
    assert _relacoes(g, "referencia") == set()
