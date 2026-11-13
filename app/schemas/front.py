"""Schemas no formato exato do hacka-front (src/contracts/models.ts e simulation.ts).

Campos `.optional()` do zod não aceitam null: as rotas usam response_model_exclude_none=True.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Tema = Literal["ferias", "inovacao", "locacao"]
Perspectiva = Literal["risks", "deadlines", "obligations", "values"]
ID = r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,79}$"


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True, populate_by_name=True)


class Citacao(BaseModel):
    id: str
    documentId: str
    codigo: str
    titulo: str
    versao: str
    status: str
    item: str
    trecho: str
    page: int | None = Field(default=None, gt=0)
    url: str | None = None


class Documento(BaseModel):
    id: str
    codigo: str
    titulo: str
    versao: str
    fase: str
    vigente: bool
    tema: Tema
    area: str
    camada: str
    resumo: str
    fileUrl: str | None = None
    substitui: str | None = None
    vigencia: str


class Fato(BaseModel):
    id: str
    title: str
    text: str
    tema: Tema
    area: str
    perspective: Perspectiva
    date: str | None = None
    valueCents: int | None = None
    citation: Citacao


class Contexto(_Entrada):
    conversationId: str = Field(default="", max_length=80)
    tema: Tema | Literal["todos"] = "todos"
    area: str = Field(default="", max_length=16)
    perspective: Perspectiva = "obligations"
    de: str = Field(default="", max_length=10, alias="from")
    to: str = Field(default="", max_length=10)
    persona: str = Field(default="", max_length=40)


class Pergunta(_Entrada):
    query: str = Field(min_length=1, max_length=4000)
    context: Contexto = Field(default_factory=Contexto)


class Resposta(BaseModel):
    id: str
    query: str
    status: Literal["answered", "abstained", "conflict", "access_required"]
    text: str
    facts: list[Fato]
    citations: list[Citacao]
    context: Contexto
    origin: Literal["api"] = "api"
    createdAt: str
    nextSteps: list[str]


class Prazo(BaseModel):
    id: str
    date: str
    title: str
    detail: str
    owner: str
    priority: Literal["Crítica", "Alta", "Normal"]
    fact: Fato


class Achado(BaseModel):
    id: str
    title: str
    detail: str
    documents: list[str]


class Pedido(BaseModel):
    id: str
    persona: str
    reason: str
    owner: str
    status: Literal["pending", "curated", "denied", "granted"]
    response: str
    createdAt: str
    decidedAt: str | None = None
    decidedBy: str | None = None


class NovoPedido(_Entrada):
    reason: str = Field(min_length=10, max_length=1000)
    persona: str | None = Field(default=None, max_length=40)
    owner: str | None = Field(default=None, max_length=16)


class DecisaoPedido(_Entrada):
    status: Literal["curated", "denied", "granted"]
    response: str = Field(min_length=1, max_length=1000)
    persona: str | None = Field(default=None, max_length=40)


class Registro(_Entrada):
    id: str = Field(pattern=ID)
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["analysis", "report"]
    persona: str | None = Field(default=None, max_length=40)
    # O conteúdo dos fatos vem do servidor: do cliente só se aproveita o id.
    facts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    context: Contexto = Field(default_factory=Contexto)
    createdAt: str = Field(default="", max_length=40)


class RegistroSalvo(BaseModel):
    id: str
    title: str
    kind: Literal["analysis", "report"]
    persona: str
    facts: list[Fato]
    context: Contexto
    createdAt: str


class Feedback(_Entrada):
    id: str = Field(pattern=ID)
    targetId: str = Field(pattern=ID)
    persona: str | None = Field(default=None, max_length=40)
    useful: bool
    reason: str = Field(default="", max_length=500)


class FeedbackSalvo(BaseModel):
    id: str
    targetId: str
    persona: str
    useful: bool
    reason: str


class FaixaFaltas(BaseModel):
    max: int = Field(ge=0)
    days: int = Field(ge=0)


class Calendario(BaseModel):
    de: str = Field(alias="from")
    to: str
    complete: bool
    holidays: list[str]
    description: str

    model_config = ConfigDict(populate_by_name=True)


class RegrasSimulacao(BaseModel):
    advanceDays: int = Field(gt=0)
    absencePercent: float = Field(gt=0, le=100)
    absenceTiers: list[FaixaFaltas]
    managerCapCents: int = Field(ge=0)
    directorCapCents: int = Field(ge=0)
    rentCents: int = Field(ge=0)
    dailyDiscountCents: int = Field(ge=0)
    globalCents: int = Field(gt=0)
    fineThroughDay: int = Field(gt=0)
    calendar: Calendario
    citations: list[Citacao]
