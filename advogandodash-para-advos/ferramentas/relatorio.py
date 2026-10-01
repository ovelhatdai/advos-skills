"""Fase 6 — relatório do lote.

Gera, na pasta do lote:
  relatorio.html   resumo + pendências por cliente, COM nomes: fica só na pasta de trabalho
  pendencias.csv   cliente, código no Dash, item e motivo, COM nomes: lista para a equipe resolver
  resumo.html      só números e pendências por tipo, SEM nomes: este pode ser compartilhado
Os números de "presentes no AdvOS" vêm do conferir.py (prova pela chave de origem); rode-o antes.
Uso: python3 relatorio.py <lote>
"""

import csv
import html
import json
import pathlib
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402

ROTULOS = {"client": "clientes", "legal_case": "processos", "proceeding": "andamentos", "deadline": "prazos",
           "task": "tarefas", "client_document": "documentos"}


def tipo(m, item):
    return ("Contrato/financeiro (falta credencial finance)" if "finance" in m else
            "Judicial sem CNJ (separado para conferência)" if "sem número CNJ" in m and "separado" in m else
            "Judicial sem CNJ (entrou como administrativo)" if "sem número CNJ" in m else
            "Senha escrita em texto (cadastrar no campo seguro)" if "senha" in m else
            "Responsável/vendedor não é membro ativo no AdvOS" if "não é membro" in m or "não está ativo" in m else
            "Cliente já existia no AdvOS" if "já existe" in m else
            "CPF ausente ou inválido no Dash" if item == "CPF" else
            "Status/serviço sem correspondente" if "sem correspondente" in m else
            "Anexo em link privado ou inválido no Dash (buscar o original)" if "não baixado do Dash" in m or "página do Drive" in m else
            "Processo duplicado no Dash (mesmo CNJ)" if "duplicado" in m else
            "Tarefa automática concluída (não migrada)" if "automática" in m else
            "Tarefa sem responsável membro (não migrada)" if "tarefa sem responsável" in m else
            "Esperando decisão de rótulo" if "esperando decisão" in m else
            "Registro sem processo no pacote" if "sem processo" in m else
            "Recusado pelo AdvOS" if "recusado" in m or "não aceitos" in m or "não migrado porque" in m else
            "Documento não transferido" if str(item).startswith("documento") else "Outros")


CSS = """:root{--bg:#f7f6f2;--fg:#1d1d1b;--mut:#6b6a66;--card:#fff;--line:#e4e2dc;--ok:#1f7a4d;--warn:#9a6b00}
@media (prefers-color-scheme:dark){:root{--bg:#151513;--fg:#ecebe6;--mut:#a3a19b;--card:#1f1f1c;--line:#34332f;--ok:#5cc28f;--warn:#e0b04d}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 "Source Sans 3",system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px} h1{font-size:26px;margin:0 0 4px} .mut{color:var(--mut)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px} .n{font-size:28px;font-weight:700}
table{width:100%;border-collapse:collapse;background:var(--card)} td{border-bottom:1px solid var(--line);padding:8px}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:6px 0;padding:8px 12px}
summary{cursor:pointer;font-weight:600} summary span{color:var(--warn);font-weight:400;margin-left:6px}"""


def pagina(titulo, corpo):
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{html.escape(titulo)}</title><style>{CSS}</style>'
            f"</head><body><main>{corpo}</main></body></html>")


