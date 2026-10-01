"""Fase 3 — equipe: liga cada usuário do Dash a um membro do AdvOS pelo e-mail.

O AdvOS liga a pessoa pelo userId do membro, nunca pelo id do Dash nem pelo nome. Entradas:
  referencia/bootstrap.json      usuários do Dash (vem com o 1º pacote baixado)
  referencia/advos-membros.json  membros do AdvOS com userId. Formatos aceitos: lista [{userId, email, name}];
                                 resposta de GET /api/v1/members ({"data": [{userId, user: {email, name}}]});
                                 resposta de GET /api/v1/tasks/assignees ({"data": [{id, name}]}, sem e-mail).
                                 De onde vem: LEIA-ME, "Membros do AdvOS".
Saídas: referencia/membros.json ({id do usuário no Dash: {advos: userId, nome, via}}) e
referencia/membros-sem-par.json (quem ficou sem par, com sugestão pelo nome quando houver). Na tela, só contagens.
Entradas feitas à mão em membros.json com "via": "manual" são preservadas.

Uso: python3 membros.py [--aceitar-nomes]
  --aceitar-nomes  liga também quem só casou pelo nome (lista do AdvOS sem e-mail), DEPOIS de a responsável
                   conferir as sugestões em membros-sem-par.json (portão 3)
"""

import json
import pathlib
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402

ARQ_ADVOS = config.REFERENCIA / "advos-membros.json"
SAIDA = config.REFERENCIA / "membros.json"
SEM_PAR = config.REFERENCIA / "membros-sem-par.json"


def norm_nome(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").split())


def membros_advos():
    """Membros do AdvOS em qualquer um dos formatos aceitos → [{userId, email, nome}]."""
    if not ARQ_ADVOS.exists():
        raise SystemExit(f"falta {ARQ_ADVOS}: veja o LEIA-ME, 'Membros do AdvOS'")
    bruto = json.loads(ARQ_ADVOS.read_text(encoding="utf-8"))
    itens = bruto.get("data", []) if isinstance(bruto, dict) else bruto
    saida = []
    for m in itens:
        user = m.get("user") or {}
        uid = m.get("userId") or m.get("user_id") or user.get("id") or m.get("id")
        email = (m.get("email") or user.get("email") or "").strip().lower() or None
        if uid:
            saida.append({"userId": uid, "email": email, "nome": m.get("name") or m.get("nome") or user.get("name")})
    return saida


def main(aceitar_nomes=False):
    config.carregar()
    boot = config.REFERENCIA / "bootstrap.json"
    if not boot.exists():
        raise SystemExit("falta referencia/bootstrap.json: baixe ao menos um pacote (baixar_pacotes.py)")
    usuarios = json.loads(boot.read_text(encoding="utf-8"))["bootstrap"]["entities"].get("User", [])
    advos = membros_advos()
    por_email = {m["email"]: m for m in advos if m["email"]}
    por_nome = {}
    for m in advos:
        por_nome.setdefault(norm_nome(m["nome"]), []).append(m)
    anterior = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {}
    ligados = {k: v for k, v in anterior.items() if v.get("via") == "manual"}
    sem_par, cont = [], {"email": 0, "nome": 0, "manual": len(ligados)}
    for u in usuarios:
        if u["id"] in ligados:
            continue
        email = (u.get("email") or "").strip().lower()
        nome = u.get("full_name") or u.get("nome")
        if email and email in por_email:
            ligados[u["id"]] = {"advos": por_email[email]["userId"], "nome": nome, "via": "email"}
            cont["email"] += 1
            continue
        candidatos = por_nome.get(norm_nome(nome)) if nome else None
        sugestao = candidatos[0]["userId"] if candidatos and len(candidatos) == 1 else None
        if sugestao and aceitar_nomes:
            ligados[u["id"]] = {"advos": sugestao, "nome": nome, "via": "nome (conferido pela responsável)"}
            cont["nome"] += 1
            continue
        sem_par.append({"dash_user_id": u["id"], "nome": nome, "email": email or None,
                        "ativo_no_dash": not (u.get("disabled") or u.get("ativo") is False or u.get("desligado_em")),
                        "sugestao_por_nome": sugestao})
    config.escrever_json(SAIDA, ligados)
    config.escrever_json(SEM_PAR, sem_par)
    sugeridos = sum(1 for s in sem_par if s["sugestao_por_nome"])
    print(f"usuários do Dash: {len(usuarios)} | membros do AdvOS: {len(advos)} (com e-mail: {len(por_email)})")
    print(f"  ligados: {len(ligados)} (e-mail {cont['email']}, nome conferido {cont['nome']}, manual {cont['manual']})")
    print(f"  sem par: {len(sem_par)} (ativos no Dash: {sum(1 for s in sem_par if s['ativo_no_dash'])}; "
          f"com sugestão pelo nome: {sugeridos}) → lista em {SEM_PAR}")
    if sugeridos and not aceitar_nomes:
        print("  sugestões pelo nome só valem depois de a responsável conferir: então  python3 membros.py --aceitar-nomes")


if __name__ == "__main__":
    main("--aceitar-nomes" in sys.argv[1:])
