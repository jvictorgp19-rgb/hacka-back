"""Respostas das rotas do hacka-front, montadas com os serviços do back.

Cada função recebe o sujeito já resolvido e só devolve o que ele pode ver. Mapa tela a rota:
docs/CONTRATO.md, seção "Telas do hacka-front".
"""

import re
import unicodedata
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

_REVOGADA = re.compile(r"^(\S+) v(\d+\.\d+\.\d+)")
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


class Conflito(ValueError):
    pass


def _agora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normal(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto.lower())
    return " ".join("".join(c for c in sem_acento if unicodedata.category(c) != "Mn").split())


# ---------- acervo ----------
def _vigencia(meta: dict, cab: dict, vigente: bool) -> str:
    if meta.get("vigencia_inicio"):
        return f"{meta['vigencia_inicio']} a {meta.get('vigencia_fim') or 'consultar instrumento'}"
    if cab.get("vigencia_inicio") or cab.get("vigencia_fim"):
        def br(iso: str | None) -> str:
            return calendario.br(date.fromisoformat(iso)) if iso else "consultar instrumento"
        return f"{br(cab.get('vigencia_inicio'))} a {br(cab.get('vigencia_fim'))}"
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
            "fase": m.get("fase") or "Versão anterior", "vigente": bool(m.get("vigente")),
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
    return re.sub(r"[^a-z0-9]+", "-", _normal(texto)).strip("-")[:48]


def prazos(sujeito: Sujeito, links: Links, hoje: date) -> list[dict]:
    """Eventos do radar, cada um com o fato que o fundamenta (curado, ou o trecho do acervo)."""
    if not sujeito.acesso.identificado:
        return []
    acervo = get_acervo()
    curados = {(f["citation"]["codigo"], f.get("date")): f
               for f in evidencias.fatos(sujeito.acesso, links) if f.get("date")}
    saida = []
    for e in eventos_visiveis(acervo, sujeito, hoje):
        codigo = e.fontes[0]
        doc = acervo.vigente(codigo)
        iso = e.data.isoformat()
        prazo_id = f"prazo-{_slug(e.titulo)}-{iso}"
        fato = curados.get((codigo, iso))
        if fato is None:
            trecho = evidencias.trecho_do_item(codigo, e.item, sujeito.acesso)
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
    if chat.rbacBlock:
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
        passos = ["Solicitar orientação"]
    elif chat.honestAbstention:
        passos = [chat.honestAbstention.botaoAcao or "Solicitar orientação"]
    else:
        passos = ["Ver fontes", "Explorar análise"] if fatos else ["Ver fontes"]
    return passos + [s for s in chat.suggestedFollowups[:2] if s not in passos]


def perguntar(query: str, contexto: Contexto, sujeito: Sujeito, links: Links) -> dict:
    """Roda o mesmo agente do POST /chat e devolve no formato Answer do front."""
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
    if bullets and status != "access_required":
        texto += "\n" + "\n".join(f"• {b}" for b in bullets)
    resposta = {
        "id": str(uuid.uuid4()), "query": guards.mascarar(query), "status": status,
        "text": texto, "facts": fatos, "citations": citacoes,
        "context": {**contexto.model_dump(by_alias=True), "persona": sujeito.id},
        "origin": "api", "createdAt": _agora(),
        "nextSteps": _proximos_passos(chat, status, fatos),
    }
    if sujeito.persona is not None:
        registros.salvar("conversa", sujeito.id, resposta["id"], resposta)
    return resposta


def conversas(sujeito: Sujeito) -> list[dict]:
    if sujeito.persona is None:
        return []
    return registros.listar("conversa", persona=sujeito.id)


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
        raise ValueError("Área responsável desconhecida: use a sigla BBTS do setor.")
    item = {"id": str(uuid.uuid4()), "persona": sujeito.id, "reason": guards.mascarar(motivo),
            "owner": dono, "status": "pending", "response": "", "createdAt": _agora()}
    registros.salvar("pedido", sujeito.id, item["id"], item, dono=dono)
    return item


def decidir_pedido(sujeito: Sujeito, pedido_id: str, status: str, resposta: str) -> dict:
    """Registra a orientação. "granted" fica só registrado: a permissão real vem do cadastro
    de acesso, nunca deste pedido (LAI art. 25, par. 1º)."""
    achado = registros.obter("pedido", pedido_id)
    if achado:
        _, dono, item = achado
    else:
        item = next((dict(s) for s in PEDIDOS_SEMENTE if s["id"] == pedido_id), None)
        dono = item["owner"] if item else None
    p = sujeito.persona
    if item is None or p is None or not (p.id == item["persona"] or _decide(p, dono)):
        raise NaoEncontrado
    if p.id == item["persona"] or not _decide(p, dono):
        raise SemPermissao("Quem decide é a curadoria ou a diretoria do setor dono.")
    if item["status"] != "pending":
        raise Conflito("Pedido já decidido.")
    item = {**item, "status": status, "response": guards.mascarar(resposta),
            "decidedAt": _agora(), "decidedBy": p.nome}
    registros.salvar("pedido", item["persona"], pedido_id, item, dono=dono)
    return item


# ---------- análises salvas e feedback ----------
def _data_iso(texto: str) -> str:
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(UTC) \
            .isoformat(timespec="seconds").replace("+00:00", "Z")
    except ValueError:
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
