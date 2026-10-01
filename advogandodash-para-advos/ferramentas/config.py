"""Configuração do kit AdvogandoDash → AdvOS: pasta de trabalho, config.json, segredos e lotes.

A pasta de trabalho (~/migracao-advos, ou MIGRACAO_ADVOS_HOME) guarda dado de cliente: fica FORA de pasta
sincronizada (Google Drive, iCloud, OneDrive, Dropbox). O kit se recusa a rodar lá.

Uso:
  python3 config.py iniciar <escritorio>        cria a pasta, as subpastas e o config.json (escritorio = apelido curto,
                                                ex.: silva-adv; vira o namespace advogandodash-<escritorio> no AdvOS)
  python3 config.py mostrar                     configuração e situação das credenciais (nenhum segredo aparece)
  python3 config.py definir <opção> '<json>'    muda uma decisão do escritório (ex.: definir judicial_sem_cnj '"administrativo"')
  python3 config.py guardar advos-import        guarda a credencial de importação do AdvOS (digitada escondida, no Terminal)
  python3 config.py guardar advos-leitura       guarda a chave de leitura advos_sk_ (opcional, para catalogos_advos.py)
"""

import base64
import contextlib
import getpass
import json
import os
import pathlib
import re
import secrets
import shutil
import sys
import threading
from datetime import datetime, timedelta, timezone

HOME = pathlib.Path(os.environ.get("MIGRACAO_ADVOS_HOME") or "~/migracao-advos").expanduser()
CONFIG = HOME / "config.json"
SEGREDOS = HOME / "segredos"
REFERENCIA = HOME / "referencia"
LOTES = HOME / "lotes"
DECISOES = HOME / "decisoes"
SP = timezone(timedelta(hours=-3))

# Contrato v6 do MCP do Dash, em uso desde 24/09/2026. Um contrato novo entra pelo config.json ("contrato_hash")
# quando for publicado.
CONTRATO_V6 = "af0671f349ee71f1d2013a8c81027fbc4411f825c0d3ae9e0b308afa85208472"

PADRAO = {
    "escritorio": None,
    "namespace": None,
    "dash_office_id": None,
    "dash_office_nome": None,
    "advos_org_id": None,
    "contrato_hash": CONTRATO_V6,
    # Decisões do escritório (SKILL.md, "Decisões do escritório"):
    "judicial_sem_cnj": "separar",          # "separar" para conferência manual | "administrativo" com o status judicial numa nota
    "tirar_senha_das_observacoes": True,    # linha com "senha" não vai para o AdvOS; vira pendência
    "tarefas_automaticas": [],              # [{"prefixos": ["título começa com..."], "abertas_para": "e-mail ou userId"}]
    "catalogos": "casar",                   # "casar" com o catálogo do AdvOS | "importar" o catálogo do escritório
}
ESCOLHAS = {"judicial_sem_cnj": ("separar", "administrativo"), "catalogos": ("casar", "importar")}
SEGREDOS_CONHECIDOS = {"advos-import": ("advos-import.txt", "advos_imp_"), "advos-leitura": ("advos-leitura.txt", "advos_sk_")}

# Pasta sincronizada pelo caminho real. Lição da migração de setembro: dado de cliente no Drive é o que não pode acontecer.
NUVEM = ("cloudstorage", "google drive", "googledrive", "mobile documents", "icloud", "onedrive", "dropbox")


def na_nuvem(caminho):
    real = str(pathlib.Path(caminho).expanduser().resolve()).lower() + "/"
    if any(m in real for m in NUVEM):
        return True
    # iCloud "Mesa e Documentos" não aparece no caminho: ~/Desktop e ~/Documents contam como nuvem quando o iCloud
    # guarda essas pastas.
    casa = pathlib.Path.home()
    icloud = casa / "Library/Mobile Documents/com~apple~CloudDocs"
    for pasta in ("Desktop", "Documents"):
        base = str((casa / pasta).resolve()).lower() + "/"
        if real.startswith(base) and (icloud / pasta).exists():
            return True
    return False


def garantir_fora_da_nuvem():
    if na_nuvem(HOME):
        raise SystemExit(f"🔴 a pasta de trabalho {HOME} está numa pasta sincronizada (nuvem). Ela guarda dado de "
                         "cliente: use uma pasta local, ex.: MIGRACAO_ADVOS_HOME=~/migracao-advos")


def agora():
    """Horário de relatório vem do relógio, nunca de estimativa (armadilha de operação 7)."""
    return datetime.now(SP).isoformat(timespec="seconds")


