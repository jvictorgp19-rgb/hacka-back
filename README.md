# Hacka — Back-end (Raiz IQ / Zero Click)

API da solução do hackathon, **Desafio 2 — Plataforma de Inteligência Empresarial**.
**Python + FastAPI**. Front-end em [hacka-front](https://github.com/jvictorgp19-rgb/hacka-front).

O Raiz IQ é um copiloto sobre as normas internas da empresa: férias, programa de inovação e
contrato de locação de coworking. Ele responde com citação de documento, item e versão. Também
calcula prazos e alçadas sem LLM, avisa quando uma regra foi revogada e se abstém quando o acervo
não cobre a pergunta. Por fim, respeita o setor e a habilitação de quem pergunta.

> O acervo é **sintético**: "A ACME Tecnologia e Serviços é uma empresa fictícia". O modo
> `AUTH_MODE=demo` é uma simulação de controle de acesso e só deve rodar com esses dados.

## Equipe

João (Sertoriel) · Lana · Victor · Thiago

## Começando

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload      # http://localhost:8000
```

- Swagger: http://localhost:8000/swagger. O caminho `/docs` é uma rota do contrato: o catálogo do
  acervo.
- Saúde: http://localhost:8000/health.
- No primeiro start, a API lê os PDFs de `acervo/bronze/` e grava o cache em `data/silver.json`.

Teste rápido, como a persona Ana (setor GOP, habilitação Interna):

```bash
curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message": "Quero férias a partir de 05/05/2027. Até quando peço?", "tema": "ferias", "personaId": "ana"}'
```

## Rotas

| Rota | O que faz |
|---|---|
| `POST /chat` | Responde perguntas com calculadora, alerta de regra revogada, abstenção honesta ou busca + LLM |
| `GET /docs?tema=` | Catálogo do acervo visível para a persona |
| `GET /radar?hoje=` | Prazos que vencem (férias, contrato), com criticidade |
| `GET /access` | Pedidos de acesso (stub de leitura) |
| `POST /reports` · `GET /reports/pptx` | Deck executivo em JSON ou `.pptx`, com citações nas notas |
| `GET /ingest?hoje=` | Auditoria do acervo: anacronismos, referências ausentes, conflito de vigência |
| `GET /grafo?tema=` | Mapa do acervo: documentos, versões e relações no nível de quem consulta |
| `POST /document-jobs` · `GET /document-jobs[/{id}]` | Envio de arquivo: triagem (sigilo + setor dono) em segundo plano |
| `POST /document-jobs/{id}/decision` | Aprovador do setor confirma, corrige ou recusa a classificação |

Formatos, identidade, limites e ajustes pedidos ao front: [docs/CONTRATO.md](docs/CONTRATO.md).

## Identidade e acesso

O acesso nunca vem do cliente. O cliente informa só o id da persona; o servidor sabe o setor, o
cargo e a habilitação (`app/core/personas.py`).

A classificação segue [docs/CLASSIFICACAO_BBTS.md](docs/CLASSIFICACAO_BBTS.md):

- **Interno**: qualquer pessoa identificada vê.
- **Sigiloso**: só vê quem cumpre duas condições (LAI art. 25, § 1º):
  1. o setor da pessoa está na lista do documento (necessidade de conhecer);
  2. a pessoa tem habilitação Sigilosa (credenciamento).

| Persona | Setor | Cargo | Habilitação | Sigilosos que vê |
|---|---|---|---|---|
| `ana` | GOP | Analista | Interna | nenhum |
| `carlos` | GOP | Gestor | Interna | nenhum |
| `marina` | GOC | Proponente | Interna | nenhum (GOC, mas sem credenciamento) |
| `rafael` | GOC | Fiscal técnico (sênior) | Sigilosa | NT_2026-018, CTR_2026-012 |
| `sergio` | GESUC | Analista de contratos | Sigilosa | NT_2026-018, CTR_2026-012 |
| `fernanda` | GFI | Analista financeira | Sigilosa | CTR_2026-012 |
| `bruno` | GEINOV | Desenvolvedor júnior | Interna | nenhum |
| `helena` | GEINOV | Tech lead (curadora) | Sigilosa | NT_2026-021 |
| `diretora_diraf` | DIRAF | Diretora | Sigilosa | NT_2026-021, NT_2026-018 |
| `curadora_ggc` | GEPEC | Curadora | Sigilosa | versões substituídas, dossiê da folha |

- `AUTH_MODE=demo` (padrão): `personaId` no body, header `X-Persona-Id` ou query `?personaId=`.
  Sem persona válida, só o nível Pública: listas vazias.
- `AUTH_MODE=token`: exige `Authorization: Bearer <token>`. Para emitir:
  `python -m app.core.auth <personaId>` (precisa de `AUTH_TOKEN_SECRET` com 32+ caracteres).

## LLM local

O back fala com qualquer servidor compatível com a API da OpenAI (vLLM, Ollama, LM Studio).
Preencha no `.env`:

```
LLM_BASE_URL=https://<vm>/v1
LLM_API_KEY=<chave>
LLM_MODEL=<nome do modelo>
```

Sem essas variáveis, o chat responde com calculadoras e trechos citados (modo extrativo). HTTP
sem TLS só é aceito para `localhost` (túnel SSH), salvo `LLM_ALLOW_HTTP=true`.

## Banco (Neon)

O banco é o [Neon](https://neon.tech), que é PostgreSQL. Ele guarda duas coisas:

- **Trilha de auditoria** (LGPD art. 37): quem perguntou, o tipo de pergunta, as fontes e o nível
  de acesso. A pergunta em si não é guardada.
- **Espelho de todo o conteúdo do sistema** (`app/services/persistencia.py`), gravado no startup
  e refeito só quando algo muda:

  | Tabela | Conteúdo |
  |---|---|
  | `acervo_documento` | Um registro por arquivo: código, versão, título, tema, área dona, nível, vigência, cabeçalho, `sha256`, link no repositório e texto completo do PDF |
  | `acervo_trecho` | Os trechos por item numerado, com nível e vigência |
  | `acervo_regra` | Os parâmetros das calculadoras, com documento e item de origem. Exemplo: pedir férias com 45 dias de antecedência (NG_111 4.5.1) |
  | `acervo_relacao` | As relações do grafo: substitui, vinculado_a, referencia |
  | `acervo_curado` | O conteúdo curado do front (taxonomia, alçadas, jornadas por tema) |
  | `acervo_ingestao` · `acervo_quarentena` | Cada execução, com contagens, e os arquivos recusados |
  | `sistema_persona` · `sistema_pedido_acesso` | Personas da demo e pedidos de acesso |

  O chat, a busca e o grafo da API continuam lendo dos arquivos: o banco é cópia, não a fonte.
  Toda linha com conteúdo do acervo tem a coluna `nivel`. Quem ler essas tabelas para mostrar
  algo a alguém precisa filtrar por ela.

Sem `DATABASE_URL`, o back usa um SQLite local, só para testes e para rodar offline. Com
`APP_ENV=production`, a `DATABASE_URL` é obrigatória e o SQLite é recusado.

1. Crie o projeto no Neon na região **São Paulo (AWS sa-east-1)**. Um banco fora do Brasil é
   transferência internacional de dados (LGPD art. 33). Em produção, a API avisa no log quando o
   host não é de `sa-east-1`. A região efetiva deve ser conferida no console.
2. Com o papel dono do banco, crie por SQL um papel só para a aplicação. Papel criado pelo console
   ou pelo CLI entra no `neon_superuser` e teria acesso demais.

   ```sql
   CREATE ROLE raiz_app LOGIN PASSWORD '<senha forte>';
   GRANT USAGE ON SCHEMA public TO raiz_app;
   ```

3. Crie as tabelas uma vez, com a connection string do **dono**. Ela não vai para o `.env` da
   aplicação:

   ```bash
   export DATABASE_URL='postgresql://<dono>:<senha>@<endpoint>.sa-east-1.aws.neon.tech/neondb?sslmode=require'
   python -m app.services.audit_log      # tabela auditoria
   python -m app.services.persistencia   # tabelas do espelho, já preenchidas
   ```

4. Libere para a aplicação só o necessário. Não conceda `UPDATE` nem `CREATE`, nem `SELECT` na
   auditoria:

   ```sql
   GRANT INSERT ON auditoria TO raiz_app;
   GRANT USAGE ON SEQUENCE auditoria_id_seq TO raiz_app;
   -- espelho: refeito por inteiro (apaga e grava), e confere a última execução
   GRANT SELECT, INSERT, DELETE ON acervo_documento, acervo_trecho, acervo_relacao, acervo_regra,
     acervo_curado, acervo_ingestao, acervo_quarentena, sistema_persona, sistema_pedido_acesso
     TO raiz_app;
   GRANT USAGE ON SEQUENCE acervo_trecho_id_seq, acervo_relacao_id_seq, acervo_ingestao_id_seq,
     acervo_quarentena_id_seq TO raiz_app;
   ```

5. No `.env` da aplicação, cole a connection string do `raiz_app` como o console entrega.
   Prefira o endpoint com `-pooler`:

   ```
   DATABASE_URL=postgresql://raiz_app:<senha>@<endpoint>-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   APP_ENV=production
   ```

Os links de cada arquivo usam `ACERVO_REPO_URL`. O padrão é o `blob/main` deste repositório.

### Regras da conexão

- **TLS completo.** Banco remoto sempre conecta com `sslmode=verify-full`, que confere o
  certificado e o nome do servidor. Também usa `channel_binding=require` e as CAs do `certifi`.
  `sslmode` sem TLS e `channel_binding=disable` impedem a API de subir.
- **Destino só pela URL.** Na query, só são aceitos `sslmode`, `channel_binding` e `sslrootcert`.
  Parâmetros como `host`, `hostaddr`, `password` e `service` são recusados. As variáveis
  `PGHOST`, `PGHOSTADDR`, `PGSERVICE` e `PGSERVICEFILE` também são recusadas.
- **Sem segredo em log.** Logs e erros nunca mostram usuário, senha nem host. As `Settings`
  escondem `DATABASE_URL`, `LLM_API_KEY` e `AUTH_TOKEN_SECRET` no `repr`.
- **Tempo limite.** Cada gravação da auditoria tem `statement_timeout` de 5 s e `lock_timeout`
  de 2 s; a do espelho, 60 s e 5 s. As duas usam keepalive TCP.

### Gravação da auditoria

- **Em segundo plano.** A resposta não espera o banco, porque o Neon hiberna e a primeira
  conexão depois disso demora.
- **Lote que falha não é descartado.** Ele volta a ser gravado com espera crescente, até 30 s
  entre tentativas. Cada evento tem um id, e regravar não duplica.
- **Fila limitada.** Enquanto o banco está fora, os novos registros esperam numa fila de até
  1.000. O excedente é descartado e contado no log.
- **Encerramento.** A API tenta gravar o que falta por até 10 s. Com o banco fora do ar, o que
  sobrar é descartado e contado.

### Limites conhecidos

- **A fila fica em memória.** Se o processo cair, o que não foi gravado se perde.
- **O dono do banco pode alterar ou apagar registros.** Para servir de prova contra quem
  administra o banco, a trilha teria que ser exportada para um armazenamento imutável, sob outro
  controle.
- **Falta definir retenção e expurgo** antes de usar dados reais. Os metadados ligados a uma
  pessoa continuam sendo dados pessoais.
- Revisão completa: [docs/SEGURANCA_NEON_CODEX.md](docs/SEGURANCA_NEON_CODEX.md).

## Testes e avaliação

```bash
ruff check .
pytest
python -m tests.eval.run_eval          # 33 perguntas com gabarito, sem LLM
python -m tests.eval.run_eval --llm    # mesmo banco, com o LLM configurado no .env
```

A avaliação mede acerto, citação correta e abstenção/bloqueio corretos.

## Acervo

- `acervo/bronze/`: PDFs do desafio.
- `app/seed/manifesto.json`: lista curada com hash, tema, área dona e classificação mínima de
  cada PDF. PDF fora do manifesto ou com hash diferente vai para quarentena. Para regerar depois
  de mudar o acervo, rode `python scripts/gerar_manifesto.py`.
- Ingestão manual: `python -m app.services.ingest.pipeline`.
- Reclassificou um documento? Reinicie a API: acervo, índice e grafo ficam em memória.

### Triagem de arquivo novo

`python scripts/triar.py <arquivo-ou-pasta>` lê PDF, DOCX, XLSX, CSV, texto e código-fonte.
Para cada arquivo, ele diz:

- se é **Interna** ou **Sigilosa**, com o motivo;
- qual é o setor dono;
- quais setores teriam acesso, seguindo [docs/CLASSIFICACAO_BBTS.md](docs/CLASSIFICACAO_BBTS.md).

Com `--ficha PASTA`, grava para a IA o JSON com o texto por página. A ficha contém o conteúdo do
arquivo: guarde-a com o mesmo sigilo dele.

O que a triagem detecta:

- dados pessoais: CPF validado, matrícula, RG, nome preenchido;
- dado sensível de saúde (LGPD art. 11);
- dado bancário (LC 105);
- credencial;
- código-fonte, que fica só com a GEINOV;
- valores comerciais;
- versão substituída.

O valor encontrado nunca vai para a saída: ela mostra só o tipo de dado e as páginas.

A triagem é só uma sugestão. Quem confirma é o aprovador do setor (LAI art. 27). Arquivo
hostil é recusado: assinatura falsa, PDF criptografado e bomba de ZIP. A leitura roda em
processo separado, com tempo limite. Sobre o acervo do desafio, a triagem reproduz a
classificação BBTS nos 13 PDFs (`tests/test_triagem.py`).

Pelo site, o mesmo fluxo roda em `POST /document-jobs`. O envio de júnior, ou o envio com
sugestão sigilosa, espera a aprovação de um gestor ou sênior do setor. Regras em
[docs/CONTRATO.md](docs/CONTRATO.md). A tabela `triagem_documento` é criada uma vez com o
papel dono: `python -m app.services.envios raiz_app`. O comando dá ao papel da aplicação só
`SELECT`, `INSERT` e `UPDATE`.

## Estrutura

```
app/
├─ main.py              # FastAPI, CORS, limite de corpo, /health, carga do acervo
├─ api/routes/          # rotas do contrato com o front
├─ core/                # config, acesso por setor, setores, personas, autenticação, limites
├─ schemas/             # contrato JSON (camelCase, igual ao front)
├─ seed/                # manifesto do acervo e JSON curado do front
└─ services/
   ├─ ingest/           # PDF -> cabeçalho -> trechos (Silver)
   ├─ rag/              # índice BM25 por perfil de acesso (setor + habilitação)
   ├─ llm/              # cliente OpenAI-compatible
   ├─ agent/            # intenções, guardas e roteador de custo do chat
   ├─ calculators/      # férias, alçadas, contrato, calendário de dias úteis
   ├─ triagem/          # arquivo enviado -> texto -> sigilo + setor dono (sugestão)
   ├─ grafo.py          # mapa do acervo
   └─ radar, reports, access, ingest_audit, audit_log
acervo/bronze/          # PDFs
scripts/                # gerador do manifesto e triagem pela linha de comando
tests/                  # pytest + tests/eval (banco de perguntas)
docs/                   # contrato, plano, metodologia e revisões de segurança
```

## Documentação

| Arquivo | Conteúdo |
|---|---|
| [docs/CONTRATO.md](docs/CONTRATO.md) | Rotas, formatos, identidade, limites e ajustes do front |
| [docs/PLANO.md](docs/PLANO.md) | Plano do back-end aprovado |
| [docs/METODOLOGIA_GRAFO.md](docs/METODOLOGIA_GRAFO.md) | Como o acervo é ingerido, como o chat busca e como o grafo é montado |
| [docs/SEGURANCA_REVISAO_CODEX.md](docs/SEGURANCA_REVISAO_CODEX.md) | Revisão de segurança do back (SEC-01 a SEC-27) |
| [docs/SEGURANCA_GRAFO_CODEX.md](docs/SEGURANCA_GRAFO_CODEX.md) | Revisão de segurança do grafo (GRAFO-01 a GRAFO-24) |
| [docs/SEGURANCA_NEON_CODEX.md](docs/SEGURANCA_NEON_CODEX.md) | Revisão de segurança da auditoria no Neon (NEON-01 a NEON-09) |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Branches e fluxo de PR |

## Branches e workflow

`main` ← `homolog-demo` ← `homolog-dev` ← branches pessoais (`joao-sertoriel`, `lana`, `victor`, `thiago`).
Detalhes em [docs/WORKFLOW.md](docs/WORKFLOW.md).
