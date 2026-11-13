# Contrato da API — Raiz IQ / Zero Click

Base: `http://localhost:8000`. Documentação interativa em **`/swagger`** (o caminho `/docs` é uma
rota do contrato: o catálogo do acervo).

Os formatos abaixo espelham os schemas zod do `hacka-front`, branch `Dev`
(`src/contracts/models.ts` e `src/services/http/client.ts`). As rotas antigas (`/chat`, `/docs`,
`/radar`, `/access`, `/reports`, `/ingest`) seguem a branch `lana` e continuam no ar.
Mudou o contrato? Avise no chat e atualize aqui.

O back segue o contrato como está. Problemas do front ficam listados em
[docs/PENDENCIAS_FRONT.md](PENDENCIAS_FRONT.md), sem contorno no back.

## Rotas

| Rota | Entrada | Saída |
|---|---|---|
| `POST /chat` | `{message, tema, perfil, personaId}` | `ChatResponse` |
| `GET /docs?tema=` | `tema`: `ferias`, `inovacao` ou `locacao` (opcional) | `{vigentes, substituidos, taxonomia, temaFiltro}` |
| `GET /radar?hoje=` | `hoje`: data ISO opcional, para simular a demo | `RadarEvent[]` |
| `GET /access` | — | `AccessRequestItem[]` |
| `POST /reports` | `{tema, personaId}` | `{tituloDeck, subtitulo, geradoEm, slides[]}` |
| `GET /reports/pptx?tema=` | — | arquivo `.pptx` |
| `GET /ingest?hoje=` | — | `IngestAuditFinding[]` |
| `GET /grafo?tema=` | `tema` opcional | `{nos[], arestas[]}`: mapa do acervo no nível de quem consulta (extra; ver `docs/METODOLOGIA_GRAFO.md`) |
| `POST /document-jobs` | multipart, campo `files` (até 10 arquivos; o front manda 1 por vez) | `UploadItem[]` |
| `GET /document-jobs/{id}` | — | `UploadItem` (404 se o sujeito não pode ver) |
| `GET /document-jobs?aprovacao=` | `pendente`, `aprovado`, `recusado` ou `dispensado` (opcional) | `UploadItem[]` que o sujeito vê |
| `POST /document-jobs/{id}/decision` | `{status: approved\|rejected, response, persona, nivel?, setores?}` | `UploadItem` |
| `POST /document-jobs/{id}/forget` | — (só quem enviou) | `UploadItem` sem dado pessoal (LGPD art. 18, VI) |
| `GET /analyses/charts?panel=&hoje=` | `panel`: `acervo`, `radar`, `triagem` ou `uso` | `Grafico[]` |
| `GET /documents` | — | `Document[]` que o sujeito vê |
| `GET /documents/{id}/file` | `id`: `CODIGO@x.y.z` | PDF (`inline`), 404 se o sujeito não vê |
| `GET /analyses/evidence` | — | `Fact[]` que o sujeito vê |
| `GET /deadlines?hoje=` | `hoje` opcional | `Deadline[]` |
| `GET /audit/findings?hoje=` | `hoje` opcional | `Finding[]` (só curadoria e diretoria) |
| `GET /simulation-rules` | — | `SimulationRules`; `401` sem identificação, `403` sem acesso a todas as fontes |
| `GET /conversations/messages?persona=` | — | `Answer[]` da própria persona |
| `POST /conversations/messages` | `{query, context}` | `Answer` |
| `GET /access-requests?persona=` | — | `AccessRequest[]`: os meus e os que eu decido |
| `POST /access-requests` | `{reason, persona, owner}` | `AccessRequest` (`422` se `owner` não é setor BBTS) |
| `POST /access-requests/{id}/decision` | `{status: curated\|denied\|granted, response, persona}` | `AccessRequest` (`403`, `404`, `409`) |
| `GET /analyses?persona=` | — | `SavedRecord[]` da própria persona |
| `POST /analyses` | `{id, title, kind, persona, facts, context, createdAt}` | `SavedRecord` |
| `GET /feedback?persona=` | — | `Feedback[]` da própria persona |
| `POST /feedback` | `{id, targetId, persona, useful, reason}` | `Feedback` (um por `targetId`) |
| `GET /health` | — | `{"status": "ok"}` |

