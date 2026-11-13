# Histórico dos commits do back

O que cada commit mudou, por quê, como foi testado e qual base legal o motivou. A ordem é
cronológica. O acervo e as pessoas são sintéticos: "A ACME Tecnologia e Serviços é uma empresa
fictícia", representando a BBTS.

- Branch de trabalho: `thiago`. Os commits até `aac3320` já estão na `main` (PRs #2 e #3).
- Os commits a partir de `fdbcb51` entram pelo PR `thiago → main`.
- Comandos de verificação usados em todos: `ruff check .`, `pytest` e
  `python -m tests.eval.run_eval` (acerto, citação e abstenção).

## Parte 1: o que já está na `main`

### Base do repositório (outros autores)

| Commit | Autor | O que fez | Situação hoje |
|---|---|---|---|
| `d6e38ad` | Sertoriel | Estrutura inicial, README, `.gitignore` e `docs/WORKFLOW.md` | Mantido |
| `cd67329`, `890565c`, `c5d6033`, `a897fac` | Lana | Back FastAPI próprio (`app/tools.py`, `app/ingest.py`, `app/models.py`, `app/ppt_generator.py`), cópia do acervo em `data/` e README | Removido em `fdbcb51` e `3ddaeda` (pedido do usuário) |

### `4699d26` docs: plano do back-end e revisão de segurança do Codex

- **O que:** `docs/PLANO.md` (escopo do back) e `docs/SEGURANCA_REVISAO_CODEX.md` (achados
  SEC-01 a SEC-19, feitos antes do código).
- **Por quê:** decidir o desenho e os riscos antes de implementar.
- **Situação:** os dois são registros históricos. O contrato vivo está em `docs/CONTRATO.md`.

### `a6366d8` feat(calculadoras): núcleo de config/ACL/auth e calculadoras determinísticas

- **O que:** configuração por `.env`, personas no servidor, `AUTH_MODE=demo` (negar por padrão)
  e token HMAC. Calculadoras de férias, alçadas e contrato, com gabaritos tirados dos PDFs.
  Acervo sintético e seed de fatos. Dependências com versão exata.
- **Por quê:** a resposta numérica não pode depender de LLM. A regra vem do item da norma.
- **Base legal:** LGPD art. 6º, VII (segurança) e art. 46: acesso negado por padrão.

### `178da81` feat(api): chat com calculadoras e RAG, catálogo, radar, relatórios e auditoria

- **O que:** rotas do contrato antigo do front (branch `lana`): `/chat`, `/docs`, `/radar`,
  `/access`, `/reports`, `/reports/pptx`, `/ingest`. Ingestão Bronze → Silver por manifesto
  com hash. Busca BM25 com filtro de permissão antes do ranking. Roteador: lacuna conhecida →
  calculadora → regra revogada → RAG (+LLM local). Limites de corpo e de taxa, CORS restrito.
- **Situação:** as rotas saíram em `3ddaeda`. O motor (busca, roteador, calculadoras) continua
  e serve `/conversations/messages`.
- **Base legal:** LGPD art. 46 (filtro antes do ranking: documento proibido nem disputa a
  busca). LGPD art. 33: o LLM é local; um provedor fora do Brasil seria transferência
  internacional.

### `a9b025f` test(eval): banco de 33 perguntas com gabarito

- **O que:** `tests/eval/` com 33 perguntas, resposta esperada, citação e casos de abstenção.
- **Por quê:** medir acerto e citação a cada mudança. Resultado atual: 100% nos três.

### `e07d299` feat(grafo) e `e5bb5d5` docs(grafo)

- **O que:** relações entre documentos (`substitui`, `vinculado_a`, `referencia`) montadas sem
  LLM, com projeção por nível em `GET /grafo`. Metodologia em `docs/METODOLOGIA_GRAFO.md`.
  `AUTH_MODE` vira enum: valor desconhecido impede o startup.
- **Situação:** a rota e a projeção saíram em `3ddaeda`. As relações continuam e vão para o
  espelho no Neon.
- **Base legal:** LAI art. 25, § 1º: uma aresta não pode revelar documento sigiloso.

### `9a2e863` docs(readme): como rodar, rotas, personas, LLM local e testes

- **O que:** README de operação. O Swagger foi para `/swagger`, porque `/docs` era rota do
  contrato antigo.

### `2893d7c` feat(auditoria) e `2a1ab19` fix(auditoria)

- **O que:** trilha de auditoria no Neon (Postgres), com psycopg 3, TLS obrigatório
  (`sslmode=verify-full`, `channel_binding=require`), fila limitada em segundo plano e
  regravação sem duplicar. Corrige NEON-01 a NEON-09 (`docs/SEGURANCA_NEON_CODEX.md`).
- **Por quê:** registrar quem consultou o quê, sem guardar o texto da pergunta.
- **Base legal:** LGPD art. 37 (registro das operações) e art. 46 (TLS, segredo fora do log).
  LGPD art. 6º, III (necessidade): sem o texto da pergunta.

### `a1fd3cc` feat(banco): espelho de todo o conteúdo do sistema no Neon

- **O que:** documentos, trechos, regras das calculadoras, relações, personas e pedidos de
  acesso no Neon. Toda linha leva o nível de acesso. O papel da aplicação tem SELECT, INSERT e
  DELETE só nessas tabelas, sem UPDATE nem CREATE.
- **Base legal:** LGPD art. 46 (menor privilégio).

### `49650c2` feat(acesso): acesso por setor e credenciamento segundo a classificação BBTS

- **O que:** segue `docs/CLASSIFICACAO_BBTS.md`. Interna vale para toda pessoa identificada.
  Sigilosa exige o setor na lista do documento e a habilitação Sigilosa. Setores em
  `app/seed/setores.json`. Personas com setor e senioridade.
- **Por quê:** pedido do usuário ("o financeiro não deve acessar o código").
- **Base legal:** LAI art. 25, § 1º (acesso restrito a quem tem necessidade e credencial).

### `7f44ca6` feat(triagem): sugere sigilo e setor dono de arquivo enviado

- **O que:** lê PDF, DOCX, XLSX, CSV, texto e código num processo separado com tempo limite.
  Recusa assinatura falsa, PDF criptografado e bomba de ZIP. Detecta dado pessoal, sensível,
  bancário, credencial e código-fonte. A saída traz o tipo e as páginas, nunca o valor achado.
- **Por quê:** o arquivo novo precisa de classificação sugerida. A decisão é de uma pessoa.
- **Base legal:** LGPD art. 5º, I e II (dado pessoal e sensível); LC 105 art. 1º (sigilo
  bancário); LAI art. 27 (a classificação formal é ato de autoridade).

### `25150a2` feat(envios): upload /document-jobs com triagem e aprovação por setor

- **O que:** `POST /document-jobs` no formato do front. Triagem em segundo plano. O arquivo é
  apagado depois da triagem; a tabela `triagem_documento` guarda só metadados. Envio de júnior
  ou com revisão humana espera aprovação. Limite de 20 MiB só nessa rota. POST com `Origin`
  fora de `CORS_ORIGINS` recebe 403.
- **Base legal:** LGPD art. 6º, III (necessidade) e art. 46.

### `66cca55` feat(identidade): GET/POST /identity com cookie HttpOnly

- **O que:** identidade do front por cookie HttpOnly e `capabilities` (upload, approve, curate,
  sigiloso).
- **Situação:** `POST /identity` e os cookies saíram em `e9f2a7a`: o front não os chama. Fica
  `GET /identity`.

### `d96456d` feat(ferias): chat calcula os dias de férias pelo que a pessoa enviou

- **O que:** do formulário de férias e do espelho de ponto, a triagem tira só números e datas
  (faltas, período aquisitivo, admissão, início). Nada de nome, CPF ou matrícula. "Quantos
  dias de férias eu tenho?" usa o envio mais recente da própria pessoa (TB_1111-001;
  NG_111 4.1.1).
