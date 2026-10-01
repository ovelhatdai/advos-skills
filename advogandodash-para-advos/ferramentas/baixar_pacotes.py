"""Baixa o pacote completo (um cliente por pacote) de cada cliente do lote no Dash.

Uso: python3 baixar_pacotes.py <lote> [corte_iso_utc] [paralelo]
Cada cliente vira lotes/<lote>/pacotes/<id>.json com snapshot, sequenceId, batch do cliente e descritores.
Retoma de onde parou (pula quem já tem arquivo). Renova o token do Dash quando expira (com trava).
O corte fica na ficha do lote no 1º download (padrão: 2 minutos atrás). O lote de bootstrap do escritório (etapas,
tipos de serviço, condições, tipos de prazo, usuários) fica guardado uma vez em referencia/bootstrap.json.
Paralelo padrão 3: o MCP monta poucos pacotes por escritório de cada vez; mais frentes só aumentam a fila.
"""

import json
import os
import pathlib
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import conectar_dash  # noqa: E402
import dash_mcp  # noqa: E402

CFG = config.carregar()
ORG = CFG["dash_office_id"]
NS = CFG["namespace"]
# A chave de idempotência leva a versão do contrato: a impressão digital do pedido inclui o hash, então reusar a chave
# de outra versão daria IDEMPOTENCY_CONFLICT.
CONTRATO = CFG["contrato_hash"]
TAG = {config.CONTRATO_V6: "v6"}.get(CONTRATO, "c" + CONTRATO[:6])
BOOT = config.REFERENCIA / "bootstrap.json"
LOCK = threading.Lock()
BOOT_LOCK = threading.Lock()


def renew():
    """Renova com trava de arquivo; se outro processo já renovou, só reaproveita o token novo."""
    before = dash_mcp.token()
    with LOCK:
        conectar_dash.renovar(before)
        dash_mcp._SESSION.clear()


BUDGET = int(os.environ.get("BUDGET", "900"))  # segundos por cliente; depois disso desiste e deixa para a repassada
DEADLINE = threading.local()


def call(tool, args, tries=60):
    attempt, r = 0, None
    while attempt < tries:
        if getattr(DEADLINE, "at", None) and time.time() > DEADLINE.at:
            return {"status": "error", "error": {"code": "CLIENT_BUDGET_EXCEEDED", "retryable": False}}
        r = dash_mcp.call(tool, args)
        if isinstance(r, dict) and r.get("httpError") in (401, 403):
            attempt += 1
            try:
                renew()
            except SystemExit as exc:  # refresh recusado: login do Dash vencido, todo o lote para
                return {"status": "error", "error": {"code": "DASH_LOGIN_EXPIRED", "message": str(exc)[:200]}}
            continue
        if isinstance(r, dict) and r.get("httpError"):
            attempt += 1; dash_mcp._SESSION.clear(); time.sleep(min(60, 5 * attempt)); continue
        err = (r.get("error") or {}) if isinstance(r, dict) and r.get("status") == "error" else None
        if err and err.get("code") == "SNAPSHOT_PREPARING":
            time.sleep(3); continue  # a montagem só avança repetindo; quem limita é o prazo por cliente
        if err and (err.get("retryable") or err.get("code") in ("RATE_LIMITED", "BASE44_TIMEOUT", "BASE44_UNAVAILABLE")):
            attempt += 1; time.sleep(min(60, 10 * attempt)); continue
        return r
    return r


def guardar_bootstrap(batch):
    """Primeiro bootstrap do escritório: catálogos do Dash que o converter e o membros.py leem. Guardado uma vez."""
    with BOOT_LOCK:
        if BOOT.exists():
            return
        origem = (batch.get("bootstrap") or {}).get("sourceOrganizationId")
        if origem and origem != ORG:
            raise SystemExit(f"🔴 bootstrap de outro escritório ({origem}); nada gravado")
        config.escrever_json(BOOT, batch, indent=None)


