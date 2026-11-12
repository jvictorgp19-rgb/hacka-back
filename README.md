
```markdown
# ⚙️ Zero Click (Raiz IQ) — Core API, Arquitetura Medalhão & Roteador Agêntico

> **Desafio 2: Plataforma de Inteligência Empresarial (HUBB/TS — Dites | Gecop | Dipin)**  
> *Backend em Python (FastAPI) para ingestão governada em camadas (Bronze/Silver/Gold), calculadoras determinísticas, controle de acesso RBAC/ABAC com Resposta Curada e geração automatizada de relatórios executivos.*

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)
![Architecture](https://img.shields.io/badge/Data_Mesh-Medallion_(Bronze/Silver/Gold)-F8D117)
![Benchmark](https://img.shields.io/badge/Eval_Suite-30%2F30_Passing_(100%25)-brightgreen)

---

## 🏗️ Arquitetura Técnica e Fluxo de Dados

```text
 Next.js (hacka-front)                       FastAPI (hacka-back)
 ┌──────────────────────┐   REST / JSON  ┌────────────────────────────────────────────┐
 │ Portal Minimalista   │ ─────────────► │ POST /chat    → Roteador FinOps → Tools/RAG│
 │ Simuladores & Timeline│               │ GET  /docs    → Catálogo, Diff & Auditor   │
 │ Radar & Governança   │               │ GET  /radar   → Prazos D-n, Contratos, SLA │
 │ Pedidos de Acesso    │               │ POST /access  → Fila RBAC & Resposta Curada│
 │ Modo Pitch (8 Passos)│               │ POST /reports → Gerador .PPTX (python-pptx)│
 └──────────────────────┘               │ POST /ingest  → Pipeline Bronze→Silver→Gold│
                                        └──────────────┬─────────────────────────────┘
                                                       │
                          SQLite / PostgreSQL + pgvector + Camada Gold (JSON/SQL)