- **Base legal:** LGPD art. 6º, III (só o necessário para o cálculo) e art. 46 (os fatos ficam
  com quem enviou, os aprovadores e a GEPEC).

### `ffc2742` fix(envios): fixa python-multipart no requirements

- **O que:** `request.form()` dependia de um pacote que só estava no `.venv` local.

### `4c805d9` feat(graficos): GET /analyses/charts com pandas

- **O que:** painéis acervo, radar, triagem e uso, com a view `auditoria_resumo` sem a coluna
  `sujeito`.
- **Situação:** saiu em `e9f2a7a`: o front não tem tela de gráficos. O pandas saiu junto.

### `a891872` fix(seguranca): corrige achados do /code-review

- **O que:** regex sem ReDoS e triagem inteira isolada; aprovador de sigiloso com habilitação e
  do setor dono; formulário em nome de outra pessoa fora do cálculo; retenção
  `RETENCAO_ENVIOS_DIAS`; versão substituída com a própria classificação; achado da auditoria
  só cita documento visível; bloqueio do RAG não confirma número sigiloso.
- **Base legal:** LAI art. 25, § 1º; LGPD art. 15 e 16 (término do tratamento e eliminação);
  LGPD art. 18, VI (a rota `/forget` saiu depois, em `e9f2a7a`).

