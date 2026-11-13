"""Respostas das rotas do hacka-front, montadas com os serviços do back.

Cada função recebe o sujeito já resolvido e só devolve o que ele pode ver. Mapa tela a rota:
docs/CONTRATO.md, seção "Telas do hacka-front".
"""

import re
import uuid
from datetime import UTC, date, datetime

from app.core.auth import Sujeito
from app.core.personas import Persona
from app.core.setores import setores
from app.schemas.api import ChatRequest, ChatResponse
from app.schemas.front import Contexto, Feedback, Registro
from app.services import evidencias, registros
from app.services.acervo import get_acervo
from app.services.agent import guards
from app.services.agent.router import responder
from app.services.calculators import alcadas, calendario, contrato, ferias
from app.services.evidencias import Links
from app.services.ingest_audit import auditar
from app.services.radar import criticidade, eventos_visiveis
from app.services.rag.index import normalizar

_REVOGADA = re.compile(r"^(\S+) v(\d+\.\d+\.\d+)")
ORIENTACAO = "Solicitar orientação"
OCULTA = "Resposta oculta: uma das fontes não está mais disponível para o seu perfil."
SEM_HISTORICO = ("Resposta calculada com os dados dos seus envios. Ela não fica guardada no "
                 "histórico (LGPD art. 6º, III): pergunte de novo para ver.")
CALENDARIO_DE, CALENDARIO_ATE = date(2026, 1, 1), date(2028, 12, 31)
# Pedido de acesso de exemplo, o mesmo do GET /access (app/services/access.py).
PEDIDOS_SEMENTE = [{
    "id": "REQ-2026-089", "persona": "ana", "owner": "GEPEC", "status": "pending",
    "reason": "Qual o detalhamento de auditoria da folha para ressarcimento de despesas em "
              "cancelamento de férias?",
    "response": "", "createdAt": "2026-11-12T14:42:10Z",
}]


class NaoEncontrado(LookupError):
    pass


class SemPermissao(PermissionError):
    pass


class Conflito(Exception):
    pass


class Invalido(Exception):
    pass


def _agora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------- acervo ----------
def _vigencia(meta: dict, cab: dict, vigente: bool) -> str:
    """Datas ISO, no mesmo formato do catálogo do front (catalog.ts), venham do seed ou do
    cabeçalho do PDF."""
    for fonte in (meta, cab):
        if fonte.get("vigencia_inicio") or fonte.get("vigencia_fim"):
            inicio = fonte.get("vigencia_inicio") or "consultar instrumento"
            return f"{inicio} a {fonte.get('vigencia_fim') or 'consultar instrumento'}"
    return "Consultar o documento" if vigente else "Versão anterior; consultar substituição"


def _resumo(meta: dict, motivo: str, titulo: str) -> str:
    legal = meta.get("resumo_legal_design")
    if isinstance(legal, dict) and legal.get("o_que_e"):
        return legal["o_que_e"]
    return meta.get("diferenca_critica_pegadinha") or motivo or titulo


def documentos(sujeito: Sujeito, links: Links) -> list[dict]:
    """Versões que o sujeito pode ver, vigentes e substituídas (cada uma pela própria regra)."""
    if not sujeito.acesso.identificado:
        return []
    acervo = get_acervo()
    seed = acervo.seed
    meta = {(d["codigo"], d["versao"]): d
            for d in seed["documentos_acervo"] + seed["documentos_substituidos_bloqueados"]}
    saida, vistos = [], set()
    for doc in acervo.documentos:
        if not acervo.pode(sujeito.acesso, doc):
            continue
        m = meta.get((doc.codigo, doc.versao), {})
        cab = acervo.cabecalhos.get(f"{doc.codigo}@{doc.versao}", {})
        substitui = m.get("substitui")
        saida.append({
            "id": evidencias.documento_id(doc.codigo, doc.versao), "codigo": doc.codigo,
            "titulo": doc.titulo, "versao": doc.versao, "fase": doc.fase,
            "vigente": doc.vigente, "tema": doc.tema, "area": doc.dominio, "camada": doc.tipo,
            "resumo": _resumo(m, doc.motivo, doc.titulo),
            "fileUrl": links.arquivo(doc.codigo, doc.versao),
            "substitui": substitui if isinstance(substitui, str) and substitui else None,
            "vigencia": _vigencia(m, cab, doc.vigente)})
        vistos.add((doc.codigo, doc.versao))
    for (codigo, versao), m in meta.items():  # versões só citadas no seed, sem PDF
        atual = acervo.vigente(codigo)
        if ((codigo, versao) in vistos or atual is None
                or not acervo.pode_versao(sujeito.acesso, codigo, versao)):
            continue
        saida.append({
            "id": evidencias.documento_id(codigo, versao), "codigo": codigo,
            "titulo": m.get("titulo") or codigo, "versao": versao,
            "fase": m.get("fase") or evidencias.VERSAO_ANTERIOR, "vigente": bool(m.get("vigente")),
            "tema": atual.tema, "area": atual.dominio, "camada": atual.tipo,
            "resumo": _resumo(m, "", m.get("titulo") or codigo), "fileUrl": None,
            "substitui": None, "vigencia": _vigencia(m, {}, bool(m.get("vigente")))})
    return saida[:100]


