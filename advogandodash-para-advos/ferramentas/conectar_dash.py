"""Login no MCP do AdvogandoDash para a migração ao AdvOS (OAuth com PKCE e registro dinâmico).
Aceita qualquer escritório liberado para a migração.

Quem roda: a responsável do escritório, no próprio computador. O script:
1. registra um cliente OAuth desta máquina (registro dinâmico; callback local em 127.0.0.1);
2. abre o login do Dash no navegador: entrar com o usuário ADMINISTRADOR do escritório;
3. confere o perfil (admin_escritorio ou admin) e os escopos (só os 4 de leitura; escopo de escrita é recusado);
4. grava os tokens em segredos/dash.json (permissão 600, troca atômica) e o escritório no config.json.
O token nunca aparece na tela nem em log.

Uso:
  python3 conectar_dash.py            login (abre o navegador)
  python3 conectar_dash.py renovar    renova o token (com trava: dois processos renovando juntos derrubam um ao outro)
"""

import base64
import hashlib
import http.server
import json
import os
import pathlib
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402

ISSUER = "https://mcp.advogandodash.com.br"
SCOPES = "read:clientes read:processos read:prazos read:financeiro"
ALLOWED_ROLES = {"admin_escritorio", "admin"}
TRAVA = config.SEGREDOS / ".renovacao.lock"
_LOCK = threading.Lock()

for _name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
    os.environ.pop(_name, None)


def call(url, data=None, headers=None):
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode() or "{}")
        except ValueError:
            body = {}
        return exc.code, {"error": body.get("error") if isinstance(body, dict) else None}


def fail(message):
    print(f"\n[ERRO] {message}")
    sys.exit(1)


def ler():
    return json.loads(config.ler_segredo("dash.json"))


def problemas(claims, cfg):
    out = []
    office = claims.get("escritorio_id")
    if not office:
        out.append("token sem escritório")
    elif cfg.get("dash_office_id") and office != cfg["dash_office_id"]:
        out.append(f"o token é de outro escritório ({office}); esta pasta é do {cfg['dash_office_id']}")
    if claims.get("tipo_usuario") not in ALLOWED_ROLES:
        out.append(f"perfil '{claims.get('tipo_usuario')}' não pode ler a migração (precisa admin_escritorio ou admin)")
    granted = set(str(claims.get("scope", "")).split())
    if granted != set(SCOPES.split()):
        out.append(f"escopos diferentes dos 4 de leitura (escrita é recusada de propósito): {sorted(granted)}")
    return out


def login():
    cfg = config.carregar()
    status, metadata = call(ISSUER + "/.well-known/oauth-authorization-server")
    if status != 200 or not metadata.get("registration_endpoint"):
        fail(f"descoberta OAuth indisponível (HTTP {status})")

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    callback_path = "/callback/" + secrets.token_urlsafe(12)
    received = threading.Event()
    result = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if parsed.path != callback_path or query.get("state", [None])[0] != state:
                self.send_error(400)
                return
            result["code"] = query.get("code", [None])[0]
            result["error"] = query.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Autorização recebida. Pode voltar ao terminal.".encode())
            received.set()

    server = http.server.HTTPServer(("127.0.0.1", 0), Callback)  # porta livre qualquer
    redirect_uri = f"http://127.0.0.1:{server.server_port}{callback_path}"

    # Registro dinâmico (RFC 7591): cliente público desta máquina, sem segredo, só para este callback.
    status, client = call(metadata["registration_endpoint"], json.dumps({
        "client_name": "AdvogandoDash para AdvOS (migração)",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }).encode(), {"Content-Type": "application/json"})
    if status not in (200, 201) or not client.get("client_id"):
        server.server_close()
        fail(f"registro do cliente OAuth recusado (HTTP {status}; {client.get('error') or 'sem detalhe'})")
    client_id = client["client_id"]

    threading.Thread(target=server.serve_forever, daemon=True).start()
    authorize_url = metadata["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": SCOPES,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    print("Abrindo o login do AdvogandoDash no navegador. Entre com o usuário ADMINISTRADOR do escritório.")
    print("Se o navegador não abrir, copie este endereço (ele não tem senha nem token):")
    print(authorize_url, flush=True)
    webbrowser.open(authorize_url)

    if not received.wait(900) or not result.get("code"):
        server.shutdown()
        fail(f"login não concluído ({result.get('error') or 'tempo esgotado: 15 min'})")
    server.shutdown()

    status, tokens = call(metadata["token_endpoint"], urllib.parse.urlencode({
        "grant_type": "authorization_code", "client_id": client_id, "redirect_uri": redirect_uri,
        "code": result["code"], "code_verifier": verifier}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"})
    access_token = tokens.get("access_token")
    if status != 200 or not access_token or not tokens.get("refresh_token"):
        fail(f"troca do código por token falhou (HTTP {status})")
    try:
        claims = config.claims_jwt(access_token)
    except (ValueError, IndexError):
        fail("token recebido não é um JWT legível; nada foi gravado")
    erros = problemas(claims, cfg)
    if erros:
        fail("credencial recusada, nada foi gravado: " + "; ".join(erros))

    config.gravar_segredo("dash.json", json.dumps({
        "access_token": access_token, "refresh_token": tokens["refresh_token"], "client_id": client_id,
        "token_endpoint": metadata["token_endpoint"], "escritorio_id": claims["escritorio_id"],
        "obtido_em": config.agora()}))
    cfg["dash_office_id"] = claims["escritorio_id"]
    config.salvar(cfg)
    access_token = None
    tokens.clear()
    expira = datetime.fromtimestamp(claims["exp"]).strftime("%d/%m %H:%M") if claims.get("exp") else "não expira"
    print("\n[OK] Credencial de leitura do Dash guardada em segredos/dash.json (valor não exibido).")
    print(f"     Perfil: {claims.get('tipo_usuario')} | Escritório (id): {claims['escritorio_id']} | "
          f"Escopos: 4 de leitura | Expira: {expira}")
    print("     Próximo passo: python3 identidade.py")


def renovar(antes=None):
    """Renova com trava de arquivo; se outro processo já renovou (token diferente de `antes`), só reaproveita.
    O refresh token é de uso único: reusar um refresh já trocado derruba a família inteira de tokens."""
    with _LOCK, config.trava(TRAVA):
        dados = ler()
        if antes is not None and dados["access_token"] != antes:
            return False
        status, body = call(dados.get("token_endpoint") or ISSUER + "/oauth/token", urllib.parse.urlencode({
            "grant_type": "refresh_token", "client_id": dados["client_id"],
            "refresh_token": dados["refresh_token"]}).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"})
        if status != 200 or not body.get("access_token") or not body.get("refresh_token"):
            raise SystemExit(f"renovação do token do Dash recusada (HTTP {status}; {body.get('error') or 'sem detalhe'}): "
                             "rode  python3 conectar_dash.py  para entrar de novo")
        claims = config.claims_jwt(body["access_token"])
        if claims.get("escritorio_id") != dados["escritorio_id"]:
            raise SystemExit("o token renovado veio de outro escritório; nada foi gravado")
        config.gravar_segredo("dash.json", json.dumps({**dados, "access_token": body["access_token"],
                                                       "refresh_token": body["refresh_token"],
                                                       "renovado_em": config.agora()}))
        return True


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "renovar":
        config.carregar()
        renovar()
        c = config.claims_jwt(ler()["access_token"])
        print("[OK] token renovado; expira", datetime.fromtimestamp(c["exp"]).strftime("%d/%m %H:%M") if c.get("exp") else "?")
    elif len(sys.argv) == 1:
        login()
    else:
        raise SystemExit(__doc__)
