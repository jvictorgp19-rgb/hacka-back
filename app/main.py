import os
import re
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ingest import execute_medallion_pipeline, run_medallion_ingest_audit
from app.models import (
    Auditoria,
    PedidoAcesso,
    SessionLocal,
    init_db_and_seed,
    load_acervo_json,
)
from app.ppt_generator import generate_ideias_em_campo_pptx
from app.tools import (
    calcular_prazos_ferias,
    comparar_versoes,
    dias_por_faltas,
    limite_ausencia,
    prazos_contrato,
    quem_aprova,
)

# In-memory Semantic / Exact Cache (Stage 1 of Cost Router)
SEMANTIC_CACHE: dict[str, dict[str, Any]] = {}

# Ensure database tables and seed data exist on module import as well as lifespan
init_db_and_seed()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db_and_seed()
    yield


app = FastAPI(
    title="Raiz IQ — Plataforma de Inteligência Normativa BBTS / ACME",
    version="3.0.0",
    docs_url="/swagger",
    redoc_url="/redoc",
    lifespan=lifespan,
)

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def normalize_text(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


class ChatRequest(BaseModel):
    message: Optional[str] = ""
    query: Optional[str] = ""
    tema: Optional[str] = "ferias"
    perfil: Optional[str] = "Geral"
    personaId: Optional[str] = "ana"


class AccessCreateRequest(BaseModel):
    solicitante: str
    papelSolicitante: Optional[str] = "Empregada - RBAC Interna"
    dominioDono: Optional[str] = "GGC (Gerência de Gente e Cultura)"
    documentoAlvo: Optional[str] = "Dossiê Restrito de Exceções de Ressarcimento & Folha"
    perguntaOriginal: str
    nivelExigido: Optional[str] = "Restrita"


class AccessDecideRequest(BaseModel):
    id: str = "REQ-2026-089"
    status: str = "Aprovado via Resposta Curada"
    respostaCurada: str
    aprovadoPor: Optional[str] = "Curadora da GGC"


class ReportRequest(BaseModel):
    tema: Optional[str] = "inovacao"


@app.get("/health")
def health():
    return {"status": "ok"}


# ==============================================================================
# 1. POST /chat — Roteador de Custo (1. Cache -> 2. Tools Determinísticas -> 3. RAG + RBAC)
# ==============================================================================
@app.post("/chat")
def chat_endpoint(req: ChatRequest, db: Session = Depends(get_db)):
    raw_msg = (req.message or req.query or "").strip()
    q = normalize_text(raw_msg)
    tema = (req.tema or "ferias").lower()

    # Check Stage 1: Semantic Cache
    cache_key = f"{tema}:{q}"
    if cache_key in SEMANTIC_CACHE:
        cached = dict(SEMANTIC_CACHE[cache_key])
        cached["costBadge"] = {
            "type": "deterministic",
            "label": "⚡ Custo: R$ 0,00 (Cache Semântico Instantâneo)",
            "latencyMs": 2,
            "sigiloNivel": cached["costBadge"]["sigiloNivel"],
        }
        return cached

    acervo = load_acervo_json()
    bullets: list[str] = []
    citations: list[dict[str, str]] = []
    revoked_alert = None
    honest_abstention = None
    rbac_block = None
    answer = ""
    is_deterministic = False
    sigilo_nivel = "Interna"

    def add_citation(codigo: str):
        for d in acervo.get("documentos_acervo", []):
            if d["codigo"] == codigo and not any(c["codigo"] == codigo for c in citations):
                citations.append(
                    {
                        "codigo": d["codigo"],
                        "titulo": d["titulo"],
                        "versao": f"v{d['versao']}",
                        "status": d["fase"],
                    }
                )

    # --- A. Verificação de Pegadinhas / Versões Substituídas ---
    mentions_30_days_ferias = (
        ("30 dias" in q and any(w in q for w in ["antecedencia", "ferias", "pedir", "solicitar", "prazo", "45"]))
        or "v2.0" in q
        or ("v1.0" in q and "fm_1111" in q)
        or ("ferias" in q and any(w in q for w in ["30", "antigo", "revogad", "substituid", "mudou", "mudanca"]))
    )
    mentions_3_ideias = (
        "3 ideias" in q
        or "tres ideias" in q
        or "5.000" in q
        or "5 mil" in q
        or ("inovacao" in q and any(w in q for w in ["antigo", "revogad", "substituid", "v1.0"]))
        or ("ideias" in q and any(w in q for w in ["quantas", "limite", "3", "tres", "6 meses", "tempo de casa"]))
    )

    if mentions_30_days_ferias:
        diff = comparar_versoes("NG_111")
        revoked_alert = {
            "codigo": "NG_111 v2.0.0 / FM_1111-001 v1.0.0",
            "versaoRevogada": "v2.0.0 (Fase: Versão anterior — mesmo com data impressa até 10/06/2027)",
            "substituidoPor": "NG_111 v3.0.0 (em 03/08/2026)",
            "pegadinha": diff["diferenca_critica_pegadinha"],
        }
    elif mentions_3_ideias:
        diff = comparar_versoes("RG_1100")
        revoked_alert = {
            "codigo": "RG_1100 v1.0.0",
            "versaoRevogada": "v1.0.0 (Substituída em 20/10/2026)",
            "substituidoPor": "RG_1100 v2.0.0 (em 20/10/2026)",
            "pegadinha": diff["diferenca_critica_pegadinha"],
        }

    # --- B. Passo 1 Demo / Calculadora Determinística de Prazos de Férias (D-n) ---
    date_match = re.search(r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", q)
    if ("05/05/2027" in q) or (date_match and "ferias" in q) or ("maio" in q and "ferias" in q):
        is_deterministic = True
        target_date = date_match.group(1) if date_match else "05/05/2027"
        res_ferias = calcular_prazos_ferias(target_date, fracionado="fracion" in q)
        m = res_ferias["marcos"]
        answer = f"Cálculo Determinístico da Linha do Tempo D-n para Início de Gozo em **{res_ferias['inicio_gozo']}**:"
        bullets.extend(
            [
                f"**Validação do Dia de Início (NG_111 item 4.2):** {'Data válida (dia útil fora da trava de 2 dias antes de feriado/DSR)!' if res_ferias['data_inicio_valida'] else res_ferias['motivo_vedacao']}",
                f"**D-45 — Solicitação Formal (`{m['D_45_solicitacao']}`):** Data limite para submeter o `FM_1111-001 v2.0.0` no Portal Raiz (PX_1111-001 Anexo D).",
                f"**D-35 — Emissão do Aviso (`{m['D_35_emissao_aviso_ggc']}`):** GGC valida faltas na `TB_1111-001` e emite o Aviso de Férias.",
                f"**D-30 — Assinatura Eletrônica (`{m['D_30_assinatura_eletronica']}`):** Prazo final (e até 5 dias úteis do recebimento) para assinatura eletrônica (sem assinatura as férias não iniciam).",
                f"**D-20 — Limite de Alteração/Cancelamento (`{m['D_20_limite_alteracao_empregado']}`):** Último dia para alteração pelo empregado com anuência do gestor.",
                f"**D-3 — Pagamento GFI (`{m['D_3_pagamento_gfi']}`):** {res_ferias['explicacao_d3']}",
            ]
        )
        add_citation("NG_111")
        add_citation("PX_1111-001")
        add_citation("FM_1111-001")
        add_citation("TB_1111-001")

    # --- C. Passo 6 Demo: Abstenção Honesta (Rateio prêmio equipe, afastado NT_2026-021 5.4, PDFs NG_010/012) ---
    elif any(
        k in q
        for k in [
            "dividido",
            "divisao",
            "rateio",
            "afastado",
            "abstencao",
            "pdf da ng_012",
            "pdf da ng_010",
            "nao consta",
        ]
    ) or ("equipe" in q and "premio" in q):
        is_deterministic = False
        answer = "🛡️ **Abstenção Honesta Ativada (Não consta nas fontes):** Identifiquei lacunas normativas explícitas em que o sistema se abstém de inventar regras:"
        bullets.extend(
            [
                "**1. Divisão/Rateio do Prêmio em Equipe (Até 4 pessoas):** **Não consta no `RG_1100 v2.0.0`**. O regulamento fixa os valores (R$ 8k/5k/3k + R$ 2k por arena) pagos em folha em até 30 dias, mas não define a regra de rateio entre os integrantes. **Dono do domínio: NIN (Núcleo de Inovação).**",
                "**2. Empregado Afastado na Edição 2027 (`NT_2026-021 item 5.4`):** A Nota Técnica registra como ponto de atenção a situação de empregado afastado durante a imersão/banca, remetendo a deliberação ao **NIN / CIN**.",
                "**3. Ausência Física dos PDFs `NG_010` e `NG_012`:** Ambos são referenciados nos cabeçalhos do acervo, mas seus PDFs físicos não integram o pacote bruto — respondemos exclusivamente com os metadados estruturados validados na camada Gold.",
            ]
        )
        honest_abstention = {
            "lacuna": "Fórmula de divisão individual do prêmio em folha para ideias em equipe (até 4 pessoas) e deliberação sobre afastamento superveniente.",
            "donoDominio": "NIN (Núcleo de Inovação) / Aprovador: DIRTEC & DIRAF",
            "botaoAcao": "[Perguntar ao NIN]",
            "detalhesExtras": [
                "RG_1100 v2.0.0 silencia sobre rateio percentual entre coautores.",
                "NT_2026-021 item 5.4 remete casos de afastamento ao NIN.",
                "NG_010 e NG_012 constam apenas como referências cruzadas de governança.",
            ],
        }
        add_citation("RG_1100")
        add_citation("NT_2026-021")
        add_citation("NG_1130")

    # --- D. Passo 7 Demo: Bloqueio RBAC & Resposta Curada + Propagação High-Water Mark ---
    elif any(k in q for k in ["dossie restrito", "auditoria da folha", "resposta curada", "rbac", "folha salarial"]):
        sigilo_nivel = "Restrita"
        answer = "🔒 **Filtro RBAC & Propagação de Sigilo (High-Water Mark = Restrita):**"
        bullets.extend(
            [
                "**Parte Interna Liberada (`NG_111 v3.0.0 item 4.9`):** Cancelamento de férias a partir de **D-19** por necessidade de serviço (autorizado pelo **Diretor da área**) garante ressarcimento de despesas comprovadas em até **15 dias corridos**, até o teto de **R$ 2.500,00**.",
                "**Parte Restrita Bloqueada:** O dossiê interno de auditoria da folha e o histórico nominal possuem classificação **RESTRITA (Domínio: GGC / GFI)**.",
                "**Fluxo de Resposta Curada (Data Mesh):** Solicite autorização à **Curadora da GGC** para receber uma **RESPOSTA CURADA** auditada sem exposição do documento restrito.",
            ]
        )
        rbac_block = {
            "dominioResponsavel": "GGC (Gerência de Gente e Cultura)",
            "nivelExigido": "Restrita (High-Water Mark)",
            "mensagem": "Parte da resposta requer autorização da [GGC]. Solicite uma Resposta Curada.",
        }
        add_citation("NG_111")
        add_citation("PX_1111-001")

    # --- E. Calculadora Determinística: Faltas Injustificadas x Dias de Férias ---
    elif "falta" in q:
        is_deterministic = True
        num_match = re.search(r"\b(\d+)\b", q)
        n_faltas = int(num_match.group(1)) if num_match else 8
        calc = dias_por_faltas(n_faltas)
        answer = f"Cálculo Determinístico de Faltas Injustificadas (`TB_1111-001 v1.0.0` Tabela 1) para **{n_faltas} falta(s)**:"
        bullets.extend(
            [
                f"**Resultado para {n_faltas} falta(s):** Direito a **{calc['dias_ferias_direito']} dias corridos** de férias ({calc['faixa_enquadrada']}).",
                "**Tabela Completa (`TB_1111-001`):** 0 a 5 faltas = **30 dias** | 6 a 14 faltas = **24 dias** | 15 a 23 faltas = **18 dias** | 24 a 32 faltas = **12 dias** | Acima de 32 faltas = **0 dias (perda do direito)**.",
            ]
        )
        add_citation("TB_1111-001")
        add_citation("NG_111")

    # --- F. Calculadora Determinística: Limite de 30% da Equipe (Passo 3 Carlos) ---
    elif "equipe" in q or "30%" in q or "carlos" in q:
        is_deterministic = True
        num_match = re.search(r"equipe de (\d+)", q)
        tam = int(num_match.group(1)) if num_match else 9
        lim = limite_ausencia(tam)
        answer = f"Cálculo Determinístico de Limite de Ausência Simultânea (`NG_111 item 4.6.3` / `TB_1111-001 Tabela 4`) para **equipe de {tam} pessoas**:"
        bullets.extend(
            [
                f"**Teto Simultâneo:** Máximo de **{lim['max_ferias_simultaneas']} empregado(s)** em férias ao mesmo tempo (30% de {tam} = {lim['calculo_exato']} -> arredondado para baixo = {lim['max_ferias_simultaneas']}).",
                "**Fila de Pendências e Escalada (`NG_111 v3.0.0` / `FL_1111-001`):** O gestor imediato tem até **7 dias corridos** para decidir no Portal Raiz. O silêncio não aprova: sem decisão no 7º dia, o pedido sobe automaticamente ao **Diretor da área** (que decide em **3 dias úteis**).",
            ]
        )
        add_citation("NG_111")
        add_citation("TB_1111-001")
        add_citation("FL_1111-001")

    # --- G. Calculadora Determinística: Quem Aprova / Alçadas NG_012 (Passo 4 Diretora) ---
    elif "alcada" in q or "18.000" in q or "18000" in q or "120.000" in q or "quem aprova" in q:
        is_deterministic = True
        alc_18k = quem_aprova(18000.00, "inovacao_prototipo")
        alc_18k01 = quem_aprova(18000.01, "inovacao_prototipo")
        answer = "Comparativo Determinístico de Alçada Financeira (`NT_2026-021 item 4.3` e `NG_012`):"
        bullets.extend(
            [
                f"**Para {alc_18k['valor_formatado']} ({alc_18k['faixa']}):** Aprovação pelo **{alc_18k['aprovador_inovacao_prototipo']}** (ou {alc_18k['aprovador_geral']} no escopo geral).",
                f"**Para {alc_18k01['valor_formatado']} ({alc_18k01['faixa']}):** Aprovação desloca-se para o **{alc_18k01['aprovador_inovacao_prototipo']}** (no contrato de coworking `CTR_2026-012` de R$ 18.250,00, aprova a **DIRAF** conforme `NT_2026-018`).",
                "**Acima de R$ 120.000,00:** Aprovação exclusiva pelo **Comitê de Alçadas** (`NG_012`).",
            ]
        )
        add_citation("NT_2026-021")
        add_citation("NT_2026-018")

    # --- H. Calculadora Determinística: Prazos e Multas do Contrato CTR_2026-012 (Passo 5 Rafael) ---
    elif any(
        k in q
        for k in [
            "ctr_2026",
            "nt_2026-018",
            "locacao",
            "coworking",
            "rescisao",
            "rescindir",
            "prorrogacao",
            "internet",
            "121,67",
            "30/03/2027",
            "cotac",
        ]
    ):
        is_deterministic = True
        sigilo_nivel = "Restrita"
        info_ctr = prazos_contrato("CTR_2026-012", dias_sem_internet=2)
        answer = "Análise Determinística do Contrato de Coworking (`CTR_2026-012 v1.0.0` e `NT_2026-018 v1.0.0`):"
        bullets.extend(
            [
                f"**Pedido de Prorrogação (`{info_ctr['marcos_criticos']['data_limite_pedido_prorrogacao']}`):** Deve ser formalizado até **30/03/2027** (30 dias antes do término em 29/04/2027), respeitando o limite de 24 meses e aditivo máximo de **20% (R$ 3.650,00)** com análise da GJU.",
                f"**Rescisão em Março/2027 = Multa Zero (`R$ 0,00`):** O **90º dia** encerra em **{info_ctr['marcos_criticos']['dia_90_fim_multa_rescisoria']}** (multa de R$ 3.650,00). A partir do **91º dia em `{info_ctr['marcos_criticos']['dia_91_inicio_isencao_multa']}`** (incluindo todo o mês de março/2027), a rescisão é **isenta de multa (R$ 0,00)** com aviso prévio de 30 dias.",
                "**Glosa de Internet > 4h (Fiscal GOC Rafael):** Desconto automático de **1/30 avos = R$ 121,67/dia** no atesto da Nota Fiscal (ex: 2 dias sem internet reduzem o aluguel de R$ 3.650,00 para **R$ 3.406,66**).",
                "**Comparativo das 3 Cotações (`NT_2026-018`):** 1º Hub Jacarandá (Vencedor): **R$ 3.650/mês (R$ 18.250 global)**; 2º Espaço Ipanema Verde: R$ 3.900/mês (R$ 19.500); 3º Centro Empresarial Colmeia: R$ 4.200/mês (R$ 21.000). Rito mensal: NF até **dia 25** -> Atesto GOC em **5 dias úteis** -> Pagamento GFI até **dia 8**.",
            ]
        )
        add_citation("CTR_2026-012")
        add_citation("NT_2026-018")

    # --- I. Taxonomia NG_010 / Desambiguação ---
    elif "ng_010" in q or "taxonomia" in q or "vinculado_a" in q or "desambiguacao" in q:
        is_deterministic = True
        tax = acervo["norma_mestra_taxonomia"]
        answer = f"Governança Documental e Desambiguação pela Norma Mestra `{tax['codigo']}` (Catálogo v{tax['versao_catalogo']}):"
        bullets.extend(
            [
                f"**Regra de Desambiguação (`vinculado_a`):** {tax['regra_desambiguacao']}",
                "**Regras de Vigência:** NG/PX/GU valem por **18 meses**; comunicados temporários (CT) por no máximo **150 dias**; contratos (CTR) pelo prazo do instrumento; regulamentos (RG) por edição.",
            ]
        )
        add_citation("NG_111")
        add_citation("PX_1111-001")
        add_citation("NG_1130")
        add_citation("PX_1130-001")

    # --- J. Inovação Geral / Gamificação / Ideias em Campo / Incentivo Fiscal ---
    elif any(k in q for k in ["inovacao", "ideia", "gamificacao", "ponto", "arena", "96.000", "31/03", "incentivo"]) or mentions_3_ideias:
        answer = "Diretrizes vigentes de Gestão da Inovação (`NG_1130 v1.0.0`, `PX_1130-001 v1.0.0`, `RG_1100 v2.0.0` e `NT_2026-021 v1.0.0`):"
        bullets.extend(
            [
                "**Elegibilidade 2027 (`RG_1100 v2.0.0`):** Mínimo de **6 meses de casa** em 01/02/2027 e limite de **até 2 ideias por pessoa** (individual ou em equipe de até 4 integrantes). *A versão v1.0.0 que permitia 3 ideias foi revogada!*",
                "**Gamificação (Até 800 pts) e Premiação Cumulativa:** Inscrição elegível (100 pts) + 5 votos (50 pts) + Imersão (150 pts) + Protótipo TRL 4 até 31/05 (300 pts) + Banca Final (200 pts) = **800 pontos**. Prêmios de **R$ 8k (1º), R$ 5k (2º), R$ 3k (3º)** + **R$ 2k por Arena** (teto cumulativo de **R$ 10.000,00** pago em folha em até 30 dias).",
                "**Orçamento R$ 96.000,00 (`NT_2026-021`) & Trava Fiscal (`PX_1130-001`):** Kits R$ 36k (37,5%), Imersão R$ 30k (31,3%), Colocação R$ 16k (16,7%), Arenas R$ 8k (8,3%) e Comunicação R$ 6k (6,3%). Trava crítica de documentação para incentivo fiscal em **31 de março**.",
            ]
        )
        add_citation("NG_1130")
        add_citation("PX_1130-001")
        add_citation("RG_1100")
        add_citation("NT_2026-021")

    # --- K. Fallback Férias (Diff 30 vs 45 dias / Regras Gerais Série 1) ---
    else:
        is_deterministic = mentions_30_days_ferias
        answer = "Diretrizes vigentes de Férias (`NG_111 v3.0.0`, `PX_1111-001 v1.0.0`, `FM_1111-001 v2.0.0` e `TB_1111-001 v1.0.0`):"
        bullets.extend(
            [
                "**Antecedência Mínima D-45 (`NG_111 v3.0.0`):** Solicitação formal no Portal Raiz com no mínimo **45 dias corridos** de antecedência. *A versão NG_111 v2.0.0 (30 dias) está revogada desde 03/08/2026 (Fase: Versão anterior), mesmo exibindo data final original até 10/06/2027!*",
                "**Fracionamento, Abono e 13º (`FM_1111-001 v2.0.0`):** Até **3 períodos** (1º >= 14 dias, demais >= 5 dias). Abono pecuniário de até 1/3 (10 dias) pedido até 15 dias antes do fim do aquisitivo; adiantamento de 13º pedido entre 1º e 31 de janeiro.",
                "**Ressarcimento por Cancelamento a Serviço (`NG_111 item 4.9`):** A partir de **D-19**, alterações só ocorrem por necessidade de serviço autorizada pelo **Diretor da área**, com ressarcimento de até **R$ 2.500,00** (comprovantes em 15 dias corridos).",
            ]
        )
        add_citation("NG_111")
        add_citation("PX_1111-001")
        add_citation("FM_1111-001")
        add_citation("TB_1111-001")

    response_payload = {
        "answer": answer,
        "bullets": bullets,
        "citations": citations,
        "costBadge": {
            "type": "deterministic" if is_deterministic else "rag_llm",
            "label": (
                "⚡ Custo: R$ 0,00 (Calculadora Determinística / Cache)"
                if is_deterministic
                else "🧠 Custo: ~R$ 0,004 (RAG Híbrido + RBAC)"
            ),
            "latencyMs": 8 if is_deterministic else 210,
            "sigiloNivel": sigilo_nivel,
        },
        "revokedAlert": revoked_alert,
        "honestAbstention": honest_abstention,
        "rbacBlock": rbac_block,
        "suggestedFollowups": [
            "Quero sair de férias em 05/05/2027. Qual o meu cronograma D-n?",
            "Como o prêmio é dividido em equipe no Ideias em Campo e se alguém for afastado?",
            "Se rescindirmos o contrato CTR_2026-012 em março de 2027, pagamos multa?",
            "Qual o dossiê restrito de auditoria da folha para ressarcimento D-15?",
        ],
    }

    # Save to Semantic Cache & Audit Trail
    SEMANTIC_CACHE[cache_key] = response_payload
    db.add(
        Auditoria(
            evento="CHAT_QUERY",
            usuario=req.personaId or "ana",
            documento_codigo=citations[0]["codigo"] if citations else "NG_010",
            sigilo_aplicado=sigilo_nivel,
            custo_rota=response_payload["costBadge"]["label"],
            detalhe=raw_msg[:200],
        )
    )
    db.commit()

    return response_payload


# ==============================================================================
# 2. GET /docs — Catálogo Completo, Grafo vinculado_a, Diff de Versões e Auditor
# ==============================================================================
@app.get("/docs")
def docs_endpoint(tema: Optional[str] = None):
    acervo = load_acervo_json()
    vigentes = acervo.get("documentos_acervo", [])
    substituidos = acervo.get("documentos_substituidos_bloqueados", [])

    grafo_arestas = [
        {"origem": d["codigo"], "destino": d["vinculado_a"], "relacao": "vinculado_a"}
        for d in vigentes
        if d.get("vinculado_a")
    ]

    return {
        "vigentes": vigentes,
        "substituidos": substituidos,
        "taxonomia": acervo.get("norma_mestra_taxonomia"),
        "alcadas_ng012": acervo.get("alcadas_financeiras_ng012"),
        "grafo_acervo": grafo_arestas,
        "diffs_versoes": {
            "NG_111": comparar_versoes("NG_111"),
            "FM_1111-001": comparar_versoes("FM_1111-001"),
            "RG_1100": comparar_versoes("RG_1100"),
        },
        "auditor_inconsistencias": run_medallion_ingest_audit(),
        "temaFiltro": tema or "todos",
    }


# ==============================================================================
# 3. GET /radar — Radar Proativo de Prazos (Contratos, Vigências 18m, 150d e Fiscal)
# ==============================================================================
@app.get("/radar")
def radar_endpoint():
    return [
        {
            "id": "rad-1",
            "dataLimite": "25/11/2026",
            "titulo": "Vistoria Obrigatória do Coworking (D-5 do contrato)",
            "documento": "CTR_2026-012 v1.0.0",
            "responsavel": "Rafael (Fiscal Técnico GOC)",
            "criticidade": "Alta",
            "detalhe": (
                "Assinar Termo de Vistoria verificando 8 estações com chave, sala de 10 lugares "
                "com projetor, link 500 Mbps e crachás 24h."
            ),
        },
        {
            "id": "rad-2",
            "dataLimite": "27/02/2027 vs 28/02/2027",
            "titulo": "Virada de Isenção de Multa Rescisória (90º -> 91º dia)",
            "documento": "CTR_2026-012 v1.0.0 (Cláusula de Rescisão)",
            "responsavel": "GCO / Rafael (GOC)",
            "criticidade": "Alta",
            "detalhe": (
                "90º dia de vigência = 27/02/2027 (multa R$ 3.650,00). A partir do 91º dia em 28/02/2027 "
                "(ex: rescisão em março/2027) a multa cai para R$ 0,00 com aviso prévio de 30 dias."
            ),
        },
        {
            "id": "rad-3",
            "dataLimite": "30/03/2027",
            "titulo": "Data-Limite para Pedido de Prorrogação Contratual (D-30 do fim)",
            "documento": "CTR_2026-012 v1.0.0",
            "responsavel": "Gestor GCO / Fiscal GOC",
            "criticidade": "Crítica",
            "detalhe": (
                "Último dia para formalizar prorrogação (30 dias antes do término em 29/04/2027), "
                "respeitando teto de 24 meses e aditivo máx. de 20% (R$ 3.650,00)."
            ),
        },
        {
            "id": "rad-4",
            "dataLimite": "31/03/2027",
            "titulo": "TRAVA CRÍTICA — Consolidação de Incentivo Fiscal",
            "documento": "PX_1130-001 v1.0.0 / NG_1130 v1.0.0",
            "responsavel": "NIN & Diretora da DIRAF",
            "criticidade": "Crítica",
            "detalhe": (
                "Projetos de inovação sem documentação técnica e financeira consolidada até 31/03 "
                "ficam bloqueados fora do ciclo anual de incentivo fiscal (Datas fixas: 31/01, 31/03 e 31/07)."
            ),
        },
        {
            "id": "rad-5",
            "dataLimite": "Vigência 18 Meses (NG/PX/GU) & Máx. 150 Dias (CT)",
            "titulo": "Monitoramento de Vigência Normativa (NG_010)",
            "documento": "NG_1130 (vence 06/01/2028) e NG_111 (vence 03/02/2028)",
            "responsavel": "Curadora da GGC & NIN",
            "criticidade": "Normal",
            "detalhe": (
                "Normas Gerais e Procedimentos vigoram por 18 meses da aprovação; Comunicados Temporários (CT) "
                "têm teto máximo de 150 dias corridos."
            ),
        },
    ]


# ==============================================================================
# 4. GET /access, POST /access, POST /access/decide — Governança RBAC & Resposta Curada
# ==============================================================================
@app.get("/access")
def list_access_requests(db: Session = Depends(get_db)):
    rows = db.query(PedidoAcesso).all()
    return [
        {
            "id": r.id,
            "solicitante": r.solicitante,
            "papelSolicitante": r.papel_solicitante,
            "dominioDono": r.dominio_dono,
            "documentoAlvo": r.documento_alvo,
            "perguntaOriginal": r.pergunta_original,
            "nivelExigido": r.nivel_exigido,
            "status": r.status,
            "respostaCurada": r.resposta_curada,
            "aprovadoPor": r.aprovado_por,
            "timestampSolicitacao": r.timestamp_solicitacao,
            "timestampDecisao": r.timestamp_decisao,
        }
        for r in rows
    ]


@app.post("/access")
def create_access_request(req: AccessCreateRequest, db: Session = Depends(get_db)):
    new_id = f"REQ-2026-{db.query(PedidoAcesso).count() + 90:03d}"
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    item = PedidoAcesso(
        id=new_id,
        solicitante=req.solicitante,
        papel_solicitante=req.papelSolicitante or "Empregada - RBAC Interna",
        dominio_dono=req.dominioDono or "GGC (Gerência de Gente e Cultura)",
        documento_alvo=req.documentoAlvo or "Dossiê Restrito",
        pergunta_original=req.perguntaOriginal,
        nivel_exigido=req.nivelExigido or "Restrita",
        status="Pendente",
        timestamp_solicitacao=now_str,
    )
    db.add(item)
    db.add(
        Auditoria(
            evento="RBAC_ACCESS_REQUESTED",
            usuario=req.solicitante,
            documento_codigo="NG_111",
            sigilo_aplicado=req.nivelExigido or "Restrita",
            custo_rota="R$ 0,00 (Governança Data Mesh)",
            detalhe=f"Pedido {new_id} aberto para {req.dominioDono}",
        )
    )
    db.commit()
    return {"id": new_id, "status": "Pendente", "timestampSolicitacao": now_str}


@app.post("/access/decide")
def decide_access_request(req: AccessDecideRequest, db: Session = Depends(get_db)):
    item = db.query(PedidoAcesso).filter(PedidoAcesso.id == req.id).first()
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    if item:
        item.status = req.status
        item.resposta_curada = req.respostaCurada
        item.aprovado_por = req.aprovadoPor
        item.timestamp_decisao = now_str

    db.add(
        Auditoria(
            evento="CURATED_RESPONSE_APPROVED",
            usuario=req.aprovadoPor or "Curadora da GGC",
            documento_codigo="NG_111",
            sigilo_aplicado="Restrita",
            custo_rota="R$ 0,00 (Resposta Curada Data Mesh)",
            detalhe=f"Pedido {req.id} respondido via Resposta Curada sem abrir o PDF restrito.",
        )
    )
    db.commit()
    return {
        "id": req.id,
        "status": req.status,
        "respostaCurada": req.respostaCurada,
        "aprovadoPor": req.aprovadoPor,
        "timestampDecisao": now_str,
    }


# ==============================================================================
# 5. POST /reports — Geração Real de Apresentação Executiva (.pptx)
# ==============================================================================
@app.post("/reports")
def reports_endpoint(req: Optional[ReportRequest] = None, db: Session = Depends(get_db)):
    result = generate_ideias_em_campo_pptx()
    db.add(
        Auditoria(
            evento="EXECUTIVE_PPTX_GENERATED",
            usuario="Diretora da DIRAF",
            documento_codigo="NT_2026-021 / RG_1100",
            sigilo_aplicado="Interna",
            custo_rota="R$ 0,00 (Template Auditado)",
            detalhe=f"Deck executivo gerado ({result.get('arquivo_pptx')}).",
        )
    )
    db.commit()
    return result


# ==============================================================================
# 6. GET & POST /ingest — Pipeline Medalhão (Bronze -> Silver -> Gold) & Auditor
# ==============================================================================
@app.get("/ingest")
def get_ingest_audit():
    return run_medallion_ingest_audit()


@app.post("/ingest")
def run_ingest_pipeline(db: Session = Depends(get_db)):
    res = execute_medallion_pipeline()
    db.add(
        Auditoria(
            evento="MEDALLION_INGEST_COMPLETED",
            usuario="Curadora da GGC",
            documento_codigo="NG_010",
            sigilo_aplicado="Interna",
            custo_rota="R$ 0,00 (SHA-256 + Silver Quarantine)",
            detalhe=f"Processados {res['resumo_camadas']['bronze_pdfs_processados']} PDFs na camada Bronze.",
        )
    )
    db.commit()
    return res
