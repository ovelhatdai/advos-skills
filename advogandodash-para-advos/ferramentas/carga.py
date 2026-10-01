"""Grava no AdvOS, em ondas, os clientes do lote cujos pacotes do Dash já foram baixados.

Por onda (até 20 clientes e até 1.000 registros por envio, o limite do AdvOS): cadastro (crm) → processos,
andamentos, prazos e tarefas (legal) → documentos.
Recusa de campo: tira o campo, registra pendência e refaz a prévia. Cliente que já existe no AdvOS (CPF) é marcado e
não é duplicado. Cliente com rótulo esperando decisão fica fora da onda. Estado em lotes/<lote>/estado.json;
pendências em lotes/<lote>/pendencias.jsonl.

Sem --gravar é simulação: nenhuma rede, só converte e conta o que iria. --gravar só depois do OK da responsável
PARA ESTE LOTE (regra 4 da skill): confere o escritório do token e a organização da credencial, pede a prévia ao
AdvOS e confirma o que vier sem recusa. Uma onda por vez: o AdvOS roda um job por organização. Rodar de novo
continua de onde parou; cada onda usa um número novo (chave repetida faz o AdvOS devolver o job antigo).
Uso: python3 carga.py <lote> [--gravar] [--max 20]
"""

import argparse
import copy
import hashlib
import http.client
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import dash_mcp  # noqa: E402
from advos_imports import call as advos  # noqa: E402
from baixar_pacotes import call as dash  # noqa: E402

CFG = config.carregar()
NS = CFG["namespace"]
TERMINAL = {"completed", "completed_with_errors", "failed", "canceled", "invalid", "partially_completed"}
WORK = STATE = PEND = PREFIXO = None  # do lote: _usar_lote()


def _usar_lote(nome):
    global WORK, STATE, PEND, PREFIXO
    WORK, ficha = config.lote(nome)
    STATE, PEND, PREFIXO = WORK / "estado.json", WORK / "pendencias.jsonl", ficha["prefixo"]
    return ficha


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(state):
    config.escrever_json(STATE, state)


def add_pend(rows):
    with PEND.open("a") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def wait(job, until, limit=900):
    start = time.time()
    while True:
        status = advos("imports_status", {"jobId": job})["data"]
        if until(status["status"]) or time.time() - start > limit:
            return status
        time.sleep(4)


def results(job):
    items, cursor = [], None
    while True:
        page = advos("imports_results", {"jobId": job, "limit": 500, "cursor": cursor})["data"]
        items += page["items"]
        cursor = page.get("nextCursor")
        if not cursor:
            return items


def strip_field(record, field):
    """Remove 'data.x' ou 'references.y' de um registro; devolve False se era obrigatório."""
    part, _, name = field.partition(".")
    if part in ("data", "references", "files") and name and name in record.get(part, {}):
        record[part].pop(name)
        return True
    return False


