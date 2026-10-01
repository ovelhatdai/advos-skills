"""Converte pacotes completos do Dash em registros do MCP de importação do AdvOS.

Regra da migração: tudo o que está no Dash vai para o AdvOS; o que faltar vira pendência. A cadeia de processos
(origem, relação, ordem) é preservada. Decisões do escritório em config.json:
  judicial_sem_cnj            "separar" para conferência manual | "administrativo" com o status judicial numa nota
  tirar_senha_das_observacoes linha com "senha" não vai para o AdvOS; vira pendência (campo seguro)
  tarefas_automaticas         tarefas de robô: concluídas não migram; abertas vão para quem a regra indica
  catalogos                   "casar" com o catálogo do AdvOS (referencia/advos-catalogos.json) |
                              "importar" o catálogo do escritório (externalKey = id no Dash)
Rótulos livres: decisor.py (exato → semente → precedentes → fila do Claude). Membros: referencia/membros.json.
"""

import json
import pathlib
import re
import sys
import unicodedata
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
from decisor import decide  # noqa: E402  (sem modelo externo: exato → semente → precedentes → Claude)

CFG = config.carregar()
SP = config.SP
CLIENT_STATUS = {"contrato_assinado": "contract_signed", "aguardando_assinatura": "awaiting_signature",
                 "ativo": "active", "cancelado": "cancelled", "lead": "lead", "negociacao": "negotiation",
                 "em_negociacao": "negotiation", "finalizado": "completed", "concluido": "completed",
                 "arquivado": "archived", "retrabalho": "rework"}
MARITAL = {"solteiro": "single", "solteira": "single", "casado": "married", "casada": "married",
           "divorciado": "divorced", "divorciada": "divorced", "separado": "divorced", "separada": "divorced",
           "viuvo": "widowed", "viuva": "widowed", "viúvo": "widowed", "viúva": "widowed",
           "uniao_estavel": "common_law", "união estável": "common_law", "uniao estavel": "common_law"}
CHANNEL = {"anuncio_facebook": "facebook_ad", "facebook": "facebook_ad", "instagram": "facebook_ad",
           "anuncio_google": "google_ad", "google": "google_ad", "indicacao": "referral", "indicação": "referral",
           "site": "website", "whatsapp": "whatsapp", "telefone": "phone", "ligacao": "phone",
           "presencial": "in_person"}
RELATION = {"primeiro_processo": "first_process", "recurso": "appeal", "nova_tentativa": "new_attempt",
            "mudanca_estrategia": "strategy_change", "mudanca_de_estrategia": "strategy_change",
            "administrativo_concluido": "administrative_completed"}
VISIBILITY = {"todos": "all", "juridico": "legal", "jurídico": "legal", "administrativo": "administrative",
              "financeiro": "financial"}
DEADLINE_STATUS = {"pendente": "pending", "cumprido": "fulfilled", "vencido": "overdue",
                   "cliente_ausente": "client_absent", "cliente_nao_compareceu": "client_absent",
                   "remarcado": "rescheduled", "cancelado": "cancelled", "documento_anexado": "document_attached"}
PRIORITY = {"baixa": "low", "media": "medium", "média": "medium", "alta": "high", "urgente": "urgent"}
TASK_STATUS = {"aberta": "open", "pendente": "open", "em_andamento": "in_progress", "aguardando": "waiting_on_third_party",
               "concluida": "completed", "concluída": "completed", "cancelada": "cancelled"}
FASE = {"juridico": "judicial", "jurídico": "judicial", "judicial": "judicial", "administrativo": "administrative",
        "administrative": "administrative", "comercial": "sales", "vendas": "sales", "sales": "sales"}
IMPORTAR = CFG["catalogos"] == "importar"
TIRAR_SENHA = CFG["tirar_senha_das_observacoes"]
JUDICIAL_SEM_CNJ = CFG["judicial_sem_cnj"]
SENHA_RETIRADA = ("linha(s) com senha retirada(s) do texto migrado (provável senha do INSS); cadastrar no campo "
                  "seguro do AdvOS")


def _referencia(nome, passo):
    f = config.REFERENCIA / nome
    if not f.exists():
        raise SystemExit(f"falta {f}: {passo}")
    return json.loads(f.read_text(encoding="utf-8"))


