"""Auditor do acervo: aponta inconsistências para o dono do documento corrigir.

Achados calculados a partir do Silver (cabeçalhos e trechos), não escritos à mão:
- documento citado que não está no acervo;
- documento que cita outro com data posterior à sua (anacronismo);
- versão substituída cujo cabeçalho ainda mostra vigência futura.

Acesso: só curadoria e diretoria (visão de governança), e só com os documentos que o sujeito
pode ver. Os demais recebem lista vazia.
"""

import re
from datetime import date

from app.core.auth import Sujeito
from app.schemas.api import IngestAuditFinding
from app.services.acervo import Acervo
from app.services.calculators.calendario import br

_CODIGO = re.compile(r"\b(?:NG|PX|PP|GU|FM|TB|FL|RG|NT|CTR)_\d{3,4}(?:-\d{3})?\b")


def _rotulo(doc, cab: dict) -> str:
    data = cab.get("data_referencia")
    return f"{doc.codigo} v{doc.versao}" + (f" ({br(date.fromisoformat(data))})" if data else "")


def auditar(acervo: Acervo, sujeito: Sujeito, hoje: date) -> list[IngestAuditFinding]:
    governanca = sujeito.persona is not None and sujeito.persona.governanca
    if not governanca:
        return []

    # Governança não é passe livre: o achado só cita documento que o sujeito pode ver (um achado
    # sobre a NT_2026-021 revelaria título e datas de um sigiloso da GEINOV à curadora da GEPEC).
    visiveis = [d for d in acervo.documentos if acervo.pode(sujeito.acesso, d)]
    catalogo = {d.codigo for d in acervo.documentos}
    vigentes = {d.codigo: d for d in visiveis if d.vigente and d.arquivo}
    cab = {d.codigo: acervo.cabecalhos.get(f"{d.codigo}@{d.versao}", {})
           for d in vigentes.values()}
    citados: dict[str, set[str]] = {codigo: set() for codigo in vigentes}
    for chunk in acervo.chunks:
        if chunk.vigente and chunk.codigo in citados:
            citados[chunk.codigo].update(_CODIGO.findall(chunk.texto))

    achados: list[IngestAuditFinding] = []

    # 1. Anacronismo: A (data X) cita B, mas B só existe a partir de uma data posterior a X.
    for codigo, refs in sorted(citados.items()):
        data_a = cab[codigo].get("data_referencia")
        for ref in sorted(refs & vigentes.keys() - {codigo}):
            data_b = cab[ref].get("data_referencia")
            if data_a and data_b and data_b > data_a:
                achados.append(IngestAuditFinding(
                    id=f"AUD-TEMP-{len(achados) + 1:02d}",
                    camada="Silver (Validated Chunk)",
                    severidade="Inconsistência Temporal",
                    documentosEnvolvidos=[_rotulo(vigentes[codigo], cab[codigo]),
                                          _rotulo(vigentes[ref], cab[ref])],
                    descricao=f"{codigo} tem data {br(date.fromisoformat(data_a))}, mas cita "
                              f"{ref}, que só tem data {br(date.fromisoformat(data_b))}.",
                    acaoRecomendada=f"A área dona ({vigentes[codigo].dominio}) deve conferir as "
                                    "datas de publicação e corrigir a referência cruzada."))

    # 2. Versão substituída com vigência impressa ainda no futuro.
    for doc in visiveis:
        c = acervo.cabecalhos.get(f"{doc.codigo}@{doc.versao}", {})
        fim = c.get("vigencia_fim")
        atual = vigentes.get(doc.codigo)
        if not doc.vigente and fim and date.fromisoformat(fim) >= hoje and atual:
            achados.append(IngestAuditFinding(
                id=f"AUD-VIG-{len(achados) + 1:02d}",
                camada="Gold (Curated Graph)",
                severidade="Conflito de Vigência",
                documentosEnvolvidos=[f"{doc.codigo} v{doc.versao} (até "
                                      f"{br(date.fromisoformat(fim))})",
                                      _rotulo(atual, cab[atual.codigo])],
                descricao=f"O cabeçalho da {doc.codigo} v{doc.versao} mostra vigência até "
                          f"{br(date.fromisoformat(fim))}, mas a fase é \"Versão anterior\": ela "
                          f"foi substituída pela v{atual.versao}.",
                acaoRecomendada="O status vem do campo Fase e da relação de substituição, não das "
                                "datas. A versão antiga fica fora do índice de respostas."))

    # 3. Documentos citados que não estão no acervo.
    ausentes: dict[str, list[str]] = {}
    for codigo, refs in citados.items():
        for ref in refs - catalogo:
            ausentes.setdefault(ref, []).append(codigo)
    for ref, quem in sorted(ausentes.items()):
        achados.append(IngestAuditFinding(
            id=f"AUD-MISS-{len(achados) + 1:02d}",
            camada="Bronze (Raw PDF)",
            severidade="Documento Referenciado Ausente",
            documentosEnvolvidos=[ref, *sorted(quem)],
            descricao=f"{ref} é citado por {len(quem)} documento(s), mas não está no acervo.",
            acaoRecomendada=f"Responder \"não consta nas fontes\" quando pedirem o texto de {ref} "
                            "e solicitar o documento à área dona."))
    return achados
