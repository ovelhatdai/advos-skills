"""Fase 2 — inventário dos clientes do escritório no Dash, só leitura.

listar_contratos pagina certo; listar_clientes e listar_processos repetem e pulam registros (ordenam por um campo que
não existe). A lista é a união dos três, sem repetir. Quem só aparece por contrato ou processo tem o status buscado
na ficha (buscar_cliente). Data de criação = a do próprio id (ObjectId), no horário de São Paulo.
Saída: referencia/clientes.json (id, criado_em, status, fontes). Na tela, só contagens: conferir o total com o Dash.

Uso:
  python3 inventario.py
  python3 inventario.py alvos <lote> [--status s1,s2] [--desde AAAA-MM-DD] [--ate AAAA-MM-DD] [--ids id1,id2] [--max N]
      cria o lote (pasta + prefixo próprio) e grava lotes/<lote>/alvos.json, do mais antigo para o mais novo
"""

import argparse
import json
import pathlib
import re
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402
from baixar_pacotes import call as dash  # noqa: E402  (retentativas e renovação do token)

ARQ = config.REFERENCIA / "clientes.json"
PAGINA = 100


def criado_em(cid):
    """O id do Dash é um ObjectId: os 8 primeiros dígitos hexadecimais são o segundo da criação (UTC)."""
    if re.fullmatch(r"[0-9a-f]{24}", cid or ""):
        return datetime.fromtimestamp(int(cid[:8], 16), tz=config.SP).date().isoformat()
    return None


def _linhas(ferramenta, resposta):
    if isinstance(resposta, list):
        return resposta
    if isinstance(resposta, dict) and not resposta.get("httpError") and resposta.get("status") != "error":
        for campo in ("clientes", "processos", "items", "data"):
            if isinstance(resposta.get(campo), list):
                return resposta[campo]
    raise SystemExit(f"🔴 {ferramenta}: resposta inesperada do Dash ({str(resposta)[:160]})")


def paginar(ferramenta, extra=None):
    """Percorre por offset até a última página (menor que a página cheia)."""
    offset = 0
    while True:
        resposta = dash(ferramenta, {**(extra or {}), "limit": PAGINA, "offset": offset})
        linhas = _linhas(ferramenta, resposta)
        yield from linhas
        if len(linhas) < PAGINA or (isinstance(resposta, dict) and resposta.get("has_more") is False):
            return
        offset += PAGINA


def inventario():
    config.carregar()
    vistos = {}

    def anota(cid, fonte, status=None):
        if not cid:
            return
        reg = vistos.setdefault(cid, {"id": cid, "criado_em": criado_em(cid), "status": None, "fontes": []})
        if fonte not in reg["fontes"]:
            reg["fontes"].append(fonte)
        if status and not reg["status"]:
            reg["status"] = status

    for c in paginar("listar_contratos"):
        anota(c.get("cliente_id"), "contratos")
    for c in paginar("listar_clientes"):
        anota(c.get("id"), "clientes", c.get("status"))
    for p in paginar("listar_processos"):
        anota(p.get("cliente_id"), "processos")
    sem_status = [cid for cid, r in vistos.items() if "clientes" not in r["fontes"]]
    for cid in sem_status:
        ficha = dash("buscar_cliente", {"cliente_id": cid})
        if isinstance(ficha, dict) and ficha.get("id") == cid:
            vistos[cid]["status"] = ficha.get("status")
            vistos[cid]["fontes"].append("ficha")
        elif ficha is None or (isinstance(ficha, dict) and not ficha.get("httpError") and not ficha.get("id")):
            vistos[cid]["status"] = "nao_encontrado"  # contrato ou processo aponta para cliente que não existe mais
    lista = sorted(vistos.values(), key=lambda r: (r["criado_em"] or "", r["id"]))
    config.escrever_json(ARQ, lista)

    fontes = Counter("+".join(sorted(r["fontes"])) for r in lista)
    print(f"clientes do escritório no Dash (união sem repetir): {len(lista)}  → confira com o total na tela do Dash")
    print("  por fonte:", dict(fontes.most_common()))
    print("  por status:", dict(Counter(r["status"] or "sem status" for r in lista).most_common()))
    print("  por ano de cadastro:", dict(sorted(Counter((r["criado_em"] or "????")[:4] for r in lista).items())))
    print(f"  gravado em {ARQ}")


def alvos(args):
    if not ARQ.exists():
        raise SystemExit("rode antes  python3 inventario.py")
    clientes = json.loads(ARQ.read_text())
    if args.ids:
        conhecidos = {c["id"] for c in clientes}
        escolhidos = [i.strip() for i in args.ids.split(",") if i.strip()]
        fora = [i for i in escolhidos if i not in conhecidos]
        if fora:
            raise SystemExit(f"{len(fora)} id(s) fora do inventário; confira os ids")
    else:
        status = {s.strip() for s in args.status.split(",")} if args.status else None
        escolhidos = [c["id"] for c in clientes
                      if c.get("status") != "nao_encontrado"
                      and (status is None or c.get("status") in status)
                      and (not args.desde or (c.get("criado_em") or "") >= args.desde)
                      and (not args.ate or (c.get("criado_em") or "9999") <= args.ate)]
    if args.max:
        escolhidos = escolhidos[:args.max]
    if not escolhidos:
        raise SystemExit("nenhum cliente com esse recorte")
    pasta, ficha = config.lote(args.lote, criar=True)
    destino = pasta / "alvos.json"
    if destino.exists() and json.loads(destino.read_text()) != escolhidos:
        raise SystemExit(f"o lote {args.lote} já tem outra lista de alvos; para outro recorte, crie outro lote")
    config.escrever_json(destino, escolhidos)
    print(f"🟢 lote {args.lote}: {len(escolhidos)} cliente(s) | prefixo {ficha['prefixo']} | {destino}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "alvos":
        ap = argparse.ArgumentParser(prog="inventario.py alvos")
        ap.add_argument("lote")
        ap.add_argument("--status")
        ap.add_argument("--desde")
        ap.add_argument("--ate")
        ap.add_argument("--ids")
        ap.add_argument("--max", type=int)
        alvos(ap.parse_args(sys.argv[2:]))
    elif len(sys.argv) == 1:
        inventario()
    else:
        raise SystemExit(__doc__)
