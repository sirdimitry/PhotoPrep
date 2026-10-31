import SwiftUI
import AppKit

struct BrushCanvas: NSViewRepresentable {
    let image: CGImage?
    let strokes: [MaskStroke]
    let tool: RetouchTool
    let brushWidth: Double
    let showMask: Bool
    let viewport: SessionView
    let panEnabled: Bool
    let onCommit: (MaskStroke) -> Void
    let onViewChange: (SessionView) -> Void

    func makeNSView(context: Context) -> BrushCanvasView {
        let view = BrushCanvasView()
        view.onCommit = onCommit
        view.onViewChange = onViewChange
        return view
    }

    func updateNSView(_ view: BrushCanvasView, context: Context) {
        view.image = image
        view.strokes = strokes
        view.tool = tool
        view.brushWidth = brushWidth
        view.showMask = showMask
        view.viewport = viewport
        view.panEnabled = panEnabled
        view.onCommit = onCommit
        view.onViewChange = onViewChange
        view.needsDisplay = true
    }
}

final class BrushCanvasView: NSView {
    var image: CGImage?
    var strokes: [MaskStroke] = []
    var tool: RetouchTool = .brush
    var brushWidth: Double = 0.06
    var showMask = true
    var viewport = SessionView()
    var panEnabled = false
    var onCommit: ((MaskStroke) -> Void)?
    var onViewChange: ((SessionView) -> Void)?
    private var currentStroke: MaskStroke?
    private var panStart: (point: CGPoint, view: SessionView)?
    private var spaceDown = false

    override var acceptsFirstResponder: Bool { true }

    private var backingScale: CGFloat {
        max(1, window?.backingScaleFactor ?? 2)
    }

    private var imageRect: CGRect {
        guard let image, image.width > 0, image.height > 0 else { return .zero }
        let available = bounds.insetBy(dx: 8, dy: 8)
        guard available.width > 0, available.height > 0 else { return .zero }
        let fit = min(available.width / CGFloat(image.width), available.height / CGFloat(image.height))
        // 100% is one image pixel per backing pixel, not per point.
        let actual = viewport.fit ? fit : (1 / backingScale) * CGFloat(max(0.05, viewport.zoom))
        let size = CGSize(width: CGFloat(image.width) * actual, height: CGFloat(image.height) * actual)
        let originX = bounds.midX - CGFloat(viewport.centerX) * size.width
        let originY = bounds.midY - (1 - CGFloat(viewport.centerY)) * size.height
        return CGRect(x: originX, y: originY, width: size.width, height: size.height)
    }

