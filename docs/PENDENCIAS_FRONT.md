# Pendências do front (hacka-front, branch `Dev`)

Lista do que o back encontrou no front ao ligar as rotas. **O back não contorna nenhum destes
pontos**: segue o contrato como está. A correção é do front.

Referência: `src/services/http/client.ts` e `src/contracts/models.ts`.

## 1. `/simulation-rules` dá 403 para todas as personas

O schema `simulationSchema` junta numa resposta só as regras de férias (NG_111, Interna), da
nota técnica de inovação (NT_2026-021, sigilosa: GEINOV, DIRTEC, DIRAF) e do contrato de
coworking (CTR_2026-012, sigiloso: GESUC, GOC, GFI). Nenhuma persona vê os dois sigilosos.

O back não devolve nada parcial nem valores de preenchimento: isso vazaria número de documento
sigiloso ou mostraria regra falsa (LAI art. 25, § 1º). Resultado: a tela de Simuladores fica
sem regras na API.

Sugestão: separar em rotas por fonte (férias, inovação, contrato), cada uma com a sua ACL.

## 2. O front nunca chama `POST /identity`

O client só faz `GET /identity`. Sem o `POST`, o cookie HttpOnly não é gravado. As rotas sem
`?persona=` (`/documents`, `/analyses/evidence`, `/deadlines`, `/audit/findings`,
`/simulation-rules`, `/documents/{id}/file`) respondem como visitante: listas vazias, ou o nível
definido em `DEMO_DEFAULT_PERSONA`.

O link do PDF (`fileUrl`) também abre sem persona, pelo mesmo motivo.

Sugestão: chamar `POST /identity` ao escolher a persona, ou mandar o header `X-Persona-Id` em
todas as chamadas.

## 3. Setor dono padrão `GGC` nos pedidos de acesso

- `Governance.tsx:26` usa `'GGC'` quando não há área.
- `Conversation.tsx:231` usa `answer.facts[0]?.area || 'GGC'` no link "pedir acesso".
- `calculations.ts:125` fixa `owner: 'GGC'`.

`GGC` é sigla da ACME, não um setor BBTS do cadastro. O back responde `422` em
`POST /access-requests` com esse `owner`.

Na resposta `access_required`, o chat não traz fatos (o conteúdo é sigiloso). Por isso o link
sempre cai no `'GGC'`. O setor dono vem em `rbacBlock.dominioResponsavel` do `/chat`, mas o
schema `answerSchema` não tem esse campo.

## 4. Seleção do setor dono limitada aos documentos visíveis

`Governance.tsx` monta a lista de setores com `documents.map((d) => d.area)`. Quem não vê um
documento não consegue escolher o setor dono dele. Exemplo: `ana` não vê nada da GESUC, então
não consegue pedir acesso ao contrato de coworking pela tela.

## 5. PDFs sigilosos em `public/docs_acervo/`

`src/services/demo/catalog.ts` e `src/services/demo/evidence.json` apontam para
`/docs_acervo/...`, servido pelo Next sem controle de acesso. Os PDFs sigilosos (NT_2026-021,
NT_2026-018, CTR_2026-012 e as versões substituídas) ficam abertos para quem souber o caminho
(LGPD art. 46; LAI art. 25).

No modo API, o back serve os PDFs por `GET /documents/{id}/file`, com ACL. Sugestão: tirar os
sigilosos de `public/` e usar só o `fileUrl` da API.

## 6. Conversa com `tema: 'todos'`

O contexto padrão manda `tema: 'todos'`. O motor do chat só conhece `ferias`, `inovacao` e
`locacao`; com outro valor, ele usa férias (`router.py`, `responder`). As calculadoras e o
reforço da busca passam a favorecer férias, e uma pergunta sobre contrato pode cair em férias.

Sugestão: mandar o tema da tela quando houver um, ou deixar a pessoa escolher.