Nas rotas do front, campo opcional sem valor sai **ausente**, nunca `null`: o zod `.optional()`
recusa `null`.

## Telas do hacka-front

| Tela | Rotas |
|---|---|
| Identidade (barra do topo) | `GET /identity` |
| Acervo | `GET /documents`, `GET /documents/{id}/file` |
| Análises e Resumos (filtros por tema, área, perspectiva e período) | `GET /analyses/evidence`, `GET /analyses`, `POST /analyses` |
| Prazos | `GET /deadlines` |
| Conversa | `GET` e `POST /conversations/messages`, `GET` e `POST /feedback` |
| Administração (governança) | `GET` e `POST /access-requests`, `POST /access-requests/{id}/decision`, `GET /audit/findings` |
| Simuladores | `GET /simulation-rules` |
| Envio de documentos | `POST /document-jobs`, `GET /document-jobs/{id}` |
| Gráficos | `GET /analyses/charts` |

### Regras das rotas do front

- **Documentos e PDFs.** `/documents` lista só o que o sujeito vê. O `fileUrl` aponta para
  `GET /documents/{id}/file`, que confere o acesso de novo antes de servir o arquivo. A versão
  substituída sem PDF próprio sai sem `fileUrl`.
- **Fatos (`/analyses/evidence`).** Vêm de `app/seed/evidencias.json`. Cada fato cita um trecho
  conferido no acervo, com a página achada no PDF. `area` é a sigla BBTS do setor dono do
  documento citado (GEPEC, GEINOV, GESUC). O fato só sai para quem vê a versão citada.
- **Prazos.** Os mesmos eventos do `/radar`. Cada prazo cita o item do documento que o fundamenta.
  `priority` é `Crítica` até 30 dias, `Alta` até 90 e `Normal` depois.
- **Achados.** Os do `/ingest`, no formato `{id, title, detail, documents}`.
- **Regras de simulação.** Valores reais das fontes: férias (NG_111), nota técnica
  (NT_2026-021) e contrato (CTR_2026-012). O contrato do front junta tudo numa resposta só. Se o
  sujeito não vê alguma das fontes, a rota responde `403` e não devolve nada parcial
  (LAI art. 25, § 1º).
- **Conversa.** Usa o mesmo motor do `/chat`. `status`: `access_required` quando há `rbacBlock`,
  `abstained` na abstenção ou sem citação, `conflict` quando há `revokedAlert`, `answered` nos
  demais casos. A pergunta fica guardada **mascarada** (CPF, e-mail, telefone etc.).
- **Pedidos de acesso.** `owner` precisa ser um setor BBTS. Decide quem cura o setor dono ou é
  diretor da diretoria dele. `granted` só registra a decisão: **não muda a permissão real**, que
  continua no cadastro (`app/core/personas.py`) e no manifesto.
- **Análises salvas.** Do corpo só se aproveita o `id` de cada fato. O conteúdo vem do servidor e
  é refeito na leitura, com a ACL do momento.
- **Persona.** Nas rotas com `persona` no corpo ou na query, a ordem de resolução é a da seção
  "Identidade". No modo `token`, uma persona diferente da do token dá `403`.
- **Retenção.** Conversas, análises, feedback e pedidos ficam na tabela `registro_front` e são
  apagados após `RETENCAO_REGISTROS_DIAS` (padrão 180) sem atualização (LGPD art. 15 e 16).
  Cada persona só lê os próprios registros. Pedido de acesso também aparece para quem decide.

`ChatResponse`:

```json
{
  "answer": "texto em Markdown simples",
  "bullets": ["..."],
  "citations": [{"codigo": "NG_111", "titulo": "Férias", "versao": "v3.0.0", "status": "Vigente"}],
  "costBadge": {"type": "deterministic", "label": "...", "latencyMs": 3, "sigiloNivel": "Interna"},
  "revokedAlert": {"codigo": "", "versaoRevogada": "", "substituidoPor": "", "pegadinha": ""},
  "honestAbstention": {"lacuna": "", "donoDominio": "", "botaoAcao": "", "detalhesExtras": []},
  "rbacBlock": {"dominioResponsavel": "", "nivelExigido": "", "mensagem": ""},
  "suggestedFollowups": ["..."]
}
```

