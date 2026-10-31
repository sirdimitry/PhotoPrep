import SwiftUI
import AppKit

struct BrushCanvas: NSViewRepresentable {
    let image: CGImage?
    let strokes: [MaskStroke]
    let tool: RetouchTool
    let brushWidth: Double
    let showMask: Bool
    let onCommit: (MaskStroke) -> Void

    func makeNSView(context: Context) -> BrushCanvasView {
        let view = BrushCanvasView()
        view.onCommit = onCommit
        return view
    }

    func updateNSView(_ view: BrushCanvasView, context: Context) {
        view.image = image
        view.strokes = strokes
        view.tool = tool
        view.brushWidth = brushWidth
        view.showMask = showMask
        view.onCommit = onCommit
        view.needsDisplay = true
    }
}

final class BrushCanvasView: NSView {
    var image: CGImage?
    var strokes: [MaskStroke] = []
    var tool: RetouchTool = .brush
    var brushWidth: Double = 0.06
    var showMask = true
    var onCommit: ((MaskStroke) -> Void)?
    private var currentStroke: MaskStroke?

    override var acceptsFirstResponder: Bool { true }

    private var imageRect: CGRect {
        guard let image, image.width > 0, image.height > 0 else { return .zero }
        let available = bounds.insetBy(dx: 4, dy: 4)
        guard available.width > 0, available.height > 0 else { return .zero }
        let scale = min(available.width / CGFloat(image.width), available.height / CGFloat(image.height))
        let size = CGSize(width: CGFloat(image.width) * scale, height: CGFloat(image.height) * scale)
        return CGRect(x: bounds.midX - size.width / 2, y: bounds.midY - size.height / 2, width: size.width, height: size.height)
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.underPageBackgroundColor.setFill()
        bounds.fill()
        guard let image, image.width > 0, image.height > 0 else { return }
        let rect = imageRect
        guard rect.width > 0, rect.height > 0 else { return }
        NSGraphicsContext.current?.imageInterpolation = .high
        NSImage(cgImage: image, size: NSSize(width: image.width, height: image.height))
            .draw(in: rect, from: .zero, operation: .sourceOver, fraction: 1.0)

        guard showMask else { return }
        var visible = strokes
        if let currentStroke { visible.append(currentStroke) }
        guard !visible.isEmpty, let context = NSGraphicsContext.current?.cgContext else { return }
        let maskWidth = max(1, Int(rect.width.rounded()))
        let maskHeight = max(1, Int(rect.height.rounded()))
        let mask = MaskRenderer.render(width: maskWidth, height: maskHeight, strokes: visible)
        guard let maskImage = Self.grayImage(mask, width: maskWidth, height: maskHeight) else { return }
        context.saveGState()
        context.clip(to: rect, mask: maskImage)
        NSColor.systemYellow.withAlphaComponent(0.35).setFill()
        rect.fill()
        context.restoreGState()
    }

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: .crosshair)
    }

    private func normalizedPoint(_ event: NSEvent) -> MaskPoint? {
        let rect = imageRect
        guard rect.width > 0, rect.height > 0 else { return nil }
        let point = convert(event.locationInWindow, from: nil)
        guard rect.contains(point) else { return nil }
        return MaskPoint(
            x: Double((point.x - rect.minX) / rect.width),
            y: Double(1.0 - (point.y - rect.minY) / rect.height)
        )
    }

    override func mouseDown(with event: NSEvent) {
        guard image != nil, let point = normalizedPoint(event) else { return }
        window?.makeFirstResponder(self)
        currentStroke = MaskStroke(points: [point], width: brushWidth, erase: tool == .eraser)
        needsDisplay = true
    }

    override func mouseDragged(with event: NSEvent) {
        guard var stroke = currentStroke, let point = normalizedPoint(event) else { return }
        if let last = stroke.points.last {
            let dx = point.x - last.x
            let dy = point.y - last.y
            if dx * dx + dy * dy < 0.000004 { return }
        }
        stroke.points.append(point)
        currentStroke = stroke
        needsDisplay = true
    }

    override func mouseUp(with event: NSEvent) {
        defer {
            currentStroke = nil
            needsDisplay = true
        }
        guard let stroke = currentStroke, !stroke.points.isEmpty else { return }
        onCommit?(stroke)
    }

    private static func grayImage(_ bytes: [UInt8], width: Int, height: Int) -> CGImage? {
        guard width > 0, height > 0, bytes.count == width * height,
              let provider = CGDataProvider(data: Data(bytes) as CFData) else { return nil }
        return CGImage(
            width: width,
            height: height,
            bitsPerComponent: 8,
            bitsPerPixel: 8,
            bytesPerRow: width,
            space: CGColorSpaceCreateDeviceGray(),
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
        )
    }
}

