"""Envio de arquivos (/document-jobs): contrato do front, triagem, aprovação por setor e banco."""

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.services import envios

CPF = "529.982.247-25"
NORMA = ("Norma de férias: o empregado solicita as férias com 45 dias de antecedência e o "
         "gestor aprova no Portal Raiz. ") * 20
CODIGO = "import os\n\n\ndef calcular(x):\n    return x * 2\n\n\nclass Servico:\n    pass\n"
FORM = (f"FM_1111-001 Solicitação de Férias\nNome do empregado: Joana Pereira da Silva\n"
        f"Matrícula: 4512398\nCPF: {CPF}\nFaltas injustificadas: 8\n")
CAMPOS_DO_FRONT = {"id", "name", "size", "status", "message"}


@pytest.fixture(autouse=True)
def _limpo():
    envios.limpar()
    yield
    envios.esperar()


def _enviar(client, persona: str | None, nome: str, conteudo: str | bytes,
            origem: str | None = None):
    corpo = conteudo.encode() if isinstance(conteudo, str) else conteudo
    headers = {"X-Persona-Id": persona} if persona else {}
    if origem:
        headers["Origin"] = origem
    return client.post("/document-jobs", files=[("files", (nome, corpo))], headers=headers)


def _triado(client, persona: str, nome: str, conteudo: str | bytes) -> dict:
    r = _enviar(client, persona, nome, conteudo)
    assert r.status_code == 200, r.text
    [item] = r.json()
    assert CAMPOS_DO_FRONT <= item.keys() and all(item[c] != "" for c in CAMPOS_DO_FRONT)
    assert envios.esperar()
    return _ver(client, persona, item["id"]).json()


def _ver(client, persona: str | None, envio_id: str):
    headers = {"X-Persona-Id": persona} if persona else {}
    return client.get(f"/document-jobs/{envio_id}", headers=headers)


def _decidir(client, persona: str, envio_id: str, **corpo):
    return client.post(f"/document-jobs/{envio_id}/decision",
                       json={"status": "approved", "response": "", **corpo},
                       headers={"X-Persona-Id": persona})


# ---------- contrato ----------
def test_anonimo_nao_envia(client):
    assert _enviar(client, None, "norma.md", NORMA).status_code == 401


def test_sem_multipart_e_415(client):
    r = client.post("/document-jobs", content=b"x", headers={"X-Persona-Id": "ana",
                                                               "Content-Type": "text/plain"})
    assert r.status_code == 415


def test_post_responde_processing_e_get_traz_a_triagem(client):
    r = _enviar(client, "ana", "norma.md", NORMA)
    [item] = r.json()
    assert item["status"] == "processing" and item["name"] == "norma.md"
    assert item["size"] == len(NORMA.encode())
    assert r.headers["cache-control"] == "private, no-store"
    envios.esperar()
    pronto = _ver(client, "ana", item["id"]).json()
    assert pronto["status"] == "ready"
    assert pronto["classificacao"]["nivel"] == "Interna"
    assert pronto["departamento"]["sigla"] == "GEPEC"
    assert pronto["aprovacao"] == "dispensado" and pronto["nivelFinal"] == "Interna"


def test_assinatura_falsa_falha_na_hora(client):
    [item] = _enviar(client, "ana", "relatorio.pdf", b"MZ\x90\x00binario").json()
    assert item["status"] == "failed" and "não suportado" in item["message"]


def test_nome_do_arquivo_sem_pasta(client):
    [item] = _enviar(client, "ana", "../../etc/passwd.txt", NORMA).json()
    assert item["name"] == "passwd.txt"


def test_mais_de_10_arquivos_e_recusado(client):
    arquivos = [("files", (f"n{i}.md", NORMA.encode())) for i in range(11)]
    r = client.post("/document-jobs", files=arquivos, headers={"X-Persona-Id": "ana"})
    assert r.status_code == 400


def test_limite_de_corpo_vale_so_para_o_envio(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 1000)
    [grande] = _enviar(client, "ana", "norma.md", NORMA).json()  # 2,6 KB > 1000 bytes
    assert grande["status"] == "failed"
    assert _enviar(client, "ana", "x.md", "a" * 70_000).status_code == 413
    r = client.post("/chat", json={"message": "a" * 20_000, "personaId": "ana"})
    assert r.status_code == 413  # as outras rotas continuam com 16 KiB


def test_origem_de_outro_site_e_recusada(client):
    r = _enviar(client, "ana", "norma.md", NORMA, origem="https://evil.example")
    assert r.status_code == 403
    assert _enviar(client, "ana", "norma.md", NORMA, origem="null").status_code == 403
    ok = _enviar(client, "ana", "norma.md", NORMA, origem="http://localhost:3000")
    assert ok.status_code == 200


