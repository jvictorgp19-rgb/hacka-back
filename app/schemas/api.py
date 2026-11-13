"""Tipos internos do motor do chat e das rotas de envio, identidade e auditoria.

O formato que o hacka-front consome está em app/schemas/front.py (espelho dos schemas zod).
Os campos ficam em camelCase porque várias rotas os devolvem como estão.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

Nivel = Literal["Pública", "Interna", "Restrita", "Sigilosa"]
Tema = Literal["ferias", "inovacao", "locacao"]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# ---------- motor do chat (app/services/agent/router.py) ----------
class ChatRequest(_Entrada):
    message: str = Field(min_length=1, max_length=4000)
    tema: str = Field(default="ferias", max_length=30)


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
    # Interno, fora do JSON: a resposta usa dados pessoais dos envios da própria pessoa. Quem
    # guarda histórico não guarda esse texto (LGPD art. 6º, III, e art. 16).
    _dados_pessoais: bool = PrivateAttr(default=False)

    @property
    def dados_pessoais(self) -> bool:
        return self._dados_pessoais

    def com_dados_pessoais(self, valor: bool) -> "ChatResponse":
        self._dados_pessoais = valor
        return self


# ---------- auditoria do acervo (GET /audit/findings) ----------
class IngestAuditFinding(BaseModel):
    id: str
    camada: Literal["Bronze (Raw PDF)", "Silver (Validated Chunk)", "Gold (Curated Graph)"]
    severidade: Literal["Inconsistência Temporal", "Documento Referenciado Ausente",
                        "Conflito de Vigência"]
    documentosEnvolvidos: list[str]
    descricao: str
    acaoRecomendada: str


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
    decidedBy: str | None = None
    decidedAt: str | None = None
    response: str | None = None
    ferias: FatosFerias | None = None  # só para quem enviou, os aprovadores e a GEPEC
    saved: bool = True
    fileAvailable: bool = False
    canApprove: bool = False


class UploadDecision(_Entrada):
    status: Literal["aprovado", "recusado"]
    response: str = Field(default="", max_length=1000)


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