`revokedAlert`, `honestAbstention` e `rbacBlock` só aparecem quando se aplicam.
`costBadge.type` é `deterministic` (calculadora ou trecho citado, sem LLM) ou `rag_llm`.

## Envio de arquivos (`/document-jobs`)

Segue o `uploadSchema` do hacka-front. Os campos `id`, `name`, `size`, `status` e `message`
vêm sempre preenchidos. Os outros campos detalham a triagem, e o front pode ignorá-los.

```json
{
  "id": "9f2c…", "name": "servico.py", "size": 84, "status": "ready",
  "message": "Sugestão: Sigilosa, setor dono GEINOV; acesso: GEINOV. Sigiloso: código-fonte. Aguarda aprovação (envio de desenvolvedor júnior): gestor ou sênior da GEINOV.",
  "createdAt": "2026-11-12T13:00:00Z", "sha256": "…", "formato": "codigo", "paginas": 1,
  "classificacao": {"nivel": "Sigilosa", "setores": ["GEINOV"], "confianca": 0.95,
                    "resumo": "…", "motivos": [{"tipo": "codigo_fonte", "rotulo": "Código-fonte",
                    "nivel": "Sigilosa", "ocorrencias": 6, "paginas": [1], "criterio": "…"}]},
  "departamento": {"sigla": "GEINOV", "nome": "…", "confianca": 0.94},
  "revisaoHumana": true, "aprovacao": "pendente", "aprovadores": "gestor ou sênior da GEINOV",
  "nivelFinal": null, "setoresFinais": [], "podeDecidir": false,
  "decidedBy": null, "decidedAt": null, "response": null
}
```

Ciclo do envio:

1. O `POST` confere identidade, tamanho e assinatura do arquivo e responde na hora.
   - Se o arquivo passa, o status é `processing`.
   - Se não passa, o status é `failed` e `message` diz o motivo.
2. A triagem roda em segundo plano, num processo separado com tempo limite.
3. O `GET /document-jobs/{id}` traz o resultado, com status `ready`, `not_extracted` ou `failed`.
4. O arquivo é apagado logo após a triagem.
5. O banco (`triagem_documento`) guarda só nome, tamanho, hash, sugestão e decisão. Ele nunca
   guarda o texto nem os valores encontrados (LGPD art. 6º, III, e art. 46).

Aprovação, conforme docs/CLASSIFICACAO_BBTS.md e LAI art. 27:

- **Quando é exigida.** Em todo envio de desenvolvedor júnior. Também quando a sugestão pede
  revisão humana: sigilosa, conteúdo não extraído ou confiança baixa. Nos demais casos,
  `aprovacao` é `dispensado`.
- **Quem aprova.** Quem enviou nunca aprova o próprio envio (`403`). Os demais dependem da
  sugestão:
  - Sugestão Interna (envio de júnior): gestor ou sênior do setor de quem enviou ou do setor
    dono, a curadoria do setor dono e o diretor da diretoria do setor dono.
  - Sugestão Sigilosa ou não extraída: só quem tem habilitação Sigilosa e necessidade de
    conhecer, ou seja, gestor ou sênior do setor dono, a curadoria dele ou o diretor da diretoria
    dele (LAI art. 25, § 1º). O gestor de quem enviou, sem habilitação, não vê o envio.
- **O que o aprovador pode mudar.** Ele confirma ou corrige `nivel` (`Interna` ou `Sigilosa`) e
  `setores`, que são siglas BBTS; o primeiro setor da lista é o dono. Ele também pode recusar o
  envio.
- **Quem vê.** Antes da decisão, só quem enviou e os aprovadores. Depois da aprovação, vale a
  regra de acesso do nível e dos setores confirmados, e o aprovador não guarda acesso extra.
  Envio recusado fica com quem enviou e com quem decidiu. Quem não pode ver recebe `404`, para
  não saber que o envio existe.

