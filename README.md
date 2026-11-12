# Raiz IQ (Zero-Click) — Backend FastAPI | BBTS / ACME

Backend oficial do **Desafio 2: Plataforma de Inteligência Empresarial** desenvolvido pela equipe **Ctrl + Alt + Business** (João · Lana · Victor · Thiago).

Implementa 100% da arquitetura da Seção 9 da `PROPOSTA.md`, integrando-se diretamente ao Frontend em Next.js (`http://localhost:3000`).

---

## Principais Módulos

- **`app/main.py`**: Servidor FastAPI com CORS para `http://localhost:3000` e as 6 rotas principais:
  - `POST /chat`: Roteador Híbrido de Custo (1. Cache Semântico → 2. Calculadoras Determinísticas `R$ 0,00` → 3. RAG Híbrido com RBAC), Propagação de Sigilo (*High-Water Mark*), Trava Histórica contra versões revogadas e **Abstenção Honesta** (`"Não consta nas fontes"` + encaminhamento ao dono do domínio).
  - `GET /docs`: Catálogo completo (`11 vigentes + 3 substituídos`), grafo `vinculado_a` (`NG_010`), Diff de versões (`NG_111 v2 vs v3`, `RG_1100 v1 vs v2`) e Auditor de Inconsistências Temporais.
  - `GET /radar`: Radar proativo de prazos contratuais (`CTR_2026-012`), vigências de 18 meses (`NG/PX/GU`), limite de 150 dias (`CT`) e travas do ciclo de incentivo fiscal (`31/01`, `31/03`, `31/07`).
  - `GET /access`, `POST /access`, `POST /access/decide`: Governança Data Mesh / RBAC com aprovação via **Resposta Curada** pela Curadora da GGC e log imutável na tabela `auditoria`.
  - `POST /reports`: Geração real de apresentação executiva `.pptx` (`python-pptx`) do Programa Ideias em Campo 2027 com notas do apresentador citando `NT_2026-021 v1.0.0` e `RG_1100 v2.0.0`.
  - `GET /ingest` e `POST /ingest`: Pipeline da Arquitetura Medalhão (**Bronze → Silver → Gold**) com extração de hash `SHA-256` dos PDFs em `data/docs_acervo/` e quarentena automática de revogados.
- **`app/models.py`**: Banco de dados SQLAlchemy (`SQLite` padrão ou `Postgres` via `DATABASE_URL`) com as 6 entidades da proposta (`documento`, `chunk`, `fato`, `usuario`, `pedido_acesso`, `auditoria`) populado automaticamente no startup a partir de `data/acervo_estruturado_acme_bbts.json`.
- **`app/tools.py`**: Calculadoras determinísticas auditadas (`calcular_prazos_ferias`, `limite_ausencia`, `dias_por_faltas`, `quem_aprova`, `prazos_contrato`, `comparar_versoes`).
- **`tests/eval/test_benchmark_30.py`**: Suíte de avaliação automatizada com as **30 verificações e perguntas do Golden FAQ**, comprovando 100% de precisão e citação.

---

## Como Executar

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Iniciar o servidor FastAPI na porta 8000
uvicorn app.main:app --reload --port 8000
```

- Documentação Swagger UI: `http://localhost:8000/docs`
- Rodar a suíte de avaliação (30 testes Golden FAQ):
  ```bash
  pytest
  ```