def arquivo_do_documento(sujeito: Sujeito, doc_id: str):
    """(caminho do PDF, documento) se o sujeito pode baixar; senão NaoEncontrado."""
    from app.services.ingest.pipeline import BRONZE

    codigo, _, versao = doc_id.partition("@")
    acervo = get_acervo()
    doc = acervo.documento(codigo, versao)
    if (doc is None or not doc.arquivo or not sujeito.acesso.identificado
            or not acervo.pode(sujeito.acesso, doc)):
        raise NaoEncontrado
    caminho = (BRONZE / doc.arquivo).resolve()
    if BRONZE.resolve() not in caminho.parents or caminho.suffix.lower() != ".pdf":
        raise NaoEncontrado
    return caminho, doc


# ---------- prazos e achados ----------
def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizar(texto)).strip("-")[:48]


def prazos(sujeito: Sujeito, links: Links, hoje: date) -> list[dict]:
    """Eventos do radar, cada um com o fato que o fundamenta (curado, ou o trecho do acervo)."""
    if not sujeito.acesso.identificado:
        return []
    acervo = get_acervo()
    curados = {(f["citation"]["codigo"], f.get("date")): f
               for f in evidencias.fatos(sujeito.acesso, links) if f.get("date")}
    itens = evidencias.itens_visiveis(sujeito.acesso)
    saida = []
    for e in eventos_visiveis(acervo, sujeito, hoje):
        codigo = e.fontes[0]
        doc = acervo.vigente(codigo)
        iso = e.data.isoformat()
        prazo_id = f"prazo-{_slug(e.titulo)}-{iso}"
        fato = curados.get((codigo, iso))
        if fato is None:
            trecho = itens.get((codigo, e.item))
            if trecho is None or doc is None:
                continue
            fato = {"id": prazo_id, "title": e.titulo, "text": e.detalhe, "tema": doc.tema,
                    "area": doc.dominio, "perspective": "deadlines", "date": iso,
                    "citation": evidencias.citacao_do_trecho(links, trecho)}
        dias = (e.data - hoje).days
        saida.append({"id": prazo_id, "date": iso, "title": e.titulo,
                      "detail": f"{e.detalhe} Faltam {dias} dias.",
                      "owner": doc.dominio if doc else fato["area"],
                      "priority": criticidade(dias), "fact": fato})
    return saida


def achados(sujeito: Sujeito, hoje: date) -> list[dict]:
    return [{"id": a.id, "title": a.severidade,
             "detail": f"{a.descricao} {a.acaoRecomendada}", "documents": a.documentosEnvolvidos}
            for a in auditar(get_acervo(), sujeito, hoje)]


# ---------- simuladores ----------
def _centavos(valor) -> int:
    return int(round(valor * 100))


FONTES_SIMULACAO = [*ferias.FONTES_TABELAS, "NT_2026-021", contrato.CODIGO]