def escrever_json(caminho, obj, modo=None, indent=1):
    """Troca atômica: quem lê nunca pega o arquivo pela metade (achado de 24/09/2026 no token do Dash)."""
    caminho = pathlib.Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(f"{caminho.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, modo or 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent)
    os.replace(tmp, caminho)
    if modo:
        os.chmod(caminho, modo)


def carregar(exigir=True):
    garantir_fora_da_nuvem()
    if not CONFIG.exists():
        if exigir:
            raise SystemExit(f"falta {CONFIG}: rode antes  python3 config.py iniciar <escritorio>")
        return dict(PADRAO)
    return {**PADRAO, **json.loads(CONFIG.read_text(encoding="utf-8"))}


def salvar(cfg):
    escrever_json(CONFIG, cfg)


# ---------- segredos (permissão 600, pasta 700; nunca impressos) ----------

def gravar_segredo(nome, conteudo):
    SEGREDOS.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(SEGREDOS, 0o700)
    destino = SEGREDOS / nome
    tmp = destino.with_name(f"{destino.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(conteudo)
    os.replace(tmp, destino)
    os.chmod(destino, 0o600)


def ler_segredo(nome):
    caminho = SEGREDOS / nome
    if not caminho.exists():
        raise SystemExit(f"credencial ausente: {caminho} (veja o LEIA-ME)")
    return caminho.read_text(encoding="utf-8").strip()


def claims_jwt(token):
    """Lê as declarações do JWT (escritório, perfil, escopos, validade) sem mostrar o token."""
    parte = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(parte + "=" * (-len(parte) % 4)))


@contextlib.contextmanager
def trava(caminho):
    """Trava de arquivo entre processos (fcntl: macOS e Linux)."""
    try:
        import fcntl
    except ImportError:
        raise SystemExit("a trava de arquivo do kit exige macOS ou Linux") from None
    caminho = pathlib.Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ---------- lotes ----------

NOME_LOTE = re.compile(r"[a-z0-9][a-z0-9-]{0,23}")


def lote(nome, criar=False):
    """Pasta e ficha do lote. O prefixo das chaves de envio é o nome + um id próprio do lote: prefixo repetido faz o
    AdvOS devolver o job antigo ("replay") sem importar ninguém (trava do leva.py de setembro de 2026). Devolve (pasta, ficha)."""
    if not NOME_LOTE.fullmatch(nome or ""):
        raise SystemExit("nome de lote: letras minúsculas, números e hífen, até 24 caracteres (ex.: piloto, lote-01)")
    carregar()
    pasta, registro_f = LOTES / nome, LOTES / "prefixos.json"
    registro = json.loads(registro_f.read_text(encoding="utf-8")) if registro_f.exists() else {}
    ficha_f = pasta / "lote.json"
    if ficha_f.exists():
        ficha = json.loads(ficha_f.read_text(encoding="utf-8"))
        if (registro.get(nome) or {}).get("id") != ficha.get("id"):
            raise SystemExit(f"🔴 lote {nome}: a ficha não confere com lotes/prefixos.json (pasta recriada?). "
                             "Não continuo: prefixo repetido faz o AdvOS devolver o job antigo. Use outro nome de lote.")
        return pasta, ficha
    if nome in registro:
        raise SystemExit(f"🔴 o nome de lote '{nome}' já foi usado (prefixo {registro[nome]['prefixo']}). Use outro nome.")
    if not criar:
        raise SystemExit(f"lote {nome} não existe: crie com  python3 inventario.py alvos {nome} ...")
    id_ = secrets.token_hex(3)
    ficha = {"nome": nome, "id": id_, "prefixo": f"{nome}-{id_}", "criado_em": agora(), "proxima_onda": 1}
    (pasta / "pacotes").mkdir(parents=True, exist_ok=True)
    escrever_json(ficha_f, ficha)
    registro[nome] = {"id": id_, "prefixo": ficha["prefixo"], "criado_em": ficha["criado_em"]}
    escrever_json(registro_f, registro)
    return pasta, ficha


def salvar_lote(pasta, ficha):
    escrever_json(pathlib.Path(pasta) / "lote.json", ficha)


def achar_chrome():
    """Chrome local para imprimir em PDF o documento que o Dash gerou em HTML (macOS; caminhos comuns do Windows)."""
    candidatos = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        str(pathlib.Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    if os.environ.get("LOCALAPPDATA"):
        candidatos.append(os.path.join(os.environ["LOCALAPPDATA"], r"Google\Chrome\Application\chrome.exe"))
    for c in candidatos:
        if os.path.isfile(c):
            return c
    return shutil.which("google-chrome") or shutil.which("chromium")


# ---------- linha de comando ----------

def _iniciar(escritorio):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,29}", escritorio or ""):
        raise SystemExit("escritorio: apelido curto com letras minúsculas, números e hífen (até 30), ex.: silva-adv")
    garantir_fora_da_nuvem()
    if sys.version_info < (3, 11):
        raise SystemExit("o kit pede Python 3.11 ou mais novo")
    for p in (HOME, REFERENCIA, LOTES, DECISOES):
        p.mkdir(parents=True, exist_ok=True)
    SEGREDOS.mkdir(mode=0o700, exist_ok=True)
    os.chmod(SEGREDOS, 0o700)
    cfg = carregar(exigir=False)
    if cfg.get("escritorio") and cfg["escritorio"] != escritorio:
        raise SystemExit(f"esta pasta já é do escritório '{cfg['escritorio']}': um escritório por pasta "
                         "(use outra MIGRACAO_ADVOS_HOME)")
    cfg.update(escritorio=escritorio, namespace=f"advogandodash-{escritorio}")
    salvar(cfg)
    print(f"🟢 pasta de trabalho: {HOME} (fora da nuvem)")
    print(f"   escritório: {escritorio} | namespace no AdvOS: {cfg['namespace']}")
    print(f"   Python {sys.version.split()[0]} | Chrome: {'encontrado' if achar_chrome() else 'NÃO encontrado (documentos em HTML viram pendência)'}")


def _mostrar():
    cfg = carregar()
    print(json.dumps(cfg, ensure_ascii=False, indent=1))
    for nome in ("dash.json", "advos-import.txt", "advos-leitura.txt"):
        f = SEGREDOS / nome
        if not f.exists():
            print(f"segredos/{nome}: ausente")
            continue
        modo = oct(f.stat().st_mode & 0o777)
        extra = ""
        if nome == "dash.json":
            try:
                c = claims_jwt(json.loads(f.read_text(encoding="utf-8"))["access_token"])
                extra = (f" | escritório {c.get('escritorio_id')} | perfil {c.get('tipo_usuario')} | expira "
                         f"{datetime.fromtimestamp(c['exp']).strftime('%d/%m %H:%M') if c.get('exp') else '?'}")
            except (ValueError, KeyError, IndexError):
                extra = " | ilegível: rode conectar_dash.py"
        print(f"segredos/{nome}: presente (permissão {modo}){extra}")


def _definir(opcao, valor_json):
    cfg = carregar()
    valor = json.loads(valor_json)
    if opcao in ESCOLHAS:
        if valor not in ESCOLHAS[opcao]:
            raise SystemExit(f"{opcao}: use um de {ESCOLHAS[opcao]}")
    elif opcao == "tirar_senha_das_observacoes":
        if not isinstance(valor, bool):
            raise SystemExit("tirar_senha_das_observacoes: true ou false")
    elif opcao == "tarefas_automaticas":
        ok = isinstance(valor, list) and all(
            isinstance(r, dict) and isinstance(r.get("prefixos"), list) and r["prefixos"]
            and all(isinstance(p, str) and p for p in r["prefixos"]) and isinstance(r.get("abertas_para"), str)
            for r in valor)
        if not ok:
            raise SystemExit('tarefas_automaticas: [{"prefixos": ["título começa com..."], "abertas_para": "e-mail ou userId"}]')
    elif opcao == "contrato_hash":
        if not re.fullmatch(r"[0-9a-f]{64}", str(valor)):
            raise SystemExit("contrato_hash: 64 caracteres hexadecimais (vem do whoami do Dash)")
    else:
        raise SystemExit("opções: judicial_sem_cnj, tirar_senha_das_observacoes, tarefas_automaticas, catalogos, contrato_hash")
    cfg[opcao] = valor
    salvar(cfg)
    print(f"🟢 {opcao} gravado")


def _guardar(qual):
    if qual not in SEGREDOS_CONHECIDOS:
        raise SystemExit(f"guardar: {' ou '.join(SEGREDOS_CONHECIDOS)}")
    carregar()
    nome, prefixo = SEGREDOS_CONHECIDOS[qual]
    valor = getpass.getpass("Cole a credencial (ela não aparece na tela) e tecle Enter: ").strip()
    if not valor.startswith(prefixo):
        raise SystemExit(f"isso não parece a credencial certa (ela começa com {prefixo}); nada foi gravado")
    gravar_segredo(nome, valor)
    print(f"🟢 guardada em segredos/{nome} (permissão 600)")


if __name__ == "__main__":
    comando = sys.argv[1] if len(sys.argv) > 1 else "mostrar"
    if comando == "iniciar" and len(sys.argv) == 3:
        _iniciar(sys.argv[2])
    elif comando == "mostrar":
        _mostrar()
    elif comando == "definir" and len(sys.argv) == 4:
        _definir(sys.argv[2], sys.argv[3])
    elif comando == "guardar" and len(sys.argv) == 3:
        _guardar(sys.argv[2])
    else:
        raise SystemExit(__doc__)
