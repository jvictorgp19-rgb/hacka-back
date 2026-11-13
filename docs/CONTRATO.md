# Contrato da API — Raiz IQ / Zero Click

Base: `http://localhost:8000`. Documentação interativa em **`/swagger`**.

Os formatos abaixo espelham os schemas zod do `hacka-front`, branch `Homolog`
(`src/contracts/models.ts` e `src/services/http/client.ts`). A API expõe só as rotas que esse
front chama, mais o PDF citado nos links (`GET /documents/{id}/file`). Mudou o contrato? Avise no
chat e atualize aqui.

O back segue o contrato como está. Problemas do front ficam listados em
[docs/PENDENCIAS_FRONT.md](PENDENCIAS_FRONT.md), sem contorno no back.

## Rotas

| Rota | Entrada | Saída |
|---|---|---|
| `GET /identity` | — | `Identity` (seção "Identidade") |
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
| `POST /document-jobs` | multipart, campo `files` (até 10 arquivos; o front manda 1 por vez) | `UploadItem[]` |
| `GET /document-jobs/{id}` | — | `UploadItem` (404 se o sujeito não pode ver) |

Campo opcional sem valor sai **ausente**, nunca `null`: o zod `.optional()` recusa `null`.

Rotas que saíram porque o front não as chama (histórico em
[docs/HISTORICO_COMMITS.md](HISTORICO_COMMITS.md)):

- contrato antigo da branch `lana`: `/chat`, `/docs`, `/radar`, `/access`, `/ingest`, `/reports`,
  `/reports/pptx` e `/grafo`;
- `GET /health`, `GET /analyses/charts`, `POST /identity`, `POST /identity/sair`,
  `GET /document-jobs` (lista), `POST /document-jobs/{id}/decision` e
  `POST /document-jobs/{id}/forget`.

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

### Regras das rotas

- **Documentos e PDFs.** `/documents` lista só o que o sujeito vê. O `fileUrl` aponta para
  `GET /documents/{id}/file`, que confere o acesso de novo antes de servir o arquivo. A versão
  substituída sem PDF próprio sai sem `fileUrl`.
- **Fatos (`/analyses/evidence`).** Vêm de `app/seed/evidencias.json`. Cada fato cita um trecho
  conferido no acervo, com a página achada no PDF. `area` é a sigla BBTS do setor dono do
  documento citado (GEPEC, GEINOV, GESUC). O fato só sai para quem vê a versão citada.
- **Prazos.** Eventos do radar de prazos (`app/services/radar.py`), por regra e calendário. Cada
  prazo cita o item do documento que o fundamenta. `priority` é `Crítica` até 30 dias, `Alta`
  até 90 e `Normal` depois.
- **Achados.** Auditoria do acervo: inconsistência temporal, documento referenciado ausente e
  conflito de vigência, no formato `{id, title, detail, documents}`. Só com documentos que o
  sujeito vê.
- **Regras de simulação.** Valores reais das fontes: férias (NG_111), nota técnica
  (NT_2026-021) e contrato (CTR_2026-012). O contrato do front junta tudo numa resposta só. Se o
  sujeito não vê alguma das fontes, a rota responde `403` e não devolve nada parcial
  (LAI art. 25, § 1º).
- **Conversa.** Usa o motor do chat (`app/services/agent/router.py`). `tema: "todos"` (valor do
  contrato) busca sem viés de tema. `status`:
  - `access_required`: o motor apontou um setor sigiloso e nada visível respondeu;
  - `abstained`: abstenção, ou resposta sem citação;
  - `conflict`: a pergunta tocou numa regra revogada;
  - `answered`: os demais casos. Se a resposta veio de trechos visíveis e o motor também apontou
    um setor sigiloso, ela sai com o aviso no fim do texto e "Solicitar orientação" nos
    `nextSteps`.
- **Histórico da conversa.** Sai da mais antiga para a mais nova (as 100 mais recentes). Guarda
  a pergunta **mascarada** (CPF, e-mail, telefone etc.), só o id dos fatos e as citações sem
  link. Na leitura, fatos e links são refeitos com o acesso e o endereço atuais. Se uma fonte
  deixou de ser visível, a resposta inteira sai oculta. Resposta calculada com os envios da
  própria pessoa não guarda o texto no histórico (dado pessoal; LGPD art. 6º, III).
- **Pedidos de acesso.** `owner` precisa ser um setor BBTS. Decide quem cura o setor dono ou é
  diretor da diretoria dele. `granted` só registra a decisão: **não muda a permissão real**, que
  continua no cadastro (`app/core/personas.py`) e no manifesto. De duas decisões ao mesmo tempo,
  só uma grava; a outra recebe `409`. A auditoria guarda o id do pedido.