def regras_simulacao(sujeito: Sujeito, links: Links) -> dict:
    """Regras das calculadoras do back, num pacote só (contrato do front).

    O pacote junta valores de documentos sigilosos (alçadas da NT_2026-021, aluguel e multa do
    CTR_2026-012). Quem não vê todas as fontes recebe 403: o contrato não tem como mandar só
    uma parte, e o valor sigiloso não sai (docs/PENDENCIAS_FRONT.md).
    """
    acervo = get_acervo()
    acesso = sujeito.acesso
    if not acervo.autorizado(FONTES_SIMULACAO, acesso):
        raise SemPermissao("Seu perfil não tem acesso a todas as fontes dos simuladores.")
    feriados = sorted(d.isoformat() for ano in range(CALENDARIO_DE.year, CALENDARIO_ATE.year + 1)
                      for d in calendario.feriados(ano))
    citacoes = {c["id"]: c for c in [f["citation"] for f in evidencias.fatos(acesso, links)]
                + evidencias.fontes_simulacao(acesso, links)}
    return {
        "advanceDays": ferias.ANTECEDENCIA_SOLICITACAO,
        "absencePercent": ferias.PERCENTUAL_AUSENCIA,
        "absenceTiers": [{"max": maximo, "days": dias}
                         for _, maximo, dias in ferias.TABELA_FALTAS],
        "managerCapCents": _centavos(alcadas.LIMITE_GERENTE),
        "directorCapCents": _centavos(alcadas.LIMITE_DIRETOR),
        "rentCents": _centavos(contrato.ALUGUEL),
        "dailyDiscountCents": _centavos(contrato.GLOSA_DIARIA),
        "globalCents": _centavos(contrato.VALOR_GLOBAL),
        "fineThroughDay": (contrato.ULTIMO_DIA_COM_MULTA - contrato.INICIO).days + 1,
        "calendar": {
            "from": CALENDARIO_DE.isoformat(), "to": CALENDARIO_ATE.isoformat(),
            "complete": False, "holidays": feriados,
            "description": "Feriados nacionais fixos e Sexta-feira Santa, os mesmos das "
                           "calculadoras do back. Feriados estaduais, municipais e pontos "
                           "facultativos não entram: valide com a unidade."},
        "citations": list(citacoes.values()),
    }


# ---------- conversa ----------
def _sem_markdown(texto: str) -> str:
    return texto.replace("**", "").strip()


def _status(chat: ChatResponse) -> str:
    """`access_required` só quando nada visível respondeu. Se o RAG respondeu com trechos que a
    pessoa vê e ainda apontou um setor sigiloso, a resposta sai e o aviso vai junto."""
    if chat.rbacBlock and not chat.citations:
        return "access_required"
    if chat.honestAbstention:
        return "abstained"
    if chat.revokedAlert:
        return "conflict"
    return "answered" if chat.citations else "abstained"


def _citacoes(chat: ChatResponse, fatos: list[dict], apoio: str, sujeito: Sujeito,
              links: Links) -> list[dict]:
    saida = {c["id"]: c for c in (f["citation"] for f in fatos)}
    cobertos = {c["codigo"] for c in saida.values()}
    for c in chat.citations:
        if c.codigo in cobertos:
            continue
        trecho = evidencias.trecho_que_apoia(c.codigo, apoio, sujeito.acesso)
        if trecho:
            citacao = evidencias.citacao_do_trecho(links, trecho)
            saida[citacao["id"]] = citacao
        cobertos.add(c.codigo)
    if chat.revokedAlert and (m := _REVOGADA.match(chat.revokedAlert.codigo)):
        codigo, versao = m.groups()  # versão antiga: só para quem pode vê-la
        trecho = evidencias.trecho_que_apoia(codigo, chat.revokedAlert.pegadinha,
                                             sujeito.acesso, versao=versao)
        if trecho:
            citacao = evidencias.citacao_do_trecho(links, trecho)
            saida[citacao["id"]] = citacao
    return list(saida.values())


def _proximos_passos(chat: ChatResponse, status: str, fatos: list[dict]) -> list[str]:
    if status == "access_required":
        passos = [ORIENTACAO]
    elif chat.honestAbstention:
        passos = [chat.honestAbstention.botaoAcao or ORIENTACAO]
    else:
        passos = ["Ver fontes", "Explorar análise"] if fatos else ["Ver fontes"]
        if chat.rbacBlock:
            passos.append(ORIENTACAO)
    return passos + [s for s in chat.suggestedFollowups[:2] if s not in passos]