def run_section(tool, records, key, owner_of, on_conflict=None, max_tries=6):
    """Prévia com correção automática; confirma quando não houver recusa. Devolve {externalKey: targetIds}."""
    records = copy.deepcopy(records)
    for attempt in range(1, max_tries + 1):
        if not records:
            return {}
        started = advos(tool, {"schemaVersion": "1", "namespace": NS, "requestKey": f"{key}-t{attempt}", "records": records})
        if started.get("isError"):
            raise SystemExit(f"{tool} recusou o lote: {started}")
        job = started["data"]["jobId"]
        print(f"  {tool}: job {job} tentativa {attempt}", flush=True)
        status = wait(job, lambda s: s != "validating", limit=7200)
        if status["status"] == "validating":
            # Não reenviar com outra chave: quando o primeiro destravar, os dois gravariam (armadilha 15 da gravação).
            raise SystemExit(f"{tool}: prévia ainda validando depois de 2 h (job {job}); onda interrompida sem marcar "
                             "clientes. Avisar a equipe Advogando.")
        items = results(job)
        rejected = [i for i in items if i["previewOutcome"] not in ("valid", "replay")]
        if status["status"] == "review_ready" and not rejected:
            review = status["review"]
            advos("imports_confirm", {"jobId": job, "reviewRevision": review["revision"],
                                      "reviewDigest": review["digest"], "allowRejectedRows": False})
            final = wait(job, lambda s: s in TERMINAL, limit=7200)
            done = results(job)
            print(f"  {tool}: {final['status']} {final['counts']} job={job} falha={final.get('failureCode')}", flush=True)
            if final["status"] == "completed_with_errors":
                for i in done:
                    if i["outcome"] == "rejected":
                        add_pend([{"cliente_dash": owner_of({"externalKey": i["externalKey"]}), "item": f"{i['entity']} {i['externalKey']}",
                                   "motivo": f"recusado na gravação ({i.get('code')}); será refeito na próxima onda"}])
            elif final["status"] != "completed":
                raise SystemExit(f"{tool}: gravação terminou em {final['status']} ({final.get('failureCode')}); onda interrompida sem marcar clientes")
            return {i["externalKey"]: i["targetIds"] for i in done if i["outcome"] in ("created", "replayed", "skipped") and i["targetIds"]}
        advos("imports_cancel", {"jobId": job})
        by_key = {r["externalKey"]: r for r in records}
        drop = set()
        for rej in rejected:
            rec = by_key.get(rej["externalKey"])
            if rec is None:
                continue
            code, fields = rej.get("code"), rej.get("fields") or []
            if code == "DEPENDENCY_FAILED":
                continue
            if on_conflict and code == "BUSINESS_KEY_CONFLICT":
                on_conflict(rec)
                drop.add(rec["externalKey"])
                continue
            inativo = code == "REFERENCE_NOT_FOUND" and not fields and rec["entity"] != "task"
            if inativo:
                # O AdvOS não diz qual referência falhou; na prática é responsável que não está mais ativo (quem saiu
                # do escritório, 23/09/2026). Fora de tarefa o responsável é opcional: o registro entra sem ele.
                fields = [f"references.{k}" for k in ("responsible_user_id", "assigned_to_id", "salesperson_id", "seller_id")
                          if k in rec.get("references", {})]
            stripped = [f for f in fields if strip_field(rec, f)]
            add_pend([{"cliente_dash": owner_of(rec), "item": f"{rec['entity']} {rec['externalKey']}",
                       "motivo": ("responsável ou vendedor do Dash não está ativo no AdvOS; registro entrou sem ele"
                                  if inativo and stripped else
                                  f"{code}: campo(s) {', '.join(stripped or fields)} não aceitos pelo AdvOS"
                                  + ("" if stripped else "; registro não migrado"))}])
            if not stripped:
                drop.add(rec["externalKey"])
        # dependentes de registros removidos também saem
        changed = True
        while changed:
            changed = False
            for rec in records:
                if rec["externalKey"] in drop:
                    continue
                for ref in rec.get("references", {}).values():
                    if isinstance(ref, dict) and ref.get("externalKey") in drop:
                        drop.add(rec["externalKey"]); changed = True
                        add_pend([{"cliente_dash": owner_of(rec), "item": f"{rec['entity']} {rec['externalKey']}",
                                   "motivo": "não migrado porque o registro do qual depende foi recusado"}])
                        break
        records = [r for r in records if r["externalKey"] not in drop]
        print(f"  {tool}: tentativa {attempt} com {len(rejected)} recusa(s); refazendo com {len(records)} registros", flush=True)
    raise SystemExit(f"{tool}: recusas persistem depois de {max_tries} tentativas")


def chave_curta(fid):
    """requestKey do envio tem teto de 200 caracteres (-32602 too_big): id longo do Dash vira hash."""
    return fid if len(fid) <= 120 else "h-" + hashlib.sha256(fid.encode()).hexdigest()[:40]


def nome_curto(nome, limite=200):
    """O AdvOS recusa fileName com mais de 200 caracteres (-32602 too_big): corta e mantém a extensão."""
    nome = nome.replace("/", "-")
    if len(nome) <= limite:
        return nome
    base, ponto, ext = nome.rpartition(".")
    ext = f".{ext}" if ponto and 0 < len(ext) <= 5 else ""
    return (base if ext else nome)[: limite - len(ext)] + ext


# Documento do Dash que é link do Google Drive: com link público o Drive devolve a página do visualizador (HTML), com
# link privado a de login. Imprimir essa página em PDF poria no AdvOS um documento falso (24/09/2026).
PAGINA_GOOGLE = (b"drive.google.com", b"accounts.google.com", b"docs.google.com")


