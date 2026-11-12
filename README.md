# Hacka — Back-end

API da solução do hackathon. **Python + FastAPI**. Front-end em [hacka-front](https://github.com/jvictorgp19-rgb/hacka-front).

> Descrição do desafio e da solução: _preencher após a ideação da equipe_.

## Equipe

João (Sertoriel) · Lana · Victor · Thiago

## Estrutura

```
app/
├─ main.py        # entrada da aplicação (FastAPI, CORS, /health)
├─ api/routes/    # endpoints agrupados por recurso
├─ core/          # configuração, segurança, dependências
├─ models/        # modelos de banco/domínio
├─ schemas/       # schemas Pydantic (contrato de entrada/saída)
├─ services/      # regras de negócio (e integrações/IA)
└─ repositories/  # acesso a dados
tests/            # pytest
docs/             # decisões e contrato da API
```

## Começando

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload     # http://localhost:8000
```

- Documentação interativa (contrato): http://localhost:8000/docs
- Testes: `pytest` · Lint: `ruff check .`

## Branches e workflow

`main` ← `homolog-demo` ← `homolog-dev` ← branches pessoais (`joao-sertoriel`, `lana`, `victor`, `thiago`).
Detalhes em [docs/WORKFLOW.md](docs/WORKFLOW.md).