def main(lote):
    cfg = config.carregar()
    pasta, ficha = config.lote(lote)
    ids = json.loads((pasta / "alvos.json").read_text()) if (pasta / "alvos.json").exists() else []
    state = json.loads((pasta / "estado.json").read_text()) if (pasta / "estado.json").exists() else {}
    conf = json.loads((pasta / "conferencia.json").read_text()) if (pasta / "conferencia.json").exists() else None
    names = {}
    for cid in ids:
        f = pasta / "pacotes" / f"{cid}.json"
        if f.exists():
            names[cid] = json.loads(f.read_text())["items"][0]["bundle"]["entities"]["Cliente"][0].get("nome_completo") or cid
    resolved = {}
    rf = pasta / "pendencias-resolvidas.jsonl"
    for line in (rf.read_text().splitlines() if rf.exists() else []):
        row = json.loads(line)
        resolved[(row["cliente_dash"], row["item"])] = row["resultado"]
    seen, pend = set(), defaultdict(list)
    pf = pasta / "pendencias.jsonl"
    for line in (pf.read_text().splitlines() if pf.exists() else []):
        row = json.loads(line)
        key = (row.get("cliente_dash"), row["item"], row["motivo"])
        if key in seen or (row.get("cliente_dash"), row["item"]) in resolved:
            continue
        seen.add(key)
        pend[row.get("cliente_dash")].append(row)
    for (cid, item), result in resolved.items():
        if result != "resolvido na repescagem":
            pend[cid].append({"cliente_dash": cid, "item": item, "motivo": result})
    new = [c for c in ids if state.get(c, {}).get("fase") == "concluido"]
    existing = [c for c in ids if state.get(c, {}).get("fase") == "existe"]
    waiting = [c for c in ids if state.get(c, {}).get("aguarda_decisao") and c not in new and c not in existing]
    missing = [c for c in ids if c not in names]
    kinds = Counter(tipo(r["motivo"], r["item"]) for rows in pend.values() for r in rows)

    with (pasta / "pendencias.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["cliente", "codigo_dash", "item", "tipo", "pendencia"])
        for cid in ids + [c for c in pend if c not in ids]:
            for r in pend.get(cid, []):
                w.writerow([names.get(cid, r.get("cliente", "")), cid or "", r["item"], tipo(r["motivo"], r["item"]), r["motivo"]])

    quando = config.agora()[:16].replace("T", " ")
    presentes = ""
    if conf:
        presentes = "".join(f'<div class="card"><div class="n">{c.get("presentes", 0)}</div>{ROTULOS[e]} presentes no AdvOS</div>'
                            for e, c in conf["por_entidade"].items() if e in ROTULOS)
        presentes += f'<p class="mut">Conferido pela chave de origem em {html.escape(conf["conferido_em"][:16].replace("T", " "))}.</p>'
    else:
        presentes = '<p class="mut">Sem conferência pela chave de origem ainda: rode conferir.py antes de declarar o lote concluído.</p>'
    cards = (f'<div class="grid"><div class="card"><div class="n">{len(ids)}</div>clientes do lote</div>'
             f'<div class="card"><div class="n" style="color:var(--ok)">{len(new)}</div>migrados</div>'
             f'<div class="card"><div class="n">{len(existing)}</div>já existiam no AdvOS</div>'
             f'<div class="card"><div class="n" style="color:var(--warn)">{len(waiting)}</div>esperando decisão</div>'
             f'<div class="card"><div class="n" style="color:var(--warn)">{len(missing)}</div>sem pacote do Dash</div>'
             f"{presentes}</div>")
    kind_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k, v in kinds.most_common())
    cabecalho = (f"<h1>Migração Dash → AdvOS — lote {html.escape(lote)}</h1><p class=\"mut\">Escritório "
                 f"{html.escape(cfg.get('dash_office_nome') or cfg.get('escritorio') or '')} · prefixo "
                 f"{html.escape(ficha['prefixo'])} · gerado em {quando}</p>")
    rows_html = []
    for cid in ids + [c for c in pend if c not in ids]:
        if not pend.get(cid):
            continue
        items = "".join(f"<li><b>{html.escape(str(r['item']))}</b> — {html.escape(r['motivo'])}</li>" for r in pend[cid])
        rows_html.append(f"<details><summary>{html.escape(names.get(cid, cid or 'sem cliente (catálogo)'))} "
                         f"<span>{len(pend[cid])}</span></summary><ul>{items}</ul></details>")
    (pasta / "relatorio.html").write_text(pagina(f"Migração — lote {lote}", cabecalho + cards
        + f"<h2>Pendências por tipo</h2><table>{kind_rows}</table><h2>Pendências por cliente</h2>{''.join(rows_html)}"),
        encoding="utf-8")
    (pasta / "resumo.html").write_text(pagina(f"Resumo — lote {lote}", cabecalho + cards
        + f"<h2>Pendências por tipo</h2><table>{kind_rows}</table>"
        + '<p class="mut">Sem nomes nem dados de clientes: pode ser compartilhado.</p>'), encoding="utf-8")
    print(f"lote {lote}: {len(new)} migrados, {len(existing)} já existiam, {len(waiting)} esperando decisão, "
          f"{len(missing)} sem pacote; pendências em {sum(1 for c in pend if pend[c])} cliente(s), {sum(kinds.values())} no total")
    print(f"  com nomes (só na pasta de trabalho): {pasta / 'relatorio.html'} e {pasta / 'pendencias.csv'}")
    print(f"  sem nomes (pode compartilhar): {pasta / 'resumo.html'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
