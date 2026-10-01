"""Fases 5 e 6 — conferência pela chave de origem.

Não confia no estado local: pergunta ao AdvOS (imports_lookup, só leitura) por cada registro que o lote converteu e
compara Dash (pacotes) × enviados × marcados como gravados (estado) × presentes no AdvOS × pendências.
O SHA-256 de cada documento já foi conferido no envio (imports_upload_complete só aceita bytes iguais aos declarados).
Na tela, só contagens. Saídas na pasta do lote:
  conferencia.json         por cliente e por entidade, só ids e números
  conferencia-visual.csv   um cliente por linha, com nome e links do Dash e do AdvOS, para a conferência na tela
Uso: python3 conferir.py <lote>
"""

import csv
import json
import pathlib
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402
from advos_imports import call as advos  # noqa: E402

SECAO = {"client": "crm", "client_party": "crm", "legal_case": "legal", "proceeding": "legal", "deadline": "legal",
         "task": "legal", "client_document": "documents"}
DASH = {"legal_case": "ProcessoJuridico", "proceeding": "AndamentoProcessual", "deadline": "PrazoProcessual",
        "task": "Tarefa", "client_document": "DocumentoCliente"}
LINK_DASH = "https://advogandodash.com.br/ClienteDetalhes?id={}"
LINK_ADVOS = "https://app.advos.ai/clients/{}"


def lookup(entity, keys, ns):
    out = {}
    for i in range(0, len(keys), 100):
        r = advos("imports_lookup", {"section": SECAO[entity], "entity": entity, "namespace": ns,
                                     "externalKeys": keys[i:i + 100]})
        if r.get("isError") or not isinstance(r.get("data"), dict):
            raise SystemExit(f"🔴 imports_lookup recusou a consulta de {entity}: {str(r)[:200]}")
        out.update({it["externalKey"]: it["status"] for it in r["data"]["items"]})
    return out


def main(lote):
    cfg = config.carregar()
    pasta, _ficha = config.lote(lote)
    from converter import convert  # noqa: E402
    estado = json.loads((pasta / "estado.json").read_text()) if (pasta / "estado.json").exists() else {}
    feitos = sorted(c for c, s in estado.items() if s.get("fase") == "concluido")
    existiam = sorted(c for c, s in estado.items() if s.get("fase") == "existe")
    if not feitos:
        raise SystemExit(f"lote {lote}: nenhum cliente concluído ainda")
    pend = Counter()
    if (pasta / "pendencias.jsonl").exists():
        vistos = set()
        for linha in (pasta / "pendencias.jsonl").read_text().splitlines():
            r = json.loads(linha)
            if (r.get("cliente_dash"), r["item"], r["motivo"]) not in vistos:
                vistos.add((r.get("cliente_dash"), r["item"], r["motivo"]))
                pend[r.get("cliente_dash")] += 1

    chaves = defaultdict(list)          # entidade → chaves convertidas
    dono, nomes, dash_n = {}, {}, defaultdict(Counter)
    for cid in feitos:
        pkg = json.loads((pasta / "pacotes" / f"{cid}.json").read_text())
        ents = pkg["items"][0]["bundle"]["entities"]
        nomes[cid] = (ents.get("Cliente") or [{}])[0].get("nome_completo") or ""
        for ent, nome_dash in DASH.items():
            dash_n[cid][ent] = len(ents.get(nome_dash) or [])
        dash_n[cid]["client"] = 1
        crm, legal, docs, _ = convert(pkg)
        for r in crm + legal:
            chaves[r["entity"]].append(r["externalKey"]); dono[(r["entity"], r["externalKey"])] = cid
        for d in docs:
            k = d["descriptor"]["sourceFileId"]
            chaves["client_document"].append(k); dono[("client_document", k)] = cid

    marcados = set()
    for cid in feitos:
        st = estado[cid]
        marcados.add(("client", cid))
        marcados |= {("legal", k) for k in (st.get("legal") or {})}
        marcados |= {("documents", k) for k in (st.get("docs") or {})}

    resumo, por_cliente, faltam = {}, defaultdict(lambda: defaultdict(Counter)), 0
    for ent, keys in sorted(chaves.items()):
        status = lookup(ent, sorted(set(keys)), cfg["namespace"])
        c = Counter()
        for k in set(keys):
            cid = dono[(ent, k)]
            # o estado não guarda o alvo do representante (client_party): para ele, só a presença conta
            marcado = (("client", k) in marcados if ent == "client" else
                       False if ent == "client_party" else (SECAO[ent], k) in marcados)
            presente = status.get(k) == "present"
            c["convertidos"] += 1
            c["marcados_gravados"] += marcado
            c["presentes"] += presente
            c["alvo_apagado"] += status.get(k) == "target_missing"
            c["marcados_e_ausentes"] += marcado and not presente
            por_cliente[cid][ent]["convertidos"] += 1
            por_cliente[cid][ent]["presentes"] += presente
        c["dash"] = sum(dash_n[cid].get(ent, 0) for cid in feitos)
        faltam += c["marcados_e_ausentes"]
        resumo[ent] = dict(c)

    saida = {"conferido_em": config.agora(), "lote": lote, "clientes_concluidos": len(feitos),
             "ja_existiam_no_advos": len(existiam), "por_entidade": resumo,
             "por_cliente": {cid: {"advos_id": estado[cid].get("crm"), "pendencias": pend[cid],
                                   "entidades": {e: {**dict(v), "dash": dash_n[cid].get(e, 0)} for e, v in por_cliente[cid].items()}}
                             for cid in feitos}}
    config.escrever_json(pasta / "conferencia.json", saida)
    with (pasta / "conferencia-visual.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ordem", "cliente", "codigo_dash", "link_dash", "id_advos", "link_advos",
                    "dash_processos", "advos_processos", "dash_andamentos", "advos_andamentos", "dash_prazos",
                    "advos_prazos", "dash_tarefas", "advos_tarefas", "dash_documentos", "advos_documentos",
                    "qtd_pendencias", "conferido_por", "resultado_conferencia", "observacao"])
        for n, cid in enumerate(feitos, 1):
            pc, aid = por_cliente[cid], estado[cid].get("crm")
            w.writerow([n, nomes[cid], cid, LINK_DASH.format(cid), aid or "", LINK_ADVOS.format(aid) if aid else ""]
                       + [x for e in ("legal_case", "proceeding", "deadline", "task", "client_document")
                          for x in (dash_n[cid].get(e, 0), pc[e]["presentes"])]
                       + [pend[cid], "", "", ""])

    print(f"lote {lote} — conferência no AdvOS pela chave de origem ({len(feitos)} cliente(s) concluído(s); "
          f"{len(existiam)} já existiam e ficam para conferência à parte)")
    for ent, c in resumo.items():
        print(f"  {ent:16} Dash {c['dash']:5} | convertidos {c['convertidos']:5} | marcados gravados {c['marcados_gravados']:5} "
              f"| presentes {c['presentes']:5} | marcados e ausentes {c['marcados_e_ausentes']}"
              + (f" | alvo apagado no AdvOS {c['alvo_apagado']}" if c.get("alvo_apagado") else ""))
    print(f"  pendências registradas: {sum(pend[c] for c in feitos)} | detalhe: {pasta / 'conferencia.json'}")
    if faltam:
        print(f"  🔴 {faltam} registro(s) marcados como gravados que o AdvOS não tem: não declarar o lote concluído")
        raise SystemExit(1)
    print("  🟢 tudo o que o lote marcou como gravado está no AdvOS (Dash − convertidos = separados ou pendências)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
