import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/raiz_iq.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class Documento(Base):
    __tablename__ = "documento"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), index=True, nullable=False)
    titulo = Column(String(255), nullable=False)
    categoria = Column(String(100), nullable=True)
    grupo = Column(String(100), nullable=True)
    serie = Column(String(100), nullable=True)
    versao = Column(String(30), nullable=False)
    fase = Column(String(50), nullable=False)
    vigente = Column(Boolean, default=True, nullable=False)
    vigencia_inicio = Column(String(30), nullable=True)
    vigencia_fim = Column(String(30), nullable=True)
    regra_vigencia = Column(String(255), nullable=True)
    vinculado_a = Column(String(50), nullable=True)
    substitui = Column(String(100), nullable=True)
    dono_dominio = Column(String(150), nullable=True)
    aprovador = Column(String(150), nullable=True)
    fiscal_tecnico = Column(String(150), nullable=True)
    sigilo = Column(String(30), default="Interna", nullable=False)
    resumo_ux = Column(Text, nullable=True)
    diferenca_critica_pegadinha = Column(Text, nullable=True)
    sha256_hash = Column(String(64), nullable=True)
    camada_medalhao = Column(String(30), default="Gold", nullable=False)


class Chunk(Base):
    __tablename__ = "chunk"

    id = Column(Integer, primary_key=True, index=True)
    documento_codigo = Column(String(50), index=True, nullable=False)
    versao = Column(String(30), nullable=False)
    vigente = Column(Boolean, default=True, nullable=False)
    item_secao = Column(String(100), nullable=False)
    conteudo = Column(Text, nullable=False)
    sigilo = Column(String(30), default="Interna", nullable=False)
    dono_dominio = Column(String(150), nullable=True)
    camada = Column(String(30), default="Gold", nullable=False)


class Fato(Base):
    __tablename__ = "fato"

    id = Column(Integer, primary_key=True, index=True)
    tema = Column(String(50), index=True, nullable=False)
    chave = Column(String(100), index=True, nullable=False)
    valor_json = Column(Text, nullable=False)
    documento_fonte = Column(String(50), nullable=False)
    item_fonte = Column(String(50), nullable=True)


class Usuario(Base):
    __tablename__ = "usuario"

    id = Column(String(50), primary_key=True, index=True)
    nome = Column(String(100), nullable=False)
    papel = Column(String(100), nullable=False)
    unidade = Column(String(100), nullable=False)
    rbac = Column(String(30), default="Interna", nullable=False)
    tema_padrao = Column(String(30), default="ferias", nullable=False)


class PedidoAcesso(Base):
    __tablename__ = "pedido_acesso"

    id = Column(String(50), primary_key=True, index=True)
    solicitante = Column(String(120), nullable=False)
    papel_solicitante = Column(String(120), nullable=False)
    dominio_dono = Column(String(120), nullable=False)
    documento_alvo = Column(String(200), nullable=False)
    pergunta_original = Column(Text, nullable=False)
    nivel_exigido = Column(String(30), default="Restrita", nullable=False)
    status = Column(String(60), default="Pendente", nullable=False)
    resposta_curada = Column(Text, nullable=True)
    aprovado_por = Column(String(120), nullable=True)
    timestamp_solicitacao = Column(String(40), nullable=False)
    timestamp_decisao = Column(String(40), nullable=True)


class Auditoria(Base):
    __tablename__ = "auditoria"

    id = Column(Integer, primary_key=True, index=True)
    evento = Column(String(100), nullable=False)
    usuario = Column(String(100), nullable=False)
    documento_codigo = Column(String(50), nullable=True)
    sigilo_aplicado = Column(String(30), default="Interna", nullable=False)
    custo_rota = Column(String(50), default="R$ 0,00 (Determinístico)", nullable=False)
    detalhe = Column(Text, nullable=False)
    criado_em = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


def get_acervo_path() -> Path:
    base_dir = Path(__file__).resolve().parent.parent
    return base_dir / "data" / "acervo_estruturado_acme_bbts.json"


