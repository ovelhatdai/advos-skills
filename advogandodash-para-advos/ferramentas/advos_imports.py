"""Cliente mínimo do MCP de importação do AdvOS (/mcp/imports).

Credencial em segredos/advos-import.txt (python3 config.py guardar advos-import); nunca impressa. Uso:
  python3 advos_imports.py tools/list
  python3 advos_imports.py <ferramenta> '<json de argumentos>'
  python3 advos_imports.py <ferramenta> @arquivo.json
"""

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import config  # noqa: E402

URL = "https://api.advos.ai/mcp/imports"


def read_bounded(response, seconds):
    """Lê a resposta com prazo total: SSE que só manda keep-alive não prende o processo."""
    deadline, chunks = time.time() + seconds, []
    while True:
        if time.time() > deadline:
            raise TimeoutError("resposta sem fim dentro do prazo")
        chunk = response.read1(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def rpc(method, params, _retry=0):
    token = config.ler_segredo("advos-import.txt")
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(
        URL,
        data=body,
        method="POST",
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": "2025-03-26",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = read_bounded(response, 240).decode()
            content_type = response.headers.get("content-type", "")
    except urllib.error.HTTPError as error:
        if error.code in (429, 502, 503, 504) and _retry < 6:
            time.sleep(10 * (_retry + 1))
            return rpc(method, params, _retry + 1)
        return {"httpError": error.code, "body": error.read().decode()[:2000]}
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        if _retry < 6:
            time.sleep(10 * (_retry + 1))
            return rpc(method, params, _retry + 1)
        raise
    if content_type.startswith("text/event-stream"):
        messages = [
            json.loads(line[5:].strip())
            for line in raw.splitlines()
            if line.startswith("data:") and line[5:].strip()
        ]
        return [m for m in messages if "id" in m][-1]
    return json.loads(raw)


def call(tool, arguments=None):
    message = rpc("tools/call", {"name": tool, "arguments": arguments or {}})
    result = message.get("result") if isinstance(message, dict) else None
    if result is None:
        return message
    if result.get("structuredContent") is not None:
        return {"isError": bool(result.get("isError")), "data": result["structuredContent"]}
    texts = [c.get("text") for c in result.get("content", []) if c.get("type") == "text"]
    parsed = []
    for text in texts:
        try:
            parsed.append(json.loads(text))
        except (TypeError, ValueError):
            parsed.append(text)
    return {"isError": bool(result.get("isError")), "data": parsed[0] if len(parsed) == 1 else parsed}


if __name__ == "__main__":
    config.carregar()
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    name = sys.argv[1]
    if name == "tools/list":
        output = rpc("tools/list", {})
        output = [t["name"] for t in output.get("result", {}).get("tools", [])] if "result" in output else output
    else:
        raw_args = sys.argv[2] if len(sys.argv) > 2 else "{}"
        if raw_args.startswith("@"):
            raw_args = pathlib.Path(raw_args[1:]).read_text()
        output = call(name, json.loads(raw_args))
    print(json.dumps(output, ensure_ascii=False, indent=1))
