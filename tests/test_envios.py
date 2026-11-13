"""Envio de arquivos (/document-jobs): contrato do front, triagem, quem vê o pendente e banco."""

import pytest
from sqlalchemy import delete, select

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
    envios.esperar()
    envios.limpar()
    with envios._engine().begin() as c:
        c.execute(delete(envios.arquivos))
        c.execute(delete(envios.tabela))
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
    r = client.post("/conversations/messages",
                    json={"query": "a" * 20_000, "context": {"persona": "ana"}})
    assert r.status_code == 413  # as outras rotas continuam com 16 KiB


def test_origem_de_outro_site_e_recusada(client):
    r = _enviar(client, "ana", "norma.md", NORMA, origem="https://evil.example")
    assert r.status_code == 403
    assert _enviar(client, "ana", "norma.md", NORMA, origem="null").status_code == 403
    ok = _enviar(client, "ana", "norma.md", NORMA, origem="http://localhost:3000")
    assert ok.status_code == 200
    mesma = _enviar(client, "ana", "norma.md", NORMA, origem="http://testserver")  # o Swagger
    assert mesma.status_code == 200


# ---------- aprovação ----------
def test_codigo_do_junior_fica_pendente_e_financeiro_nao_ve(client):
    item = _triado(client, "bruno", "servico.py", CODIGO)
    assert item["classificacao"]["nivel"] == "Sigilosa"
    assert item["classificacao"]["setores"] == ["GEINOV"]
    assert item["aprovacao"] == "pendente" and "GEINOV" in item["aprovadores"]
    assert _ver(client, "helena", item["id"]).status_code == 200  # tech lead: aprovador
    assert _ver(client, "fernanda", item["id"]).status_code == 404  # financeiro não vê código
    assert _ver(client, None, item["id"]).status_code == 404


def test_junior_com_conteudo_interno_nao_vai_para_o_setor_sem_aprovacao(client):
    item = _triado(client, "bruno", "guia.md", NORMA)
    assert item["classificacao"]["nivel"] == "Interna" and item["aprovacao"] == "pendente"
    assert _ver(client, "marina", item["id"]).status_code == 404
    assert _ver(client, "helena", item["id"]).status_code == 200


def test_formulario_preenchido_vai_para_a_gepec_aprovar(client):
    item = _triado(client, "ana", "ferias_joana.txt", FORM)
    assert item["classificacao"]["nivel"] == "Sigilosa"
    assert item["departamento"]["sigla"] == "GEPEC" and item["aprovacao"] == "pendente"
    # Gestor de quem enviou, sem habilitação Sigilosa nem necessidade de conhecer: não vê.
    assert _ver(client, "carlos", item["id"]).status_code == 404
    assert _ver(client, "curadora_ggc", item["id"]).status_code == 200  # setor dono
    assert _ver(client, "diretora_diraf", item["id"]).status_code == 200  # diretoria da GEPEC
    assert _ver(client, "helena", item["id"]).status_code == 404


# ---------- retenção (LGPD) ----------
def test_prazo_de_retencao_elimina_os_dados_pessoais(client):
    from datetime import UTC, datetime, timedelta

    item = _triado(client, "ana", "ferias_joana.txt", FORM)
    depois = datetime.now(UTC) + timedelta(days=get_settings().retencao_envios_dias + 1)
    assert envios.expurgar(depois) == 1
    envio = envios.obter(item["id"])
    assert envio.fatos_ferias is None and envio.nome_arquivo == envios.EXPURGADO
    assert envios.expurgar(depois) == 0  # não repete


def test_tarefa_cancelada_no_desligamento_apaga_o_temporario(tmp_path):
    from concurrent.futures import Future

    caminho = tmp_path / "raiz-envio.bin"
    caminho.write_bytes(b"x")
    tarefa = Future()
    with envios._trava:
        antes = envios._na_fila
        envios._na_fila += 1
        envios._temporarios[tarefa] = caminho
    tarefa.add_done_callback(envios._ao_terminar)
    assert tarefa.cancel()
    assert not caminho.exists() and envios._na_fila == antes


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
    assert _ver(client, "bruno", item["id"]).status_code == 200
    assert envios.restaurar() >= 1
    volta = _ver(client, "helena", item["id"]).json()
    assert volta["aprovacao"] == "pendente"


def test_id_invalido_e_404(client):
    assert _ver(client, "ana", "../../etc").status_code == 404
    assert _ver(client, "ana", "0" * 32).status_code == 404


def test_historico_e_original_sobrevivem_a_memoria_vazia(client):
    item = _triado(client, "bruno", "servico.py", CODIGO)
    envios.limpar()
    r = client.get("/document-jobs", headers={"X-Persona-Id": "bruno"})
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    assert [e["id"] for e in r.json()] == [item["id"]]
    assert r.json()[0]["saved"] and r.json()[0]["fileAvailable"]
    original = client.get(f"/document-jobs/{item['id']}/file",
                          headers={"X-Persona-Id": "bruno"})
    assert original.status_code == 200 and original.content == CODIGO.encode()
    assert original.headers["cache-control"] == "private, no-store"
    assert "attachment" in original.headers["content-disposition"]


