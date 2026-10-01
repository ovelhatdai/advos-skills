"""Cliente de leitura do MCP do AdvogandoDash.

Token em segredos/dash.json (conectar_dash.py), renovado com trava; nunca impresso.
Uso: python3 dash_mcp.py <ferramenta> '<json>'   |   python3 dash_mcp.py escopos
"""

import itertools
import json
import pathlib
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402

URL = "https://mcp.advogandodash.com.br/mcp"


def token():
    # A renovação regrava o arquivo (troca atômica): tenta de novo antes de desistir (24/09/2026).
    for _tentativa in range(10):
        try:
            return json.loads((config.SEGREDOS / "dash.json").read_text(encoding="utf-8"))["access_token"]
        except (OSError, ValueError, KeyError):
            time.sleep(0.3)
    raise SystemExit("token do Dash ausente: rode  python3 conectar_dash.py")


def claims():
    """Escritório, perfil, escopos e validade do token atual (sem mostrar o token)."""
    return config.claims_jwt(token())


_LOCAL = threading.local()
_IDS = itertools.count(1000)
_IDS_LOCK = threading.Lock()


class _SessionView:
    """Sessão MCP por thread: pedidos simultâneos nunca compartilham sessão."""

    def _d(self):
        if not hasattr(_LOCAL, "session"):
            _LOCAL.session = {}
        return _LOCAL.session

    def __contains__(self, key):
        return key in self._d()

    def __getitem__(self, key):
        return self._d()[key]

    def __setitem__(self, key, value):
        self._d()[key] = value

    def clear(self):
        self._d().clear()


_SESSION = _SessionView()


def _next_id():
    with _IDS_LOCK:
        return next(_IDS)


def _post(payload, session=None):
    headers = {"authorization": f"Bearer {token()}", "content-type": "application/json",
               "accept": "application/json, text/event-stream", "mcp-protocol-version": "2025-03-26"}
    if session:
        headers["mcp-session-id"] = session
    request = urllib.request.Request(URL, data=json.dumps(payload).encode(), method="POST", headers=headers)
    with urllib.request.urlopen(request, timeout=300) as response:
        # leitura com prazo total: SSE que só manda keep-alive não prende o processo
        deadline, chunks = time.time() + 600, []
        while True:
            if time.time() > deadline:
                raise TimeoutError("resposta sem fim dentro do prazo")
            chunk = response.read1(65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode(), response.headers.get("content-type", ""), response.headers.get("mcp-session-id")


def _session():
    if "id" not in _SESSION:
        _, _, sid = _post({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "advogandodash-para-advos", "version": "0.2"}}})
        _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
        _SESSION["id"] = sid
    return _SESSION["id"]


def call(tool, arguments=None):
    request_id = _next_id()
    payload = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": tool, "arguments": arguments or {}}}
    try:
        raw, ctype, _ = _post(payload, _session())
    except urllib.error.HTTPError as error:
        return {"httpError": error.code, "body": error.read().decode()[:500]}
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
        return {"httpError": 599, "body": f"rede: {type(error).__name__}"}
    if ctype.startswith("text/event-stream"):
        msgs = [json.loads(l[5:].strip()) for l in raw.splitlines() if l.startswith("data:") and l[5:].strip()]
        msg = [m for m in msgs if "id" in m][-1]
    else:
        msg = json.loads(raw)
    if msg.get("id") != request_id:
        return {"httpError": 598, "body": f"resposta de outro pedido (id {msg.get('id')} != {request_id})"}
    result = msg.get("result")
    if result is None:
        return msg
    if result.get("structuredContent") is not None:
        data = result["structuredContent"]
        return data.get("result", data) if isinstance(data, dict) and set(data) == {"result"} else data
    texts = [c.get("text") for c in result.get("content", []) if c.get("type") == "text"]
    try:
        return json.loads(texts[0]) if len(texts) == 1 else texts
    except (TypeError, ValueError):
        return texts


if __name__ == "__main__":
    config.carregar()
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    if sys.argv[1] == "escopos":
        c = claims()
        print(c.get("scope") or c.get("scopes"), c.get("tipo_usuario"), c.get("escritorio_id"))
    else:
        print(json.dumps(call(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}), ensure_ascii=False)[:3000])
