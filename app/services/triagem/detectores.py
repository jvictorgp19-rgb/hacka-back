"""Detectores de sigilo. Seguem o critério de docs/CLASSIFICACAO_BBTS.md, seção 2:

- INTERNO: orienta qualquer empregado (regra, passo a passo, formulário em branco, programa aberto).
- SIGILOSO: traz dados financeiros, comerciais ou de terceiros (preços, cotações, multas, alçadas,
  orçamento), dados pessoais (formulário preenchido) ou é versão obsoleta.

Mais três casos que o documento não cobre e que tornam qualquer arquivo sigiloso do setor:
código-fonte, credencial exposta e dado pessoal sensível (LGPD art. 5º, II).

Um achado guarda tipo, contagem, páginas e o critério. NUNCA guarda o valor encontrado: o CPF, a
senha ou o preço não saem daqui (LGPD art. 6º, III).
"""

import re
import unicodedata
from dataclasses import asdict, dataclass
from functools import lru_cache

LIMIAR_COMERCIAL = 15.0  # calibrado no acervo: interno chega a 9,5; sigiloso começa em 28,5
TOPO = 1500  # cabeçalho: onde fica a marcação de classificação


@dataclass
class Achado:
    tipo: str
    rotulo: str
    nivel: str  # nível que o achado sugere
    ocorrencias: int
    paginas: list[int]
    criterio: str  # por que isso pesa, com a fonte (classificação BBTS ou lei)

    def as_dict(self) -> dict:
        return asdict(self)


@lru_cache(maxsize=16)
def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")


def _paginas(padrao: re.Pattern, paginas: list[str], normalizado: bool = False,
             validar=None) -> tuple[int, list[int]]:
    total, onde = 0, []
    for numero, pagina in enumerate(paginas, 1):
        alvo = normalizar(pagina) if normalizado else pagina
        achados = [m for m in padrao.finditer(alvo) if validar is None or validar(m)]
        if achados:
            total += len(achados)
            onde.append(numero)
    return total, onde


# ---------- validação de documentos brasileiros ----------
def cpf_valido(numero: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", numero)]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(v * (tamanho + 1 - i) for i, v in enumerate(d[:tamanho]))
        if (soma * 10 % 11) % 10 != d[tamanho]:
            return False
    return True


def luhn_valido(numero: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", numero)][::-1]
    if not 13 <= len(d) <= 19:
        return False
    soma = sum(v if i % 2 == 0 else (v * 2 - 9 if v * 2 > 9 else v * 2) for i, v in enumerate(d))
    return soma % 10 == 0


# ---------- padrões ----------
_CPF = re.compile(r"(?<![\d.])\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?![\d.])")
# Quantificadores limitados ({0,3}): \s* encadeado é backtracking quadrático (ReDoS).
_MATRICULA = re.compile(r"matr[ií]cula[ \t]{0,3}(?:n[º°o.]{0,3})?[ \t]{0,3}:?[ \t]{0,3}\d{4,12}",
                        re.IGNORECASE)
_NOME_PREENCHIDO = re.compile(
    r"\bnome(?: do empregado| completo| do titular)?[ \t]{0,3}:[ \t]{0,3}"
    r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]{1,30}"
    r"(?:[ \t]{1,3}(?:d[aeo]s?[ \t]{1,3})?[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]{1,30}){1,6}")
_RG = re.compile(r"\bRG[ \t]{0,3}(?:n[º°o.]{0,3})?[ \t]{0,3}:?[ \t]{0,3}"
                 r"\d{1,2}\.?\d{3}\.?\d{3}-?[\dXx]\b")
_EMAIL = re.compile(r"\b[\w+-][\w.+-]{0,63}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,6}\b")
_TELEFONE = re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-\d{4}\b")
_ADMISSAO = re.compile(r"admiss[aã]o[ \t]{0,3}:?[ \t]{0,3}\d{2}/\d{2}/\d{4}", re.IGNORECASE)

_SENSIVEL = re.compile(
    r"\bcid[- ]?(?:10)?[ \t]{0,3}:?[ \t]{0,3}[a-tv-z]\d{2}(?:\.\d)?\b|atestado medico|"
    r"laudo (?:medico|psicologico|pericial)|prontuario|diagnostico de|biometri|"
    r"impressao digital|dado genetico|"
    r"filiad[oa] ao sindicato|filiacao sindical|religiao:|orientacao sexual|origem racial|etnia:")
_SENSIVEL_GENERICO = re.compile(r"\b(?:doenca|gestante|gravidez|hiv|deficiencia)\b")

_CREDENCIAL = re.compile(
    r"(?:senha|password|passwd|pwd|secret|token|api[_-]?key|chave de acesso)[ \t]{0,3}[:=]"
    r"[ \t]{0,3}\S{4,200}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|"
    r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s:/]{1,100}:[^\s@]{1,200}@",
    re.IGNORECASE)