Retenção e eliminação (LGPD art. 15, 16 e 18, VI):

- Passados `RETENCAO_ENVIOS_DIAS` (padrão 180), o nome do arquivo, a resposta do aprovador e os
  fatos de férias são eliminados. A classificação e a decisão ficam, sem dado pessoal.
- Quem enviou pode pedir a eliminação antes do prazo com `POST /document-jobs/{id}/forget`.
  Para os outros, a rota responde `404`. Com a triagem ainda rodando, responde `409`.

Férias pelos envios:

- A triagem tira de formulário preenchido (FM_1111-001) e de espelho de ponto (planilha com
  coluna "Ocorrência") só números e datas: faltas injustificadas, período aquisitivo, admissão e
  início de gozo. Nome, CPF e matrícula ficam de fora.
- Arquivo com esses fatos é sugerido como Sigiloso da GEPEC (achado `registro_ferias`).
- O campo `ferias` do `UploadItem` traz `{faltasInjustificadas, origemFaltas, periodoInicio,
  periodoFim, admissao, inicioGozo, diasDeFerias, paginas}`.
- `ferias` só aparece para quem enviou, para o aprovador enquanto o envio está pendente e para a
  GEPEC habilitada que pode ver o envio, mesmo depois da aprovação (LGPD art. 6º, III). Para os
  demais, o campo vem `null`.
- O nome do empregado preenchido no formulário só serve para conferir se o arquivo é de quem
  enviou. Ele não é guardado. Formulário de outro empregado não entra no cálculo do chat, e o
  chat avisa.
- No chat, a pergunta "quantos dias de férias eu tenho?", sem número, usa o envio mais recente
  da própria pessoa. O cálculo segue a TB_1111-001, Tabela 1, e a NG_111, item 4.1.1.
  A resposta cita o arquivo e avisa quando o envio ainda aguarda aprovação.
- Sem envio com faltas, o chat explica o que enviar e encaminha à GEPEC.
- O chat nunca usa o envio de outra pessoa.

Limites:

- até 20 MiB por arquivo (`MAX_UPLOAD_BYTES`) e 10 arquivos por requisição;
- 20 envios por minuto (`RATE_UPLOAD_PER_MIN`);
- fila de triagem com até 20 arquivos (`TRIAGEM_FILA_MAX`); acima disso, o item volta como `failed`.

O limite de 16 KiB do corpo vale para todas as outras rotas.

`POST` vindo de navegador com `Origin` fora de `CORS_ORIGINS` recebe `403` (proteção contra CSRF,
porque o front manda `credentials: include`).

## Gráficos (`/analyses/charts`)

O back agrega os dados com pandas e devolve séries prontas; o front escolhe a biblioteca de
gráfico.

```json
{"id": "acervo-tema", "titulo": "Documentos por tema", "tipo": "barra",
 "eixoX": "Tema", "eixoY": "Documentos",
 "series": [{"nome": "Documentos", "pontos": [{"x": "ferias", "y": 5}]}],
 "nota": null}
```

Valores de `tipo`: `barra`, `barra_empilhada`, `pizza`, `linha` e `heatmap`. No `heatmap`, cada
série é uma linha da grade. Quando não há dado visível, `nota` explica o motivo.

| Painel | Gráficos | Quem vê |
|---|---|---|
| `acervo` | por tema, por setor dono, vigentes x substituídas, classificação x tema | qualquer perfil; conta só os documentos que ele vê |
| `radar` | prazos por criticidade, prazos por mês (`hoje` simula a data) | qualquer perfil; conta só os prazos que ele vê |
| `triagem` | classificação sugerida, setor dono, classificação x setor, tipos de dado sigiloso, situação da aprovação | conta só os envios que o perfil vê |
| `uso` | eventos por dia, permitido/bloqueado/abstenção, intenções, nível | só governança (`curate`): `401` para anônimo, `403` para os demais |

As contagens nunca incluem o que o perfil não vê. Uma barra "Sigilosa: 2" já revelaria que
esses documentos existem.

