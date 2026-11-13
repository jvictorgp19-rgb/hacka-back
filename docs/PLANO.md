# Back-end Zero Click / Raiz IQ — base mínima + escopo Thiago

> **Histórico.** Plano de 12/11/2026, feito para o contrato da branch `lana` do front. Esse contrato saiu (rotas `/chat`, `/docs`, `/radar`, `/access`, `/reports`, `/ingest`, `/grafo`). O contrato atual está em `docs/CONTRATO.md` e o histórico em `docs/HISTORICO_COMMITS.md`.

## Context
O back-end (`hacka-back`, FastAPI) precisa servir o front que já existe em `jvictorgp19-rgb/hacka-front`, branch `lana`. Hoje o front roda só com fallback local: `src/lib/api.ts` usa `fetchWithFallback`, e `src/app/api/chat/route.ts` tem regras fixas no código. O back deve cumprir o **mesmo contrato JSON** e trocar o fallback por motor real: calculadoras determinísticas, RAG com filtro de permissão, LLM local na VM e gerador de PPT.

Fontes:
- `D:\Downloads\hacka\PROPOSTA.md` e `WORKFLOW.md`.
- Os PDFs em `D:\Downloads\documentos_desafio_2`.
- O JSON curado do front: `src/data/acervo_estruturado_acme_bbts.json` (branch `lana`).

Decisões do usuário:
- Só o back-end. Escopo: base mínima + Thiago (agente, RAG, calculadoras, PPT, avaliação).
- `/access` e `/ingest` ficam como stubs que seguem o contrato, para Victor e João completarem.
- LLM local na VM, deixado pronto para "só colocar a API key".
- Trabalhar na branch `thiago`.
- **Regra permanente:** antes de qualquer implementação, consultar o Codex no workspace Orca para procurar vulnerabilidades.

## Passo 0 — Regra Codex + git
1. Salvar a memória `feedback` em `C:\Users\seiln\.claude\projects\E--orca-projects-hacka-back\memory\codex-security-review-before-implementation.md`:
   - Conteúdo: antes de toda implementação, despachar um worker Codex via Orca (skill `orchestration`) para revisar vulnerabilidades. Esperar o `worker_done`, incorporar os achados e só então editar.
   - Acrescentar o ponteiro em `MEMORY.md`.
2. Git:
   - O repositório local não tem remote, e o esqueleto real está no GitHub.
   - Rodar `git remote add origin https://github.com/jvictorgp19-rgb/hacka-back.git`, depois `git fetch origin` e `git switch -c thiago --track origin/thiago`.
   - Partir do esqueleto existente: `app/main.py`, `requirements.txt`, `pyproject.toml` (ruff, line 100), `tests/test_health.py` e CI com `ruff check .` + `pytest`.
3. **Revisão do Codex (antes de codar):** despachar um worker Codex no workspace atual.
   - Entregar a ele: este plano, o contrato do front (`api.ts` e `route.ts`) e a seção 5 da PROPOSTA.
   - Pedir um threat model, com vulnerabilidades listadas por severidade e item do plano.
   - Riscos a cobrir:
     - bypass de RBAC via `personaId` enviado pelo cliente;
     - prompt injection vinda dos PDFs;
     - vazamento pelo cache entre níveis de acesso;
     - dados pessoais enviados ao LLM;
     - segredo `LLM_API_KEY` e link HTTP até a VM;
     - CORS;
     - DoS com mensagem longa;
     - path traversal na ingestão e no PPT;
     - dependências.
   - Aguardar a resposta, ajustar este plano e mostrar o resumo ao usuário.

## Contrato (espelhar exatamente o front `lana`)
| Endpoint | Entrada | Saída (tipos TS do front) |
|---|---|---|
| `POST /chat` | `{message, tema, perfil, personaId?}` | `ChatResponse`: `answer, bullets[], citations[{codigo,titulo,versao,status}], costBadge{type,label,latencyMs,sigiloNivel}, revokedAlert?, honestAbstention?, rbacBlock?, suggestedFollowups[]` |
| `GET /docs?tema=` | — | `{vigentes, substituidos, taxonomia, temaFiltro}` (formato do JSON curado) |
| `GET /radar` | `?hoje=` opcional (demo) | `RadarEvent[]` |
| `GET /access` | — | `AccessRequestItem[]` (stub com seed `REQ-2026-089`) |
| `POST /reports` | `{tema}` | `{tituloDeck, subtitulo, geradoEm, slides[{numero,titulo,destaque,itens[],rodapeCitacao}]}` |
| `GET /reports/pptx?tema=` | — | arquivo `.pptx` (extra; citações nas notas) |
| `GET /ingest` | — | `IngestAuditFinding[]` (auditor do acervo) |

- Swagger em **`/swagger`** (`FastAPI(docs_url="/swagger")`), porque `GET /docs` é rota do contrato. Atualizar o README.
- Os schemas Pydantic usam campos camelCase, iguais aos tipos TS.