def test_historico_e_download_respeitam_permissoes(client):
    item = _triado(client, "bruno", "servico.py", CODIGO)
    assert client.get("/document-jobs").status_code == 401
    for persona in ("fernanda", "ana"):
        headers = {"X-Persona-Id": persona}
        assert client.get("/document-jobs", headers=headers).json() == []
        assert client.get(f"/document-jobs/{item['id']}/file", headers=headers).status_code == 404
    aprovador = client.get("/document-jobs", headers={"X-Persona-Id": "helena"}).json()
    assert aprovador[0]["canApprove"]
    assert not _ver(client, "bruno", item["id"]).json()["canApprove"]


def test_aprovacao_persistida_e_nao_repetida(client):
    item = _triado(client, "bruno", "servico.py", CODIGO)
    url = f"/document-jobs/{item['id']}/decision"
    body = {"status": "aprovado"}
    assert client.post(url, json=body, headers={"X-Persona-Id": "bruno"}).status_code == 403
    aprovado = client.post(url, json=body, headers={"X-Persona-Id": "helena"})
    assert aprovado.status_code == 200
    assert aprovado.json()["aprovacao"] == "aprovado" and not aprovado.json()["canApprove"]
    assert aprovado.json()["decidedBy"] == "helena" and aprovado.json()["decidedAt"].endswith("Z")
    assert aprovado.json()["nivelFinal"] == "Sigilosa"
    assert aprovado.json()["setoresFinais"] == ["GEINOV"]
    envios.limpar()
    assert _ver(client, "bruno", item["id"]).json()["aprovacao"] == "aprovado"
    assert client.post(url, json=body, headers={"X-Persona-Id": "helena"}).status_code == 409


def test_falha_de_gravacao_nao_confirma_recebimento(client, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    def falhar(*args):
        raise SQLAlchemyError("credencial-do-driver-que-nao-deve-sair")

    monkeypatch.setattr(envios, "_gravar_no_banco", falhar)
    r = _enviar(client, "ana", "norma.md", NORMA)
    assert r.status_code == 503
    assert "credencial" not in r.text
    assert client.get("/document-jobs", headers={"X-Persona-Id": "ana"}).json() == []
    assert envios._na_fila == 0


def test_retencao_e_eliminacao_removem_originais_do_banco(client):
    from datetime import UTC, datetime, timedelta

    item = _triado(client, "ana", "norma.md", NORMA)
    assert envios.eliminar_a_pedido(item["id"]) == "eliminado"
    assert not _ver(client, "ana", item["id"]).json()["fileAvailable"]
    assert client.get(f"/document-jobs/{item['id']}/file",
                      headers={"X-Persona-Id": "ana"}).status_code == 404
    outro = _triado(client, "ana", "norma.md", NORMA)
    envios.limpar()  # retenção precisa alcançar também envios fora do cache
    depois = datetime.now(UTC) + timedelta(days=get_settings().retencao_envios_dias + 1)
    assert envios.expurgar(depois) == 1
    with envios._engine().connect() as c:
        assert c.execute(select(envios.arquivos)).first() is None
    assert _ver(client, "ana", outro["id"]).json()["name"] == envios.EXPURGADO


def test_paginacao_do_historico_depois_da_autorizacao(client):
    _triado(client, "bruno", "servico.py", CODIGO)
    primeiro = _triado(client, "ana", "um.md", NORMA)
    segundo = _triado(client, "ana", "dois.md", NORMA)
    headers = {"X-Persona-Id": "ana"}
    assert client.get("/document-jobs?limit=1", headers=headers).json()[0]["id"] == segundo["id"]
    assert client.get("/document-jobs?limit=1&offset=1", headers=headers).json()[0]["id"] \
        == primeiro["id"]


def test_original_e_registro_lidos_por_outro_processo(client):
    import json
    import subprocess
    import sys

    item = _triado(client, "bruno", "servico.py", CODIGO)
    r = subprocess.run([sys.executable, "-c", (
        "import json, sys; from app.services import envios; "
        "e=envios.obter(sys.argv[1]); "
        "print(json.dumps({'nome':e.nome_arquivo, 'conteudo':envios.conteudo(e).decode()}))"
    ), item["id"]], capture_output=True, text=True, check=True, timeout=20)
    assert json.loads(r.stdout) == {"nome": "servico.py", "conteudo": CODIGO}


def test_duas_decisoes_concorrentes_so_confirmam_uma(client):
    from concurrent.futures import ThreadPoolExecutor

    from app.core.personas import PERSONAS

    item = _triado(client, "bruno", "servico.py", CODIGO)
    primeiro, segundo = envios.obter(item["id"]), envios.obter(item["id"])

    def decidir(envio, status):
        try:
            return envios.decidir(envio, PERSONAS["helena"], status).aprovacao
        except envios.DecisaoConflitante:
            return "conflito"

    with ThreadPoolExecutor(max_workers=2) as fila:
        a = fila.submit(decidir, primeiro, "aprovado")
        b = fila.submit(decidir, segundo, "recusado")
        resultados = [a.result(), b.result()]
    assert resultados.count("conflito") == 1
    assert envios.obter(item["id"]).aprovacao in resultados