def html_to_pdf(raw):
    """Documento gerado no Dash vem em HTML e o AdvOS não aceita HTML: imprime em PDF com o Chrome local."""
    chrome = config.achar_chrome()
    if not chrome:
        raise OSError("Chrome não encontrado")
    with tempfile.TemporaryDirectory(dir=config.HOME) as tmp:
        src, out = pathlib.Path(tmp) / "doc.html", pathlib.Path(tmp) / "doc.pdf"
        src.write_bytes(raw)
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--blink-settings=imagesEnabled=true", f"--print-to-pdf={out}", src.as_uri()],
                       check=True, capture_output=True, timeout=120)
        return out.read_bytes()


def baixar_arquivo(fd, pkg):
    """Ticket do Dash + download (2 tentativas). Devolve (bytes, None) ou (None, motivo)."""
    raw, falha = None, None
    for _tentativa in range(2):  # 404 no download já se mostrou passageiro: ticket novo e mais uma vez
        ticket = dash("migration_source_get_file_ticket", {
            "sourceSnapshotId": pkg["sourceSnapshotId"], "sourceBatchId": pkg["sourceBatchId"],
            "sourceFileId": fd["sourceFileId"], "expectedDescriptorHash": fd["descriptorHash"],
            "sequenceId": pkg["sequenceId"]})
        if not isinstance(ticket, dict) or ticket.get("status") != "ok":
            return None, f"ticket recusado: {json.dumps(ticket, ensure_ascii=False)[:200]}"
        t = ticket["ticket"]
        request = urllib.request.Request(t["downloadUrl"], headers=t.get("downloadHeaders") or {})
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                raw = response.read()
            break
        except urllib.error.HTTPError as exc:  # ex.: 404 = o arquivo não estava onde o Dash apontava
            falha = f"HTTP {exc.code}"
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError) as exc:
            falha = type(exc).__name__  # inclui IncompleteRead: conexão caiu no meio do arquivo
    if raw is None:
        return None, f"download do arquivo falhou duas vezes ({falha}); o cliente migra sem este documento"
    if hashlib.sha256(raw).hexdigest() != fd["sha256"] or len(raw) != fd["sizeBytes"]:
        return None, "arquivo baixado não confere com a impressão digital do Dash"
    return raw, None


def transfer(doc, pkg):
    """Baixa o arquivo pelo ticket do Dash, confere o SHA-256 e envia ao armazenamento do AdvOS."""
    fd = doc["descriptor"]
    name = nome_curto(doc["fileName"])
    mime = fd.get("mimeType") or "application/pdf"
    chave = f"{PREFIXO}-doc-{chave_curta(fd['sourceFileId'])}"
    raw = None
    tipo = mime.split(";")[0].strip()
    if tipo in ("application/octet-stream", "binary/octet-stream", "text/html"):
        # O AdvOS recusa octet-stream e HTML já na criação (UPLOAD_INVALID; ~175 documentos em setembro): baixa antes,
        # descobre o formato pelos bytes e imprime em PDF o documento gerado em HTML no Dash.
        raw, err = baixar_arquivo(fd, pkg)
        if raw is None:
            return None, err
        real = sniff(raw)
        if not real and (tipo == "text/html" or raw.lstrip()[:1] == b"<"):
            if any(m in raw[:300000].lower() for m in PAGINA_GOOGLE):
                return None, ("link do Google Drive: veio a página do Drive, não o arquivo (não baixado do Dash); "
                              "buscar o original")
            try:
                raw, real = html_to_pdf(raw), ("application/pdf", "pdf")
            except (subprocess.SubprocessError, OSError) as exc:
                return None, f"conversão de HTML para PDF falhou ({type(exc).__name__}); original preservado no Dash"
        if not real:
            return None, "formato do arquivo não reconhecido (o Dash informa application/octet-stream); original preservado no Dash"
        mime, chave = real[0], f"{chave}-{real[1]}"
        name = nome_curto(f"{name.rsplit('.', 1)[0] if '.' in name else name}.{real[1]}")
        doc["fileName"] = name
    tamanho, impressao = (len(raw), hashlib.sha256(raw).hexdigest()) if raw is not None else (fd["sizeBytes"], fd["sha256"])
    created = advos("imports_upload_create", {"section": "documents", "purpose": "client_document",
                                              "requestKey": chave, "fileName": name, "mimeType": mime,
                                              "sizeBytes": tamanho, "sha256": impressao})
    if created.get("isError"):
        return None, f"envio recusado: {created.get('data')}"
    already = advos("imports_upload_complete", {"uploadId": created["data"]["uploadId"]})
    if not already.get("isError") and (already.get("data") or {}).get("status") == "verified":
        return created["data"]["uploadId"], None
    if raw is None:
        raw, err = baixar_arquivo(fd, pkg)
        if raw is None:
            return None, err
    digest = hashlib.sha256(raw).hexdigest()
    upload_id, err = put_and_verify(created["data"], raw)
    if err and "UPLOAD_INVALID" in err:
        real = sniff(raw)
        if real and real[0] != mime:
            base = name.rsplit(".", 1)[0]
            again = advos("imports_upload_create", {"section": "documents", "purpose": "client_document",
                                                    "requestKey": f"{PREFIXO}-doc-{chave_curta(fd['sourceFileId'])}-{real[1]}",
                                                    "fileName": nome_curto(f"{base}.{real[1]}"), "mimeType": real[0],
                                                    "sizeBytes": len(raw), "sha256": digest})
            if again.get("isError"):
                return None, f"envio recusado: {again.get('data')}"
            doc["fileName"] = nome_curto(f"{base}.{real[1]}")
            return put_and_verify(again["data"], raw)
        return None, f"{err}; formato real do arquivo: {real[0] if real else 'não reconhecido'}"
    return upload_id, err


