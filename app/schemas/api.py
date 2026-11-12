"""Contrato JSON da API. Os nomes dos campos espelham os tipos TypeScript do front
(hacka-front, src/lib/api.ts e src/app/api/chat/route.ts); por isso estão em camelCase.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Nivel = Literal["Pública", "Interna", "Restrita", "Sigilosa"]
Tema = Literal["ferias", "inovacao", "locacao"]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# ---------- /chat ----------
class ChatRequest(_Entrada):
    message: str = Field(min_length=1, max_length=4000)
    tema: str = Field(default="ferias", max_length=30)
    perfil: str = Field(default="", max_length=80)
    personaId: str | None = Field(default=None, max_length=40)


class Citation(BaseModel):
    codigo: str
    titulo: str
    versao: str
    status: str


class CostBadge(BaseModel):
    type: Literal["deterministic", "rag_llm"]
    label: str
    latencyMs: int
    sigiloNivel: Nivel


class RevokedAlert(BaseModel):
    codigo: str
    versaoRevogada: str
    substituidoPor: str
    pegadinha: str


class HonestAbstention(BaseModel):
    lacuna: str
    donoDominio: str
    botaoAcao: str
    detalhesExtras: list[str]


class RbacBlock(BaseModel):
    dominioResponsavel: str
    nivelExigido: str
    mensagem: str


class ChatResponse(BaseModel):
    answer: str
    bullets: list[str]
    citations: list[Citation]
    costBadge: CostBadge
    revokedAlert: RevokedAlert | None = None
    honestAbstention: HonestAbstention | None = None
    rbacBlock: RbacBlock | None = None
    suggestedFollowups: list[str]


# ---------- /docs ----------
class DocsResponse(BaseModel):
    vigentes: list[dict]
    substituidos: list[dict]
    taxonomia: dict
    temaFiltro: str


# ---------- /radar ----------
class RadarEvent(BaseModel):
    id: str
    dataLimite: str
    titulo: str
    documento: str
    responsavel: str
    criticidade: Literal["Crítica", "Alta", "Normal"]
    detalhe: str


# ---------- /access ----------
class AccessRequestItem(BaseModel):
    id: str
    solicitante: str
    papelSolicitante: str
    dominioDono: str
    documentoAlvo: str
    perguntaOriginal: str
    nivelExigido: Nivel
    status: Literal["Pendente", "Aprovado via Resposta Curada", "Acesso Total Concedido"]
    respostaCurada: str | None = None
    timestampSolicitacao: str
    timestampDecisao: str | None = None
    aprovadoPor: str | None = None


# ---------- /reports ----------
class ReportRequest(_Entrada):
    tema: Tema = "inovacao"
    personaId: str | None = Field(default=None, max_length=40)


class Slide(BaseModel):
    numero: int
    titulo: str
    destaque: str
    itens: list[str]
    rodapeCitacao: str


class ReportResponse(BaseModel):
    tituloDeck: str
    subtitulo: str
    geradoEm: str
    slides: list[Slide]


# ---------- /ingest ----------
class IngestAuditFinding(BaseModel):
    id: str
    camada: Literal["Bronze (Raw PDF)", "Silver (Validated Chunk)", "Gold (Curated Graph)"]
    severidade: Literal["Inconsistência Temporal", "Documento Referenciado Ausente",
                        "Conflito de Vigência"]
    documentosEnvolvidos: list[str]
    descricao: str
    acaoRecomendada: str
