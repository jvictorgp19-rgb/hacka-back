"""Elimina os dados pessoais de um envio a pedido do titular (LGPD art. 18, VI).

    python scripts/eliminar_envio.py <id-do-envio>

Ferramenta do encarregado (LGPD art. 41) enquanto o front não tem a tela. Roda com o DATABASE_URL
da aplicação: o papel raiz_app tem UPDATE em triagem_documento. Ficam só os metadados sem dado
pessoal (hash, nível, setor, decisão). Depois, reinicie a API: ela ainda guarda a cópia em memória.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import audit_log, envios  # noqa: E402

MENSAGENS = {
    "eliminado": "Dados pessoais eliminados. Reinicie a API para tirar a cópia da memória.",
    "em_triagem": "O envio ainda está em triagem. Tente de novo em instantes.",
    "nao_encontrado": "Envio não encontrado.",
}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not re.fullmatch(r"[0-9a-f]{32}", argv[0]):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        resultado = envios.eliminar_a_pedido(argv[0])
    except Exception as erro:  # noqa: BLE001 - a mensagem do driver pode trazer host e usuário
        print(f"Falha ao acessar o banco: {type(erro).__name__}.", file=sys.stderr)
        return 1
    if resultado == "eliminado":
        audit_log.registrar("encarregado", "eliminacao", "permitido", "titular:art18-vi",
                            [f"envio:{argv[0]}"], "-")
        audit_log.encerrar()
    print(MENSAGENS[resultado])
    return 0 if resultado == "eliminado" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
