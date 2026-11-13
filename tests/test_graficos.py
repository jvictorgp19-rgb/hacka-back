"""Gráficos (/analyses/charts): contagens só com o que a persona vê; painel uso da governança."""

import pytest

from app.services import audit_log, envios

CODIGO = "import os\n\n\ndef calcular(x):\n    return x * 2\n\n\nclass Servico:\n    pass\n"


@pytest.fixture(autouse=True)
def _limpo(client):
    envios.limpar()
    client.cookies.clear()
    yield
    envios.esperar()


def _painel(client, painel: str, persona: str | None, **params):
    headers = {"X-Persona-Id": persona} if persona else {}
    return client.get("/analyses/charts", params={"panel": painel, **params}, headers=headers)


def _serie(graficos: list[dict], id_: str) -> dict[str, float]:
    g = next(g for g in graficos if g["id"] == id_)
    return {p["x"]: p["y"] for s in g["series"] for p in s["pontos"]}


def _por_serie(graficos: list[dict], id_: str) -> dict[str, dict[str, float]]:
    g = next(g for g in graficos if g["id"] == id_)
    return {s["nome"]: {p["x"]: p["y"] for p in s["pontos"]} for s in g["series"]}


def test_acervo_conta_so_o_que_a_persona_ve(client):
    ana = _painel(client, "acervo", "ana").json()
    niveis_ana = _por_serie(ana, "acervo-nivel-tema")
    assert set(niveis_ana) == {"Interna"}  # nenhuma barra Sigilosa para quem não vê
    assert _serie(ana, "acervo-fase") == {"Vigente": _serie(ana, "acervo-fase")["Vigente"]}

    helena = _por_serie(_painel(client, "acervo", "helena").json(), "acervo-nivel-tema")
    sigilosos = {tema: n for tema, n in helena["Sigilosa"].items() if n}
    assert sigilosos == {"inovacao": 1.0}  # só a NT_2026-021 da GEINOV
    curadora = _serie(_painel(client, "acervo", "curadora_ggc").json(), "acervo-fase")
    assert curadora["Substituída"] >= 1  # versões substituídas: só GEPEC


def test_acervo_anonimo_vem_vazio_com_nota(client):
    graficos = _painel(client, "acervo", None).json()
    assert all(not s["pontos"] for g in graficos for s in g["series"])
    assert graficos[0]["nota"]


def test_radar_por_criticidade(client):
    r = _painel(client, "radar", "ana", hoje="2026-11-12")
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    g = r.json()
    assert set(_serie(g, "radar-criticidade")) <= {"Crítica", "Alta", "Normal"}
    assert sum(_serie(g, "radar-mes").values()) == sum(_serie(g, "radar-criticidade").values())


def test_triagem_so_conta_envios_visiveis(client):
    client.post("/document-jobs", files=[("files", ("servico.py", CODIGO.encode()))],
                headers={"X-Persona-Id": "bruno"})
    assert envios.esperar()
    helena = _painel(client, "triagem", "helena").json()
    assert _serie(helena, "triagem-setor") == {"GEINOV": 1.0}
    assert _serie(helena, "triagem-achados") == {"Código-fonte": 1.0}
    fernanda = _painel(client, "triagem", "fernanda").json()
    assert _serie(fernanda, "triagem-setor") == {}  # o financeiro nem conta o código


def test_uso_so_para_governanca_e_sem_pessoa(client):
    client.post("/chat", json={"message": "Quantos dias de férias com 3 faltas?",
                               "personaId": "ana"})
    assert _painel(client, "uso", "ana").status_code == 403
    assert _painel(client, "uso", None).status_code == 401
    r = _painel(client, "uso", "diretora_diraf")
    assert r.status_code == 200
    graficos = r.json()
    assert sum(_serie(graficos, "uso-dia").values()) >= 1
    corpo = r.text
    assert "ana" not in corpo.split('"nota"')[0]  # nenhuma série por pessoa


def test_painel_desconhecido_e_422(client):
    assert _painel(client, "pessoas", "diretora_diraf").status_code == 422


def test_resumo_da_auditoria_nao_tem_sujeito():
    audit_log.registrar("helena", "teste", "permitido", "x", [], "Interna")
    assert audit_log.esvaziar()
    linhas = audit_log.resumo()
    assert linhas and all("sujeito" not in linha for linha in linhas)
