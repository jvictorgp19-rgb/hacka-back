"""Triagem pela linha de comando: diz se cada arquivo é Interno ou Sigiloso e de qual setor.

    python scripts/triar.py <arquivo-ou-pasta> [--json] [--ficha PASTA] [--sem-isolar]

--json        imprime o resultado completo em JSON (sem o texto do arquivo).
--ficha PASTA grava, para cada arquivo, a "ficha para a IA": o JSON da triagem com o texto por
              página. A ficha contém o conteúdo do arquivo: guarde com o mesmo sigilo dele.
--sem-isolar  lê no mesmo processo (mais rápido; use só com arquivos de confiança).

Classificação: docs/CLASSIFICACAO_BBTS.md. É sugestão: quem confirma é o aprovador do setor.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.triagem.extracao import ArquivoRecusado  # noqa: E402
from app.services.triagem.servico import triar_arquivo  # noqa: E402

LIMITE_ARQUIVOS = 500


def _arquivos(alvo: Path) -> list[Path]:
    if alvo.is_file():
        return [alvo]
    lista = sorted(p for p in alvo.rglob("*") if p.is_file() and not p.is_symlink())
    return lista[:LIMITE_ARQUIVOS]


def main() -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("alvo", type=Path)
    args.add_argument("--json", action="store_true")
    args.add_argument("--ficha", type=Path)
    args.add_argument("--sem-isolar", action="store_true")
    opcoes = args.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows usa cp1252 em pipe
    if not opcoes.alvo.exists():
        print(f"Não encontrado: {opcoes.alvo}", file=sys.stderr)
        return 2
    if opcoes.ficha:
        opcoes.ficha.mkdir(parents=True, exist_ok=True)

    resultados = []
    for arquivo in _arquivos(opcoes.alvo):
        try:
            t = triar_arquivo(arquivo, isolar=not opcoes.sem_isolar)
        except ArquivoRecusado as erro:
            resultados.append({"nome": arquivo.name, "status": "failed", "mensagem": str(erro)})
            if not opcoes.json:
                print(f"FALHA     {arquivo.name}: {erro}")
            continue
        resultados.append(t.as_dict())
        if opcoes.ficha:
            destino = opcoes.ficha / f"{arquivo.stem}.ficha.json"
            destino.write_text(json.dumps(t.as_dict(com_texto=True), ensure_ascii=False,
                                          indent=2), encoding="utf-8")
        if not opcoes.json:
            c, d = t.classificacao, t.departamento
            print(f"{c.nivel:9} {d['sigla']:6} ({d['confianca']:.0%}) {arquivo.name}")
            print(f"          acesso: {', '.join(c.setores)} | {c.resumo}")
    if opcoes.json:
        print(json.dumps(resultados, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