O painel `uso` lê a view `auditoria_resumo`. A view agrega por dia, ação, resultado, intent e
nível, e não tem a coluna `sujeito`: não há gráfico por pessoa (LGPD art. 6º, III). O papel da
aplicação tem `SELECT` só na view, não na tabela `auditoria`. Para criar a view, rode uma vez
com o papel dono: `python -m app.services.audit_log`.

## Identidade: como o back sabe quem pergunta

O acesso **nunca** vem do cliente. O cliente informa só o id da persona; setor, cargo e
habilitação saem do cadastro no servidor (`app/core/personas.py`).

| `AUTH_MODE` | Como identificar | Sem identificação |
|---|---|---|
| `demo` (padrão) | `personaId` no body, **ou** header `X-Persona-Id`, **ou** query `?personaId=`/`?persona=`, **ou** cookie `raiz_persona` | Vê só o nível Pública: listas vazias |
| `token` | `Authorization: Bearer <token>` **ou** cookie `raiz_sessao` (emitir: `python -m app.core.auth <personaId>`) | `401` |

### Identidade do front (`/identity`)

No modo API, o front não escolhe a persona: ele chama `GET /identity`, como faria com um SSO. Não
há tela de login. Para gravar a identidade, quem apresenta chama `POST /identity` uma vez, pelo
Swagger (`/swagger`) ou pelo front. O servidor responde com um cookie HttpOnly, e o front o manda
em todas as chamadas (`credentials: include`).

| Rota | Corpo | Resposta |
|---|---|---|
| `GET /identity` | — | `{id, name, capabilities, modo, setor, setorNome, cargo, senioridade, habilitacao}` |
| `POST /identity` | demo: `{persona}`; token: `{token}` | igual ao GET, com `Set-Cookie` |
| `POST /identity/sair` | — | visitante; apaga os cookies |

`capabilities` só orienta a tela. A autorização é refeita em cada rota.

| Capacidade | Quem tem |
|---|---|
| `upload` | toda pessoa identificada |
| `approve` | sênior, gestor e diretor |
| `curate` | curadoria e diretoria; o front usa esta capacidade para mostrar a governança |
| `sigiloso` | quem tem habilitação Sigilosa |

O cookie usa `SameSite=Lax` por padrão. Isso funciona com o front e a API em
`localhost:3000` e `localhost:8000`, porque portas diferentes contam como o mesmo site.

Com o front e a API em domínios diferentes:

- use `COOKIE_SAMESITE=none`;
- o cookie passa a ser enviado só por HTTPS (`Secure`);
- a checagem de `Origin` continua barrando POST vindo de outros sites.

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

O modo `demo` é uma **simulação de RBAC**: qualquer pessoa pode escolher qualquer persona.
Use só com o acervo sintético. Com dados reais, use `AUTH_MODE=token` atrás de HTTPS.

## O que o front precisa ajustar (branch `lana`, rotas antigas)

Pendências da branch `Dev` em [docs/PENDENCIAS_FRONT.md](PENDENCIAS_FRONT.md).

1. **Mandar a persona em todas as chamadas.** Hoje só `/chat` envia `personaId`. Em `/docs`,
   `/radar`, `/access`, `/ingest` e `/reports`, mande o header `X-Persona-Id` (ou `personaId` no
   body do `/reports`). Sem isso essas rotas devolvem listas vazias, ou `403` no `/reports`.
2. **Definir `NEXT_PUBLIC_API_URL`.** Sem essa variável o `fetchWithFallback` nem chama o back.
3. **Subir o timeout do `/chat`.** O `fetchWithFallback` desiste em 1,8 s. Calculadoras e modo
   extrativo respondem em milissegundos, mas com o LLM ligado a resposta leva alguns segundos.
   Use `LLM_TIMEOUT_S + 2` segundos no `/chat`.
4. **Não cair no fallback local em `401`, `403` ou `429`.** Hoje qualquer erro vira fallback, e o
   fallback (`/api/chat` do Next) ignora a persona e devolve dados do contrato de locação.
   Isso anula o controle de acesso do back. Nesses status, mostre a mensagem de erro.
5. **`/reports`:** hoje o front manda só `{tema}`. Inclua `personaId`.

## Controle de acesso

