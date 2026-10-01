"""Decisor de correspondências Dash → AdvOS, sem modelo externo.

Cascata, do barato para o caro:
  0. pergunta já decidida neste escritório (decisoes/decisoes.json, pela chave da pergunta)
  1. nome idêntico na lista do AdvOS                → resolve sozinho
  2. legado opcional (decisoes/legado.json, mesma chave): precedentes próprios importados; só quem já migrou com outra ferramenta tem
  3. semente (../referencias/semente-tipos-documento.json): só tipo de documento e só confiança "alta"
  4. mesmo rótulo com outra grafia, mesmas palavras ou mesma família (testemunha, extrato do benefício), a partir
     das decisões deste escritório: só quando todas concordam
  5. o que sobrar → fila do Claude (decisoes/fila.json); rótulo que a semente marca "abrir o documento" vai com a
     nota da semente como contexto (abrir um documento com espiar_documento.py antes de decidir)
Só rótulos; nunca dado de cliente. Quem decide a fila é o Claude, na sessão, e a responsável aprova (portão 3).

Uso:
  python3 decisor.py fila                       mostra a fila (rótulo, opções e contexto)
  python3 decisor.py responder <chave> <valor>  grava a decisão do Claude e tira o item da fila
  python3 decisor.py tabela                     decisoes/tabela.csv com todas as correspondências, para o portão 3
"""

import contextlib
import csv
import hashlib
import json
import pathlib
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402

CACHE = config.DECISOES / "decisoes.json"     # decisões deste escritório (cascata + Claude)
FILA = config.DECISOES / "fila.json"          # o que só o Claude resolve
LEGADO = config.DECISOES / "legado.json"      # opcional: precedentes próprios de outra ferramenta (ex.: decisões de uma leva anterior)
TRAVA = config.DECISOES / ".decisor.lock"     # importador e Claude gravam os mesmos arquivos
SEMENTE = HERE.parent / "referencias" / "semente-tipos-documento.json"
LIMIAR = 0.7