# ---------- aprovação ----------
def test_codigo_do_junior_espera_o_tech_lead_e_financeiro_nao_ve(client):
    item = _triado(client, "bruno", "servico.py", CODIGO)
    assert item["classificacao"]["nivel"] == "Sigilosa"
    assert item["classificacao"]["setores"] == ["GEINOV"]
    assert item["aprovacao"] == "pendente" and "GEINOV" in item["aprovadores"]
    assert not item["podeDecidir"]  # quem enviou não aprova

    assert _ver(client, "fernanda", item["id"]).status_code == 404  # financeiro não vê código
    assert _ver(client, None, item["id"]).status_code == 404
    r = _decidir(client, "bruno", item["id"])
    assert r.status_code == 403 and "próprio" in r.json()["detail"]

    pendentes = client.get("/document-jobs?aprovacao=pendente",
                           headers={"X-Persona-Id": "helena"}).json()
    assert [p["id"] for p in pendentes] == [item["id"]] and pendentes[0]["podeDecidir"]
    r = _decidir(client, "helena", item["id"], response="Revisado.")
    assert r.status_code == 200, r.text
    aprovado = r.json()
    assert aprovado["aprovacao"] == "aprovado" and aprovado["decidedBy"] == "helena"
    assert aprovado["nivelFinal"] == "Sigilosa" and aprovado["setoresFinais"] == ["GEINOV"]
    assert _decidir(client, "helena", item["id"]).status_code == 403  # já decidido
    assert _ver(client, "fernanda", item["id"]).status_code == 404  # continua fora do GFI


def test_junior_com_conteudo_interno_so_aparece_depois_da_aprovacao(client):
    item = _triado(client, "bruno", "guia.md", NORMA)
    assert item["classificacao"]["nivel"] == "Interna" and item["aprovacao"] == "pendente"
    assert _ver(client, "marina", item["id"]).status_code == 404
    assert _decidir(client, "marina", item["id"]).status_code == 404  # nem sabe que existe
    assert _decidir(client, "helena", item["id"]).status_code == 200
    assert _ver(client, "marina", item["id"]).status_code == 200


def test_aprovador_corrige_nivel_e_setores(client):
    item = _triado(client, "bruno", "guia.md", NORMA)
    r = _decidir(client, "helena", item["id"], nivel="Sigilosa", setores=["GEINOV", "XYZ"])
    assert r.status_code == 422
    r = _decidir(client, "helena", item["id"], nivel="Sigilosa", setores=["GEINOV", "DIRTEC"])
    assert r.json()["setoresFinais"] == ["GEINOV", "DIRTEC"]
    assert _ver(client, "marina", item["id"]).status_code == 404


def test_recusa(client):
    item = _triado(client, "bruno", "servico.py", CODIGO)
    r = client.post(f"/document-jobs/{item['id']}/decision",
                    json={"status": "rejected", "response": "Falta revisão de código."},
                    headers={"X-Persona-Id": "helena"})
    assert r.json()["aprovacao"] == "recusado" and "Falta revisão" in r.json()["message"]
    assert _ver(client, "bruno", item["id"]).status_code == 200


def test_formulario_preenchido_vai_para_a_gepec_aprovar(client):
    item = _triado(client, "ana", "ferias_joana.txt", FORM)
    assert item["classificacao"]["nivel"] == "Sigilosa"
    assert item["departamento"]["sigla"] == "GEPEC" and item["aprovacao"] == "pendente"
    assert _ver(client, "carlos", item["id"]).json()["podeDecidir"]  # gestor do GOP (quem enviou)
    assert _ver(client, "curadora_ggc", item["id"]).json()["podeDecidir"]  # setor dono
    assert _ver(client, "diretora_diraf", item["id"]).json()["podeDecidir"]  # diretoria da GEPEC
    assert _ver(client, "helena", item["id"]).status_code == 404


# ---------- banco ----------
def test_banco_guarda_a_triagem_sem_o_conteudo(client):
    item = _triado(client, "ana", "ferias_joana.txt", FORM)
    with envios._engine().connect() as c:
        linha = c.execute(select(envios.tabela).where(envios.tabela.c.id == item["id"])
                          ).mappings().one()
    assert linha["nivel_sugerido"] == "Sigilosa" and linha["enviado_por"] == "ana"
    gravado = " ".join(str(v) for v in linha.values())
    assert CPF not in gravado and "4512398" not in gravado and "Joana" not in gravado


def test_restaurar_traz_os_envios_de_volta(client):
    item = _triado(client, "bruno", "servico.py", CODIGO)
    envios.limpar()
    assert _ver(client, "bruno", item["id"]).status_code == 404
    assert envios.restaurar() >= 1
    volta = _ver(client, "helena", item["id"]).json()
    assert volta["aprovacao"] == "pendente" and volta["podeDecidir"]


def test_id_invalido_e_404(client):
    assert _ver(client, "ana", "../../etc").status_code == 404
    assert _ver(client, "ana", "0" * 32).status_code == 404