def load_catalogs():
    boot = _referencia("bootstrap.json", "baixe ao menos um pacote (baixar_pacotes.py)")["bootstrap"]["entities"]
    users = _referencia("membros.json", "rode membros.py")
    cat = {"deadline_types": [], "service_types": [], "medical_conditions": []}
    statuses, slugs = {"administrative": [], "judicial": []}, {}
    if not IMPORTAR:
        advos = _referencia("advos-catalogos.json", "rode catalogos_advos.py (ou veja o LEIA-ME)")

        def ativos(nome):
            return [r for r in advos.get(nome) or [] if r.get("is_active", True) is not False]

        cat["deadline_types"] = [[r["id"], r["name"]] for r in ativos("deadline_types")]
        cat["service_types"] = [[r["id"], r["name"]] for r in ativos("legal_service_types")]
        cat["medical_conditions"] = [[r["id"], r["name"]] for r in ativos("medical_conditions")]
        for r in ativos("case_statuses"):
            if r.get("phase") in statuses:
                statuses[r["phase"]].append({"value": r["id"], "label": r["name"]})
        slugs = {r["slug"]: r["id"] for r in ativos("deadline_types") if r.get("slug")}
    return cat, boot, statuses, users, slugs


CAT, BOOT, STATUSES, USERS, ADVOS_SLUG = load_catalogs()
DASH_STATUS = {s["id"]: s for s in BOOT.get("StatusProcessual", [])}
DASH_SERVICE = {s["id"]: s.get("nome_servico") for s in BOOT.get("TipoServicoJuridico", [])}
DASH_CONDITION = {c["id"]: c.get("nome") for c in BOOT.get("Condicao", [])}
DASH_DEADLINE = {t["slug"]: t["id"] for t in BOOT.get("TipoPrazo", []) if t.get("slug")}
DEADLINE_BY_SLUG = {}
for row in CAT["deadline_types"]:
    DEADLINE_BY_SLUG[row[1].lower()] = row[0]
SLUGS = {"pericia": "perícia", "protocolo": "protocolo", "exigencia": "exigência", "defesa": "defesa",
         "audiencia": "audiência", "recurso": "recurso", "replica": "réplica",
         "solicitar_documentos": "solicitar documentos", "manifestacao_de_laudo": "manifestação de laudo",
         "outros": "manifestação simples", "manifestacao_simples": "manifestação simples",
         "proposta_de_acordo": "proposta de acordo", "pericia_medica": "perícia médica"}


def options(section):
    return [{"value": r[0], "label": r[1]} for r in CAT[section]]


AGUARDANDO = []  # rótulos deste convert() que esperam decisão do Claude (decisoes/fila.json)
NOME_CLIENTE = set()  # partes do nome do cliente deste convert(): nunca saem para a fila nem para a semente
_PARTICULAS = {"de", "da", "do", "dos", "das", "e"}


def _norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def sem_nome(texto):
    """Troca por [nome] a parte do nome do cliente que a equipe digitou no rótulo (ex.: 'PROCESSO FULANO')."""
    if not texto or not NOME_CLIENTE:
        return texto
    saida = "".join("[nome]" if _norm(p) in NOME_CLIENTE else p for p in re.split(r"(\W+)", texto))
    return re.sub(r"\[nome\](?:\W*\[nome\])+", "[nome]", saida)


def decidir(kind, source, opts, context=None):
    if not source:
        return None
    source = sem_nome(source)
    [d] = decide([{"kind": kind, "source": source, "context": context, "options": opts}])
    if d["status"] == "claude":
        AGUARDANDO.append(f"{kind} '{source}'")
    return d["applied"]


DOC_OPTIONS = [{"value": v, "label": l} for v, l in [
    ("identity", "Documento de identificação (RG, CNH, CPF, CTPS)"), ("medical_report", "Laudo, relatório ou documento médico"),
    ("proof_of_address", "Comprovante de residência"), ("court_document", "Documento judicial (petição, decisão, sentença)"),
    ("contract", "Contrato (ex.: contrato de honorários)"), ("letter", "Carta ou ofício (ex.: comunicação do INSS)"),
    ("power_of_attorney", "Procuração"), ("other", "Outro documento")]]
PROC_OPTIONS = [{"value": v, "label": l} for v, l in [
    ("filing", "Protocolo ou ajuizamento"), ("petition", "Petição"), ("hearing", "Audiência"), ("appeal", "Recurso"),
    ("sentence", "Sentença"), ("order", "Despacho ou decisão"), ("notice", "Intimação ou notificação"),
    ("status_change", "Mudança de status/etapa do processo"), ("document_upload", "Envio de documento"),
    ("client_edit", "Edição do cadastro do cliente"), ("system_entry", "Registro automático do sistema"),
    ("initial_import", "Importação inicial"), ("other", "Outro"), ("automatic_movement", "Movimentação automática do tribunal")]]


def digits(value):
    return re.sub(r"\D", "", str(value or ""))


def text(value):
    value = (str(value).strip() if value is not None else "")
    return value or None


