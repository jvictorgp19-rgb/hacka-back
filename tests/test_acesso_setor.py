"""Matriz de acesso da classificação BBTS (docs/CLASSIFICACAO_BBTS.md).

Interno: toda pessoa identificada. Sigiloso: setor listado E credenciamento (LAI art. 25, § 1º).
"""

import pytest

from app.core.acl import ACESSO_ANONIMO, Acesso, pode_ver
from app.core.auth import Sujeito
from app.core.personas import PERSONAS
from app.services.acervo import get_acervo

SIGILOSOS = {"NT_2026-021", "NT_2026-018", "CTR_2026-012", "DOSSIE_GGC_FOLHA"}
INTERNOS = {"NG_111", "PX_1111-001", "FM_1111-001", "TB_1111-001", "FL_1111-001", "NG_1130",
            "PX_1130-001", "RG_1100"}


def _vistos(persona: str) -> set[str]:
    p = PERSONAS[persona]
    return {d.codigo for d in get_acervo().visiveis(Sujeito(p, p.nivel).acesso)}


@pytest.mark.parametrize(("persona", "sigilosos_vistos"), [
    ("ana", set()),  # GOP: não é setor de nenhum sigiloso
    ("carlos", set()),
    ("marina", set()),  # GOC, mas sem credenciamento
    ("bruno", set()),  # júnior da GEINOV, sem credenciamento
    ("rafael", {"NT_2026-018", "CTR_2026-012"}),  # GOC: unidade demandante e fiscal
    ("sergio", {"NT_2026-018", "CTR_2026-012"}),  # GESUC: dona do contrato
    ("fernanda", {"CTR_2026-012"}),  # GFI paga o contrato; cotações não são dela
    ("helena", {"NT_2026-021"}),  # GEINOV: orçamento do Ideias em Campo
    ("diretora_diraf", {"NT_2026-021", "NT_2026-018"}),  # aprovadora listada nas duas NTs
    ("curadora_ggc", {"DOSSIE_GGC_FOLHA"}),
])
def test_matriz_de_sigilosos_por_setor(persona, sigilosos_vistos):
    vistos = _vistos(persona)
    assert vistos & SIGILOSOS == sigilosos_vistos
    assert INTERNOS <= vistos  # interno vale para a empresa toda


def test_versoes_substituidas_so_no_arquivo_historico_da_gepec():
    acervo = get_acervo()
    antigas = [d for d in acervo.documentos if not d.vigente]
    assert {d.codigo for d in antigas} == {"NG_111", "FM_1111-001"}
    assert all(d.nivel == "Sigilosa" and d.setores == ("GEPEC",) for d in antigas)
    assert all(acervo.pode(Acesso("GEPEC", True), d) for d in antigas)
    assert not any(acervo.pode(Acesso("GOP"), d) for d in antigas)


def test_anonimo_nao_ve_nem_o_interno():
    assert get_acervo().visiveis(ACESSO_ANONIMO) == []


def test_regra_pura():
    assert pode_ver(ACESSO_ANONIMO, "Pública")
    assert not pode_ver(ACESSO_ANONIMO, "Interna")
    assert pode_ver(Acesso("GOP"), "Interna", ["GEPEC"])
    assert not pode_ver(Acesso("GOP", True), "Sigilosa", ["GEPEC"])  # credenciado, outro setor
    assert not pode_ver(Acesso("GEPEC"), "Sigilosa", ["GEPEC"])  # setor certo, sem credencial
    assert pode_ver(Acesso("GEPEC", True), "Sigilosa", ["GEPEC"])
    assert pode_ver(Acesso("GEPEC"), "Restrita", ["GEPEC"])  # Restrita dispensa credencial


def test_bloqueio_aponta_o_setor_dono_sem_revelar_documento(perguntar):
    d = perguntar("Qual o valor do aluguel do coworking?", "marina", "locacao")
    assert d["rbacBlock"]["dominioResponsavel"].startswith("GESUC")
    assert d["rbacBlock"]["nivelExigido"] == "Sigilosa"
    assert "CTR_2026" not in str(d["rbacBlock"])


def test_catalogo_da_rota_segue_a_matriz(client):
    corpo = client.get("/documents", headers={"X-Persona-Id": "fernanda"}).json()
    codigos = {d["codigo"] for d in corpo if d["vigente"]}
    assert "CTR_2026-012" in codigos and "NT_2026-018" not in codigos