    override func draw(_ dirtyRect: NSRect) {
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
        NSColor.systemYellow.withAlphaComponent(0.28).setFill()
        rect.fill()
        context.restoreGState()
    }

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: (panEnabled || spaceDown) ? .openHand : .crosshair)
    }

    private func normalizedPoint(_ event: NSEvent) -> MaskPoint? {
        let rect = imageRect
        guard rect.width > 0, rect.height > 0 else { return nil }
        let point = convert(event.locationInWindow, from: nil)
        guard rect.contains(point) else { return nil }
        return MaskPoint(
            x: min(1, max(0, Double((point.x - rect.minX) / rect.width))),
            y: min(1, max(0, Double(1.0 - (point.y - rect.minY) / rect.height)))
        )
    }

    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        let p = convert(event.locationInWindow, from: nil)
        if panEnabled || spaceDown {
            panStart = (p, viewport)
            NSCursor.closedHand.push()
            return
        }
        guard image != nil, let point = normalizedPoint(event) else { return }
        currentStroke = MaskStroke(points: [point], width: brushWidth, erase: tool == .eraser)
        needsDisplay = true
    }

    override func mouseDragged(with event: NSEvent) {
        let p = convert(event.locationInWindow, from: nil)
        if let start = panStart {
            let rect = imageRect
            guard rect.width > 0, rect.height > 0 else { return }
            var next = start.view
            next.fit = false
            next.centerX = min(1, max(0, start.view.centerX - Double((p.x - start.point.x) / rect.width)))
            next.centerY = min(1, max(0, start.view.centerY + Double((p.y - start.point.y) / rect.height)))
            viewport = next
            onViewChange?(next)
            needsDisplay = true
            return
        }
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
        if panStart != nil {
            panStart = nil
            NSCursor.pop()
            return
        }
        guard let stroke = currentStroke, !stroke.points.isEmpty else { return }
        onCommit?(stroke)
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 49 { spaceDown = true; window?.invalidateCursorRects(for: self); return }
        super.keyDown(with: event)
    }

    override func keyUp(with event: NSEvent) {
        if event.keyCode == 49 { spaceDown = false; window?.invalidateCursorRects(for: self); return }
        super.keyUp(with: event)
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        window?.makeFirstResponder(self)
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
    @State private var exportFormat: ExportFormat = .png
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
            HStack {
                Button(text("Кадрирование", "Crop")) { model.beginCrop() }
                    .disabled(model.selected == nil || model.retouchBusy)
                if model.cropMode {
                    Button(text("Готово", "Done")) { model.cropMode = false }
                    Button(text("Сбросить", "Reset")) { model.resetCrop() }
                }
                Button(text("Отменить кадр", "Undo Crop")) { model.undoCrop() }
                    .disabled(model.crop == nil || model.retouchBusy)
            }.font(.caption)

            if let logo = model.logo {
                Divider()
                Text(text("Логотип", "Logo")).font(.caption).bold()
                HStack {
                    Text(text("Размер", "Size")).font(.caption2)
                    Slider(value: Binding(get: { logo.width }, set: { model.updateLogo(width: $0) }), in: 0.01...0.94)
                }
                HStack {
                    Text(text("Прозрачность", "Opacity")).font(.caption2)
                    Slider(value: Binding(get: { logo.opacity }, set: { model.updateLogo(opacity: $0) }), in: 0...1)
                }
                HStack {
                    Button(text("Применить ко всем", "Apply to all")) { model.applyLogoToAll() }
                    Button(text("Убрать", "Remove")) { model.removeLogo() }
                }.font(.caption)
            } else {
                Button(text("Выбрать PNG-логотип…", "Choose PNG logo…")) { model.chooseLogo() }
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
            Text(text("Экспорт", "Export")).font(.caption).bold()
            HStack {
                Picker("", selection: $exportFormat) {
                    Text("PNG").tag(ExportFormat.png)
                    Text("JPEG").tag(ExportFormat.jpeg)
                }.pickerStyle(.segmented).frame(width: 130)
                Button(text("Экспорт…", "Export…")) {
                    model.exportPanel(format: exportFormat, quality: 0.92)
                }.disabled(model.photos.isEmpty || model.exportBusy || model.sessionReadOnly != nil)
            }
            if model.exportBusy {
                HStack {
                    ProgressView().controlSize(.small)
                    Text("\(model.exportDone)/\(model.exportTotal)").font(.caption)
                    Spacer()
                    Button(text("Отмена", "Cancel")) { model.cancelExport() }.font(.caption)
                }
            }
            if let error = model.exportError {
                Text(error).font(.caption).foregroundStyle(.orange)
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

struct CropCanvas: NSViewRepresentable {
    let image: CGImage?
    let crop: SessionCrop
    let outputAspect: Double
    let onChange: (SessionCrop) -> Void

    func makeNSView(context: Context) -> CropCanvasView {
        let view = CropCanvasView()
        view.onChange = onChange
        return view
    }

    func updateNSView(_ view: CropCanvasView, context: Context) {
        view.image = image
        view.crop = crop
        view.outputAspect = outputAspect
        view.onChange = onChange
        view.needsDisplay = true
    }
}

final class CropCanvasView: NSView {
    var image: CGImage?
    var crop = SessionCrop(x: 0, y: 0, width: 1, height: 1)
    var outputAspect: Double = 1
    var onChange: ((SessionCrop) -> Void)?
    private var lastPoint: NSPoint?

    override var isFlipped: Bool { true }

    private var frameRect: CGRect {
        let available = bounds.insetBy(dx: 24, dy: 24)
        guard available.width > 0, available.height > 0 else { return .zero }
        var w = available.width, h = w / outputAspect
        if h > available.height { h = available.height; w = h * outputAspect }
        return CGRect(x: bounds.midX - w / 2, y: bounds.midY - h / 2, width: w, height: h)
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.underPageBackgroundColor.setFill(); bounds.fill()
        guard let image, image.width > 0, image.height > 0 else { return }
        let frame = frameRect
        guard frame.width > 0, crop.width > 0, crop.height > 0 else { return }
        let displayW = frame.width / CGFloat(crop.width)
        let displayH = frame.height / CGFloat(crop.height)
        let rect = CGRect(x: frame.minX - CGFloat(crop.x) * displayW,
                          y: frame.minY - CGFloat(crop.y) * displayH,
                          width: displayW, height: displayH)
        NSGraphicsContext.current?.imageInterpolation = .high
        NSImage(cgImage: image, size: NSSize(width: image.width, height: image.height))
            .draw(in: rect, from: .zero, operation: .sourceOver, fraction: 1.0)
        NSColor.black.withAlphaComponent(0.55).setFill()
        let outside = NSBezierPath(rect: bounds)
        outside.append(NSBezierPath(rect: frame))
        outside.windingRule = .evenOdd
        outside.fill()
        NSColor.systemYellow.setStroke()
        let border = NSBezierPath(rect: frame); border.lineWidth = 2; border.stroke()
    }

    override func mouseDown(with event: NSEvent) { lastPoint = convert(event.locationInWindow, from: nil) }
    override func mouseDragged(with event: NSEvent) {
        guard let last = lastPoint else { return }
        let point = convert(event.locationInWindow, from: nil)
        let frame = frameRect
        guard frame.width > 0 else { return }
        let dx = Double(point.x - last.x) / Double(frame.width / CGFloat(crop.width))
        let dy = Double(point.y - last.y) / Double(frame.height / CGFloat(crop.height))
        var next = crop
        next.x -= dx; next.y -= dy
        next.x = min(max(0, next.x), 1 - next.width)
        next.y = min(max(0, next.y), 1 - next.height)
        crop = next; lastPoint = point; onChange?(next); needsDisplay = true
    }
    override func scrollWheel(with event: NSEvent) {
        guard image != nil else { return }
        let factor = event.deltaY > 0 ? 0.94 : 1.06
        let cx = crop.x + crop.width / 2, cy = crop.y + crop.height / 2
        var next = crop
        next.width = min(1, max(0.02, crop.width * factor))
        next.height = min(1, next.width * (Double(image!.width) / Double(image!.height)) / outputAspect)
        if next.height > 1 { next.height = 1; next.width = outputAspect * (Double(image!.height) / Double(image!.width)) }
        next.x = min(max(0, cx - next.width / 2), 1 - next.width)
        next.y = min(max(0, cy - next.height / 2), 1 - next.height)
        crop = next; onChange?(next); needsDisplay = true
    }
}