def sem_senha(value):
    """Texto sem as linhas que falam de senha (o Dash guarda a senha do INSS em texto aberto). Sem a opção ligada,
    ou sem 'senha' no texto, devolve o texto como está."""
    texto = text(value)
    if not TIRAR_SENHA or not texto or not re.search(r"senha", texto, re.I):
        return texto
    return text("\n".join(l for l in texto.splitlines() if not re.search(r"senha", l, re.I)))


def as_date(value):
    if not value:
        return None
    value = str(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (dt.astimezone(SP) if dt.tzinfo else dt).date().isoformat()
    except ValueError:
        return None


def as_datetime(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=SP)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def valid_cpf(value):
    d = digits(value)
    if len(d) != 11 or d == d[0] * 11:
        return None
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(d[n]):
            return None
    return d


def duplicados(processes):
    """Processos judiciais do mesmo cliente com o mesmo CNJ: {duplicado: mantido (o mais antigo)}.
    O AdvOS aceita um só processo por CNJ e a prévia não pega a repetição dentro do lote: a gravação cai com
    INFRASTRUCTURE_FAILURE (acréscimo trfnovos, 23/09/2026)."""
    vistos, canon = {}, {}
    for p in sorted(processes, key=lambda p: (p.get("created_date") or "", p["id"])):
        n = digits(p.get("numero_processo"))
        if (p.get("tipo_processo") or "").lower() == "judicial" and len(n) == 20:
            if n in vistos:
                canon[p["id"]] = vistos[n]
            else:
                vistos[n] = p["id"]
    return canon


def member(dash_user_id):
    entry = USERS.get(dash_user_id or "")
    return entry["advos"] if entry else None


# ---------- catálogo do escritório (modo "importar") ----------

def _slug(valor):
    s = re.sub(r"[^a-z0-9]+", "_", _norm(valor)).strip("_")
    return s[:120] or None


def _catalogo_dash():
    """Catálogo do Dash como registros do AdvOS (externalKey = id no Dash). Nome repetido no Dash vira um registro só
    (o AdvOS valida unicidade): os ids repetidos apontam para o primeiro. Devolve (registros, {(entidade, id): id})."""
    regs, alias = [], {}

    def add(entity, rows, nome_de, extra, chave_de):
        vistos = {}
        for r in sorted(rows, key=lambda r: (r.get("created_date") or "", r["id"])):
            nome = text(nome_de(r))
            dados = {"name": nome[:120], **extra(r)} if nome else None
            if not dados or not all(v is not None for v in dados.values()):
                continue
            k = chave_de(dados)
            if k in vistos:
                alias[(entity, r["id"])] = vistos[k]
                continue
            vistos[k] = alias[(entity, r["id"])] = r["id"]
            regs.append({"entity": entity, "externalKey": r["id"], "data": dados})

    add("case_status", BOOT.get("StatusProcessual", []), lambda r: r.get("nome"),
        lambda r: {"phase": FASE.get((r.get("fase") or "").lower())}, lambda d: (d["phase"], _norm(d["name"])))
    nomes = {_norm(r["data"]["name"]): r["data"]["name"] for r in regs if r["entity"] == "case_status"}
    for r in regs:  # etapa seguinte só quando ela também está no catálogo
        proxima = text(DASH_STATUS.get(r["externalKey"], {}).get("proximo_status_nome"))
        if proxima and _norm(proxima) in nomes and _norm(proxima) != _norm(r["data"]["name"]):
            r["data"]["next_status_name"] = nomes[_norm(proxima)]
    add("legal_service_type", BOOT.get("TipoServicoJuridico", []), lambda r: r.get("nome_servico"),
        lambda r: {}, lambda d: _norm(d["name"]))
    add("medical_condition", BOOT.get("Condicao", []), lambda r: r.get("nome"), lambda r: {}, lambda d: _norm(d["name"]))
    add("deadline_type", BOOT.get("TipoPrazo", []), lambda r: r.get("nome"),
        lambda r: {"slug": _slug(r.get("slug") or r.get("nome"))}, lambda d: d["slug"])
    return regs, alias


CATALOGO, ALIAS = _catalogo_dash() if IMPORTAR else ([], {})


def catalogos_importar():
    """Registros de catálogo que a carga manda junto em cada onda do jurídico (modo "importar"). Repetir o mesmo
    registro em outra onda é seguro: o AdvOS devolve o id já criado (replay)."""
    return [json.loads(json.dumps(r)) for r in CATALOGO]


def _ref_catalogo(entity, dash_id):
    canon = ALIAS.get((entity, dash_id or ""))
    return {"entity": entity, "externalKey": canon} if canon else None


# ---------- tarefas automáticas (robô) ----------

def _quem(destino):
    """Membro do AdvOS indicado na regra: e-mail (do Dash ou da lista de membros do AdvOS) ou o próprio userId."""
    destino = (destino or "").strip()
    if "@" not in destino:
        return destino or None
    alvo = destino.lower()
    for u in BOOT.get("User", []):
        if (u.get("email") or "").strip().lower() == alvo and member(u["id"]):
            return member(u["id"])
    arq = config.REFERENCIA / "advos-membros.json"
    if arq.exists():
        import membros  # noqa: E402  (só quando a regra usa e-mail)
        return next((m["userId"] for m in membros.membros_advos() if m["email"] == alvo), None)
    return None


REGRAS_ROBO = [(tuple(r.get("prefixos") or ()), _quem(r.get("abertas_para"))) for r in CFG["tarefas_automaticas"]]


def responsavel_automatica(tk):
    """Membro do AdvOS para tarefa de robô sem responsável membro; "concluida" se não migra; None se não é de robô."""
    titulo = (tk.get("titulo") or "").strip()
    regra = next((r for r in REGRAS_ROBO if r[0] and titulo.startswith(r[0])), None)
    if not regra:
        return None
    if TASK_STATUS.get((tk.get("status") or "").lower()) in ("completed", "cancelled"):
        return "concluida"
    return regra[1]


def drop_none(record):
    return {k: v for k, v in record.items() if v not in (None, "", [], {})}


def convert(package):
    """Devolve (crm, legal, docs, pendencias) de um pacote de cliente."""
    item = package["items"][0]
    bundle = item["bundle"]
    ents = bundle["entities"]
    [cliente] = ents["Cliente"]
    cid = cliente["id"]
    name = text(cliente.get("nome_completo")) or cid
    pend = []

    quarentenados = set()

    AGUARDANDO.clear()
    NOME_CLIENTE.clear()
    NOME_CLIENTE.update(p for p in _norm(name).split() if len(p) >= 3 and p not in _PARTICULAS)

    def pendencia(item_, motivo, **marcas):
        pend.append({"cliente_dash": cid, "cliente": name, "item": item_, "motivo": motivo, **marcas})

    # ---------- cliente ----------
    cpf = valid_cpf(cliente.get("cpf"))
    if not cpf:
        pendencia("CPF", f"CPF ausente ou inválido no Dash ({text(cliente.get('cpf')) or 'vazio'})")
    status = CLIENT_STATUS.get((cliente.get("status_cliente") or "").lower())
    if cliente.get("status_cliente") and not status:
        pendencia("status do cliente", f"status '{cliente.get('status_cliente')}' sem correspondente")
    phones = [digits(cliente.get(f"telefone_{i}")) for i in (1, 2, 3, 4)]
    phones = [p for i, p in enumerate(phones) if p and p not in phones[:i]]
    rep_name = text(cliente.get("representante_legal_nome"))
    obs = [sem_senha(cliente.get("observacoes")), sem_senha(cliente.get("resumo_caso"))]
    for extra in phones[2:]:
        obs.append(f"Outro telefone no Dash: {extra}")
    # Vídeo de confirmação vai só como link (decisão da migração de setembro, 22/09/2026).
    for q in bundle.get("fileQuarantine") or []:
        if q.get("quarantineCode") == "LINK_ONLY" and q.get("sourceLink"):
            origem = "do contrato" if q.get("sourceEntity") == "Contrato" else "do cliente"
            obs.append(f"Vídeo de confirmação {origem}: {q['sourceLink']}")
    # Campos novos do AdvOS (mother_name, father_name, pis_pasep, ctps, benefit_number, address_number,
    # address_complement): o Cliente do Dash não tem campo correspondente nos contratos v4 a v6 (conferido em 1.745
    # cadastros da migração de setembro, 01/10/2026). Mapear quando um contrato novo trouxer.
    data = drop_none({
        "entity_type": "pf" if cpf or len(digits(cliente.get("cpf"))) != 14 else "pj",
        "full_name": name,
        "cpf": cpf,
        "rg": text(cliente.get("rg")),
        "date_of_birth": as_date(cliente.get("data_nascimento")),
        "email": text(cliente.get("email")),
        "phone_primary": phones[0] if phones else None,
        "phone_secondary": phones[1] if len(phones) > 1 else None,
        "marital_status": MARITAL.get((cliente.get("estado_civil") or "").strip().lower()),
        "occupation": text(cliente.get("profissao")),
        "full_address": text(cliente.get("endereco_completo")),
        "city": text(cliente.get("cidade")),
        "state": text(cliente.get("estado")),
        "zip_code": digits(cliente.get("cep")) or None,
        "neighborhood": text(cliente.get("bairro")),
        "acquisition_channel": CHANNEL.get((cliente.get("canal_aquisicao") or "").lower(),
                                           "other" if cliente.get("canal_aquisicao") else None),
        "status": status,
        "notes": "\n".join(o for o in obs if o) or None,
        "contract_date": as_date(cliente.get("data_contrato")),
        "requires_legal_representative": True if rep_name else None,
    })
    refs = {}
    seller = member(cliente.get("vendedor_id"))
    if seller:
        refs["salesperson_id"] = {"id": seller}
    elif cliente.get("vendedor_id"):
        pendencia("vendedor", "vendedor do Dash não é membro do escritório no AdvOS")
    crm = [drop_none({"entity": "client", "externalKey": cid, "data": data, "references": refs})]
    if rep_name:
        crm.append(drop_none({"entity": "client_party", "externalKey": f"{cid}:representante", "data": drop_none({
            "role": "legal_representative", "name": rep_name, "cpf": valid_cpf(cliente.get("representante_legal_cpf")),
            "rg": text(cliente.get("representante_legal_rg")),
            "relationship": text(cliente.get("representante_legal_parentesco"))}),
            "references": {"client_id": {"entity": "client", "externalKey": cid}}}))

    for label, value in (("observações do cliente", cliente.get("observacoes")), ("resumo do cliente", cliente.get("resumo_caso"))):
        if value and re.search(r"senha", str(value), re.I):
            pendencia(label, SENHA_RETIRADA if TIRAR_SENHA else
                      "texto contém senha (provável senha do INSS); mover para o campo seguro no AdvOS")

    # ---------- processos ----------
    legal = []
    processes = ents.get("ProcessoJuridico", [])
    canon = duplicados(processes)
    if canon:  # une o duplicado ao mantido: o que apontava para ele passa a apontar para o mantido (sem mexer no pacote)
        def une(row, campo):
            return {**row, campo: canon.get(row.get(campo), row.get(campo))}
        ents = {**ents, **{e: [une(r, "processo_id") for r in ents.get(e, [])]
                           for e in ("AndamentoProcessual", "PrazoProcessual", "Tarefa", "DocumentoCliente")}}
        processes = [une(p, "processo_origem_id") for p in processes if p["id"] not in canon]
        for dup, keep in canon.items():
            pendencia(f"processo {dup}", f"processo duplicado no Dash (mesmo CNJ do processo {keep}): andamentos, "
                                         "prazos, tarefas e documentos unidos a ele")
    process_ids = {p["id"] for p in processes}
    if IMPORTAR:
        condition_ref = _ref_catalogo("medical_condition", cliente.get("condicao_id"))
    else:
        condition = DASH_CONDITION.get(cliente.get("condicao_id") or "")
        condition_id = decidir("condicao", condition, options("medical_conditions")) if condition else None
        condition_ref = {"id": condition_id} if condition_id else None
    for proc in processes:
        pid = proc["id"]
        notes = [sem_senha(proc.get("observacoes"))]
        tipo = (proc.get("tipo_processo") or "").lower()
        number = digits(proc.get("numero_processo"))
        judicial = tipo == "judicial" and len(number) == 20
        sem_cnj = tipo == "judicial" and not judicial
        if sem_cnj and JUDICIAL_SEM_CNJ == "separar":
            # O AdvOS exige CNJ válido em processo judicial ("Judicial cases require a valid CNJ process number").
            # Sem CNJ é porque ainda não foi protocolado: separa para conferência manual depois da migração.
            quarentenados.add(pid)
            pendencia(f"processo {pid}",
                      "judicial sem número CNJ (ainda não protocolado): separado para conferência manual",
                      quarentena=True)
            continue
        dash_status = DASH_STATUS.get(proc.get("status_fase_id") or "")
        status_name = (dash_status or {}).get("nome") or proc.get("status_fase_nome")
        status_ref = None
        if sem_cnj:
            # decisão do escritório: entra como administrativo, com o status judicial numa nota (nunca inventar CNJ)
            notes.append("Processo judicial no AdvogandoDash, ainda sem número CNJ válido"
                         + (f"; número informado: {text(proc.get('numero_processo'))}" if text(proc.get("numero_processo")) else "")
                         + (f"; status no Dash: {status_name}" if status_name else "") + ".")
            pendencia(f"processo {pid}", "judicial sem número CNJ: entrou como administrativo, com o status judicial "
                                         "na nota (decisão do escritório); conferir")
        elif IMPORTAR:
            status_ref = _ref_catalogo("case_status", proc.get("status_fase_id"))
            if status_name and not status_ref:
                notes.append(f"Status no AdvogandoDash: {status_name} (sem correspondente no AdvOS).")
                pendencia(f"processo {pid}", f"status '{status_name}' sem correspondente; ficou o status padrão")
        else:
            status_phase = (dash_status or {}).get("fase") or ("juridico" if tipo == "judicial" else "administrativo")
            status_ctx = ("processo judicial; fase do status no Dash: juridico" if status_phase == "juridico"
                          else "processo administrativo; fase do status no Dash: administrativo")
            status_opts = STATUSES["judicial" if status_phase == "juridico" else "administrative"]
            status_id = decidir("status_processo", status_name, status_opts, status_ctx) if status_name else None
            status_ref = {"id": status_id} if status_id else None
            if status_name and not status_id:
                notes.append(f"Status no AdvogandoDash: {status_name} (sem correspondente no AdvOS).")
                pendencia(f"processo {pid}", f"status '{status_name}' sem correspondente; ficou o status padrão")
        service = DASH_SERVICE.get(proc.get("tipo_servico_id") or "")
        if IMPORTAR:
            service_ref = _ref_catalogo("legal_service_type", proc.get("tipo_servico_id"))
        else:
            service_id = decidir("tipo_servico", service, options("service_types")) if service else None
            service_ref = {"id": service_id} if service_id else None
        if service and not service_ref:
            notes.append(f"Tipo de serviço no AdvogandoDash: {service}.")
            pendencia(f"processo {pid}", f"tipo de serviço '{service}' sem correspondente")
        for money in ("valor_causa", "data_expedicao_rpv", "data_pagamento_efetivo", "valor_beneficio_concedido"):
            if proc.get(money):
                pendencia(f"processo {pid}", f"{money} não migrado (exige credencial finance)")
        responsible = member(proc.get("responsavel_id"))
        if proc.get("responsavel_id") and not responsible:
            pendencia(f"processo {pid}", "responsável do Dash não é membro do escritório no AdvOS")
        order = proc.get("ordem_cronologica")
        trf = text(proc.get("trf_id"))
        pdata = drop_none({
            "process_type": "judicial" if judicial else "administrative",
            "process_number": number if judicial else None,
            "inss_protocol": text(proc.get("numero_processo")) if not judicial and not sem_cnj else None,
            "comarca": text(proc.get("comarca")),
            "judge_name": text(proc.get("juiz_nome")),
            "opposing_party": text(proc.get("parte_contraria")),
            "court_address": text(proc.get("endereco_tribunal")),
            "physical_location": text(proc.get("local_fisico")),
            "court_subsection": text(proc.get("vara_subsecao")),
            "judicial_section": text(proc.get("secao_judiciaria")),
            "state_court": text(proc.get("tribunal_estadual")),
            "cnj_subject": text(proc.get("assunto_cnj")),
            "case_summary": sem_senha(proc.get("resumo_caso")),
            "action_type": text(proc.get("tipo_acao")),
            "trf": trf.upper() if trf and trf.upper() in {"TRF1", "TRF2", "TRF3", "TRF4", "TRF5", "TRF6"} else None,
            "filing_date": as_date(proc.get("data_protocolo")),
            "citation_date": as_date(proc.get("data_citacao_reu")),
            "contestation_date": as_date(proc.get("data_contestacao")),
            "expert_exam_date": as_date(proc.get("data_pericia")),
            "first_instance_sentence_date": as_date(proc.get("data_sentenca_1a_instancia")),
            "inss_appeal_date": as_date(proc.get("data_recurso_inss")),
            "appeal_judgment_date": as_date(proc.get("data_julgamento_recurso")),
            "final_judgment_date": as_date(proc.get("data_transito_julgado")),
            "closed_at": as_datetime(proc.get("data_conclusao")),
            "relation_type": RELATION.get((proc.get("relacao_processo_anterior") or "").lower(),
                                          "other" if proc.get("relacao_processo_anterior") else None),
            "chronological_order": int(order) if str(order or "").isdigit() and int(order) >= 1 else None,
            "notes": "\n".join(n for n in notes if n) or None,
        })
        prefs = {"client_id": {"entity": "client", "externalKey": cid}}
        if status_ref:
            prefs["case_status_id"] = status_ref
        if service_ref:
            prefs["legal_service_type_id"] = service_ref
        if condition_ref:
            prefs["medical_condition_id"] = dict(condition_ref)
        if responsible:
            prefs["assigned_to_id"] = {"id": responsible}
            prefs["responsible_user_id"] = {"id": responsible}
        origin = proc.get("processo_origem_id")
        if origin and origin not in process_ids:
            pendencia(f"processo {pid}", f"processo de origem {origin} não está no pacote do cliente")
        for label, value in (("resumo do processo", proc.get("resumo_caso")), ("observações do processo", proc.get("observacoes"))):
            if value and re.search(r"senha", str(value), re.I):
                pendencia(f"processo {pid}", f"{label}: {SENHA_RETIRADA}" if TIRAR_SENHA else
                          f"{label} contém senha (provável senha do INSS); mover para o campo seguro")
        legal.append({"entity": "legal_case", "externalKey": pid, "data": pdata, "references": prefs})

    # O AdvOS aceita um só derivado de cada tipo por processo de origem: tentativas repetidas
    # sobre a mesma origem viram uma sequência (cada uma aponta para a anterior do mesmo tipo).
    cases = {r["externalKey"]: r for r in legal if r["entity"] == "legal_case"}
    created = {p["id"]: p.get("created_date") or "" for p in processes}
    used = {}
    for proc in sorted(processes, key=lambda p: (created[p["id"]], p["id"])):
        origin = proc.get("processo_origem_id")
        if not origin or origin not in cases or origin == proc["id"] or proc["id"] not in cases:
            continue
        rec = cases[proc["id"]]
        kind = rec["data"]["process_type"]
        target, seen = origin, set()
        while (target, kind) in used and target not in seen:
            seen.add(target)
            target = used[(target, kind)]
        used[(target, kind)] = proc["id"]
        rec["references"]["origin_case_id"] = {"entity": "legal_case", "externalKey": target}
        if target != origin:
            note = f"Origem no AdvogandoDash: processo {origin} (encadeado depois da tentativa anterior)."
            rec["data"]["notes"] = "\n".join(n for n in (rec["data"].get("notes"), note) if n)

    # ---------- andamentos ----------
    for and_ in ents.get("AndamentoProcessual", []):
        if and_.get("processo_id") in quarentenados:
            pendencia(f"andamento {and_['id']}",
                      "andamento de processo judicial sem CNJ: separado junto com o processo",
                      quarentena=True)
            continue
        if and_.get("processo_id") not in process_ids:
            pendencia(f"andamento {and_['id']}", "andamento sem processo no pacote")
            continue
        desc = text(and_.get("descricao")) or " → ".join(
            x for x in (text(and_.get("status_anterior_nome")), text(and_.get("status_novo_nome"))) if x) or None
        when = as_date(and_.get("data_andamento")) or as_date(and_.get("created_date"))
        if not desc or not when:
            pendencia(f"andamento {and_['id']}", "andamento sem descrição ou data")
            continue
        kind = decidir("tipo_andamento", and_.get("tipo_andamento"), PROC_OPTIONS) or "other"
        refs = {"legal_case_id": {"entity": "legal_case", "externalKey": and_["processo_id"]}}
        who = member(and_.get("responsavel_id"))
        if who:
            refs["responsible_user_id"] = {"id": who}
        legal.append({"entity": "proceeding", "externalKey": and_["id"], "data": {
            "type": kind, "description": desc, "event_date": when,
            "visibility": VISIBILITY.get((and_.get("visivel_para") or "todos").lower(), "all")}, "references": refs})

    # ---------- prazos ----------
    for pz in ents.get("PrazoProcessual", []):
        case = pz.get("processo_id")
        if case in quarentenados:
            pendencia(f"prazo {pz['id']}",
                      "prazo de processo judicial sem CNJ: separado junto com o processo",
                      quarentena=True)
            continue
        if case not in process_ids:
            pendencia(f"prazo {pz['id']}", "prazo sem processo no pacote (o AdvOS exige processo)")
            continue
        slug = (pz.get("tipo_prazo") or "").lower()
        if IMPORTAR:  # o prazo guarda o slug do tipo; há prazo antigo com o nome ("Perícia"): normaliza antes
            type_ref = _ref_catalogo("deadline_type", DASH_DEADLINE.get(slug) or DASH_DEADLINE.get(_slug(slug)))
        else:
            type_id = (ADVOS_SLUG.get(slug) or ADVOS_SLUG.get(_slug(slug)) or DEADLINE_BY_SLUG.get(SLUGS.get(slug, slug))
                       or decidir("tipo_prazo", pz.get("tipo_prazo"), options("deadline_types")))
            type_ref = {"id": type_id} if type_id else None
        due = as_date(pz.get("data_vencimento"))
        if not type_ref or not due:
            pendencia(f"prazo {pz['id']}", f"prazo sem tipo correspondente ou sem vencimento ({pz.get('tipo_prazo')})")
            continue
        start, end = text(pz.get("horario_inicio")), text(pz.get("horario_fim"))
        times = {"start_time": start, "end_time": end} if start and end and start < end else {}
        desc = [text(pz.get("descricao"))]
        if start and not times:
            desc.append(f"Horário no Dash: {start}")
        refs = {"legal_case_id": {"entity": "legal_case", "externalKey": case}, "deadline_type_id": type_ref}
        who = member(pz.get("responsavel_id"))
        if who:
            refs["assigned_to_id"] = {"id": who}
        legal.append({"entity": "deadline", "externalKey": pz["id"], "data": drop_none({
            "title": text(pz.get("titulo")) or text(pz.get("tipo_prazo")) or "Prazo",
            "description": "\n".join(d for d in desc if d) or None,
            "due_date": due,
            "status": DEADLINE_STATUS.get((pz.get("status") or "").lower()),
            "priority": PRIORITY.get((pz.get("prioridade") or "").lower()),
            "location": text(pz.get("local_endereco")),
            "expert_name": text(pz.get("perito_juiz_nome")),
            "completed_at": as_datetime(pz.get("data_cumprimento")),
            **times}), "references": refs})

    # ---------- tarefas ----------
    for tk in ents.get("Tarefa", []):
        # Como andamento e prazo: sem isso a tarefa apontaria para um processo que não vai ao AdvOS (nenhum caso na migração de setembro).
        if tk.get("processo_id") in quarentenados:
            pendencia(f"tarefa {tk['id']}", "tarefa de processo judicial sem CNJ: separada junto com o processo",
                      quarentena=True)
            continue
        who = member(tk.get("responsavel_id") or tk.get("atribuido_para_id")) or responsavel_automatica(tk)
        if who == "concluida":
            pendencia(f"tarefa {tk['id']}", "tarefa automática (robô) já concluída: não migrada (decisão do escritório)")
            continue
        if not who:
            pendencia(f"tarefa {tk['id']}", "tarefa sem responsável membro do escritório no AdvOS (o AdvOS exige)")
            continue
        refs = {"client_id": {"entity": "client", "externalKey": cid}, "assigned_to_id": {"id": who}}
        if tk.get("processo_id") in process_ids:
            refs["legal_case_id"] = {"entity": "legal_case", "externalKey": tk["processo_id"]}
        legal.append({"entity": "task", "externalKey": tk["id"], "data": drop_none({
            "title": text(tk.get("titulo")) or "Tarefa", "description": text(tk.get("descricao")),
            "status": TASK_STATUS.get((tk.get("status") or "").lower()),
            "priority": PRIORITY.get((tk.get("prioridade") or "").lower()),
            "due_date": as_date(tk.get("data_vencimento"))}), "references": refs})

    for fin in ("Contrato", "Venda", "TarefaFinanceira", "ReceitaFinanceira", "DespesaFinanceira"):
        if ents.get(fin):
            pendencia(fin, f"{len(ents[fin])} registro(s) de {fin} não migrado(s) (exige credencial finance)")

    # ---------- documentos ----------
    doc_rows = {d["id"]: d for d in ents.get("DocumentoCliente", [])}
    docs = []
    for fd in item.get("fileDescriptors", []):
        row = doc_rows.get(fd.get("sourceRecordId"), {})
        label = fd.get("type") or row.get("tipo_documento")
        docs.append({"descriptor": fd, "client": cid,
                     "case": row.get("processo_id") if row.get("processo_id") in process_ids else None,
                     "documentType": decidir("tipo_documento", label, DOC_OPTIONS) or "other",
                     "dashType": label, "fileName": fd.get("filename") or f"{fd['sourceFileId']}.pdf"})
    described = {fd.get("sourceRecordId") for fd in item.get("fileDescriptors", [])}
    # Arquivo que o Dash referencia mas não entrega (o MCP do Dash põe em quarentena).
    for q in bundle.get("fileQuarantine") or []:
        key = q.get("sourceRecordId") if q.get("sourceEntity") == "DocumentoCliente" else q.get("sourceFileId")
        if q.get("quarantineCode") == "LINK_ONLY":
            if not q.get("sourceLink"):
                pendencia(f"documento {key}", "vídeo de confirmação guardado no Dash sem link permanente — conferir no Dash")
            described.add(key)
            continue
        origem = ("link do Google Drive que só abre logado" if q.get("sourceHost") == "drive.google.com"
                  else f"origem {q.get('sourceHost')}" if q.get("sourceHost")
                  else "o Dash guarda um valor que não é arquivo dele nem link HTTPS")
        pendencia(f"documento {key}", f"arquivo '{q.get('type') or q.get('filename') or '?'}' não baixado do Dash "
                                      f"({origem}; HTTP {q.get('httpStatus', '?')}) — buscar o original e anexar")
        described.add(key)
    for did, row in doc_rows.items():
        if did not in described:
            pendencia(f"documento {did}", f"documento '{row.get('nome_arquivo')}' sem arquivo disponível no pacote")
    if AGUARDANDO:
        pendencia("decisão", "esperando decisão do Claude: " + "; ".join(sorted(set(AGUARDANDO))),
                  aguarda_decisao=True)
    return crm, legal, docs, pend
