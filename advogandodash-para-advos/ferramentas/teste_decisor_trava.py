"""Teste da trava e da cascata do decisor.

O Claude responde enquanto o importador decide. Sem a trava, o decide() regravava a fila lida antes e apagava a
resposta (a versão anterior à trava falhava 4 de 7). Confere também a cascata sem modelo externo: exato, legado, semente
("alta" resolve; "abrir o documento" vai para a fila com a nota), mesmas palavras e família.
Uso: python3 teste_decisor_trava.py   (grava só na pasta dec/ ao lado do script: rodar numa cópia FORA do Drive)
"""
import json
import os
import pathlib
import shutil
import sys
import threading
import time

HERE = pathlib.Path(__file__).parent
D = HERE / "dec"
os.environ["MIGRACAO_ADVOS_HOME"] = str(D / "home")
sys.path.insert(0, str(HERE))
import decisor  # noqa: E402

shutil.rmtree(D, ignore_errors=True)
D.mkdir()
decisor.CACHE, decisor.FILA, decisor.LEGADO, decisor.TRAVA = D / "decisoes.json", D / "fila.json", D / "legado.json", D / ".lock"
decisor.SEMENTE, decisor._SEM = D / "semente.json", None
decisor.SEMENTE.write_text(json.dumps({"rotulos": [
    {"rotulo": "rotulo novo", "chave": "rotulo novo", "tipo": "identity", "confianca": "abrir o documento", "nota": "nota de teste"},
    {"rotulo": "RG E CPF", "chave": "rg e cpf", "tipo": "identity", "confianca": "alta"},
]}))
OPC = [{"value": "identity", "label": "Documento de identificação"}, {"value": "other", "label": "Outro documento"}]


def q(fonte):
    return {"kind": "tipo_documento", "source": fonte, "context": None, "options": OPC}


q_pend, q_novo, q_exato = q("rotulo pendente"), q("rotulo novo"), q("Outro documento")
k_pend = decisor.chave(q_pend)
q_leg = q("rotulo do legado")
decisor.LEGADO.write_text(json.dumps({decisor.chave(q_leg): {"kind": "tipo_documento", "source": "rotulo do legado",
                                                             "context": None, "value": "other", "confidence": 0.9}}))
# estado inicial: um pendente na fila (como o comprovante biométrico)
decisor.CACHE.write_text(json.dumps({k_pend: {**{x: q_pend[x] for x in ("kind", "source", "context")}, "value": None, "confidence": 0.0, "origem": "claude-pendente"}}))
decisor.FILA.write_text(json.dumps({k_pend: {"kind": "tipo_documento", "source": "rotulo pendente", "context": None, "options": OPC}}))

# janela: o importador demora dentro do decide() enquanto o Claude responde
_indice_original = decisor._indice


def indice_lento(*a):
    time.sleep(1.5)
    return _indice_original(*a)


decisor._indice = indice_lento
res = {}


def importador():
    res["out"] = decisor.decide([q_pend, q_novo, q_exato])


t = threading.Thread(target=importador)
t.start()
time.sleep(0.5)
decisor.responder(k_pend, "other")      # o Claude responde no meio do decide()
t.join()
decisor._indice = _indice_original
cache, fila = json.loads(decisor.CACHE.read_text()), json.loads(decisor.FILA.read_text())
ok = []
ok.append(("resposta do Claude sobreviveu", cache[k_pend]["value"] == "other" and cache[k_pend]["origem"] == "claude"))
ok.append(("pendente respondido saiu da fila", k_pend not in fila))
item_novo = fila.get(decisor.chave(q_novo), {})
ok.append(("rótulo 'abrir o documento' foi para a fila com a nota da semente",
           (item_novo.get("semente") or {}).get("nota") == "nota de teste" and cache[decisor.chave(q_novo)]["value"] is None))
ok.append(("rótulo idêntico resolvido sozinho", cache[decisor.chave(q_exato)]["value"] == "other"))
ok.append(("decide devolveu 3 respostas", len(res["out"]) == 3))
# segunda rodada: o importador vê a decisão do Claude e não repõe na fila
out2 = decisor.decide([q_pend])
ok.append(("segunda rodada usa a decisão do Claude", out2[0]["applied"] == "other" and out2[0]["status"] == "ok"))
ok.append(("segunda rodada não repõe na fila", k_pend not in json.loads(decisor.FILA.read_text())))
# terceira rodada: variação só de palavras vazias/nome mascarado reaproveita a decisão; palavra a mais não
q_var, q_dif = q("ROTULO PENDENTE [nome]"), q("rotulo pendente assinado")
out3 = decisor.decide([q_var, q_dif])
ok.append(("variação com nome mascarado reaproveita a decisão", out3[0]["applied"] == "other" and out3[0].get("origem") == "mesmo-rotulo-palavras"))
ok.append(("rótulo com palavra a mais vai para o Claude", out3[1]["status"] == "claude"))
# quarta rodada (24/09): testemunha com o nome herda a decisão da família; família em conflito vai para o Claude
cache = json.loads(decisor.CACHE.read_text())
for fonte, valor in (("TESTEMUNHA 1", "other"), ("video testemunha 1", "other"), ("VÍDEO TESTEMUNHA 2", "identity")):
    cache[decisor.chave(q(fonte))] = {"kind": "tipo_documento", "source": fonte, "context": None, "value": valor, "confidence": 1.0, "origem": "claude"}
decisor.CACHE.write_text(json.dumps(cache))
out4 = decisor.decide([q("TESTEMUNHA 2 FULANA"), q("Vídeo testemunha 3 [nome]"), q("testemunhas depoimento")])
ok.append(("testemunha com nome herda a decisão da família", out4[0]["applied"] == "other" and out4[0].get("origem") == "familia-rotulo"))
ok.append(("família com decisões diferentes vai para o Claude", out4[1]["status"] == "claude"))
ok.append(("'testemunhas ...' não entra na família 'testemunha'", out4[2]["status"] == "claude"))
# quinta rodada (kit genérico): semente "alta" resolve, inclusive com outra grafia; legado resolve pela chave
out5 = decisor.decide([q("RG e CPF"), q("rg  cpf"), q_leg])
ok.append(("semente 'alta' resolve sozinha", out5[0]["applied"] == "identity" and out5[0].get("origem") == "semente"))
ok.append(("semente pelas mesmas palavras resolve", out5[1]["applied"] == "identity" and out5[1].get("origem") == "semente"))
ok.append(("legado resolve pela chave da pergunta", out5[2]["applied"] == "other" and out5[2].get("origem") == "legado"))
decisor.responder(out5[0]["chave"], "other")
ok.append(("decisão do Claude prevalece sobre a semente", decisor.decide([q("RG e CPF")])[0]["applied"] == "other"))
try:
    decisor.responder(decisor.chave(q("rotulo pendente assinado")), "valor_inexistente")
    ok.append(("responder recusa valor fora das opções", False))
except SystemExit:
    ok.append(("responder recusa valor fora das opções", "rotulo pendente assinado" in json.dumps(json.loads(decisor.FILA.read_text()))))
for nome, passou in ok:
    print(("🟢" if passou else "🔴"), nome)
if all(p for _, p in ok):
    shutil.rmtree(D, ignore_errors=True)
sys.exit(0 if all(p for _, p in ok) else 1)
