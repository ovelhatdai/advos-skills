// OCR local com o Vision do macOS, sem rede e sem instalar nada.
// Serve para a fila de decisão do Claude: rótulo ambíguo + documento escaneado.
// Uso: DEVELOPER_DIR=/Library/Developer/CommandLineTools swift ocr_local.swift <arquivo> [páginas=3] [ocr]
//   imagem → texto reconhecido (pt-BR)
//   PDF    → texto do próprio PDF; se vier quase vazio (escaneado) ou com "ocr", desenha até N páginas e reconhece
// Nunca imprimir o texto na conversa: quem chama (espiar_documento.py) só conta palavras-chave e apaga o arquivo.
import AppKit
import Foundation
import PDFKit
import Vision

// Fundo branco antes do OCR: PNG com transparência vira texto preto sobre preto para o Vision (teste de 01/10/2026).
func sobreBranco(_ cg: CGImage) -> CGImage {
    guard let ctx = CGContext(data: nil, width: cg.width, height: cg.height, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
    else { return cg }
    let area = CGRect(x: 0, y: 0, width: cg.width, height: cg.height)
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(area)
    ctx.draw(cg, in: area)
    return ctx.makeImage() ?? cg
}

func reconhecer(_ cg: CGImage) -> String {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["pt-BR"]
    try? VNImageRequestHandler(cgImage: sobreBranco(cg), options: [:]).perform([req])
    return (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

let args = CommandLine.arguments
guard args.count > 1 else { print("uso: swift ocr_local.swift <arquivo> [páginas] [ocr]"); exit(2) }
let url = URL(fileURLWithPath: args[1])
let paginas = args.count > 2 ? (Int(args[2]) ?? 3) : 3
let forcar = args.count > 3 && args[3] == "ocr"
let ehPDF = (try? FileHandle(forReadingFrom: url).readData(ofLength: 4)) == Data("%PDF".utf8)

if ehPDF, let pdf = PDFDocument(url: url) {
    let texto = pdf.string ?? ""
    if !forcar && texto.trimmingCharacters(in: .whitespacesAndNewlines).count >= 40 {
        print(texto)
        exit(0)
    }
    for i in 0..<min(paginas, pdf.pageCount) {
        guard let pagina = pdf.page(at: i) else { continue }
        let caixa = pagina.bounds(for: .mediaBox)
        let escala: CGFloat = 150.0 / 72.0  // 150 dpi, como o pdftoppm -r 150 da versão anterior
        let imagem = pagina.thumbnail(of: NSSize(width: caixa.width * escala, height: caixa.height * escala), for: .mediaBox)
        if let cg = imagem.cgImage(forProposedRect: nil, context: nil, hints: nil) { print(reconhecer(cg)) }
    }
    exit(0)
}
guard let img = NSImage(contentsOf: url), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("arquivo inválido")
    exit(1)
}
print(reconhecer(cg))