def load_acervo_json() -> dict[str, Any]:
    path = get_acervo_path()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def init_db_and_seed() -> None:
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        if db.query(Documento).count() > 0:
            return

        acervo = load_acervo_json()

        # 1. Seed Usuarios (6 Personas Nominais)
        personas = [
            Usuario(
                id="ana",
                nome="Ana",
                papel="Analista / Empregada",
                unidade="Operações / Portal Raiz",
                rbac="Interna",
                tema_padrao="ferias",
            ),
            Usuario(
                id="carlos",
                nome="Carlos",
                papel="Gestor - Equipe de 9",
                unidade="Gerência Operacional",
                rbac="Interna",
                tema_padrao="ferias",
            ),
            Usuario(
                id="marina",
                nome="Marina",
                papel="Proponente - Ideias em Campo",
                unidade="Operações de Campo / NIN",
                rbac="Interna",
                tema_padrao="inovacao",
            ),
            Usuario(
                id="rafael",
                nome="Rafael",
                papel="Fiscal Técnico - GOC",
                unidade="GOC (Gerência de Operações de Campo)",
                rbac="Restrita",
                tema_padrao="locacao",
            ),
            Usuario(
                id="diretora_diraf",
                nome="Diretora da DIRAF",
                papel="Executiva - Alçada Diretoria",
                unidade="DIRAF / DIRTEC",
                rbac="Sigilosa",
                tema_padrao="inovacao",
            ),
            Usuario(
                id="curadora_ggc",
                nome="Curadora da GGC",
                papel="Dona do Domínio / Data Mesh",
                unidade="GGC (Gerência de Gente e Cultura)",
                rbac="Sigilosa",
                tema_padrao="ferias",
            ),
        ]
        db.add_all(personas)

        # 2. Seed Documentos Vigentes + Chunks
        for doc in acervo.get("documentos_acervo", []):
            gov = doc.get("governanca", {})
            dono = gov.get("dono_elaborador") or gov.get("dono_gestor_contrato") or "GGC"
            aprovador = gov.get("aprovador", "DIRAF")
            fiscal = gov.get("fiscal_tecnico") or gov.get("unidade_demandante")
            resumo = doc.get("resumo_legal_design", {}).get("o_que_e") or "Fluxograma oficial."
            sigilo_doc = "Restrita" if doc["codigo"] in ("CTR_2026-012", "NT_2026-018") else "Interna"

            db_doc = Documento(
                codigo=doc["codigo"],
                titulo=doc["titulo"],
                categoria=doc.get("categoria"),
                grupo=doc.get("grupo"),
                serie=doc.get("serie"),
                versao=doc["versao"],
                fase=doc["fase"],
                vigente=True,
                vigencia_inicio=doc.get("vigencia_inicio") or doc.get("aprovado_em"),
                vigencia_fim=doc.get("vigencia_fim"),
                regra_vigencia=doc.get("regra_vigencia"),
                vinculado_a=doc.get("vinculado_a"),
                substitui=doc.get("substitui"),
                dono_dominio=dono,
                aprovador=aprovador,
                fiscal_tecnico=fiscal,
                sigilo=sigilo_doc,
                resumo_ux=resumo,
                camada_medalhao="Gold",
            )
            db.add(db_doc)

            db.add(
                Chunk(
                    documento_codigo=doc["codigo"],
                    versao=doc["versao"],
                    vigente=True,
                    item_secao="Resumo Normativo & Governança",
                    conteudo=f"{doc['codigo']} v{doc['versao']} ({doc['titulo']}): {resumo}",
                    sigilo=sigilo_doc,
                    dono_dominio=dono,
                    camada="Gold",
                )
            )

        # 3. Seed Documentos Substituídos / Bloqueados (Camada Silver Quarentena)
        for sub in acervo.get("documentos_substituidos_bloqueados", []):
            db_sub = Documento(
                codigo=sub["codigo"],
                titulo=sub["titulo"],
                categoria="Substituído",
                grupo="Histórico",
                serie="Histórico",
                versao=sub["versao"],
                fase=sub["fase"],
                vigente=False,
                vigencia_inicio=sub.get("vigencia_original") or sub.get("aprovado_em"),
                substitui=sub.get("substituido_por"),
                sigilo="Interna",
                diferenca_critica_pegadinha=sub.get("diferenca_critica_pegadinha"),
                camada_medalhao="Silver",
            )
            db.add(db_sub)

        # 4. Seed Fatos Estruturados (Regras Simuladores)
        for tema_key, tema_val in acervo.get("jornadas_por_tema", {}).items():
            regras_sim = tema_val.get("regras_simuladores", {})
            for r_key, r_val in regras_sim.items():
                db.add(
                    Fato(
                        tema=tema_key,
                        chave=r_key,
                        valor_json=json.dumps(r_val, ensure_ascii=False),
                        documento_fonte="NG_111"
                        if tema_key == "ferias"
                        else "RG_1100"
                        if tema_key == "inovacao"
                        else "CTR_2026-012",
                        item_fonte="regras_simuladores",
                    )
                )

        # 5. Seed Pedido de Acesso RBAC Pendente (Passo 7 da Demo)
        db.add(
            PedidoAcesso(
                id="REQ-2026-089",
                solicitante="Ana (Analista / Empregada)",
                papel_solicitante="Empregada - RBAC Interna",
                dominio_dono="GGC (Gerência de Gente e Cultura)",
                documento_alvo="Dossiê Restrito de Exceções de Ressarcimento & Folha (GGC/GFI)",
                pergunta_original="Qual o detalhamento interno de auditoria da folha para ressarcimento de passagens não reembolsáveis canceladas em D-15 e histórico nominal da equipe?",
                nivel_exigido="Restrita",
                status="Pendente",
                timestamp_solicitacao="12/11/2026 11:42:10",
            )
        )

        # 6. Seed Auditoria Inicial
        db.add(
            Auditoria(
                evento="STARTUP_SEED_GOLD",
                usuario="Sistema Raiz IQ",
                documento_codigo="NG_010",
                sigilo_aplicado="Interna",
                custo_rota="R$ 0,00 (Bootstrap)",
                detalhe="Acervo estruturado (11 documentos vigentes + 3 substituídos) carregado na Arquitetura Medalhão.",
            )
        )

        db.commit()
    finally:
        db.close()