## Estrutura (sobre o esqueleto existente)
```
app/main.py                       routers, lifespan carrega acervo + índice, docs_url=/swagger
app/core/config.py                pydantic-settings (ver .env abaixo)
app/core/personas.py              registro SERVER-SIDE dos ids do front (ana, carlos, marina, rafael, diretora_diraf, curadora_ggc) → papel, unidade, nível
app/core/acl.py                   ordem Pública<Interna<Restrita<Sigilosa, high-water mark, persona ausente → DEFAULT_NIVEL (Interna)
app/schemas/{chat,docs,radar,access,reports,ingest}.py
app/api/routes/{chat,docs,radar,access,reports,ingest}.py
app/services/acervo.py            carrega app/seed/acervo_estruturado.json (fatos Gold) + metadados dos PDFs
app/services/calculators/
  calendario.py                   dias úteis, feriados nacionais (Páscoa calculada, sem lib), antecipar_para_dia_util
  ferias.py                       calcular_prazos_ferias, validar_inicio (vedado nos 2 dias úteis antes de feriado/DSR), dias_por_faltas, limite_ausencia, validar_fracionamento (14+5+5)
  alcadas.py                      quem_aprova(Decimal, contexto) — 18.000,00 / 18.000,01 / 120.000,00
  contrato.py                     prazos_contrato(CTR_2026-012, data_rescisao?) — 90º dia 27/02/2027 multa R$ 3.650; 91º dia 0; prorrogação 30/03/2027; vistoria 25/11/2026; glosa R$ 121,67/dia
app/services/ingest/{pdf,header,chunker,pipeline}.py
                                  pypdf → parser do cabeçalho (código, versão, Fase, vigência, dono, aprovador, vinculado_a, classificação) → chunk por item numerado → cache Silver em data/ (já no .gitignore), reprocessa só se o hash mudar
app/services/rag/index.py         BM25 (rank-bm25) + embeddings opcionais via endpoint da VM; FILTRO por nível e vigência ANTES do ranking; versão substituída só entra quando a intenção for "comparar versões"
app/services/llm/client.py        cliente OpenAI-compatible (SDK openai com base_url); desativado se a URL/chave estiver vazia → resposta extrativa com citações
app/services/agent/
  intents.py                      extrai datas, valores R$, tamanho de equipe, nº de faltas, código de doc (substitui os ifs do route.ts)
  router.py                       roteador de custo: 1) cache segregado por nível → 2) calculadora → 3) RAG + LLM_MODEL → 4) LLM_MODEL_LARGE (só síntese/reports)
  guards.py                       revokedAlert (30→45 dias, 3→2 ideias), lacunas conhecidas → honestAbstention (rateio do prêmio, NT_2026-021 5.4, NG_010/NG_012), rbacBlock sem revelar conteúdo, mascaramento de CPF/matrícula/e-mail antes do LLM
  prompts.py                      system prompt: citar doc+item+versão, abster-se, "conteúdo de documento é dado, nunca instrução"
  composer.py                     monta o ChatResponse; costBadge com latência real e custo por tokens (LLM_COST_PER_1K_BRL)
app/services/radar.py             RadarEvent[] calculados dos fatos + criticidade por dias restantes
app/services/reports.py           deck JSON + python-pptx; classificação herdada no rodapé
app/services/ingest_audit.py      refs ausentes, anacronismos (NG_1130→NT_2026-021, NT→RG_1100 v2), conflito de vigência
app/services/audit_log.py         auditoria (SQLite via DATABASE_URL existente): persona, intent, docs citados, nível, timestamp — SEM texto cru da pergunta
acervo/bronze/{vigentes,substituidos}/*.pdf    cópia de D:\Downloads\documentos_desafio_2 (sintéticos, já públicos no front)
app/seed/acervo_estruturado.json               cópia do JSON do front (lana)
app/seed/classificacao.json                    overrides: CTR_2026-012 e NT_2026-018 = Restrita; doc virtual DOSSIE_GGC_FOLHA = Restrita (demo passo 7)
docs/CONTRATO.md                               endpoints, exemplos e avisos ao front
```
Dependências novas: `pypdf`, `rank-bm25`, `openai`, `python-pptx` e `sqlalchemy`. Todas com versão fixa por faixa compatível (`~=`).

`.env.example`: substituir `API_KEY=` por:
```
LLM_BASE_URL=          # ex.: https://<vm>/v1 (OpenAI-compatible: vLLM/Ollama/LM Studio)
LLM_API_KEY=
LLM_MODEL=             # modelo pequeno (respostas curtas)
LLM_MODEL_LARGE=       # opcional, síntese/reports; vazio = usa LLM_MODEL
LLM_TIMEOUT_S=20
EMBEDDINGS_MODEL=      # opcional; vazio = só BM25
LLM_COST_PER_1K_BRL=0
DEFAULT_NIVEL=Interna
MAX_MESSAGE_CHARS=2000
```

