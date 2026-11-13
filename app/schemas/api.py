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


# ---------- /grafo ----------
class GrafoNo(BaseModel):
    id: str
    tipo: Literal["documento", "referencia", "dominio"]
    rotulo: str
    codigo: str | None = None
    versao: str | None = None
    titulo: str | None = None
    categoria: str | None = None
    tema: str | None = None
    dominio: str | None = None
    nivel: Nivel | None = None
    vigente: bool | None = None


class GrafoAresta(BaseModel):
    origem: str
    destino: str
    tipo: Literal["substitui", "vinculado_a", "referencia", "pertence_a"]
    itens: list[str]


class GrafoResponse(BaseModel):
    nos: list[GrafoNo]
    arestas: list[GrafoAresta]


# ---------- /document-jobs (hacka-front: uploadSchema) ----------
class MotivoTriagem(BaseModel):
    tipo: str
    rotulo: str
    nivel: str
    ocorrencias: int
    paginas: list[int]
    criterio: str


class ClassificacaoSugerida(BaseModel):
    nivel: Literal["Interna", "Sigilosa"]
    setores: list[str]
    confianca: float
    resumo: str
    motivos: list[MotivoTriagem]


class SetorSugerido(BaseModel):
    sigla: str
    nome: str
    confianca: float


class FatosFerias(BaseModel):
    faltasInjustificadas: int | None = None
    origemFaltas: Literal["declarado", "contagem"] | None = None
    periodoInicio: str | None = None
    periodoFim: str | None = None
    admissao: str | None = None
    inicioGozo: str | None = None
    diasDeFerias: int | None = None  # TB_1111-001, Tabela 1
    paginas: list[int]


class UploadItem(BaseModel):
    """Os 5 primeiros campos são o uploadSchema do front; os demais detalham a triagem."""

    id: str
    name: str
    size: int
    status: Literal["waiting", "processing", "ready", "failed", "not_extracted"]
    message: str
    createdAt: str
    sha256: str | None = None
    formato: str | None = None
    paginas: int | None = None
    classificacao: ClassificacaoSugerida | None = None
    departamento: SetorSugerido | None = None
    revisaoHumana: bool
    aprovacao: Literal["pendente", "aprovado", "recusado", "dispensado"] | None = None
    aprovadores: str | None = None
    nivelFinal: Literal["Interna", "Sigilosa"] | None = None
    setoresFinais: list[str]
    podeDecidir: bool
    decidedBy: str | None = None
    decidedAt: str | None = None
    response: str | None = None
    ferias: FatosFerias | None = None  # só para quem enviou, os aprovadores e a GEPEC


class UploadDecision(_Entrada):
    status: Literal["approved", "rejected"]
    response: str = Field(default="", max_length=500)
    persona: str | None = Field(default=None, max_length=40)
    nivel: Literal["Interna", "Sigilosa"] | None = None
    setores: list[str] | None = Field(default=None, max_length=10)


# ---------- /identity (hacka-front: identitySchema) ----------
class Identity(BaseModel):
    """id, name e capabilities são o identitySchema do front; o resto descreve o acesso."""

    id: str
    name: str
    capabilities: list[str]
    modo: Literal["demo", "token"]
    setor: str | None = None
    setorNome: str | None = None
    cargo: str | None = None
    senioridade: str | None = None
    habilitacao: Nivel


class IdentityLogin(_Entrada):
    persona: str | None = Field(default=None, max_length=40)  # AUTH_MODE=demo
    token: str | None = Field(default=None, max_length=300)  # AUTH_MODE=token


# ---------- /analyses/charts (gráficos: o back agrega, o front desenha) ----------
class Ponto(BaseModel):
    x: str
    y: float


class Serie(BaseModel):
    nome: str
    pontos: list[Ponto]


class Grafico(BaseModel):
    id: str
    titulo: str
    tipo: Literal["barra", "barra_empilhada", "pizza", "linha", "heatmap"]
    eixoX: str
    eixoY: str
    series: list[Serie]
    nota: str | None = None