_AGENCIA_CONTA = re.compile(r"ag[eê]ncia[ \t]{0,3}:?[ \t]{0,3}\d{3,5}(?:-[\dxX])?[\s,;/|]{1,5}"
                            r"(?:c/?c|conta(?: corrente)?)[ \t]{0,3}:?[ \t]{0,3}\d{3,12}-[\dxX]",
                            re.IGNORECASE)
_CARTAO = re.compile(r"\b(?:\d{4}[ -]){3}\d{1,7}\b")
_EXTRATO = re.compile(r"\b(?:saldo|extrato)\b[^\n]{0,40}r\$\s?\d")

# Inclui os nomes de nível do próprio sistema (Sigilosa, Restrita) e o feminino da LAI.
_MARCA_SIGILO = re.compile(r"^#(?:sigilosa|restrita)\b|\b(?:confidencial|sigiloso|sigilosa|"
                           r"reservado|reservada|secreto|secreta|ultrassecreto|ultrassecreta|"
                           r"restrita)\b", re.IGNORECASE | re.MULTILINE)
_MARCA_INTERNA = re.compile(r"^#interna\b|\buso interno\b", re.IGNORECASE | re.MULTILINE)

_CODIGO_LINHA = re.compile(
    r"^\s*(?:def |class |import |from \S+ import |function |const |let |var |public |private |"
    r"package |#include|using |SELECT |INSERT |CREATE TABLE|return\b|if \(|for \()",
    re.MULTILINE)

# Termos comerciais (normalizados) e peso. Prêmio de programa aberto NÃO conta: o RG_1100 é
# interno mesmo citando valores de prêmio.
_COMERCIAIS = [
    (re.compile(r"\bcotac(?:ao|oes)\b"), 3.0),
    (re.compile(r"\bvalor global\b"), 2.0),
    (re.compile(r"\bprecos?\b"), 1.0),
    (re.compile(r"\bfornecedor(?:es)?\b"), 1.0),
    (re.compile(r"\balcadas?\b"), 1.0),
    (re.compile(r"\bmultas?\b"), 1.0),
    (re.compile(r"\baluguel\b"), 1.0),
    (re.compile(r"\borcamento\b"), 1.0),
    (re.compile(r"\blocador[a]?\b|\blocataria\b"), 0.5),
]
_REAIS = re.compile(r"r\$\s?\d")
_TETO_POR_TERMO = 10


def pontuacao_comercial(texto_normalizado: str) -> float:
    pontos = sum(min(len(p.findall(texto_normalizado)), _TETO_POR_TERMO) * peso
                 for p, peso in _COMERCIAIS)
    if pontos:  # valor em reais só pesa junto de contexto comercial
        pontos += min(len(_REAIS.findall(texto_normalizado)), 30) * 0.5
    return pontos


