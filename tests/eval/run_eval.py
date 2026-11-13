"""Avaliação de exatidão do chat, pela rota que o front usa (POST /conversations/messages).

Mede, sobre tests/eval/perguntas.yaml:
- % de acerto            (a resposta contém o gabarito)
- % de citação correta   (o documento esperado está nas citações)
- % de abstenção correta (abstém-se ou bloqueia quando deve, e só quando deve)

Rodar:  python -m tests.eval.run_eval          (sem LLM: calculadoras + modo extrativo)
        python -m tests.eval.run_eval --llm    (usa o LLM configurado no .env)
"""

import os
import sys
from pathlib import Path

import yaml

if "--llm" not in sys.argv:
    for _var in ("LLM_BASE_URL", "LLM_MODEL"):
        os.environ[_var] = ""
os.environ.setdefault("AUTH_MODE", "demo")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.limites import zerar_taxas  # noqa: E402
from app.main import app  # noqa: E402

CASOS = yaml.safe_load((Path(__file__).parent / "perguntas.yaml").read_text(encoding="utf-8"))


def avaliar() -> dict:
    acertos = citacoes = com_citacao = abstencoes = 0
    falhas = []
    with TestClient(app) as cliente:
        for caso in CASOS:
            zerar_taxas()
            contexto = {"conversationId": "eval", "tema": caso["tema"], "area": "",
                        "perspective": "obligations", "from": "", "to": "",
                        "persona": caso["persona"] or ""}
            d = cliente.post("/conversations/messages",
                             json={"query": caso["pergunta"], "context": contexto}).json()
            texto = d["text"].lower()
            ok = all(trecho.lower() in texto for trecho in caso["contem"])

            status = d["status"]  # answered, abstained, conflict ou access_required
            tipo_ok = {"resposta": status == "answered",
                       "revogada": status == "conflict",
                       "abstencao": status == "abstained",
                       "bloqueio": status == "access_required"}[caso["tipo"]]

            acertos += ok and tipo_ok
            abstencoes += tipo_ok
            if caso["cita"]:
                com_citacao += 1
                citou = caso["cita"] in [c["codigo"] for c in d["citations"]]
                citacoes += citou
            else:
                citou = True
            if not (ok and tipo_ok and citou):
                falhas.append((caso["pergunta"], f"[{status}] {d['text'][:110]}"))
    total = len(CASOS)
    return {"total": total, "acerto": acertos / total, "citacao": citacoes / com_citacao,
            "comportamento": abstencoes / total, "falhas": falhas}


if __name__ == "__main__":
    r = avaliar()
    print(f"Perguntas: {r['total']}")
    print(f"Acerto:                          {r['acerto']:.0%}")
    print(f"Citação correta:                 {r['citacao']:.0%}")
    print(f"Abstenção/bloqueio corretos:     {r['comportamento']:.0%}")
    for pergunta, resposta in r["falhas"]:
        print(f"  FALHA: {pergunta}\n         -> {resposta}")