MAGIC = [(b"%PDF", ("application/pdf", "pdf")), (b"\xff\xd8\xff", ("image/jpeg", "jpg")),
         (b"\x89PNG", ("image/png", "png")), (b"PK\x03\x04", ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx")),
         (b"\xd0\xcf\x11\xe0", ("application/msword", "doc"))]


def sniff(raw):
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ("image/webp", "webp")
    return next((kind for magic, kind in MAGIC if raw.startswith(magic)), None)


def put_and_verify(up, raw):
    if up.get("url"):
        put = urllib.request.Request(up["url"], data=raw, method="PUT", headers=up.get("requiredHeaders") or {})
        try:
            with urllib.request.urlopen(put, timeout=300):
                pass
        except urllib.error.HTTPError as error:
            return None, f"PUT recusado HTTP {error.code}"
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError) as error:
            return None, f"PUT falhou por rede ({type(error).__name__}); documento fica para a repescagem"
    for _ in range(24):
        done = advos("imports_upload_complete", {"uploadId": up["uploadId"]})
        if done.get("isError") and (done.get("data") or {}).get("code") == "UPLOAD_VERIFYING":
            time.sleep(5); continue
        if done.get("isError"):
            return None, f"verificação recusada: {(done.get('data') or {}).get('code') or done.get('data')}"
        return up["uploadId"], None
    return None, "verificação não terminou"