def detectar(paginas: list[str], formato: str, fase: str | None) -> list[Achado]:
    achados: list[Achado] = []
    texto = "\n".join(paginas)
    normal = normalizar(texto)

    if fase == "Versão anterior":
        achados.append(Achado(
            "versao_obsoleta", "Versão substituída", "Sigilosa", 1, [1],
            "Versão obsoleta pode levar a erro: fica só no arquivo histórico do setor dono "
            "(classificação BBTS, seção 5)."))

    pontos = pontuacao_comercial(normal)
    if pontos >= LIMIAR_COMERCIAL:
        termos = re.compile("|".join(p.pattern for p, _ in _COMERCIAIS))
        ocorrencias, onde = _paginas(termos, paginas, normalizado=True)
        achados.append(Achado(
            "financeiro_comercial", "Dados financeiros ou comerciais", "Sigilosa", ocorrencias,
            onde, f"Preços, cotações, multas, alçadas ou orçamento (pontuação {pontos:.1f}, "
                  f"corte {LIMIAR_COMERCIAL:.0f}; classificação BBTS, seção 2)."))

    pessoais = [
        ("CPF", *_paginas(_CPF, paginas, validar=lambda m: cpf_valido(m.group()))),
        ("matrícula", *_paginas(_MATRICULA, paginas)),
        ("nome preenchido", *_paginas(_NOME_PREENCHIDO, paginas)),
        ("RG", *_paginas(_RG, paginas)),
        ("e-mail", *_paginas(_EMAIL, paginas)),
        ("telefone", *_paginas(_TELEFONE, paginas)),
        ("data de admissão", *_paginas(_ADMISSAO, paginas)),
    ]
    encontrados = [(nome, n, onde) for nome, n, onde in pessoais if n]
    identificador = any(nome in ("CPF", "matrícula", "nome preenchido", "RG")
                        for nome, _, _ in encontrados)
    if identificador:
        achados.append(Achado(
            "dados_pessoais", "Dados pessoais: " + ", ".join(n for n, _, _ in encontrados),
            "Sigilosa", sum(n for _, n, _ in encontrados),
            sorted({p for _, _, onde in encontrados for p in onde}),
            "Dado pessoal (LGPD art. 5º, I). Formulário preenchido é sigiloso do setor "
            "(classificação BBTS, seção 3)."))

    n, onde = _paginas(_SENSIVEL, paginas, normalizado=True)
    if not n and identificador:
        n, onde = _paginas(_SENSIVEL_GENERICO, paginas, normalizado=True)
    if n:
        achados.append(Achado(
            "dado_sensivel", "Dado pessoal sensível (saúde, biometria, sindicato…)", "Sigilosa",
            n, onde, "Dado sensível (LGPD art. 5º, II): tratamento só nas hipóteses do art. 11."))

    n, onde = _paginas(_CREDENCIAL, paginas)
    if n:
        achados.append(Achado(
            "credencial", "Credencial exposta (senha, token ou chave)", "Sigilosa", n, onde,
            "Credencial em arquivo: troque a senha ou revogue a chave e remova do documento "
            "(LGPD art. 46: segurança)."))

    bancarios = (_paginas(_AGENCIA_CONTA, paginas)[0]
                 + _paginas(_CARTAO, paginas, validar=lambda m: luhn_valido(m.group()))[0]
                 + _paginas(_EXTRATO, paginas, normalizado=True)[0])
    if bancarios:
        achados.append(Achado(
            "dado_bancario", "Dado bancário (conta, cartão ou extrato)", "Sigilosa", bancarios,
            [i for i, p in enumerate(paginas, 1)
             if _AGENCIA_CONTA.search(p) or _EXTRATO.search(normalizar(p))
             or any(luhn_valido(m.group()) for m in _CARTAO.finditer(p))],
            "Operação bancária de cliente é sigilosa (LC 105/2001, art. 1º)."))

    linhas_codigo = len(_CODIGO_LINHA.findall(texto))
    if formato == "codigo" or linhas_codigo >= 8:
        achados.append(Achado(
            "codigo_fonte", "Código-fonte", "Sigilosa", max(linhas_codigo, 1),
            list(range(1, len(paginas) + 1)),
            "Código-fonte é ativo da empresa (NG_1130: direitos sobre as soluções): fica com o "
            "setor de desenvolvimento. Outras áreas, como o financeiro, não acessam."))

    topo = texto[:TOPO]
    if _MARCA_SIGILO.search(topo):
        achados.append(Achado(
            "marcacao_sigilo", "Marcado como sigiloso no próprio arquivo", "Sigilosa", 1, [1],
            "A marcação do autor é respeitada; a triagem nunca reduz o nível marcado."))
    elif _MARCA_INTERNA.search(topo):
        achados.append(Achado(
            "marcacao_interna", "Marcado como interno no próprio arquivo", "Interna", 1, [1],
            "A marcação não reduz o nível: o conteúdo pode torná-lo sigiloso (classificação "
            "BBTS, seção 5)."))
    return achados
