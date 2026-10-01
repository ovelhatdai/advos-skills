"""Lê no AdvOS, com a chave de leitura advos_sk_, os catálogos da organização (para o modo "casar") e os membros
(para membros.py). Só GET.

Rotas conferidas no OpenAPI do AdvOS (versão de 29/09/2026). Todas têm a guarda process:read, que a chave de
leitura tem (o dono da organização cria a chave em POST /api/v1/server-api-keys):
  GET /api/v1/case-statuses · /api/v1/legal-service-types · /api/v1/medical-conditions · /api/v1/deadline-types
  GET /api/v1/tasks/assignees   membros da organização: userId e nome, SEM e-mail
GET /api/v1/members (com e-mail) exige member:invite, que a chave de leitura não tem (403): ver o LEIA-ME.

A chave fica em segredos/advos-leitura.txt (python3 config.py guardar advos-leitura) e nunca é impressa.
Uso: python3 catalogos_advos.py   →  referencia/advos-catalogos.json e referencia/advos-membros.json
"""

import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402
import membros as membros_mod  # noqa: E402

BASE ="https://api.advos.ai/api/v1"
ROTAS = {"case_statuses": "/case-statuses", "legal_service_types": "/legal-service-types",
         "medical_conditions": "/medical-conditions", "deadline_types": "/deadline-types"}
CAMPOS = {"case_statuses": ("id", "name", "phase", "is_active", "next_status_name"),
          "legal_service_types": ("id", "name", "is_active"), "medical_conditions": ("id", "name", "is_active"),
          "deadline_types": ("id", "name", "slug", "is_active")}


def get(caminho, **params):
    """GET com até 5 tentativas em 429/5xx. Devolve o JSON."""
    url = BASE + caminho + ("?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}) if params else "")
    chave = config.ler_segredo("advos-leitura.txt")
    for tentativa in range(5):
        req = urllib.request.Request(url, headers={"authorization": f"Bearer {chave}", "accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and tentativa < 4:
                time.sleep(2 * (tentativa + 1)); continue
            raise SystemExit(f"🔴 GET {caminho} → HTTP {e.code}" + (" (a chave não tem essa permissão)" if e.code == 403 else "")) from None
        except (urllib.error.URLError, TimeoutError) as e:
            if tentativa < 4:
                time.sleep(2 * (tentativa + 1)); continue
            raise SystemExit(f"🔴 GET {caminho} → rede: {type(e).__name__}") from None


def todos(caminho):
    """Percorre a paginação do AdvOS (meta.hasMore + meta.nextCursor → starting_after). Os catálogos vêm inteiros."""
    itens, cursor = [], None
    while True:
        j = get(caminho, starting_after=cursor) if cursor else get(caminho)
        itens += j.get("data") or []
        meta = j.get("meta") or {}
        novo = meta.get("nextCursor")
        if not meta.get("hasMore") or not novo or novo == cursor:
            return itens
        cursor = novo


def main():
    cfg = config.carregar()
    saida = {"lido_em": config.agora(), "organizationId": None}
    orgs = set()
    for nome, rota in ROTAS.items():
        linhas = todos(rota)
        orgs |= {r.get("organization_id") for r in linhas if r.get("organization_id")}
        saida[nome] = [{c: r.get(c) for c in CAMPOS[nome]} for r in linhas]
    if len(orgs) > 1 or (cfg.get("advos_org_id") and orgs and orgs != {cfg["advos_org_id"]}):
        raise SystemExit("🔴 a chave de leitura é de outra organização (não confere com a credencial de importação); "
                         "nada gravado")
    saida["organizationId"] = next(iter(orgs), None)
    config.escrever_json(config.REFERENCIA / "advos-catalogos.json", saida)
    membros = get("/tasks/assignees").get("data") or []
    if membros_mod.ARQ_ADVOS.exists() and any(m["email"] for m in membros_mod.membros_advos()):
        print("  referencia/advos-membros.json já tem e-mails: mantido (a lista desta rota não tem e-mail)")
    else:
        config.escrever_json(membros_mod.ARQ_ADVOS,
                             [{"userId": m.get("id"), "email": None, "name": m.get("name")} for m in membros])
    print("🟢 catálogos do AdvOS: " + " | ".join(f"{n}: {len(saida[n])}" for n in ROTAS))
    print(f"   membros da organização: {len(membros)} (sem e-mail: membros.py sugere pelo nome, para a responsável conferir)")


if __name__ == "__main__":
    main()