### `045618f` feat(front): rotas do contrato do hacka-front

- **O que:** `/documents`, `/documents/{id}/file` (PDF com ACL), `/analyses/evidence`,
  `/deadlines`, `/audit/findings`, `/simulation-rules`, `/conversations/messages`,
  `/access-requests`, `/analyses` e `/feedback`, nos schemas zod do front. Fatos curados em
  `app/seed/evidencias.json`. Registros do site em `registro_front`, com a pergunta mascarada.
  `docs/PENDENCIAS_FRONT.md` lista o que o front precisa corrigir.
- **Base legal:** LGPD art. 15 e 16 (`RETENCAO_REGISTROS_DIAS`); LGPD art. 6º, III (pergunta
  mascarada).

### `aac3320` fix(front): corrige achados do /code-review das rotas do hacka-front

- **O que:** tema `todos` sem viés; histórico da conversa sem o texto da resposta feita com
  envios da pessoa; retenção periódica (`app/services/retencao.py`); decisão de pedido com
  compare-and-set (a segunda decisão recebe 409); 503 só para erro de banco; datas sem fuso
  como UTC.
- **Base legal:** LGPD art. 6º, III; LGPD art. 15 e 16.

### Merges

- PR #1 (`lana → main`): o back da Lana.
- PR #2 (`thiago → homolog-dev`) e PR #3 (`homolog-dev → main`). O merge `7f46f5d` trouxe de
  volta os arquivos do PR #1, que nenhuma rota usava, e deixou o CI da `main` falhando. O
  `fdbcb51` corrige isso.

## Parte 2: PR `thiago → main`

Pedido do usuário: remover o back e o front da Lana, deixar só o back alinhado ao hacka-front
(branch `Homolog`) e limpar o código sem uso.

### `fdbcb51` chore: remove o backend da Lana que voltou no merge da main

- **O que:** apaga `app/tools.py`, `app/ingest.py`, `app/models.py`, `app/ppt_generator.py`,
  `tests/eval/test_benchmark_30.py`, `data/` (cópia idêntica de `acervo/` e `app/seed/`, mesmo
  hash) e `reports_out/` (arquivo gerado). 20 arquivos, 1.846 linhas a menos.
- **Por quê:** só se importavam entre si. O teste chamava rotas que não existem.
- **Teste:** corrige o CI da `main`: o ruff tinha 63 erros e o pytest 13 falhas, todos nesses
  arquivos.

### `3ddaeda` refactor: remove as rotas do contrato antigo do front (branch lana)

- **O que:** saem `POST /chat`, `GET /docs`, `/radar`, `/access`, `/ingest`, `POST /reports`,
  `GET /reports/pptx` e `GET /grafo` (`app/api/routes/contrato.py`), `app/services/access.py`,
  `app/services/reports.py`, o `python-pptx` e a projeção do grafo (`projetar`,
  `versao_anterior`, `para_mermaid`).
- **Por quê:** o front atual (`src/services/http/client.ts`) não chama nenhuma delas. Elas
  atendiam o `src/lib/api.ts` da branch `lana`, que não existe mais.
- **O que fica:** o motor do chat, o radar e a auditoria do acervo, servindo
  `/conversations/messages`, `/deadlines` e `/audit/findings`.
- **Teste:** os testes e o eval passam a usar as rotas do front. Eval 100%, medido no texto que
  o front recebe.

### `5fa8db6` chore: remove código sem uso

- **O que:** `calendario.somar_dias_uteis`, `contrato.glosa_internet`,
  `contrato.pagamento_do_mes` (e o teste dele), `graficos.PAINEIS`, `app/repositories/.gitkeep`
  e `docs/.gitkeep`.
- **Por quê:** nenhum chamador fora dos testes.

### `e9f2a7a` refactor: remove as rotas que o hacka-front não chama

- **O que sai:**
  - `GET /health`;
  - `GET /analyses/charts`, o módulo de gráficos e o pandas;
  - `POST /identity`, `POST /identity/sair` e os cookies `raiz_persona` e `raiz_sessao`;
  - `GET /document-jobs` (lista), `POST /document-jobs/{id}/decision` e `/forget`.
- **Efeitos:**
  - Em `AUTH_MODE=demo`, a persona vem de `X-Persona-Id`, `?persona=` ou
    `DEMO_DEFAULT_PERSONA`. Em `AUTH_MODE=token`, só de `Authorization: Bearer`.
  - O envio que precisa de aprovação fica pendente, visível só para quem enviou e para os
    aprovadores. O campo `podeDecidir` sai do item.
  - O setup da auditoria apaga a view `auditoria_resumo`.
