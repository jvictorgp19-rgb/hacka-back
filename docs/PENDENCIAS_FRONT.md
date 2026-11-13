# Pendências do front (hacka-front, branch `Homolog`)

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

## 2. O front não manda a identidade nas chamadas

O client faz `GET /identity` e manda `?persona=` só em algumas rotas. Nas outras
(`/identity`, `/documents`, `/analyses/evidence`, `/deadlines`, `/audit/findings`,
`/simulation-rules`, `/documents/{id}/file` e `POST /document-jobs`), o back não sabe quem chama:

- `AUTH_MODE=demo`: vale `DEMO_DEFAULT_PERSONA`. Sem ela, o sujeito é visitante e as listas vêm
  vazias. Para trocar de persona, é preciso reiniciar o back com outro valor.
- `AUTH_MODE=token`: o front nunca manda `Authorization: Bearer`, então tudo dá `401`.

O link do PDF (`fileUrl`) também abre sem identidade, pelo mesmo motivo.

O back não tem mais `POST /identity` nem cookie de sessão: o front não chamava essas rotas.

Sugestão: mandar `Authorization: Bearer <token>` (ou `X-Persona-Id` no modo demo) em todas as
chamadas.

## 3. Setor dono padrão `GGC` nos pedidos de acesso

- `Governance.tsx:26` usa `'GGC'` quando não há área.
- `Conversation.tsx:231` usa `answer.facts[0]?.area || 'GGC'` no link "pedir acesso".
- `calculations.ts:125` fixa `owner: 'GGC'`.

`GGC` é sigla da ACME, não um setor BBTS do cadastro. O back responde `422` em
`POST /access-requests` com esse `owner`.

Na resposta `access_required`, o chat não traz fatos (o conteúdo é sigiloso). Por isso o link
sempre cai no `'GGC'`. O motor do chat sabe o setor dono (`rbacBlock.dominioResponsavel`), mas
o schema `answerSchema` não tem esse campo.

## 4. Seleção do setor dono limitada aos documentos visíveis

`Governance.tsx` monta a lista de setores com `documents.map((d) => d.area)`. Quem não vê um
documento não consegue escolher o setor dono dele. Exemplo: `ana` não vê nada da GESUC, então
não consegue pedir acesso ao contrato de coworking pela tela.

## 5. Aprovação e eliminação de envios sem tela

O front envia arquivos (`POST /document-jobs`) e consulta o estado (`GET /document-jobs/{id}`),
mas não tem tela para:

- o aprovador decidir o envio que exige aprovação (de júnior, sigiloso ou com confiança baixa).
  O envio fica `pendente`, visível só para quem enviou e para os aprovadores;
- quem enviou pedir a eliminação dos dados pessoais antes do prazo (LGPD art. 18, VI). Até
  existir a tela, o pedido vai pelo encarregado (LGPD art. 41), que roda
  `python scripts/eliminar_envio.py <id>`. A eliminação automática por
  `RETENCAO_ENVIOS_DIAS` continua.

As rotas de decisão e de eliminação saíram do back junto com as outras que o front não chama.
Voltam quando a tela existir.

## Resolvido

- **PDFs sigilosos em `public/docs_acervo/`.** O modo demo apontava para PDFs servidos pelo Next
  sem controle de acesso, inclusive os sigilosos (LGPD art. 46; LAI art. 25). Saíram do front com
  o código da Lana e o modo demo (branch `chore/remove-codigo-lana`, [PR #3](https://github.com/jvictorgp19-rgb/hacka-front/pull/3) para `Homolog`). Os PDFs
  agora só saem por `GET /documents/{id}/file`, com ACL.