def main(lote, gravar=False, maximo=20):
    ficha = _usar_lote(lote)
    # converter só aqui: espiar_documento.py usa este módulo antes de os catálogos existirem
    from converter import IMPORTAR, catalogos_importar, convert
    limite = 1000  # registros por envio (imports_capabilities: limits.inlineRows)
    if gravar:
        # Regra 5 da skill: antes de gravar, o escritório do token e a organização da credencial são os combinados.
        if not CFG.get("advos_org_id") or dash_mcp.claims().get("escritorio_id") != CFG.get("dash_office_id"):
            raise SystemExit("🔴 escritório do Dash diferente do combinado (rode identidade.py); nada gravado")
        cap = advos("imports_capabilities", {})
        if (cap.get("data") or {}).get("organizationId") != CFG["advos_org_id"]:
            raise SystemExit("🔴 a credencial do AdvOS é de outra organização; nada gravado")
        limite = ((cap.get("data") or {}).get("limits") or {}).get("inlineRows") or limite
    state = load_state()
    packages = {}
    for f in sorted((WORK / "pacotes").glob("*.json")):
        cid = f.stem
        if state.get(cid, {}).get("fase") in ("concluido", "existe") or state.get(cid, {}).get("grande_demais"):
            continue
        pkg = json.loads(f.read_text())
        item = pkg["items"][0]
        if item.get("sourceClientId") != cid or item["bundle"]["entities"]["Cliente"][0]["id"] != cid:
            print(f"  pacote {cid} tem outro cliente; ignorado", flush=True)
            continue
        packages[cid] = pkg
    if not packages:
        print("nada novo para importar"); return
    # Quem já começou numa onda interrompida vem primeiro. Gravando, converte só até encher a onda (converter o lote
    # inteiro a cada onda custa ~1 s por cliente); a simulação converte tudo para mostrar o lote inteiro.
    converted, espera, prontos = {}, set(), []
    for cid in sorted(packages, key=lambda c: (not state.get(c, {}).get("crm"), c)):
        if gravar and len(prontos) >= maximo:
            break
        converted[cid] = convert(packages[cid])
        # Cliente com rótulo esperando decisão do Claude não entra: entraria com o valor padrão errado.
        if any(p.get("aguarda_decisao") for p in converted[cid][3]):
            espera.add(cid)
        else:
            prontos.append(cid)
    # O AdvOS recebe até `limite` registros por envio (cadastro, jurídico com o catálogo, documentos): a onda para antes
    # de passar. Cliente que sozinho passa do limite precisaria de envio por manifesto, que o kit ainda não faz.
    extra = len(catalogos_importar()) if IMPORTAR else 0
    onda, somas, grandes = [], [0, extra, 0], {}
    for cid in prontos:
        tam = [len(converted[cid][0]), len(converted[cid][1]), len(converted[cid][2])]
        if max(tam[0], tam[1] + extra, tam[2]) > limite:
            grandes[cid] = max(tam[0], tam[1] + extra, tam[2])
            continue
        if len(onda) >= maximo or any(s + t > limite for s, t in zip(somas, tam)):
            break
        onda.append(cid)
        somas = [s + t for s, t in zip(somas, tam)]

    if not gravar:
        conta = Counter(r["entity"] for c in onda for r in converted[c][0] + converted[c][1])
        print(f"simulação (nada enviado ao AdvOS; rótulo novo vai para a fila de decisão): {len(packages)} pacote(s) "
              f"pendente(s) | esperando decisão: {len(espera)} | prontos: {len(prontos)} | esta onda: {len(onda)} cliente(s)"
              + (f" | grandes demais para um envio: {len(grandes)}" if grandes else ""))
        print("  registros da onda: " + ", ".join(f"{k} {v}" for k, v in sorted(conta.items()))
              + (f" | catálogo do escritório: {len(catalogos_importar())}" if IMPORTAR else "")
              + f" | documentos: {sum(len(converted[c][2]) for c in onda)}"
              + f" | pendências: {sum(len(converted[c][3]) for c in onda)}")
        print("  para gravar (com o OK da responsável para este lote): python3 carga.py", lote, "--gravar")
        return

    for cid, n in grandes.items():
        state.setdefault(cid, {})["grande_demais"] = n
        add_pend([{"cliente_dash": cid, "item": "cliente", "motivo": f"{n} registros num só envio: passa do limite de "
                   f"{limite} do AdvOS (precisa de envio por manifesto, que o kit ainda não faz); chamar a equipe Advogando"}])
    if grandes:
        print(f"  {len(grandes)} cliente(s) grandes demais para um envio: separados, com pendência", flush=True)
    wave = ficha["proxima_onda"]
    ficha["proxima_onda"] = wave + 1  # número gasto antes de enviar: nunca se repete, nem depois de queda
    config.salvar_lote(WORK, ficha)

    for cid in converted:
        state.setdefault(cid, {})["aguarda_decisao"] = cid in espera
    if espera:
        print(f"  {len(espera)} cliente(s) esperando decisão do Claude (decisoes/fila.json)", flush=True)
    converted = {cid: converted[cid] for cid in onda}
    if not converted:
        save_state(state)
        print("nada pronto para importar nesta onda"); return
    print(f"onda {wave}: {len(converted)} cliente(s)", flush=True)
    for cid, (_, _, _, pend) in converted.items():
        if not state.get(cid, {}).get("pendencias_registradas"):
            add_pend(pend)
            state.setdefault(cid, {})["pendencias_registradas"] = True
    save_state(state)

    # 1. cadastro
    owner = {}
    crm = []
    for cid, (c, _, _, _) in converted.items():
        if state.get(cid, {}).get("crm"):
            continue
        for rec in c:
            owner[rec["externalKey"]] = cid
        crm += c

    def conflict(rec):
        cid = owner[rec["externalKey"]]
        state.setdefault(cid, {})["fase"] = "existe"
        add_pend([{"cliente_dash": cid, "item": "cliente", "motivo": "já existe no AdvOS (mesmo CPF); não duplicado — conferir processos e documentos"}])

    if crm:
        targets = run_section("import_crm", crm, f"{PREFIXO}-crm-w{wave}", lambda r: owner.get(r["externalKey"]), conflict)
        for key, ids in targets.items():
            cid = owner.get(key)
            if cid and key == cid:
                state.setdefault(cid, {})["crm"] = ids[0]
        save_state(state)

    ready = [cid for cid in converted if state.get(cid, {}).get("crm") and not state[cid].get("legal")]
    # 2. processos e afins
    legal, owner = [], {}
    for cid in ready:
        for rec in converted[cid][1]:
            rec = copy.deepcopy(rec)
            for ref in rec.get("references", {}).values():
                if isinstance(ref, dict) and ref.get("entity") == "client" and ref.get("externalKey") == cid:
                    ref.clear(); ref["id"] = state[cid]["crm"]
            owner[rec["externalKey"]] = cid
            legal.append(rec)
    if legal and IMPORTAR:
        # catálogo do escritório no mesmo envio (o AdvOS ordena as dependências dentro do lote); repetir é replay
        legal = catalogos_importar() + legal
    if legal:
        targets = run_section("import_legal", legal, f"{PREFIXO}-legal-w{wave}", lambda r: owner.get(r["externalKey"]))
        for cid in ready:
            state[cid]["legal"] = {k: v for k, v in targets.items() if owner.get(k) == cid}
        save_state(state)
    else:
        for cid in ready:
            state[cid]["legal"] = {}

    # 3. documentos
    docs_records, owner = [], {}
    for cid in converted:
        st = state.get(cid, {})
        if not st.get("crm") or "legal" not in st or st.get("docs") is not None:
            continue
        for doc in converted[cid][2]:
            fid = doc["descriptor"]["sourceFileId"]
            upload_id, err = transfer(doc, packages[cid])
            if err:
                add_pend([{"cliente_dash": cid, "item": f"documento {fid}", "motivo": err}])
                continue
            refs = {"client_id": {"id": st["crm"]}}
            case_ids = st["legal"].get(doc["case"]) if doc["case"] else None
            if case_ids:
                refs["legal_case_id"] = {"id": case_ids[0]}
            owner[fid] = cid
            docs_records.append({"entity": "client_document", "externalKey": fid, "files": {"file": upload_id},
                                 "references": refs, "data": {"file_name": doc["fileName"][:255],
                                 "document_type": doc["documentType"],
                                 "notes": f"Tipo no AdvogandoDash: {doc['dashType']}" if doc.get("dashType") else None}})
            docs_records[-1]["data"] = {k: v for k, v in docs_records[-1]["data"].items() if v}
        print(f"  arquivos do cliente {cid} transferidos", flush=True)
    if docs_records:
        targets = run_section("import_documents", docs_records, f"{PREFIXO}-docs-w{wave}", lambda r: owner.get(r["externalKey"]))
    else:
        targets = {}
    for cid in converted:
        st = state.get(cid, {})
        if st.get("crm") and "legal" in st and st.get("docs") is None:
            st["docs"] = {k: v for k, v in targets.items() if owner.get(k) == cid}
            st["fase"] = "concluido"
    save_state(state)
    done = sum(1 for s in state.values() if s.get("fase") == "concluido")
    exist = sum(1 for s in state.values() if s.get("fase") == "existe")
    print(f"onda {wave} terminada: {done} concluído(s), {exist} já existiam no AdvOS | prova: python3 conferir.py {lote}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="grava o lote no AdvOS em ondas (sem --gravar: simulação)")
    ap.add_argument("lote")
    ap.add_argument("--gravar", action="store_true", help="grava de verdade (só com o OK da responsável para este lote)")
    ap.add_argument("--max", type=int, default=20, help="clientes por onda (padrão 20)")
    a = ap.parse_args()
    main(a.lote, a.gravar, a.max)