def perguntar(query: str, contexto: Contexto, sujeito: Sujeito,
              links: Links) -> tuple[dict, dict | None]:
    """Roda o agente do chat (agent/router.py). Devolve (Answer do front, cópia do histórico).

    A cópia é None para visitante. Ela guarda a pergunta mascarada, só o id dos fatos e as
    citações sem link: tudo é refeito na leitura, com o acesso e o endereço de quem lê. Resposta
    feita com os envios da pessoa não entra no histórico (dado pessoal; LGPD art. 6º, III).
    """
    chat = responder(ChatRequest(message=query, tema=contexto.tema), sujeito)
    status = _status(chat)
    bullets = [_sem_markdown(b) for b in chat.bullets]
    if status == "access_required":
        texto = chat.rbacBlock.mensagem
        fatos, citacoes = [], []
    else:
        texto = _sem_markdown(chat.answer)
        apoio = " ".join([query, texto, *bullets])
        codigos = [c.codigo for c in chat.citations]
        fatos = evidencias.relacionados(codigos, apoio, sujeito.acesso, links)
        citacoes = _citacoes(chat, fatos, apoio, sujeito, links)
        if bullets:
            texto += "\n" + "\n".join(f"• {b}" for b in bullets)
        if chat.rbacBlock:
            texto += "\n" + chat.rbacBlock.mensagem
    resposta = {
        "id": str(uuid.uuid4()), "query": guards.mascarar(query), "status": status,
        "text": texto, "facts": fatos, "citations": citacoes,
        "context": {**contexto.model_dump(by_alias=True), "persona": sujeito.id},
        "origin": "api", "createdAt": _agora(),
        "nextSteps": _proximos_passos(chat, status, fatos),
    }
    if sujeito.persona is None:
        return resposta, None
    copia = {**resposta, "facts": [{"id": f["id"]} for f in fatos],
             "citations": [{k: v for k, v in c.items() if k != "url"} for c in citacoes]}
    if chat.dados_pessoais:
        copia["text"] = SEM_HISTORICO
    return resposta, copia


def guardar_conversa(sujeito: Sujeito, copia: dict) -> None:
    registros.salvar("conversa", sujeito.id, copia["id"], copia)


def _reler(item: dict, sujeito: Sujeito, links: Links) -> dict:
    """Refaz fatos e links com o acesso de agora. Fonte que deixou de ser visível oculta a
    resposta inteira: o texto foi escrito a partir dela."""
    acesso = sujeito.acesso
    ids = list(dict.fromkeys(str(f.get("id", "")) for f in item.get("facts", [])))
    fatos = evidencias.por_ids(ids, acesso, links)
    citacoes = item.get("citations", [])
    if len(fatos) < len(ids) or not all(
            evidencias.pode_ver(acesso, c["codigo"], c["versao"]) for c in citacoes):
        return {**item, "text": OCULTA, "facts": [], "citations": []}
    return {**item, "facts": fatos,
            "citations": [{**c, "url": links.arquivo(c["codigo"], c["versao"])}
                          for c in citacoes]}


def conversas(sujeito: Sujeito, links: Links) -> list[dict]:
    """Da mais antiga à mais nova (ordem do front), já relidas com o acesso atual."""
    if sujeito.persona is None:
        return []
    return [_reler(item, sujeito, links)
            for item in registros.listar("conversa", persona=sujeito.id)]


# ---------- pedidos de acesso ----------
def _decide(persona: Persona, dono: str) -> bool:
    """Curadoria do setor dono ou diretor da diretoria dele."""
    if dono in persona.cura_dominios:
        return True
    setor = setores().get(dono)
    return (persona.senioridade == "diretor" and setor is not None
            and persona.setor == setor.diretoria)


def _setores_que_decide(persona: Persona) -> set[str]:
    return {sigla for sigla in setores() if _decide(persona, sigla)}


def pedidos(sujeito: Sujeito) -> list[dict]:
    """Os pedidos da pessoa e os pedidos do setor que ela decide."""
    p = sujeito.persona
    if p is None:
        return []
    donos = _setores_que_decide(p)
    salvos = registros.listar("pedido", persona=p.id, donos=donos)
    ids = {s["id"] for s in salvos}
    semente = [dict(s) for s in PEDIDOS_SEMENTE
               if s["id"] not in ids and (s["persona"] == p.id or s["owner"] in donos)
               and registros.obter("pedido", s["id"]) is None]
    return salvos + semente