struct RetouchPanel: View {
    @ObservedObject var model: WorkspaceModel
    let language: String
    private var ru: Bool { language == "ru" }
    private func text(_ russian: String, _ english: String) -> String { ru ? russian : english }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(text("Ретушь", "Retouch"), systemImage: "paintbrush.pointed").font(.headline)
            Text(text("Удаление логотипов и восстановление фона",
                      "Logo removal and background restoration")).font(.subheadline)
            Picker("", selection: $model.tool) {
                Text(text("Кисть", "Brush")).tag(RetouchTool.brush)
                Text(text("Ластик", "Eraser")).tag(RetouchTool.eraser)
            }.pickerStyle(.segmented)
            HStack {
                Text(text("Размер", "Size")).font(.caption)
                Slider(value: $model.brushWidth, in: 0.01...0.25)
            }
            HStack {
                Button(text("Отменить штрих", "Undo Stroke")) { model.undoLastStroke() }
                    .disabled(!model.canUndoStroke)
                Button(text("Очистить", "Clear")) { model.clearMask() }
                    .disabled(model.strokes.isEmpty || model.retouchBusy)
            }
            if model.passCount > 0 {
                HStack {
                    Text(text("Проходов: \(model.passCount)", "Passes: \(model.passCount)"))
                        .font(.caption)
                    Spacer()
                    Button(text("Отменить проход", "Undo Pass")) { model.undoLastPass() }
                        .font(.caption)
                        .disabled(!model.canUndoPass)
                }
            }
            if model.passCount > 0 && model.resultImage == nil && !model.retouchBusy {
                Button(text("Восстановить результат", "Restore result")) {
                    model.restoreCurrentResult()
                }
                .font(.caption)
            }
            Button {
                model.processMask()
            } label: {
                Label(text("Удалить логотип", "Remove Logo"), systemImage: "wand.and.stars")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint(.yellow)
            .disabled(!model.canProcess)

            if model.retouchBusy {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(model.retouchPhase == "preparing"
                         ? text("Подготовка…", "Preparing…")
                         : text("Обработка…", "Processing…"))
                        .font(.caption)
                    Spacer()
                    Button(text("Отмена", "Cancel")) { model.cancelRetouch() }
                        .font(.caption)
                }
            }
            if model.resultImage != nil {
                Toggle(text("Показать результат", "Show result"), isOn: $model.showingAfter)
                    .toggleStyle(.switch)
                    .font(.caption)
                Text(text("До/После: выключите, чтобы увидеть оригинал.",
                          "Before/After: turn off to see the original."))
                    .font(.caption2).foregroundStyle(.secondary)
            }
            if model.sourceNeedsDecision {
                Text(text("Исходник изменился. Рецепты сохранены; выберите действие.",
                          "The source changed. Recipes are preserved; choose an action."))
                    .font(.caption).foregroundStyle(.orange)
                HStack {
                    Button(text("Принять новый исходник", "Rebase source")) { model.rebaseSource() }
                    Button(text("Сбросить рецепты", "Reset recipes")) { model.resetEdits() }
                }.font(.caption)
            }
            if let error = model.retouchError {
                Text(message(error)).font(.caption).foregroundStyle(.orange)
            }
            if model.pressure != .normal {
                Text(text("Недостаточно памяти: обработка приостановлена.",
                          "Low memory: processing is paused."))
                    .font(.caption).foregroundStyle(.orange)
            }
            Divider()
            Label(text("Локальная обработка", "Local processing"), systemImage: "lock.shield")
            Text(text("Одна модель LaMa, отдельный worker-процесс, без сети.",
                      "One LaMa model, a separate worker process, no network."))
                .font(.caption).foregroundStyle(.secondary)
            Spacer()
        }
        .padding(20)
    }

    private func message(_ code: String) -> String {
        switch code {
        case "empty_mask": return text("Маска пуста: нарисуйте область.", "The mask is empty: draw an area.")
        case "source_changed": return text("Исходный файл изменился. Результат не применён.", "The source changed. The result was not applied.")
        case "model_missing": return text("Модель LaMa не найдена в приложении.", "The LaMa model is missing from the app.")
        case "unsupported_alpha": return text("Формат alpha не позволяет сохранить hidden RGB.", "This alpha layout cannot preserve hidden RGB.")
        case "unsupported_color": return text("Неподдерживаемая цветовая модель (нужен RGB).", "Unsupported color model (RGB required).")
        case "memory", "insufficient_memory": return text("Недостаточно памяти для этого фото.", "Not enough memory for this photo.")
        case "timeout": return text("Обработка превысила таймаут; worker остановлен.", "Processing timed out; the worker was stopped.")
        case "worker_crashed", "worker_launch_failed", "worker_failed": return text("Worker завершился с ошибкой. Приложение продолжает работу.", "The worker failed. The app is still running.")
        case "invalid_output", "non_finite_output", "invalid_input": return text("Модель вернула некорректный результат.", "The model returned an invalid result.")
        case "image_too_large": return text("Фото превышает лимит 40 Мп.", "The photo exceeds the 40 MP limit.")
        case "invalid_image": return text("Не удалось прочитать фото или маску.", "Could not read the photo or mask.")
        default: return text("Не удалось обработать фото.", "Could not process the photo.")
        }
    }
}
