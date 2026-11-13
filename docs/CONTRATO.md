# Contrato da API — Raiz IQ / Zero Click

Base: `http://localhost:8000`. Documentação interativa em **`/swagger`** (o caminho `/docs` é uma
rota do contrato: o catálogo do acervo).

Os formatos abaixo espelham os tipos TypeScript do `hacka-front`, branch `lana`
(`src/lib/api.ts` e `src/app/api/chat/route.ts`). Mudou o contrato? Avise no chat e atualize aqui.

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
| `GET /health` | — | `{"status": "ok"}` |

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

## Identidade: como o back sabe quem pergunta

O acesso **nunca** vem do cliente. O cliente informa só o id da persona; setor, cargo e
habilitação saem do cadastro no servidor (`app/core/personas.py`).

| `AUTH_MODE` | Como identificar | Sem identificação |
|---|---|---|
| `demo` (padrão) | `personaId` no body, **ou** header `X-Persona-Id`, **ou** query `?personaId=` | Vê só o nível Pública: listas vazias |
| `token` | `Authorization: Bearer <token>` (emitir: `python -m app.core.auth <personaId>`) | `401` |

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

## O que o front precisa ajustar (Lana)

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

## Pendências conhecidas (fora deste escopo)

- `/access` é um stub de leitura com um pedido sintético. Criar pedido, decidir e emitir resposta
  curada é escopo do Victor.
- `/ingest` só audita. A ingestão é offline (`python -m app.services.ingest.pipeline`), a partir
  do manifesto. Upload e conectores são escopo do João.
- Busca só lexical (BM25). Embeddings ficaram fora: enviar o acervo a um serviço de embeddings
  exige decidir antes onde a VM fica (LGPD art. 33).
- O Neon (PostgreSQL) guarda a auditoria e um espelho de todo o conteúdo do sistema
  (documentos, trechos, regras, relações, conteúdo curado). As rotas continuam lendo dos arquivos.
  A auditoria é gravada em segundo plano por um papel que só tem `INSERT` nela. Ela ainda não é
  inviolável: quem é dono do banco pode alterar registros. Configuração no README, seção
  "Banco (Neon)".
- Riscos e mitigações completos: `docs/SEGURANCA_REVISAO_CODEX.md`.