def criar_pedido(sujeito: Sujeito, motivo: str, dono_informado: str | None) -> dict:
    """`owner` é a sigla BBTS do setor que decide (a mesma `area` de /documents)."""
    dono = (dono_informado or "").strip()
    if dono not in setores():
        raise Invalido("Área responsável desconhecida: use a sigla BBTS do setor.")
    item = {"id": str(uuid.uuid4()), "persona": sujeito.id, "reason": guards.mascarar(motivo),
            "owner": dono, "status": "pending", "response": "", "createdAt": _agora()}
    registros.salvar("pedido", sujeito.id, item["id"], item, dono=dono)
    return item


def decidir_pedido(sujeito: Sujeito, pedido_id: str, status: str, resposta: str) -> dict:
    """Registra a orientação. "granted" fica só registrado: a permissão real vem do cadastro
    de acesso, nunca deste pedido (LAI art. 25, par. 1º)."""
    salvo = registros.obter("pedido", pedido_id)
    if salvo:
        dono, item, versao = salvo.dono, salvo.dados, salvo.versao
    else:  # pedido de exemplo, ainda não gravado
        item = next((dict(s) for s in PEDIDOS_SEMENTE if s["id"] == pedido_id), None)
        dono, versao = (item["owner"] if item else None), None
    p = sujeito.persona
    if item is None or p is None or not (p.id == item["persona"] or _decide(p, dono)):
        raise NaoEncontrado
    if p.id == item["persona"] or not _decide(p, dono):
        raise SemPermissao("Quem decide é a curadoria ou a diretoria do setor dono.")
    if item["status"] != "pending":
        raise Conflito("Pedido já decidido.")
    item = {**item, "status": status, "response": guards.mascarar(resposta),
            "decidedAt": _agora(), "decidedBy": p.nome}
    # Compare-and-set: de duas decisões ao mesmo tempo, só uma grava; a outra recebe 409.
    if not registros.trocar("pedido", item["persona"], pedido_id, item, dono, versao):
        raise Conflito("Pedido já decidido.")
    return item


# ---------- análises salvas e feedback ----------
def _data_iso(texto: str) -> str:
    """ISO em UTC. Sem fuso, vale como UTC: o resultado não depende do fuso do servidor."""
    try:
        data = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        if data.tzinfo is None:
            data = data.replace(tzinfo=UTC)
        return data.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return _agora()


def salvar_analise(sujeito: Sujeito, registro: Registro, links: Links) -> dict:
    ids = [str(f.get("id", "")) for f in registro.facts]
    item = {"id": registro.id, "title": guards.mascarar(registro.title), "kind": registro.kind,
            "persona": sujeito.id, "facts": evidencias.por_ids(ids, sujeito.acesso, links),
            "context": {**registro.context.model_dump(by_alias=True), "persona": sujeito.id},
            "createdAt": _data_iso(registro.createdAt)}
    registros.salvar("analise", sujeito.id, registro.id, item)
    return item


def analises(sujeito: Sujeito, links: Links) -> list[dict]:
    """As análises da pessoa. Os fatos são refeitos agora: link e acesso atuais."""
    if sujeito.persona is None:
        return []
    saida = []
    for item in registros.listar("analise", persona=sujeito.id):
        ids = [f["id"] for f in item.get("facts", [])]
        saida.append({**item, "facts": evidencias.por_ids(ids, sujeito.acesso, links)})
    return saida


def salvar_feedback(sujeito: Sujeito, fb: Feedback) -> dict:
    item = {"id": fb.id, "targetId": fb.targetId, "persona": sujeito.id, "useful": fb.useful,
            "reason": guards.mascarar(fb.reason)}
    registros.salvar("feedback", sujeito.id, fb.targetId, item)  # um por alvo e pessoa
    return item


def feedbacks(sujeito: Sujeito) -> list[dict]:
    if sujeito.persona is None:
        return []
    return registros.listar("feedback", persona=sujeito.id)
