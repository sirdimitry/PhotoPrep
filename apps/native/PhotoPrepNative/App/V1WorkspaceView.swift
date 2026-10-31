import SwiftUI
import AppKit
import UniformTypeIdentifiers

enum V1PanelTool: String, CaseIterable, Identifiable {
    case brush, eraser, crop, move, logo, comparison
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .brush: return "paintbrush.pointed"
        case .eraser: return "eraser"
        case .crop: return "crop"
        case .move: return "arrow.up.and.down.and.arrow.left.and.right"
        case .logo: return "signature"
        case .comparison: return "rectangle.split.2x1"
        }
    }
}

private struct V1Checkerboard: View {
    var body: some View {
        Canvas { context, size in
            let cell: CGFloat = 14
            var y: CGFloat = 0
            var row = 0
            while y < size.height {
                var x: CGFloat = row % 2 == 0 ? 0 : -cell
                while x < size.width {
                    context.fill(Path(CGRect(x: x, y: y, width: cell, height: cell)),
                                 with: .color(Color(white: 0.16)))
                    x += cell * 2
                }
                y += cell; row += 1
            }
        }.background(Color(white: 0.12))
    }
}

private struct V1Rulers: View {
    var body: some View {
        GeometryReader { geo in
            Canvas { context, size in
                let line = Color(white: 0.45)
                context.stroke(Path { p in
                    p.move(to: CGPoint(x: 22, y: 18)); p.addLine(to: CGPoint(x: size.width, y: 18))
                    p.move(to: CGPoint(x: 22, y: 18)); p.addLine(to: CGPoint(x: 22, y: size.height))
                }, with: .color(line), lineWidth: 0.7)
                var x: CGFloat = 22
                var n = 0
                while x < size.width {
                    let h: CGFloat = n % 100 == 0 ? 9 : (n % 50 == 0 ? 6 : 3)
                    context.stroke(Path { p in
                        p.move(to: CGPoint(x: x, y: 18)); p.addLine(to: CGPoint(x: x, y: 18 + h))
                    }, with: .color(line), lineWidth: 0.7)
                    if n % 100 == 0 {
                        context.draw(Text("\(n)").font(.system(size: 8)).foregroundStyle(.secondary),
                                     at: CGPoint(x: x + 10, y: 9))
                    }
                    x += 25; n += 25
                }
                var y: CGFloat = 18
                n = 0
                while y < size.height {
                    let w: CGFloat = n % 100 == 0 ? 9 : (n % 50 == 0 ? 6 : 3)
                    context.stroke(Path { p in
                        p.move(to: CGPoint(x: 22, y: y)); p.addLine(to: CGPoint(x: 22 + w, y: y))
                    }, with: .color(line), lineWidth: 0.7)
                    if n % 100 == 0 {
                        context.draw(Text("\(n)").font(.system(size: 8)).foregroundStyle(.secondary),
                                     at: CGPoint(x: 9, y: y + 6))
                    }
                    y += 25; n += 25
                }
            }
        }.allowsHitTesting(false)
    }
}

private struct V1OutputFrame: View {
    let aspect: CGFloat
    var body: some View {
        GeometryReader { geo in
            let pad: CGFloat = 44
            let availableW = max(20, geo.size.width - pad * 2)
            let availableH = max(20, geo.size.height - pad * 2)
            let h = min(availableW / aspect, availableH)
            let w = h * aspect
            Rectangle()
                .stroke(Color.yellow, lineWidth: 1.4)
                .frame(width: w, height: h)
                .position(x: geo.size.width / 2, y: geo.size.height / 2)
        }.allowsHitTesting(false)
    }
}

private struct V1PhotoThumb: View {
    let photo: PhotoHeader
    @State private var image: NSImage?
    var body: some View {
        Group {
            if let image {
                Image(nsImage: image).resizable().aspectRatio(contentMode: .fill)
            } else {
                Color(white: 0.18).overlay(Image(systemName: "photo").foregroundStyle(.secondary))
            }
        }
        .frame(width: 74, height: 34).clipped().cornerRadius(4)
        .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color(white: 0.3), lineWidth: 0.5))
        .task(id: photo.url) {
            image = NSImage(contentsOf: photo.url)
        }
    }
}

struct V1WorkspaceView: View {
    @ObservedObject var model: WorkspaceModel
    let language: String
    @State private var tool: V1PanelTool = .brush
    @State private var exportFormat: ExportFormat = .png
    @State private var exportQuality: Double = 0.92