def chave(q):
    return hashlib.sha256(json.dumps(
        [q["kind"], q["source"], q.get("context"), q["options"]],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").split())


_VAZIAS = {"de", "do", "da", "dos", "das", "e", "a", "o", "as", "os", "ao", "aos", "com", "para", "pra", "em", "no", "na",
           "nos", "nas"}


def palavras(s):
    """Rótulo reduzido às palavras que importam: sem acento, caixa, pontuação, nome mascarado e palavras vazias
    ("DECLARAÇÃO HIPOSSUFICIÊNCIA" = "Declaração de hipossuficiência"; "MANIFESTAÇÃO AO LAUDO - [nome]" = "Manifestação ao laudo")."""
    t = norm((s or "").replace("[nome]", " "))
    return " ".join(sorted({w for w in re.findall(r"[a-z0-9]+", t) if w not in _VAZIAS}))


def _ler(p):
    return json.loads(p.read_text(encoding="utf-8") or "{}") if p.exists() else {}


@contextlib.contextmanager
def _trava():
    """Ler e gravar só com a trava: sem ela, o decide() do importador regravava a fila lida antes e apagava a
    resposta que o Claude tinha dado no meio (23/09/2026)."""
    with config.trava(TRAVA):
        yield


def _gravar(cache, fila):
    config.escrever_json(CACHE, cache)
    config.escrever_json(FILA, fila)


def _indice(cache, legado):
    """(tipo, contexto, rótulo normalizado) → decisão já tomada. Só decisões aplicadas; nunca pendentes."""
    ind = {}
    for d in legado.values():
        if d.get("source") and d.get("value") is not None and (d.get("confidence") or 0) >= LIMIAR:
            ind.setdefault((d["kind"], d.get("context"), norm(d["source"])), d["value"])
    for d in cache.values():  # as deste escritório (incluindo as do Claude) prevalecem sobre o legado
        if d.get("source") and d.get("value") is not None:
            ind[(d["kind"], d.get("context"), norm(d["source"]))] = d["value"]
    return ind


def _indice_palavras(cache, legado):
    """(tipo, contexto, palavras do rótulo) → {decisões}. Só vale quando todas as grafias já decididas concordam."""
    ind = {}
    for d in list(legado.values()) + list(cache.values()):
        ok = d.get("value") is not None and (d in cache.values() or (d.get("confidence") or 0) >= LIMIAR)
        if d.get("source") and ok and palavras(d["source"]):
            ind.setdefault((d["kind"], d.get("context"), palavras(d["source"])), set()).add(d["value"])
    return ind


# Rótulo de testemunha leva o nome dela ("TESTEMUNHA 2 FULANA") e o extrato do benefício leva o NB: nenhum se repete,
# então cada um caía na fila. Herda a decisão da família só se todas as decisões dela concordam (24/09/2026).
FAMILIAS = ("testemunha", "video testemunha", "video testemunho", "extrato de informacoes do beneficio")


def familia(s):
    t = norm(s)
    return next((f for f in FAMILIAS if t == f or t.startswith(f + " ")), None)


def _indice_familia(cache, legado):
    """(tipo, contexto, família do rótulo) → {decisões}."""
    ind = {}
    for d in list(legado.values()) + list(cache.values()):
        ok = d.get("value") is not None and (d in cache.values() or (d.get("confidence") or 0) >= LIMIAR)
        if d.get("source") and ok and (f := familia(d["source"])):
            ind.setdefault((d["kind"], d.get("context"), f), set()).add(d["value"])
    return ind


_SEM = None


def _semente():
    """Semente de rótulos de documento (precedente de outra migração): por rótulo normalizado e por palavras."""
    global _SEM
    if _SEM is None:
        dados = json.loads(SEMENTE.read_text(encoding="utf-8")) if SEMENTE.exists() else {"rotulos": []}
        _SEM = {"rotulo": {}, "palavras": {}}
        for r in dados["rotulos"]:
            _SEM["rotulo"].setdefault(norm(r["rotulo"]), r)
            _SEM["palavras"].setdefault(palavras(r["rotulo"]), []).append(r)
    return _SEM


def semente_registro(source):
    """Registro da semente para o rótulo: o idêntico ou, pelas palavras, só se todos os registros concordam."""
    sem = _semente()
    r = sem["rotulo"].get(norm(source))
    if r:
        return r
    regs = sem["palavras"].get(palavras(source)) or []
    if regs and len({(x["tipo"], x["confianca"]) for x in regs}) == 1:
        return regs[0]
    return None


def _enfileirar(fila, k, q):
    item = {"kind": q["kind"], "source": q["source"], "context": q.get("context"), "options": q["options"],
            "enfileiradoEm": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    r = semente_registro(q["source"]) if q["kind"] == "tipo_documento" else None
    if r:
        item["semente"] = {"tipo": r["tipo"], "confianca": r["confianca"], **({"nota": r["nota"]} if r.get("nota") else {})}
    fila[k] = item


def decide(questions):
    with _trava():
        cache, fila, legado = _ler(CACHE), _ler(FILA), _ler(LEGADO)
        indice = _indice(cache, legado)
        indice_pal = _indice_palavras(cache, legado)
        indice_fam = _indice_familia(cache, legado)
        out, mudou = [], False
        for q in questions:
            k = chave(q)
            validos = {o["value"] for o in q["options"]}
            if k not in cache:
                ident = {"kind": q["kind"], "source": q["source"], "context": q.get("context")}
                exato = {norm(o["label"]): o["value"] for o in q["options"]}.get(norm(q["source"]))
                mesmo = indice.get((q["kind"], q.get("context"), norm(q["source"])))
                sem = semente_registro(q["source"]) if q["kind"] == "tipo_documento" else None
                if exato is not None:
                    cache[k] = {**ident, "value": exato, "confidence": 1.0, "origem": "exato"}
                elif legado.get(k, {}).get("value") is not None and (legado[k].get("confidence") or 0) >= LIMIAR:
                    cache[k] = {**ident, "value": legado[k]["value"], "confidence": legado[k]["confidence"], "origem": "legado"}
                elif sem and sem["confianca"] == "alta" and sem["tipo"] in validos:
                    # precedente da semente: só o que o rótulo diz sozinho ("alta"); genérico vai para a fila
                    cache[k] = {**ident, "value": sem["tipo"], "confidence": 1.0, "origem": "semente"}
                elif mesmo in validos:
                    # mesmo rótulo com outra grafia ("Cnis" × "CNIS"): reaproveita a decisão já tomada
                    cache[k] = {**ident, "value": mesmo, "confidence": 1.0, "origem": "mesmo-rotulo"}
                elif len(pv := indice_pal.get((q["kind"], q.get("context"), palavras(q["source"])), set())) == 1 and next(iter(pv)) in validos:
                    # mesmas palavras em outra ordem, sem "de"/"ao" ou com nome mascarado: reaproveita (só se as grafias concordam)
                    cache[k] = {**ident, "value": next(iter(pv)), "confidence": 1.0, "origem": "mesmo-rotulo-palavras"}
                elif ((f := familia(q["source"])) and len(fv := indice_fam.get((q["kind"], q.get("context"), f), set())) == 1
                      and next(iter(fv)) in validos):
                    # testemunha com o nome dela: herda a decisão da família (só se todas concordam)
                    cache[k] = {**ident, "value": next(iter(fv)), "confidence": 1.0, "origem": "familia-rotulo"}
                else:
                    cache[k] = {**ident, "value": None, "confidence": 0.0, "origem": "claude-pendente"}
                    _enfileirar(fila, k, q)
                mudou = True
            elif cache[k]["value"] is None and k not in fila:
                # pendente sem item na fila (fila apagada ou perdida): repõe, senão o cliente espera para sempre
                _enfileirar(fila, k, q)
                mudou = True
            out.append(k)
        if mudou:
            _gravar(cache, fila)
    return [{**cache[k], "applied": cache[k]["value"], "chave": k,
             "status": "ok" if cache[k]["value"] is not None else "claude"} for k in out]


def responder(chave_, value):
    """O Claude grava a decisão dele e tira o item da fila."""
    with _trava():
        cache, fila = _ler(CACHE), _ler(FILA)
        item = fila.pop(chave_, {}) or {}
        validos = {o["value"] for o in item.get("options") or []}
        if validos and value not in validos:
            raise SystemExit(f"valor '{value}' não é uma das opções: {sorted(validos)}")
        cache[chave_] = {"kind": item.get("kind", cache.get(chave_, {}).get("kind")),
                         "source": item.get("source", cache.get(chave_, {}).get("source")),
                         "context": item.get("context", cache.get(chave_, {}).get("context")),
                         "value": value, "confidence": 1.0, "origem": "claude"}
        _gravar(cache, fila)


def tabela():
    """Correspondências para a responsável aprovar (portão 3). O CSV tem os rótulos digitados pela equipe: fica na
    pasta de trabalho."""
    cache = _ler(CACHE)
    destino = config.DECISOES / "tabela.csv"
    with destino.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tipo", "rotulo_no_dash", "contexto", "valor_no_advos", "origem", "chave"])
        for k, d in sorted(cache.items(), key=lambda kv: (kv[1].get("kind") or "", norm(kv[1].get("source")))):
            w.writerow([d.get("kind"), d.get("source"), d.get("context") or "", d.get("value") or "(na fila)", d.get("origem"), k])
    print(f"{len(cache)} correspondência(s) em {destino}")
    print("  por origem:", dict(Counter(d.get("origem") for d in cache.values()).most_common()))


if __name__ == "__main__":
    config.garantir_fora_da_nuvem()
    if sys.argv[1:2] == ["fila"]:
        print(json.dumps(_ler(FILA), ensure_ascii=False, indent=1))
    elif sys.argv[1:2] == ["responder"] and len(sys.argv) == 4:
        responder(sys.argv[2], sys.argv[3])
        print(f"🟢 decisão gravada; itens na fila: {len(_ler(FILA))}")
    elif sys.argv[1:2] == ["tabela"]:
        tabela()
    elif len(sys.argv) == 2 and pathlib.Path(sys.argv[1]).exists():
        print(json.dumps(decide(json.loads(pathlib.Path(sys.argv[1]).read_text())), ensure_ascii=False, indent=1))
    else:
        raise SystemExit(__doc__)