def fetch(cid, out, until, prefixo):
    target = out / f"{cid}.json"
    if target.exists():
        return cid, "já baixado"
    DEADLINE.at = time.time() + BUDGET
    sel = {"version": "migration-selection/v2", "field": "Cliente.created_date", "timezone": "America/Sao_Paulo",
           "createdFrom": "2000-01-01T00:00:00Z", "createdUntil": until,
           "order": ["created_at_asc", "source_id_asc"], "maximumClients": 1, "pilotSourceClientIds": [cid]}
    chave = f"{NS}-{prefixo}-{cid}-{TAG}"
    snap = call("migration_source_create_snapshot", {"sourceOrganizationId": ORG, "contractHash": CONTRATO,
                "idempotencyKey": f"{chave}-1", "until": until, "selection": sel})
    if isinstance(snap, dict) and (snap.get("error") or {}).get("code") == "SOURCE_DIVERGED":
        # cliente alterado no Dash depois do corte: corte novo (2 min atrás) e chave nova. Se repetir, não é mudança:
        # há documento/prazo ligado a processo de outro cliente (armadilha 3 da leitura).
        fresh = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        snap = call("migration_source_create_snapshot", {"sourceOrganizationId": ORG, "contractHash": CONTRATO,
                    "idempotencyKey": f"{chave}-2-{fresh[:16]}", "until": fresh, "selection": sel})
    if not isinstance(snap, dict) or snap.get("status") != "ok" or "snapshot" not in snap:
        return cid, f"snapshot falhou: {json.dumps(snap, ensure_ascii=False)[:300]}"
    s = snap["snapshot"]
    seq = next(p["sequenceId"] for p in s["phases"] if p["phase"] == "pilot")
    cursor, client_batch = None, None
    for _ in range(5):
        b = call("migration_source_next_batch", {"sourceSnapshotId": s["sourceSnapshotId"], "cursor": cursor, "limit": 1, "sequenceId": seq})
        if not isinstance(b, dict) or b.get("status") != "ok":
            return cid, f"batch falhou: {json.dumps(b, ensure_ascii=False)[:300]}"
        if b.get("kind") == "bootstrap" and not BOOT.exists():
            guardar_bootstrap(b)
        if b.get("kind") == "clients":
            client_batch = b
        cursor = b.get("nextCursor")
        if not cursor:
            break
    if not client_batch:
        return cid, "sem batch de cliente"
    item = (client_batch.get("items") or [{}])[0]
    got = item.get("sourceClientId")
    rows = ((item.get("bundle") or {}).get("entities") or {}).get("Cliente") or [{}]
    if got != cid or rows[0].get("id") != cid:
        return cid, f"pacote de outro cliente ({got}); descartado"
    config.escrever_json(target, {"sourceSnapshotId": s["sourceSnapshotId"], "sequenceId": seq,
                                  "sourceBatchId": client_batch["sourceBatchId"], "items": client_batch["items"]},
                         indent=None)
    return cid, "ok"


def main(lote, corte=None, parallel="3"):
    # Mensagem de erro com caractere inválido (surrogate) derrubava o laço de registro sem parar os workers: o log
    # congelou às 03:19 de 24/09 enquanto os pacotes seguiam chegando. Escapa em vez de falhar.
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
    pasta, ficha = config.lote(lote)
    if not ORG:
        raise SystemExit("escritório do Dash ainda não definido: rode conectar_dash.py e identidade.py")
    if dash_mcp.claims().get("escritorio_id") != ORG:  # regra 5: o token é do escritório combinado
        raise SystemExit("🔴 o token do Dash é de outro escritório; nada baixado")
    if ficha.get("corte") and corte and corte != ficha["corte"]:
        raise SystemExit(f"o lote já tem corte {ficha['corte']}; para outro corte, crie outro lote")
    if not ficha.get("corte"):
        ficha["corte"] = corte or (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        config.salvar_lote(pasta, ficha)
    if len(f"{NS}-{ficha['prefixo']}-{'0' * 24}-{TAG}-2-{'0' * 16}") > 128:
        raise SystemExit("chave de idempotência passaria de 128 caracteres: use um nome de lote mais curto")
    if int(parallel) > 3:
        print("aviso: mais de 3 em paralelo só aumenta a fila do MCP (armadilha 1 da leitura)", flush=True)
    ids = json.loads((pasta / "alvos.json").read_text())
    out = pasta / "pacotes"
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    todo = [c for c in ids if not (out / f"{c}.json").exists()]
    print(f"lote {lote} (corte {ficha['corte']}): faltam {len(todo)} de {len(ids)}", flush=True)
    with ThreadPoolExecutor(int(parallel)) as pool:
        futures = [pool.submit(fetch, c, out, ficha["corte"], ficha["prefixo"]) for c in todo]
        for n, fut in enumerate(as_completed(futures), 1):
            try:
                cid, status = fut.result()
            except (Exception, SystemExit) as exc:  # noqa: BLE001 — SystemExit: token lido durante a renovação
                cid, status = "?", f"erro: {type(exc).__name__}: {str(exc)[:200]}"
            print(f"{n}/{len(todo)} {cid} {status} ({int(time.time()-started)}s)", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(*sys.argv[1:4])
