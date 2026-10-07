// Reads the text in each image named on the command line with macOS Vision and
// prints one JSON line per image: {"file": <path>, "text": <lines joined by \n>}.
// Any failure exits non-zero; the showcase render then refuses the video,
// because an OCR run that read nothing must never count as a clean one.
//
// Built by the render with `swiftc -O` into its work directory (showcase/render/ocr.py).

import Foundation
import Vision

for path in CommandLine.arguments.dropFirst() {
    let url = URL(fileURLWithPath: path)
    guard FileManager.default.fileExists(atPath: path) else {
        FileHandle.standardError.write("vision_ocr: \(path): no such file\n".data(using: .utf8)!)
        exit(2)
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    // Credentials are not words: never let a language model "correct" them.
    request.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(url: url, options: [:])
    do {
        try handler.perform([request])
    } catch {
        FileHandle.standardError.write("vision_ocr: \(path): \(error)\n".data(using: .utf8)!)
        exit(3)
    }
    let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    let record: [String: String] = ["file": path, "text": lines.joined(separator: "\n")]
    guard let data = try? JSONSerialization.data(withJSONObject: record, options: []) else {
        FileHandle.standardError.write("vision_ocr: \(path): could not encode the result\n".data(using: .utf8)!)
        exit(4)
    }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}
