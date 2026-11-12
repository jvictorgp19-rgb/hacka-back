# Zero Click (Raiz IQ) — Core API, Arquitetura Medalhão & Roteador Agêntico (FastAPI)

> **Desafio 2: Plataforma de Inteligência Empresarial | Hackathon HUBB/TS (Dites · Gecop · Dipin)**  
> **Organização Sintética:** ACME Tecnologia e Serviços (Representação Institucional BBTS — BB Tecnologia e Serviços)  
> **Repositório Frontend complementar:** [`hacka-front` (Next.js + Design System BBTS + Simuladores Zero-Click)](https://github.com/jvictorgp19-rgb/hacka-front)

---

## 👥 Equipe Ctrl + Alt + Business

| Integrante | Papel no Projeto |
| :--- | :--- |
| **Thiago Santos Medeiros** | Arquitetura de Solução, Governança Normativa & Estratégia de Produto |
| **José Victor Guerra Pereira** | Engenharia Full-Stack, Integração de Sistemas & Orquestração |
| **Lana Sofia Alcântara da Silva Azevedo** | Engenharia Frontend/Backend, Legal Design, UX Writing & Simuladores Determinísticos |
| **Alberto Ramos de Souza Silva** | Inteligência Artificial, RAG Governado, Avaliação & FinOps |
| **João Sertoriel** | Engenharia de Dados, Pipeline Medalhão & Infraestrutura |

---

## 🏗️ Arquitetura Técnica & Pipeline Medalhão (`Bronze -> Silver -> Gold`)

O Backend do **Zero Click (Raiz IQ)** foi construído em **Python + FastAPI + SQLAlchemy** seguindo a premissa central da nossa proposta: **um LLM nunca deve calcular prazos, decidir alçadas financeiras no escuro ou recuperar chunks de normas revogadas/restritas sem filtro prévio**.

### Diagrama Geral da Arquitetura

```text
+-----------------------------------------------------------------------------------+
|                        FRONTEND: NEXT.JS (PORTAL RAIZ IQ)                         |
|   4 Abas Limpas (bbts.com.br)  |  6 Personas RBAC  |  Roteiro Demo (8 Passos)     |
+-----------------------------------------+-----------------------------------------+
                                          |  REST / JSON (CORS http://localhost:3000)
                                          v
+-----------------------------------------------------------------------------------+
|                     BACKEND: FASTAPI CORE ENGINE (PORTA 8000)                     |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  |                 ROTEADOR FINOPS DE CUSTO ("LLM ÚLTIMO RECURSO")             |  |
|  |  [1] Cache Semântico (R$ 0,00 | ~2ms)                                       |  |
|  |   |--> [2] Calculadoras Determinísticas tools.py (R$ 0,00 | ~8ms)           |  |
|  |         |--> [3] RAG Híbrido c/ Filtro RBAC Pré-Busca (~R$ 0,004)           |  |
|  |               |--> [4] Síntese Executiva & Gerador PPTX (python-pptx)       |  |
|  +-----------------------------------------------------------------------------+  |
|                                         |                                         |
|  +--------------------------------------+--------------------------------------+  |
|  |             GOVERNANÇA DATA MESH, RBAC/ABAC & HIGH-WATER MARK               |  |
|  |  * Filtro de Vigência (vigente = True) antes da recuperação                 |  |
|  |  * Propagação de Sigilo: Pública -> Interna -> Restrita -> Sigilosa         |  |
|  |  * Abstenção Honesta ("Não consta nas fontes" -> Encaminha ao Dono NIN/GGC) |  |
|  |  * Fluxo de Pedido de Acesso -> Aprovação via RESPOSTA CURADA + Auditoria   |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|          ARQUITETURA MEDALHÃO & PERSISTÊNCIA (SQLite / Postgres + pgvector)       |
|                                                                                   |
|  [CAMADA BRONZE]               [CAMADA SILVER]              [CAMADA GOLD]         |
|  14 PDFs brutos imutáveis  ->  Cabeçalhos normalizados  ->  11 Docs Vigentes      |
|  Extração de Hash SHA-256      Validação vinculado_a        Fatos Determinísticos |
|  (data/docs_acervo/)           Quarentena de 3 Revogados    Grafo NG_010 + Índice |
|                                Auditor Temporal de Datas    6 Tabelas SQLAlchemy  |
+-----------------------------------------------------------------------------------+
```

### Detalhamento das 3 Camadas da Arquitetura Medalhão (`app/ingest.py`)

1. **Camada Bronze (Ingestão Bruta Imutável):**
   - Armazena os PDFs originais em `data/docs_acervo/vigentes/` e `data/docs_acervo/substituidos/`.
   - Calcula o hash criptográfico **`SHA-256`** de cada arquivo binário para garantir rastreabilidade e integridade forense.
2. **Camada Silver (Normalização, Desambiguação `NG_010` e Quarentena):**
   - Extrai e valida os cabeçalhos normativos obrigatórios (`codigo`, `versao`, `fase`, `vigencia`, `vinculado_a`, `substitui`, `dono_elaborador`, `aprovador`).
   - Aplica a regra de desambiguação da **`NG_010`**: números sequenciais nunca são lidos isoladamente (`PX_1111-001` vincula-se à `NG_111` da Série 1, enquanto `PX_1130-001` vincula-se à `NG_1130` da Série 11).
   - Coloca automaticamente em **quarentena** qualquer documento com `Fase: Versão anterior` (`vigente = False`), impedindo que seus chunks contaminem a busca vetorial/lexical padrão.
   - Executa o **Auditor de Inconsistências Temporais** entre datas de assinatura, aprovação e referências cruzadas.
3. **Camada Gold (Fatos Estruturados, Grafo Normativo e Simuladores):**
   - Popula automaticamente as **6 tabelas do modelo relacional** (`documento`, `chunk`, `fato`, `usuario`, `pedido_acesso`, `auditoria`) a partir de `data/acervo_estruturado_acme_bbts.json`.
   - Alimenta as calculadoras determinísticas (`app/tools.py`), o Radar de Prazos (`/radar`) e o gerador de apresentações executivas (`app/ppt_generator.py`).

---

## 🛡️ Governança Data Mesh, RBAC/ABAC e Regra *High-Water Mark*

### 1. Filtro RBAC/ABAC na Recuperação (Antes do LLM)
Diferente de arquiteturas frágeis que tentam esconder dados sensíveis via prompt (*post-filtering*), o Raiz IQ aplica o controle de acesso **na camada de recuperação de dados**:
- Cada documento e chunk possui metadados de `sigilo` (`Pública`, `Interna`, `Restrita`, `Sigilosa`) e `dono_dominio` (`GGC`, `NIN`, `GCO`, `GOC`, `DIRAF`).
- Quando uma persona com nível `Interna` (ex.: **Ana**) consulta informações que dependem de dossiês de nível `Restrita`, o motor separa a regra normativa geral (liberada) e bloqueia o trecho restrito antes da geração.

### 2. Regra de Contaminação de Sigilo (*High-Water Mark*)
Sempre que uma resposta ou relatório combina múltiplas fontes do acervo, a classificação final herda obrigatoriamente o **maior nível de restrição** entre todos os insumos consultados:

$$\text{Sigilo}_{\text{Resposta}} = \max\big(\{\text{Pública} < \text{Interna} < \text{Restrita} < \text{Sigilosa}\}\big)$$

### 3. Fluxo de Pedido de Acesso & Resposta Curada (Sem Expor o PDF)
1. O colaborador recebe a parte pública/interna da resposta e o aviso: **`"Parte da resposta requer autorização da [GGC]."`**
2. Ao acionar `POST /access`, o pedido entra na fila da dona do domínio (**Curadora da GGC**).
3. A Curadora utiliza `POST /access/decide` para emitir uma **`RESPOSTA CURADA`** — uma orientação oficial auditada que resolve a dúvida operacional do colaborador **sem abrir nem compartilhar o documento restrito bruto**.
4. Toda a operação é gravada de forma imutável na tabela `auditoria`.

---

## ⚡ Roteador FinOps de Custo ("O LLM é o Último Recurso")

Cada requisição em `POST /chat` percorre uma cascata de 4 níveis projetada para maximizar a precisão e minimizar o custo operacional:

| Estágio do Roteador | Escopo de Atuação | Custo por Consulta | Latência Média | Exemplo de Consulta Atendida |
| :--- | :--- | :---: | :---: | :--- |
| **1. Cache Semântico / Exato** | Perguntas recorrentes do FAQ já validadas na sessão | **`R$ 0,00`** | `~2 ms` | *"Posso pedir férias com 30 dias de antecedência?"* |
| **2. Calculadoras Determinísticas (`tools.py`)** | Prazos `D-n`, faltas x férias, limite 30% equipe, alçadas `NG_012`, glosa `R$ 121,67/dia`, multa 90º/91º dia e Diff de versões | **`R$ 0,00`** | `~8 ms` | *"Quero sair de férias em 05/05/2027"* ou *"Alçada R$ 18.000,01"* |
| **3. RAG Híbrido + Guardrail de Abstenção** | Cruzamento interpretativo de cláusulas vigentes, verificação de lacunas e RBAC | **`~R$ 0,004`** | `~210 ms` | *"Como o prêmio é dividido em equipe no Ideias em Campo?"* |
| **4. Síntese Executiva & PPTX (`ppt_generator.py`)** | Consolidação de indicadores, orçamento e cronograma em slides `.pptx` auditados | **`~R$ 0,004`** | `~350 ms` | *Geração do Deck Executivo Ideias em Campo 2027* |

> **Impacto Financeiro (ROI Estimado):** Em uma operação com `2.000 consultas/mês` economizando `10 minutos` de busca manual por consulta (a um custo médio de `R$ 60/hora`), a plataforma gera uma economia produtiva de **`R$ 20.000,00/mês`** com custo residual de IA inferior a `R$ 3,00/mês`.

---

## 🔌 Documentação das 6 Rotas REST e Ferramentas Determinísticas (`tools.py`)

### Endpoints Oficiais da API (`app/main.py`)

| Método | Rota | Descrição Técnica |
| :---: | :--- | :--- |
| `GET` | `/health` | Healthcheck da aplicação (`{"status": "ok"}`). |
| `POST` | `/chat` | Roteador principal: executa cache, tools determinísticas ou RAG com RBAC, retornando `answer`, `bullets`, `citations`, `costBadge`, `revokedAlert`, `honestAbstention` e `rbacBlock`. |
| `GET` | `/docs` | Retorna os `11 documentos vigentes`, os `3 documentos substituídos`, o grafo `vinculado_a` (`NG_010`), os Diffs de versão e os achados do Auditor do Acervo. |
| `GET` | `/radar` | Retorna os alertas proativos de vencimento contratual (`CTR_2026-012`), vigências de 18 meses (`NG/PX/GU`), teto de 150 dias (`CT`) e travas fiscais (`31/01`, `31/03`, `31/07`). |
| `GET` / `POST` | `/access` | Lista e cria solicitações de acesso RBAC/ABAC encaminhadas ao dono do domínio (`GGC`, `NIN`, `GCO`). |
| `POST` | `/access/decide` | Permite à Curadora aprovar uma solicitação via **Resposta Curada** e registra o evento na tabela `auditoria`. |
| `POST` | `/reports` | Gera o arquivo físico **`reports_out/ideias_em_campo_2027_executivo.pptx`** (via `python-pptx`) com 3 slides executivos e citações normativas nas notas do apresentador. |
| `GET` / `POST` | `/ingest` | Executa o pipeline Medalhão (`Bronze -> Silver -> Gold`), calcula os hashes `SHA-256` dos PDFs em `data/docs_acervo/` e executa o Auditor de Inconsistências Temporais. |

### Funções Determinísticas (`app/tools.py`)

- **`calcular_prazos_ferias(inicio, fracionado)`**: Calcula `D-45`, `D-35`, `D-30`, `D-20`, `D-19` e `D-3`. Antecipa automaticamente `D-3` para o dia útil anterior quando cai em fim de semana ou feriado (ex.: para início em `05/05/2027`, `D-3` cairia no domingo `02/05/2027` e `01/05` é Dia do Trabalhador, antecipando para **sexta-feira `30/04/2027`** conforme `NG_111 item 4.5` e `PX_1111-001 Anexo D`) e valida dias vedados (`NG_111 item 4.2`).
- **`limite_ausencia(tamanho_equipe)`**: Aplica `floor(tamanho_equipe * 0.30)` com mínimo de `1` para equipes de 1 a 3 pessoas (`NG_111 item 4.6.3` / `TB_1111-001 Tabela 4`). Para a equipe de 9 pessoas de Carlos, retorna **`2`**.
- **`dias_por_faltas(n)`**: Aplica a Tabela 1 da `TB_1111-001 v1.0.0` (`0–5 -> 30d`, `6–14 -> 24d`, `15–23 -> 18d`, `24–32 -> 12d`, `≥ 33 -> 0d`).
- **`quem_aprova(valor, contexto)`**: Aplica a matriz de alçadas da `NG_012` e `NT_2026-021 item 4.3` (`Até R$ 18.000,00 -> Gerente do NIN`; `R$ 18.000,01 a R$ 120.000,00 -> Diretor da DIRTEC / DIRAF`; `> R$ 120.000,00 -> Comitê de Alçadas`).
- **`prazos_contrato(codigo, dias_sem_internet)`**: Calcula os marcos do `CTR_2026-012` (vistoria até `25/11/2026`, 90º dia em `27/02/2027`, **isenção de multa `R$ 0,00` a partir do 91º dia em `28/02/2027`**, pedido de prorrogação até `30/03/2027` e glosa de `R$ 121,67/dia` sem internet > 4h).
- **`comparar_versoes(codigo)`**: Retorna o Diff estruturado entre `NG_111 v2.0.0 vs v3.0.0`, `FM_1111-001 v1.0.0 vs v2.0.0` e `RG_1100 v1.0.0 vs v2.0.0`.

---

## ⚠️ Armadilhas do Acervo ACME Tratadas pelo Backend

O acervo sintético do Desafio 2 contém **pegadinhas deliberadas de governança, vigência e omissão** que derrubam soluções de RAG convencionais. Veja como o nosso Backend neutraliza cada uma delas:

| Categoria da Armadilha | Caso Real no Acervo ACME / BBTS | Risco em um RAG Comum | Tratamento no Zero Click (Raiz IQ) |
| :--- | :--- | :--- | :--- |
| **1. Data de Vigência Enganosa em Norma Substituída** | O PDF da `NG_111 v2.0.0` exibe no cabeçalho vigência de `10/12/2025 a 10/06/2027`, parecendo válido em 2026/2027. | Responder que férias podem ser pedidas com **30 dias** de antecedência. | Bloqueio pelo metadado `Fase: Versão anterior` e pelo campo `substitui` da `NG_111 v3.0.0` (vigente desde `03/08/2026`, exigindo **45 dias / D-45**). |
| **2. Mudança de Regras entre Edições de Programa** | O `RG_1100 v1.0.0` (02/03/2026) permitia **3 ideias** por pessoa, sem tempo mínimo de casa e prêmio de R$ 5k. | Informar regras da 1ª edição para o ciclo de 2027. | Quarentena da `v1.0.0` e aplicação estrita do `RG_1100 v2.0.0` (20/10/2026): **máx. 2 ideias**, **6 meses de casa**, gamificação 800 pts e prêmios de R$ 8k/5k/3k + R$ 2k/arena. |
| **3. Lacuna Normativa Explícita (Rateio em Equipe)** | O `RG_1100 v2.0.0` permite equipes de até 4 pessoas, mas **não define como o prêmio em dinheiro é dividido** em folha. | Alucinar divisão igualitária (25% para cada) sem base legal. | **Abstenção Honesta:** declara `"Não consta no RG_1100. Dono: NIN"` e exibe botão **`[Perguntar ao NIN]`**. |
| **4. Ponto Pendente de Deliberação (Afastados)** | A `NT_2026-021 (item 5.4)` aponta que a situação de empregado afastado durante a imersão/banca carece de definição. | Inventar regra de desclassificação ou substituição. | **Abstenção Honesta** citando o item `5.4` da `NT_2026-021` e encaminhando ao **NIN / Comitê CIN**. |
| **5. Documentos Citados mas Fisicamente Ausentes** | `NG_010` (Taxonomia) e `NG_012` (Alçadas) são citadas em todo o acervo, mas seus PDFs brutos não estão na pasta. | Alucinar artigos inexistentes da `NG_010` ou `NG_012`. | Responde apenas com os metadados taxonômicos e faixas de alçada extraídos na Camada Gold e alerta sobre a ausência física do PDF. |
| **6. Inconsistências Temporais Cruzadas nos PDFs** | `NG_1130` (`06/07/2026`) cita `NT_2026-021` (`14/10/2026`); e `NT_2026-021` (`16/10/2026`) cita `RG_1100 v2.0.0` (`20/10/2026`). | Confusão cronológica na linha do tempo de vigência. | O **Auditor do Acervo (`/ingest` e `/docs`)** sinaliza os anacronismos na Camada Silver e preserva a rastreabilidade para a curadoria. |

---

## 🚀 Como Executar o Servidor e o Banco de Avaliação (30 Perguntas)

### 1. Instalação e Execução do Servidor FastAPI

```bash
# 1. Instalar as dependências do projeto
pip install -r requirements.txt

# 2. Iniciar o servidor FastAPI na porta 8000
uvicorn app.main:app --reload --port 8000
```

- **API Base URL:** `http://localhost:8000`
- **Documentação Interativa (Swagger UI):** `http://localhost:8000/swagger`
- **Redoc:** `http://localhost:8000/redoc`

### 2. Executar o Banco de Avaliação Oficial (`30 Testes Golden FAQ`)

O arquivo `tests/eval/test_benchmark_30.py` executa **30 verificações automatizadas** cobrindo todas as calculadoras determinísticas (`tools.py`), perguntas do FAQ com verificação de código citado, bloqueio de versões substituídas, Abstenção Honesta, fluxo RBAC de Resposta Curada e geração de `.pptx`:

```bash
pytest tests/eval/test_benchmark_30.py -v
```

Saída esperada:
```text
collected 30 items
tests/eval/test_benchmark_30.py::test_01_ferias_05_05_2027_timeline_exata PASSED
...
tests/eval/test_benchmark_30.py::test_30_fluxo_rbac_resposta_curada_e_relatorio_pptx PASSED
============================== 30 passed in 2.00s ==============================
```

---

<p align="center">
  <strong>Equipe Ctrl + Alt + Business</strong> • Hackathon HUBB/TS — Desafio 2<br/>
  <em>⚖️ Em caso de divergência, prevalece o documento oficial.</em>
</p>