- **Base legal:**
  - LGPD art. 46 (menor privilégio): sem a view, o papel da aplicação perde o único SELECT
    que tinha na auditoria.
  - LGPD art. 15 e 16: os dados pessoais dos envios continuam eliminados por
    `RETENCAO_ENVIOS_DIAS`.
  - LGPD art. 18, VI e art. 41: sem a rota `/forget`, o pedido de eliminação do titular vai
    pelo encarregado até o front ter a tela.
- **Teste:** `tests/test_rotas.py` confere que as rotas removidas dão 404 ou 405. 217 testes
  passando; eval 100%.
- **Pendência no Neon:** a view `auditoria_resumo` some quando o dono do banco rodar
  `python -m app.services.audit_log`.

### `291ceaa` chore: remove helpers que só os testes chamavam

- **O que:** `calendario.postergar_para_dia_util`, `extracao.extrair_isolado` e `_no_filho`.
- **Por quê:** a API isola leitura e detecção juntas em `triar_arquivo(isolar=True)`. O teste
  do tempo limite passa a usar esse caminho, o mesmo da API.

### `913eb10` fix(chat): antecedência de férias não vira pergunta sobre os envios

- **O que:** "Quantos dias de antecedência para pedir férias?" caía na intenção dos arquivos
  enviados e respondia "Não encontrei faltas injustificadas". Agora a intenção exige "quantos
  dias de férias" (ou "tenho direito", "meu saldo") e ignora perguntas com "antecedência".
- **Por quê:** achado no teste de ponta a ponta com o hacka-front em modo API. A resposta certa
  é a NG_111 v3.0.0, item 8.1.2 (45 dias).
- **Teste:** `test_antecedencia_e_regra_da_norma_nao_saldo_de_envio`. 219 testes passando;
  eval 100%.

### `5e6f5b0` docs: contrato, pendências do front e histórico de cada commit

- **O que:** `docs/CONTRATO.md` só com as rotas que o front chama; `docs/PENDENCIAS_FRONT.md`
  atualizado para a branch `Homolog`; este arquivo; README com as rotas atuais e o curl de
  `/conversations/messages`; `docs/METODOLOGIA_GRAFO.md`, `docs/PLANO.md` e
  `docs/SEGURANCA_GRAFO_CODEX.md` marcados como históricos onde citam rotas removidas.

### fix: corrige achados do /code-review do PR (commit seguinte ao `5e6f5b0`)

- **Intenção de férias.** O `913eb10` estreitou demais o gatilho: "Quantos dias tenho de
  férias?" e "Quantos dias me restam de férias?" deixaram de usar o envio da pessoa. Volta
  "quantos dias" e saem só as perguntas de prazo ("antecedência", "dias antes").
- **Capacidade `approve`.** Sem rota de decisão, ninguém aprova pela API. O `GET /identity`
  deixa de anunciar `approve`. O front não usava essa capacidade.
- **Eliminação a pedido (LGPD art. 18, VI).** Sem a rota `/forget`, faltava um caminho para o
  encarregado (LGPD art. 41). `scripts/eliminar_envio.py <id>` elimina nome do arquivo, resposta
  e fatos de férias de um envio, registra na auditoria (LGPD art. 37) e pede para reiniciar a
  API. Envio ainda em triagem é recusado.
- **Limpeza.** Comentário do CORS (o `allow_credentials` fica: o front chama com
  `credentials: 'include'`), import morto `papel_valido` em `audit_log`, comentários que
  apontavam `app/services/access.py`, o painel de uso e o `POST /identity`.
- **Teste:** `test_outras_formas_de_perguntar_o_proprio_saldo`,
  `test_prazo_com_dias_antes_nao_vira_saldo_de_envio` e
  `test_encarregado_elimina_os_dados_pessoais_a_pedido`. 223 testes passando; eval 100%.
- **Não mudou, por decisão do usuário:** o envio pendente sem rota de decisão, o modo token sem
  cookie e a saída do `/health` (pedido "remova" para as rotas que o front não chama).

## Mudança no front ligada a este PR

No hacka-front, a branch `chore/remove-codigo-lana` (PR para `Homolog`) remove o código da Lana
(simuladores, `MermaidFlowchart`, o JSON do acervo e os PDFs de `public/docs_acervo/`) e o modo
demo. O front passa a usar só a API. Os PDFs sigilosos deixam de ser servidos pelo Next sem
controle de acesso (LGPD art. 46; LAI art. 25).