    private var ru: Bool { language == "ru" }
    private func t(_ r: String, _ e: String) -> String { ru ? r : e }
    private var current: PhotoHeader? {
        guard let url = model.selected else { return nil }
        return model.photos.first { $0.url == url }
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(Color(white: 0.22))
            HStack(spacing: 0) {
                toolRail
                Divider().overlay(Color(white: 0.22))
                VStack(spacing: 0) {
                    canvasArea
                    Divider().overlay(Color(white: 0.22))
                    filmstrip
                }
                Divider().overlay(Color(white: 0.22))
                rightPanel.frame(width: 296)
            }
        }
        .background(Color(white: 0.16))
        .tint(.yellow)
        .background(WindowCloseGuardView(workspace: model))
    }

    private var header: some View {
        HStack(spacing: 10) {
            Text("PhotoPrep Native").font(.system(size: 17, weight: .semibold))
            Text("v1").font(.system(size: 9, weight: .bold))
                .padding(.horizontal, 5).padding(.vertical, 2)
                .background(Color.yellow.opacity(0.18)).foregroundStyle(.yellow)
                .clipShape(Capsule())
            Text(current?.url.lastPathComponent ?? "—")
                .font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1)
            Spacer(minLength: 12)
            Button { model.importPhotos() } label: { Label(t("Открыть фото", "Open Photos"), systemImage: "photo") }
                .buttonStyle(.borderedProminent).tint(.yellow).foregroundStyle(.black)
                .disabled(model.busy || model.pressure != .normal)
            Button { model.importFolder() } label: { Label(t("Открыть папку", "Open Folder"), systemImage: "folder") }
                .disabled(model.busy || model.pressure != .normal)
            Button { model.exportPanel(format: exportFormat, quality: exportQuality) } label: {
                Label(t("Экспорт", "Export"), systemImage: "square.and.arrow.up")
            }.buttonStyle(.borderedProminent).tint(.yellow).foregroundStyle(.black)
                .disabled(model.photos.isEmpty || model.exportBusy || model.sessionReadOnly != nil || model.sourceNeedsDecision)
            SettingsLink { Image(systemName: "gearshape") }.help(t("Настройки оформления", "Appearance settings"))
        }
        .font(.system(size: 12))
        .padding(.horizontal, 12).frame(height: 44)
    }

    private var toolRail: some View {
        VStack(spacing: 6) {
            rail(.brush, "Кисть", "Brush") { selectTool(.brush); model.tool = .brush }
            rail(.eraser, "Ластик", "Eraser") { selectTool(.eraser); model.tool = .eraser }
            rail(.crop, "Кадрирование", "Crop") { selectTool(.crop); model.beginCrop() }
            rail(.move, "Перемещение", "Move") { selectTool(.move) }
            rail(.logo, "Логотип", "Logo") { selectTool(.logo) }
            rail(.comparison, "До/После", "Before/After") {
                selectTool(.comparison)
                guard model.resultImage != nil else { return }
                model.showingAfter.toggle()
            }
            Spacer()
        }
        .padding(.vertical, 10).frame(width: 54)
        .background(Color(white: 0.155))
    }

    private func rail(_ value: V1PanelTool, _ r: String, _ e: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: value.symbol).font(.system(size: 17, weight: .medium))
                .frame(width: 38, height: 36)
                .background(tool == value ? Color.yellow : Color.clear)
                .foregroundStyle(tool == value ? Color.black : Color(white: 0.78))
                .clipShape(RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain).help(t(r, e))
    }

    private func selectTool(_ value: V1PanelTool) {
        tool = value
        if value != .crop { model.cropMode = false }
    }

    private var canvasArea: some View {
        GeometryReader { geo in
            ZStack {
                V1Checkerboard()
                Group {
                    if model.cropMode, let crop = model.crop, let image = model.cropImage {
                        CropCanvas(image: image, crop: crop, outputAspect: model.outputAspect,
                                   onChange: { model.setCrop($0) })
                    } else if let image = model.displayImage {
                        BrushCanvas(image: image, strokes: model.strokes, tool: model.tool,
                                    brushWidth: model.brushWidth, showMask: !model.showingAfter,
                                    viewport: model.canvasView, panEnabled: tool == .move,
                                    onCommit: { model.addStroke($0) },
                                    onViewChange: { model.setCanvasView($0) })
                    } else if !model.busy {
                        VStack(spacing: 10) {
                            Image(systemName: "photo.on.rectangle.angled").font(.system(size: 40)).foregroundStyle(.secondary)
                            Text(t("Откройте фото или папку", "Open photos or a folder")).font(.headline)
                            Button(t("Открыть фото…", "Open Photos…")) { model.importPhotos() }
                                .buttonStyle(.borderedProminent).tint(.yellow).disabled(model.pressure != .normal)
                        }
                    }
                }
                if !model.cropMode, let header = current, let selected = model.selected,
                   let image = model.displayImage {
                    V1CanvasGuides(imageSize: CGSize(width: header.width, height: header.height),
                                   imageRect: viewImageRect(size: geo.size, imageSize: CGSize(width: header.width, height: header.height)),
                                   crop: model.effectiveCrop(for: selected),
                                   backingScale: displayScale)
                }
                if model.busy { ProgressView().controlSize(.large) }
            }
        }
        .frame(minWidth: 360, maxWidth: .infinity, maxHeight: .infinity)
        .clipped()
    }

    @Environment(\.displayScale) private var displayScale

    private func viewImageRect(size: CGSize, imageSize: CGSize) -> CGRect {
        let available = CGRect(origin: .zero, size: size).insetBy(dx: 8, dy: 8)
        guard available.width > 0, available.height > 0, imageSize.width > 0, imageSize.height > 0 else { return .zero }
        let fit = min(available.width / imageSize.width, available.height / imageSize.height)
        let actual = model.canvasView.fit ? fit : (1 / max(1, displayScale)) * CGFloat(max(0.05, model.canvasView.zoom))
        let w = imageSize.width * actual, h = imageSize.height * actual
        return CGRect(x: size.width / 2 - CGFloat(model.canvasView.centerX) * w,
                      y: size.height / 2 - CGFloat(model.canvasView.centerY) * h,
                      width: w, height: h)
    }

    private var zoomPercent: Int {
        if model.canvasView.fit { return 0 }
        return Int((model.canvasView.zoom * 100).rounded())
    }
    private func setZoom(_ value: Double) {
        var next = model.canvasView
        next.fit = false
        next.zoom = min(8, max(0.1, value))
        model.setCanvasView(next)
    }
    private func zoomStep(_ factor: Double) {
        guard !model.canvasView.fit else {
            var next = model.canvasView; next.fit = false; next.zoom = 1; model.setCanvasView(next); return
        }
        setZoom(model.canvasView.zoom * factor)
    }

    private var filmstrip: some View {
        VStack(spacing: 6) {
            HStack(spacing: 8) {
                Text(t("Фотографии", "Photos")).font(.system(size: 11, weight: .semibold))
                    .lineLimit(1).fixedSize()
                Text("· \(model.photos.count)").font(.system(size: 11)).foregroundStyle(.secondary)
                    .lineLimit(1).fixedSize()
                Spacer()
                Button { zoomStep(1 / 1.15) } label: { Image(systemName: "minus.magnifyingglass") }
                Text(model.canvasView.fit ? "—" : "\(zoomPercent)%").font(.system(size: 10)).frame(width: 38)
                Button { zoomStep(1.15) } label: { Image(systemName: "plus.magnifyingglass") }
                Button("100%") { setZoom(1) }.font(.system(size: 10))
                Button(t("Вписать", "Fit")) {
                    var next = model.canvasView; next.fit = true; next.zoom = 1; next.centerX = 0.5; next.centerY = 0.5
                    model.setCanvasView(next)
                }.font(.system(size: 10))
                Divider().frame(height: 12)
                Button { step(-1) } label: { Image(systemName: "chevron.left") }.disabled(model.photos.count < 2)
                Button { step(1) } label: { Image(systemName: "chevron.right") }.disabled(model.photos.count < 2)
                Button { model.selected = nil } label: { Image(systemName: "xmark") }.disabled(model.selected == nil)
            }.font(.system(size: 11)).padding(.horizontal, 12)
            statusBar
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(model.photos) { photo in
                        Button { model.selected = photo.url } label: {
                            VStack(spacing: 3) {
                                V1PhotoThumb(photo: photo)
                                Text(photo.url.lastPathComponent).font(.system(size: 9)).lineLimit(1)
                                    .foregroundStyle(model.selected == photo.url ? .white : .secondary)
                            }
                            .padding(4)
                            .background(RoundedRectangle(cornerRadius: 6)
                                .fill(model.selected == photo.url ? Color.yellow.opacity(0.18) : Color.clear))
                            .overlay(RoundedRectangle(cornerRadius: 6)
                                .stroke(model.selected == photo.url ? Color.yellow : Color.clear, lineWidth: 1))
                        }.buttonStyle(.plain)
                    }
                }.padding(.horizontal, 12)
            }.frame(height: 52)
        }
        .padding(.top, 4).background(Color(white: 0.155))
    }

    private func step(_ delta: Int) {
        guard let selected = model.selected,
              let index = model.photos.firstIndex(where: { $0.url == selected }) else { return }
        let next = min(max(0, index + delta), model.photos.count - 1)
        model.selected = model.photos[next].url
    }

    private var statusBar: some View {
        HStack(spacing: 10) {
            Text("\(model.photos.count) " + t("фото", model.photos.count == 1 ? "photo" : "photos"))
            if let current { Text("· \(current.width) × \(current.height)") }
            Text("· \(model.sessionOutputWidth) × \(model.sessionOutputHeight)")
            if model.busy || model.retouchBusy {
                Text("· " + (model.retouchPhase.isEmpty ? t("обработка", "processing") : model.retouchPhase))
            }
            Spacer()
            if let issue = model.issue {
                Text(issueText(issue)).foregroundStyle(.orange).lineLimit(1)
            }
            if let reason = model.sessionReadOnly {
                Text(t("Набор только для чтения: \(reason)", "Workspace read-only: \(reason)"))
                    .foregroundStyle(.orange).lineLimit(1)
            }
            if let error = model.exportError { Text(error).foregroundStyle(.orange).lineLimit(1) }
        }.font(.system(size: 10)).foregroundStyle(.secondary)
        .padding(.horizontal, 10).frame(height: 20)
    }

    private func issueText(_ issue: ResourceFailure) -> String {
        switch issue {
        case .memoryPressure: return t("Память: загрузка приостановлена", "Memory: loading paused")
        case .insufficientMemory: return t("Недостаточно памяти", "Not enough memory")
        case .imageTooLarge, .invalidDimensions: return t("Фото больше 40 Мп", "Photo exceeds 40 MP")
        case .invalidImage: return t("Не удалось прочитать фото", "Cannot read photo")
        }
    }

    @ViewBuilder private var rightPanel: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(t("Параметры", "Parameters")).font(.system(size: 13, weight: .semibold))
                .padding(.horizontal, 14).frame(height: 38)
            Divider().overlay(Color(white: 0.22))
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let current {
                        section(t("Изображение", "Image"))
                        keyValue(t("Исходный размер", "Source size"), "\(current.width) × \(current.height) px")
                        keyValue(t("Размер экспорта", "Export size"), "\(model.sessionOutputWidth) × \(model.sessionOutputHeight) px")
                    }
                    if model.sourceNeedsDecision {
                        Text(t("Исходник изменился. Рецепты сохранены.", "Source changed. Recipes are preserved."))
                            .font(.system(size: 11)).foregroundStyle(.orange)
                        HStack {
                            Button(t("Принять исходник", "Rebase source")) { model.rebaseSource() }
                            Button(t("Сбросить", "Reset")) { model.resetEdits() }
                        }.font(.system(size: 11))
                    }
                    switch tool {
                    case .brush, .eraser: retouchControls
                    case .crop: cropControls
                    case .move: moveControls
                    case .logo: logoControls
                    case .comparison: comparisonControls
                    }
                    exportControls
                }.padding(14)
            }
        }.background(Color(white: 0.155))
    }

    private func section(_ value: String) -> some View {
        Text(value.uppercased()).font(.system(size: 9, weight: .semibold)).foregroundStyle(.secondary)
    }
    private func keyValue(_ key: String, _ value: String) -> some View {
        HStack { Text(key); Spacer(); Text(value).foregroundStyle(.primary).monospacedDigit() }
            .font(.system(size: 11)).foregroundStyle(.secondary)
    }

    private var retouchControls: some View {
        VStack(alignment: .leading, spacing: 10) {
            section(t("Кисть маски", "Mask brush"))
            HStack {
                Text(t("Размер", "Size")).font(.system(size: 11))
                Slider(value: $model.brushWidth, in: 0.01...0.25)
                Text("\(Int(model.brushWidth * 1000))").font(.system(size: 10)).monospacedDigit().frame(width: 26)
            }
            Toggle(t("Показывать маску", "Show mask"), isOn: Binding(get: { !model.showingAfter }, set: { model.showingAfter = !$0 }))
                .font(.system(size: 11)).disabled(model.resultImage == nil)
            HStack {
                Button(t("Отменить штрих", "Undo stroke")) { model.undoLastStroke() }.disabled(!model.canUndoStroke)
                Button(t("Очистить", "Clear")) { model.clearMask() }.disabled(model.strokes.isEmpty || model.retouchBusy)
            }.font(.system(size: 11))
            Button { model.processMask() } label: {
                Text(t("Удалить выделенное", "Remove selection")).frame(maxWidth: .infinity)
            }.buttonStyle(.borderedProminent).tint(.yellow).foregroundStyle(.black)
                .disabled(!model.canProcess)
            if model.retouchBusy || model.busy {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.small)
                    Text(model.retouchPhase.isEmpty ? t("Обработка…", "Processing…") : model.retouchPhase)
                        .font(.system(size: 10)).lineLimit(1)
                    Spacer()
                    Button(t("Отмена", "Cancel")) { model.cancel() }.font(.system(size: 10))
                }
            }
            if model.passCount > 0 {
                HStack {
                    Text(t("Проходов: \(model.passCount)", "Passes: \(model.passCount)")).font(.system(size: 11))
                    Spacer()
                    Button(t("Отменить проход", "Undo pass")) { model.undoLastPass() }.font(.system(size: 10))
                        .disabled(!model.canUndoPass)
                }
            }
            Text(t("Рисуйте область · Пробел — перемещение", "Paint an area · Space to pan"))
                .font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }

    private var cropControls: some View {
        VStack(alignment: .leading, spacing: 10) {
            section(t("Кадрирование", "Crop"))
            Text(t("Рамка неподвижна. Перетаскивайте изображение, колесо — масштаб.", "Frame is fixed. Drag the image, scroll to zoom."))
                .font(.system(size: 10)).foregroundStyle(.secondary)
            if model.crop != nil {
                HStack {
                    Button(t("Готово", "Done")) { model.cropMode = false; tool = .brush }
                    Button(t("Сбросить", "Reset")) { model.resetCrop() }
                    Button(t("Отменить", "Undo")) { model.undoCrop() }
                }.font(.system(size: 11))
            } else {
                Button(t("Начать кадрирование", "Start crop")) { model.beginCrop() }
            }
        }
    }

    private var moveControls: some View {
        VStack(alignment: .leading, spacing: 8) {
            section(t("Перемещение", "Move"))
            Text(t("Перетаскивание изображения доступно в режиме кадрирования.", "Drag the image in crop mode."))
                .font(.system(size: 10)).foregroundStyle(.secondary)
            Text(t("Положение изображения не сбрасывается при смене инструмента.", "Image position is preserved when switching tools."))
                .font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }

    private var logoControls: some View {
        VStack(alignment: .leading, spacing: 10) {
            section(t("Логотип", "Logo"))
            if let logo = model.logo {
                Toggle(t("Показывать", "Visible"), isOn: Binding(get: { logo.enabled }, set: { model.updateLogo(enabled: $0) }))
                    .font(.system(size: 11))
                HStack { Text(t("Размер", "Size")).font(.system(size: 11)); Slider(value: Binding(get: { logo.width }, set: { model.updateLogo(width: $0) }), in: 0.01...0.94) }
                HStack { Text(t("Прозрачность", "Opacity")).font(.system(size: 11)); Slider(value: Binding(get: { logo.opacity }, set: { model.updateLogo(opacity: $0) }), in: 0...1) }
                HStack { Text("X").font(.system(size: 10)); Slider(value: Binding(get: { logo.x }, set: { model.updateLogo(x: $0) }), in: 0...1) }
                HStack { Text("Y").font(.system(size: 10)); Slider(value: Binding(get: { logo.y }, set: { model.updateLogo(y: $0) }), in: 0...1) }
                HStack {
                    Button(t("Применить ко всем", "Apply to all")) { model.applyLogoToAll() }
                    Button(t("Убрать", "Remove")) { model.removeLogo() }
                }.font(.system(size: 11))
                Button(t("Другой PNG…", "Another PNG…")) { model.chooseLogo() }.font(.system(size: 11))
            } else {
                Button(t("Выбрать PNG-логотип…", "Choose PNG logo…")) { model.chooseLogo() }
                Text(t("Локальный PNG с alpha. Применяется к одному фото или коллекции.", "Local PNG with alpha. Applies to one photo or collection."))
                    .font(.system(size: 10)).foregroundStyle(.secondary)
            }
        }
    }

    private var comparisonControls: some View {
        VStack(alignment: .leading, spacing: 9) {
            section(t("До / После", "Before / After"))
            Button(model.showingAfter ? t("Показать исходник", "Show original") : t("Показать результат", "Show result")) {
                guard model.resultImage != nil else { return }
                model.showingAfter.toggle()
            }.disabled(model.resultImage == nil)
            Text(t("Сравнение не меняет маску и рецепты.", "Comparison does not change the mask or recipes."))
                .font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }

    private var exportControls: some View {
        VStack(alignment: .leading, spacing: 9) {
            Divider().overlay(Color(white: 0.22))
            section(t("Экспорт", "Export"))
            Picker("", selection: $exportFormat) {
                Text("PNG").tag(ExportFormat.png); Text("JPEG").tag(ExportFormat.jpeg)
            }.pickerStyle(.segmented).labelsHidden()
            if exportFormat == .jpeg {
                HStack { Text(t("Качество", "Quality")); Slider(value: $exportQuality, in: 0.5...1) }
                    .font(.system(size: 10))
            }
            Button { model.exportPanel(format: exportFormat, quality: exportQuality) } label: {
                Text(t("Экспортировать коллекцию…", "Export collection…")).frame(maxWidth: .infinity)
            }.buttonStyle(.bordered).disabled(model.photos.isEmpty || model.exportBusy || model.sessionReadOnly != nil || model.sourceNeedsDecision)
            if model.exportBusy {
                HStack {
                    ProgressView().controlSize(.small)
                    Text("\(model.exportDone)/\(model.exportTotal)").font(.system(size: 10))
                    Spacer(); Button(t("Отмена", "Cancel")) { model.cancelExport() }.font(.system(size: 10))
                }
            }
        }
    }
}

private struct V1CanvasGuides: View {
    let imageSize: CGSize
    let imageRect: CGRect
    let crop: SessionCrop
    let backingScale: CGFloat

    var body: some View {
        Canvas { context, _ in
            guard imageRect.width > 1, imageRect.height > 1 else { return }
            let tick = Color(white: 0.45)
            let label = Color(white: 0.62)
            // Rulers are in image-pixel coordinates and follow the same transform as the canvas.
            let step = CGFloat(100)
            var px: CGFloat = 0
            while px <= imageSize.width {
                let x = imageRect.minX + px * imageRect.width / imageSize.width
                let h: CGFloat = px.truncatingRemainder(dividingBy: 500) == 0 ? 9 : 5
                context.stroke(Path { p in
                    p.move(to: CGPoint(x: x, y: imageRect.minY))
                    p.addLine(to: CGPoint(x: x, y: imageRect.minY - h))
                }, with: .color(tick), lineWidth: 0.7)
                if px.truncatingRemainder(dividingBy: 500) == 0 {
                    context.draw(Text("\(Int(px))").font(.system(size: 8)).foregroundStyle(label),
                                 at: CGPoint(x: x + 12, y: imageRect.minY - 13))
                }
                px += step
            }
            var py: CGFloat = 0
            while py <= imageSize.height {
                let y = imageRect.minY + py * imageRect.height / imageSize.height
                let w: CGFloat = py.truncatingRemainder(dividingBy: 500) == 0 ? 9 : 5
                context.stroke(Path { p in
                    p.move(to: CGPoint(x: imageRect.minX, y: y))
                    p.addLine(to: CGPoint(x: imageRect.minX - w, y: y))
                }, with: .color(tick), lineWidth: 0.7)
                if py.truncatingRemainder(dividingBy: 500) == 0 {
                    context.draw(Text("\(Int(py))").font(.system(size: 8)).foregroundStyle(label),
                                 at: CGPoint(x: imageRect.minX - 24, y: y))
                }
                py += step
            }
            let frame = CGRect(x: imageRect.minX + CGFloat(crop.x) * imageRect.width,
                               y: imageRect.minY + CGFloat(crop.y) * imageRect.height,
                               width: CGFloat(crop.width) * imageRect.width,
                               height: CGFloat(crop.height) * imageRect.height)
            var outside = Path()
            outside.addRect(imageRect)
            outside.addRect(frame)
            context.fill(outside, with: .color(.black.opacity(0.22)), style: FillStyle(eoFill: true))
            context.stroke(Path(frame.insetBy(dx: -1, dy: -1)), with: .color(.black.opacity(0.75)), lineWidth: 3)
            context.stroke(Path(frame), with: .color(.yellow), lineWidth: 2)
        }
        .allowsHitTesting(false)
    }
}