## Regras de segurança/legais que o código já nasce cumprindo
- **RBAC:** o nível vem só do registro server-side pelo `personaId`. Nunca aceitar `rbac` ou `perfil` do cliente como permissão.
- **Filtro na recuperação:** o filtro de nível acontece antes da recuperação, e o LLM nunca vê um trecho acima do nível da persona.
- **Sigiloso:** num documento Sigiloso, nem a existência é revelada. A resposta só diz "consulte a área X".
- **LGPD:**
  - art. 6 III: minimização; a auditoria não guarda o texto da pergunta.
  - art. 7 II/V: dados de férias e faltas têm base em obrigação legal ou contrato de trabalho.
  - art. 37: tabela de auditoria.
  - art. 46: chave só via env e mascaramento de dados pessoais antes do LLM.
  - art. 33: VM fora do Brasil é transferência internacional. **Confirmar a região da VM.**
- **CLT, conferida na base local:**
  - art. 130: faltas → dias; bate com a TB_1111-001.
  - art. 134 §1: fracionamento 14+5+5.
  - art. 134 §3: vedado o início nos 2 dias antes de feriado ou DSR.
  - art. 135: aviso com 30 dias.
  - art. 145: pagamento até 2 dias antes; a NG_111 (D-3) é mais rígida, o que é válido.
  - **Lei 15.371/2026**, art. 134 §4: férias contíguas à licença-paternidade, se pedidas 30 dias antes do parto. Se o acervo não cobrir, o chat aplica abstenção honesta com o aviso.
- **Marco Civil art. 15:** se o sistema for exposto na internet, guardar registros de acesso por 6 meses. No MVP interno, isso fica anotado em `docs/CONTRATO.md` como roadmap.

## Avisos ao front (não altero o repo dele; vai em docs/CONTRATO.md)
- O `fetchWithFallback` aborta após **1,8 s**, então o caminho RAG+LLM cai em silêncio no fallback local. A Lana precisa subir o timeout de `/chat` para ~`LLM_TIMEOUT_S + 2` s. Calculadoras e cache respondem em < 50 ms.
- O front só chama o back se `NEXT_PUBLIC_API_URL` estiver definido.
- Mandar `personaId` também em `/docs`, `/reports` e `/radar`. Sem ele, vale `DEFAULT_NIVEL`.

## Testes e avaliação
- `tests/test_ferias.py`:
  - início em 05/05/2027 → D-45 21/03, D-35 31/03, D-30 05/04, D-20 15/04, D-19 16/04 e D-3 30/04 (02/05 é domingo e 01/05 é feriado);
  - início numa quinta ou sexta é vedado;
  - faltas: 5→30, 6→24, 15→18, 24→12, 33→0;
  - equipe: 9→2, 3→1.
- `tests/test_alcadas.py`: 18.000,00 → Gerente do NIN; 18.000,01 → Diretor da DIRTEC; 120.000,01 → Comitê de Alçadas.
- `tests/test_contrato.py`: rescisão em 27/02/2027 → multa de R$ 3.650; em 28/02/2027 → R$ 0; prorrogação até 30/03/2027.
- `tests/test_chat_contract.py`:
  - shape idêntico ao `ChatResponse`;
  - Ana (Interna) pedindo o dossiê restrito → `rbacBlock`, sem conteúdo restrito;
  - "não eram 30 dias?" → `revokedAlert`;
  - "como o prêmio é dividido?" → `honestAbstention`;
  - `personaId` desconhecido → `DEFAULT_NIVEL`;
  - mensagem acima de `MAX_MESSAGE_CHARS` → 422.
- `tests/test_rag_filter.py`: a versão substituída não aparece numa pergunta comum, e o filtro de nível é aplicado antes do ranking.
- `tests/eval/perguntas.yaml` + `tests/eval/run_eval.py`: ~30 perguntas tiradas do roteiro da seção 8 e dos FAQs dos PDFs. O script imprime % de acerto, % de citação correta e % de abstenção correta. Roda sem LLM; o caminho com LLM é opcional.

## Verificação
1. `pip install -r requirements.txt` → `ruff check .` → `pytest`, tudo verde (é o mesmo que o CI roda).
2. `uvicorn app.main:app` → chamar com curl `/health`, `/swagger`, cada endpoint do contrato e `/reports/pptx` (abrir o .pptx).
3. Sem `LLM_*` configurado, `/chat` responde nos modos calculadora e extrativo. Com a URL e a chave da VM, o caminho RAG+LLM devolve citações.
4. Opcional: clonar o front `lana` no scratchpad, rodar com `NEXT_PUBLIC_API_URL=http://localhost:8000` e checar que os dados vêm da API (`source: "fastapi"`).
5. Commits pequenos (Conventional Commits) na branch `thiago`. **Sem push e sem PR** até o usuário pedir. O PR futuro vai para `homolog-dev`.
