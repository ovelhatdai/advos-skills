"""Fila de decisão: abre UM documento de um rótulo ambíguo ("abrir o documento" na semente) e conta palavras-chave
por tipo, sem imprimir o texto (pode ter nome, CPF, dado de saúde).

O arquivo vem pelo ticket do Dash (carga.baixar_arquivo), fica num temporário DENTRO da pasta de trabalho e é apagado
no fim. Texto: PDF pelo próprio PDF (PDFKit) e, se for escaneado, OCR nativo do macOS (ocr_local.swift); DOCX/ODT
pelo XML interno. Sem rede além do Dash e sem instalar nada.
Uso: python3 espiar_documento.py <lote | pasta de pacotes> "<rótulo exato>" [termo1,termo2,...]
ESPIAR_OCR=1 força o OCR mesmo com texto (PDF com carimbo em texto e corpo em imagem).
"""

import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402

TIPOS = {
    "proof_of_address": ["conta de", "fatura", "energia", "consumo", "kwh", "leitura", "cep", "residencia", "endereco", "agua", "saneamento"],
    "contract": ["contrato", "contratante", "contratad", "clausula", "honorario", "prestacao de servico"],
    "inss_protocolo": ["protocolo", "requerimento", "inss", "meu inss", "agendamento", "servico solicitado"],
    "letter_inss": ["comunicado", "decisao", "indeferi", "concessao", "carta de", "exigencia"],
    "identity": ["registro geral", "carteira de identidade", "filiacao", "naturalidade", "habilitacao", "titulo de eleitor"],
    "medical_report": ["cid", "laudo", "medic", "crm", "diagnostic", "atestado", "exame"],
    "court_document": ["processo", "juizo", "vara", "sentenca", "excelentissim", "autor", "reu"],
    "pagamento": ["pix", "pagamento", "transferencia", "valor", "banco", "agencia", "comprovante de pagamento"],
    "rural": ["rural", "sindicato", "agricultor", "itr", "produtor", "imovel rural"],
    "trabalho": ["ctps", "empregador", "admissao", "demissao", "rescisao", "salario", "cnis", "vinculo"],
}


def norm(s):
    return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()


def texto_do_arquivo(f, raw, forcar_ocr=False):
    """Texto para contagem (nunca impresso). DOCX/ODT pelo XML; PDF e imagem pelo ocr_local.swift."""
    if raw[:2] == b"PK":  # docx/odt: o texto está no XML interno (24/09/2026)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xml = next((n for n in ("word/document.xml", "content.xml") if n in z.namelist()), None)
            return re.sub(r"<[^>]+>", " ", z.read(xml).decode("utf-8", "ignore")) if xml else ""
    env = dict(os.environ, DEVELOPER_DIR=os.environ.get("DEVELOPER_DIR", "/Library/Developer/CommandLineTools"))
    cmd = ["swift", str(HERE / "ocr_local.swift"), str(f), "3"] + (["ocr"] if forcar_ocr else [])
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    if r.returncode != 0:  # erro do swift (compilação, permissão): sem texto do documento na mensagem
        raise SystemExit(f"OCR local falhou (código {r.returncode}): {(r.stderr or '').strip().splitlines()[:1]}")
    return r.stdout


def main(origem, rotulo, extras=None):
    config.carregar()
    from carga import baixar_arquivo, sniff  # noqa: E402  (download pelo ticket do Dash, com renovação do token)
    pasta = pathlib.Path(origem) if pathlib.Path(origem).is_dir() else config.lote(origem)[0] / "pacotes"
    if extras:  # termos extras, separados por vírgula, contados à parte
        TIPOS["extra"] = [norm(x.strip()) for x in extras.split(",") if x.strip()]
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="espiar-", dir=config.HOME))
    try:
        pkg = it = did = None
        for pf in sorted(pasta.glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True):
            cand = json.loads(pf.read_text())
            d = next((d for d in cand["items"][0]["bundle"]["entities"].get("DocumentoCliente", [])
                      if str(d.get("tipo_documento") or "").strip().lower() == rotulo.strip().lower()), None)
            if d:
                pkg, it, did = cand, cand["items"][0], d["id"]
                break
        if not pkg:
            raise SystemExit("rótulo não encontrado nos pacotes")
        fd = next((d for d in it.get("fileDescriptors", []) if did in (d.get("sourceRecordId"), d.get("sourceFileId"))), None)
        if not fd:
            raise SystemExit("descritor do arquivo não encontrado no pacote (documento em quarentena?)")
        raw, err = baixar_arquivo(fd, pkg)
        if err:
            raise SystemExit(f"download: {err}")
        print("tipo real:", sniff(raw), "| tamanho:", len(raw))
        f = tmp / ("doc.pdf" if raw[:4] == b"%PDF" else "doc")
        f.write_bytes(raw)
        texto = texto_do_arquivo(f, raw, bool(os.environ.get("ESPIAR_OCR")))
        t = norm(texto)
        print("caracteres de texto:", len(t))
        for k, termos in TIPOS.items():
            n = {w: t.count(w) for w in termos if t.count(w)}
            print(f"  {k:16} {sum(n.values()):4}  {n}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print("temporário apagado:", not tmp.exists())


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:4])