- **Análises salvas.** Do corpo só se aproveita o `id` de cada fato. O conteúdo vem do servidor e
  é refeito na leitura, com a ACL do momento.
- **Persona.** Nas rotas com `persona` no corpo ou na query, a ordem de resolução é a da seção
  "Identidade". No modo `token`, uma persona diferente da do token dá `403`.
- **Retenção.** Conversas, análises, feedback e pedidos ficam na tabela `registro_front`. Depois
  de `RETENCAO_REGISTROS_DIAS` (padrão 180) sem atualização, o registro some da leitura na hora.
  A retenção periódica apaga esses registros e elimina os dados pessoais dos envios vencidos
  (LGPD art. 15 e 16). Ela roda no startup e a cada `RETENCAO_INTERVALO_H` horas (padrão 6).
  Cada persona só lê os próprios registros. Pedido de acesso também aparece para quem decide.
- **Links.** `fileUrl` e `citation.url` usam `API_PUBLIC_URL`. Sem ela, usam o endereço da
  própria requisição. Em produção, defina `API_PUBLIC_URL`.
- **Erros.** Banco fora do ar dá `503` com mensagem fixa nas rotas que gravam ou leem registros.
  A conversa responde mesmo assim, mas não entra no histórico.

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
  "nivelFinal": null, "setoresFinais": [], "decidedBy": null, "decidedAt": null, "response": null
}
```

Ciclo do envio:

1. O `POST` confere identidade, tamanho e assinatura do arquivo e responde na hora.
   - Se o arquivo passa, o status é `processing`.
   - Se não passa, o status é `failed` e `message` diz o motivo.
2. A triagem roda em segundo plano, num processo separado com tempo limite.
3. O `GET /document-jobs/{id}` traz o resultado, com status `ready`, `not_extracted` ou `failed`.
4. O arquivo é apagado logo após a triagem.
5. O banco (`triagem_documento`) guarda só nome, tamanho, hash, sugestão e situação da
   aprovação. Ele nunca guarda o texto nem os valores encontrados (LGPD art. 6º, III, e art. 46).

Aprovação, conforme docs/CLASSIFICACAO_BBTS.md e LAI art. 27:

- **Quando é exigida.** Em todo envio de desenvolvedor júnior. Também quando a sugestão pede
  revisão humana: sigilosa, conteúdo não extraído ou confiança baixa. Nos demais casos,
  `aprovacao` é `dispensado`.
- **Sem rota de decisão.** O hacka-front não tem tela de aprovação, então a API também não tem
  rota para decidir. O envio que exige aprovação fica `pendente` (docs/PENDENCIAS_FRONT.md,
  item 5). `aprovadores` diz quem poderia aprovar.
- **Quem vê o pendente.** Quem enviou e os aprovadores. Quem enviou nunca aprova o próprio envio.
  - Sugestão Interna (envio de júnior): gestor ou sênior do setor de quem enviou ou do setor
    dono, a curadoria do setor dono e o diretor da diretoria do setor dono.
  - Sugestão Sigilosa ou não extraída: só quem tem habilitação Sigilosa e necessidade de
    conhecer, ou seja, gestor ou sênior do setor dono, a curadoria dele ou o diretor da diretoria
    dele (LAI art. 25, § 1º). O gestor de quem enviou, sem habilitação, não vê o envio.
- **Dispensado.** Vale a regra de acesso do nível e dos setores sugeridos. Quem não pode ver
  recebe `404`, para não saber que o envio existe.

Retenção (LGPD art. 15 e 16):

- Passados `RETENCAO_ENVIOS_DIAS` (padrão 180), o nome do arquivo, a resposta do aprovador e os
  fatos de férias são eliminados. A classificação fica, sem dado pessoal.
- O pedido de eliminação antes do prazo (LGPD art. 18, VI) não tem rota. O encarregado
  roda `python scripts/eliminar_envio.py <id>` e reinicia a API; o pedido chega por ele
  (LGPD art. 41) até o front ter a tela.

Férias pelos envios:

- A triagem tira de formulário preenchido (FM_1111-001) e de espelho de ponto (planilha com
  coluna "Ocorrência") só números e datas: faltas injustificadas, período aquisitivo, admissão e
  início de gozo. Nome, CPF e matrícula ficam de fora.
- Arquivo com esses fatos é sugerido como Sigiloso da GEPEC (achado `registro_ferias`).
- O campo `ferias` do `UploadItem` traz `{faltasInjustificadas, origemFaltas, periodoInicio,
  periodoFim, admissao, inicioGozo, diasDeFerias, paginas}`.
- `ferias` só aparece para quem enviou, para os aprovadores enquanto o envio está pendente e,
  fora disso, para a GEPEC habilitada que pode ver o envio (LGPD art. 6º, III). Para os demais,
  o campo vem `null`.
- O nome do empregado preenchido no formulário só serve para conferir se o arquivo é de quem
  enviou. Ele não é guardado. Formulário de outro empregado não entra no cálculo do chat, e o
  chat avisa.
- No chat, a pergunta "quantos dias de férias eu tenho?", sem número, usa o envio mais recente
  da própria pessoa. O cálculo segue a TB_1111-001, Tabela 1, e a NG_111, item 4.1.1.
  A resposta cita o arquivo e avisa quando o envio ainda aguarda aprovação. Pergunta sobre
  antecedência ("quantos dias de antecedência para pedir férias?") é regra da NG_111, não saldo.
- Sem envio com faltas, o chat explica o que enviar e encaminha à GEPEC.
- O chat nunca usa o envio de outra pessoa.

Limites:

- até 20 MiB por arquivo (`MAX_UPLOAD_BYTES`) e 10 arquivos por requisição;
- 20 envios por minuto (`RATE_UPLOAD_PER_MIN`);
- fila de triagem com até 20 arquivos (`TRIAGEM_FILA_MAX`); acima disso, o item volta como `failed`.

O limite de 16 KiB do corpo vale para todas as outras rotas.

`POST` vindo de navegador com `Origin` fora de `CORS_ORIGINS` recebe `403` (proteção contra CSRF:
no modo `demo`, um POST sem persona age como `DEMO_DEFAULT_PERSONA`). A própria origem da API
(o Swagger) passa.

## Identidade: como o back sabe quem pergunta

O acesso **nunca** vem do cliente. O cliente informa só o id da persona; setor, cargo e
habilitação saem do cadastro no servidor (`app/core/personas.py`).

| `AUTH_MODE` | Como identificar | Sem identificação |
|---|---|---|
| `demo` (padrão) | `personaId` no body, **ou** header `X-Persona-Id`, **ou** query `?personaId=`/`?persona=`, **ou** `DEMO_DEFAULT_PERSONA` | Vê só o nível Pública: listas vazias |
| `token` | `Authorization: Bearer <token>` (emitir: `python -m app.core.auth <personaId>`) | `401` |

### `GET /identity`

No modo API, o front não escolhe a persona: ele chama `GET /identity`, como faria com um SSO. A
resposta sai do mesmo sujeito das outras rotas:
`{id, name, capabilities, modo, setor, setorNome, cargo, senioridade, habilitacao}`.

O front não manda identidade no `GET /identity` nem nas rotas sem `?persona=`
(docs/PENDENCIAS_FRONT.md, item 2). No modo `demo`, essas rotas usam `DEMO_DEFAULT_PERSONA`:
para apresentar com outra persona, reinicie o back com outro valor. No modo `token`, o front
ainda não manda `Authorization`, e as rotas respondem `401`.

`capabilities` só orienta a tela. A autorização é refeita em cada rota.

| Capacidade | Quem tem |
|---|---|
| `upload` | toda pessoa identificada |
| `curate` | curadoria e diretoria; o front usa esta capacidade para mostrar a governança |
| `sigiloso` | quem tem habilitação Sigilosa |

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
- Calculadoras e prazos declaram as fontes e passam pela mesma checagem.
- O bloqueio do chat revela só o **setor dono** do conteúdo sigiloso, nunca código, título ou
  trecho.
- **Exceção aceita (GRAFO-21):** o chat confirma que existe algo fora do alcance da pessoa e diz
  qual setor cuida do pedido de acesso. É de propósito: é o passo do pedido de acesso na demo.
  Nenhuma outra rota faz isso.
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
| Envios de arquivo | 20 por minuto (`429`) | `RATE_UPLOAD_PER_MIN` |
| Gravações do site (pedidos, análises, feedback) | 60 por minuto (`429`) | `RATE_REGISTROS_PER_MIN` |

## Pendências conhecidas (fora deste escopo)

- A ingestão do acervo é offline (`python -m app.services.ingest.pipeline`), a partir do
  manifesto. O upload (`/document-jobs`) só faz triagem: o arquivo não entra no índice do chat.
  Conectores são escopo do João.
- Busca só lexical (BM25). Embeddings ficaram fora: enviar o acervo a um serviço de embeddings
  exige decidir antes onde a VM fica (LGPD art. 33).
- O Neon (PostgreSQL) guarda a auditoria e um espelho de todo o conteúdo do sistema
  (documentos, trechos, regras, relações, conteúdo curado). As rotas continuam lendo dos arquivos.
  A auditoria é gravada em segundo plano por um papel que só tem `INSERT` nela. Ela ainda não é
  inviolável: quem é dono do banco pode alterar registros. Configuração no README, seção
  "Banco (Neon)".
- Riscos e mitigações completos: `docs/SEGURANCA_REVISAO_CODEX.md`.
