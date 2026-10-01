"""Fase 1 — prova de identidade, só leitura.

Pergunta ao Dash quem é o escritório do token (migration_source_whoami) e ao AdvOS qual é a organização da credencial
de importação (imports_capabilities). Grava os dois no config.json e referencia/identidade.json e mostra o resumo do
portão 1. Recusa se o escritório ou a organização mudarem em relação ao que já estava combinado. Nenhum segredo na tela.
Uso: python3 identidade.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import advos_imports  # noqa: E402
import config  # noqa: E402
import dash_mcp  # noqa: E402
from baixar_pacotes import call as dash  # noqa: E402  (retentativas e renovação do token)

SECOES = {"crm", "legal", "documents"}


def main():
    cfg = config.carregar()
    problemas = []

    w = dash("migration_source_whoami", {})
    if not isinstance(w, dict) or w.get("status") != "ok":
        codigo = ((w.get("error") or {}).get("code") if isinstance(w, dict) else None) or "resposta inesperada"
        if codigo == "TENANT_FORBIDDEN":
            raise SystemExit("🔴 Dash: TENANT_FORBIDDEN — o escritório ainda não foi liberado no MCP do Dash. "
                             "Chamar a equipe Advogando.")
        raise SystemExit(f"🔴 Dash: whoami falhou ({codigo})")
    office = w.get("sourceOrganizationId")
    nome = (w.get("sourceOrganization") or {}).get("name")
    if office != dash_mcp.claims().get("escritorio_id"):
        problemas.append("o whoami devolveu um escritório diferente do token")
    if cfg.get("dash_office_id") and office != cfg["dash_office_id"]:
        problemas.append(f"o escritório do Dash mudou ({cfg['dash_office_id']} → {office}): um escritório por pasta")
    contratos = {c.get("hash"): c.get("version") for c in w.get("supportedContracts") or []}
    if cfg["contrato_hash"] not in contratos:
        problemas.append("o MCP do Dash não anuncia o contrato configurado (config.json, contrato_hash): chamar a "
                         "equipe Advogando")

    cap = advos_imports.call("imports_capabilities", {})
    data = cap.get("data") if isinstance(cap, dict) else None
    if not isinstance(data, dict) or cap.get("isError") or not data.get("organizationId"):
        raise SystemExit(f"🔴 AdvOS: a credencial de importação foi recusada "
                         f"({cap.get('httpError') if isinstance(cap, dict) else '?'}): pedir outra à equipe Advogando")
    org = data["organizationId"]
    if cfg.get("advos_org_id") and org != cfg["advos_org_id"]:
        problemas.append(f"a organização do AdvOS mudou ({cfg['advos_org_id']} → {org}): credencial de outra organização")
    falta = SECOES - set(data.get("sections") or [])
    if falta:
        problemas.append(f"a credencial do AdvOS não tem as seções {sorted(falta)}")

    if problemas:
        for p in problemas:
            print(f"🔴 {p}")
        raise SystemExit(1)
    cfg.update(dash_office_id=office, dash_office_nome=nome, advos_org_id=org)
    config.salvar(cfg)
    limites = data.get("limits") or {}
    config.escrever_json(config.REFERENCIA / "identidade.json", {
        "conferido_em": config.agora(),
        "dash": {"escritorio_id": office, "escritorio_nome": nome, "usuario_id": (w.get("user") or {}).get("id"),
                 "escopos": w.get("scopes"), "contrato": contratos.get(cfg["contrato_hash"]),
                 "servidor": w.get("serverVersion")},
        "advos": {"organizationId": org, "secoes": data.get("sections"), "limites": limites,
                  "entidades": data.get("executableEntities")},
    })
    print(f"Dash: escritório {nome} ({office}) → AdvOS: organização {org}")
    print(f"  Dash: perfil de leitura conferido; contrato {contratos.get(cfg['contrato_hash'])} anunciado")
    print(f"  AdvOS: seções {', '.join(data.get('sections') or [])}; 1 job por vez: {limites.get('runningJobs')}; "
          f"pedidos/min: {limites.get('requestsPerMinute')}; registros por envio: {limites.get('inlineRows')}; "
          f"documento até {round((limites.get('clientDocumentBytes') or 0) / 1048576)} MB")
    print("Portão 1: a responsável confirma o escritório; o id da organização tem de ser o que a equipe Advogando "
          "informou ao emitir a credencial.")


if __name__ == "__main__":
    main()