A classificação segue [docs/CLASSIFICACAO_BBTS.md](CLASSIFICACAO_BBTS.md):

- **Interno**: qualquer pessoa identificada vê.
- **Sigiloso**: só vê quem cumpre duas condições (LAI art. 25, § 1º):
  1. o setor da pessoa está na lista do documento (necessidade de conhecer);
  2. a pessoa tem habilitação Sigilosa (credenciamento).
- Classificação e setores por documento em `app/seed/manifesto.json`, gerado por
  `scripts/gerar_manifesto.py`. O `#interna` impresso no PDF nunca reduz a classificação.
- Sigilosos: `NT_2026-021` (GEINOV, DIRTEC, DIRAF), `NT_2026-018` (GESUC, GOC, DIRAF),
  `CTR_2026-012` (GESUC, GOC, GFI) e as versões substituídas (só GEPEC).
- O filtro acontece antes da busca: o índice de cada perfil de acesso (setor + habilitação) só
  contém o que aquele perfil pode ver. O LLM nunca recebe trecho proibido.
- Calculadoras, radar e relatórios declaram as fontes e passam pela mesma checagem.
- `rbacBlock` revela só o **setor dono** do conteúdo sigiloso, nunca código, título ou trecho.
- **Exceção aceita (GRAFO-21):** o chat confirma que existe algo fora do alcance da pessoa e diz
  qual setor cuida do pedido de acesso. É de propósito: é o passo 7 da demo
  (pedir acesso). Nenhuma outra rota faz isso. O `/grafo` trata documento invisível como
  inexistente.
- Não há cache de respostas. Toda resposta sai com `Cache-Control: private, no-store`.

## LLM local

Preencha no `.env`:

```
LLM_BASE_URL=https://<vm>/v1
LLM_API_KEY=<chave>
LLM_MODEL=<nome do modelo>
```

Qualquer servidor compatível com a API da OpenAI serve (vLLM, Ollama, LM Studio). Sem essas
variáveis o chat funciona com calculadoras e trechos citados. HTTP sem TLS só é aceito para
`localhost` (túnel SSH), salvo `LLM_ALLOW_HTTP=true`. A resposta do modelo só é usada se citar
os trechos enviados; sem citação válida, o back devolve os trechos em modo extrativo.

## Limites

| Limite | Padrão | Variável |
|---|---|---|
| Tamanho do corpo | 16 KiB (`413`) | `MAX_BODY_BYTES` |
| Tamanho da mensagem | 2.000 caracteres (`422`) | `MAX_MESSAGE_CHARS` |
| Chat | 30 por minuto por persona e IP (`429`) | `RATE_CHAT_PER_MIN` |
| Relatórios | 3 por minuto (`429`) | `RATE_REPORTS_PER_MIN` |
| Grafo | 30 por minuto (`429`) | `RATE_GRAFO_PER_MIN` |
| Gravações do site (pedidos, análises, feedback) | 60 por minuto (`429`) | `RATE_REGISTROS_PER_MIN` |

## Pendências conhecidas (fora deste escopo)

- `/access` (branch `lana`) é um stub de leitura. Na branch `Dev`, `/access-requests` cria e
  decide pedidos, mas a decisão não altera a permissão real.
- `/ingest` só audita. A ingestão é offline (`python -m app.services.ingest.pipeline`), a partir
  do manifesto. O upload (`/document-jobs`) faz triagem e aprovação; o arquivo aprovado
  ainda não entra no índice do chat. Conectores são escopo do João.
- Busca só lexical (BM25). Embeddings ficaram fora: enviar o acervo a um serviço de embeddings
  exige decidir antes onde a VM fica (LGPD art. 33).
- O Neon (PostgreSQL) guarda a auditoria e um espelho de todo o conteúdo do sistema
  (documentos, trechos, regras, relações, conteúdo curado). As rotas continuam lendo dos arquivos.
  A auditoria é gravada em segundo plano por um papel que só tem `INSERT` nela. Ela ainda não é
  inviolável: quem é dono do banco pode alterar registros. Configuração no README, seção
  "Banco (Neon)".
- Riscos e mitigações completos: `docs/SEGURANCA_REVISAO_CODEX.md`.
