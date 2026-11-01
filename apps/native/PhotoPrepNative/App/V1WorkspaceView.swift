import SwiftUI
import AppKit
import UniformTypeIdentifiers


enum V1PanelTool: String, CaseIterable, Identifiable {
    case brush, eraser, crop, logo
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .brush: return "paintbrush.pointed"
        case .eraser: return "eraser"
        case .crop: return "crop"
        case .logo: return "logo"
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
    @State private var image: CGImage?

    var body: some View {
        Group {
            if let image {
                Image(decorative: image, scale: 1).resizable().aspectRatio(contentMode: .fill)
            } else {
                Color(white: 0.2).overlay(Image(systemName: "photo").foregroundStyle(.secondary))
            }
        }
        .frame(width: 120, height: 80).clipped().cornerRadius(4)
        .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color(white: 0.32), lineWidth: 0.5))
        .task(id: photo.url) {
            image = await ThumbnailCache.shared.image(for: photo.url)
        }
    }
}

private struct V1PhotoInfoButton: View {
    let photo: PhotoHeader
    let exportWidth: Int
    let exportHeight: Int
    @State private var showInfo = false

    private var format: String { photo.url.pathExtension.uppercased() }
    private var bytes: Int64 {
        (try? photo.url.resourceValues(forKeys: [.fileSizeKey]).fileSize).map(Int64.init) ?? 0
    }

    var body: some View {
        Button { showInfo.toggle() } label: {
            Image(systemName: "info.circle.fill")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(.white, Color.black.opacity(0.8))
                .frame(width: 24, height: 24)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Информация о файле")
        .help("Информация о файле")
        .popover(isPresented: $showInfo, arrowEdge: .top) {
            VStack(alignment: .leading, spacing: 6) {
                Text(photo.url.lastPathComponent)
                    .font(.system(size: 12, weight: .semibold))
                    .lineLimit(2).truncationMode(.middle)
                Divider().overlay(Color(white: 0.3))
                row("Исходник", "\(photo.width) × \(photo.height) px")
                row("Формат", format)
                row("Файл", ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file))
                row("Экспорт", "\(exportWidth) × \(exportHeight) px")
            }.font(.system(size: 11)).padding(14).frame(width: 260, alignment: .leading)
        }
    }
    private func row(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).foregroundStyle(.secondary)
            Spacer(minLength: 12)
            Text(value).multilineTextAlignment(.trailing)
        }
    }
}

struct V1WorkspaceView: View {
    @ObservedObject var model: WorkspaceModel
    let language: String
    @State private var tool: V1PanelTool = .brush
    @State private var exportFormat: ExportFormat = .png
    @State private var exportQuality: Double = 0.92
    @State private var canvasSize: CGSize = .zero

    private var ru: Bool { language == "ru" }
    private func t(_ r: String, _ e: String) -> String { ru ? r : e }
    private var current: PhotoHeader? {
        guard let url = model.selected else { return nil }
        return model.photos.first { $0.url == url }
    }

    var body: some View {
        VStack(spacing: 0) {
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
        .background(WindowTitleAccessor(title: "PhotoPrep Native v1" + (current.map { " — \($0.url.lastPathComponent)" } ?? "")))
    }

    private var header: some View {
        HStack(spacing: 10) {
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
            logoRail
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
        .buttonStyle(.plain).help(t("\(r) — \(e)", "\(e)"))
    }

    private var logoRail: some View {
        Button { selectTool(.logo) } label: {
            LogoGlyph()
                .frame(width: 38, height: 36)
                .background(tool == .logo ? Color.yellow : Color.clear)
                .foregroundStyle(tool == .logo ? Color.black : Color(white: 0.78))
                .clipShape(RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .help(t("Логотип — добавить и настроить наложение", "Logo — add and configure an overlay"))
        .accessibilityLabel(t("Логотип", "Logo"))
    }

    private func selectTool(_ value: V1PanelTool) {
        if model.cropMode && value != .crop { model.commitCrop() }
        tool = value
    }

    private func logoFrame(imageRect: CGRect, crop: SessionCrop) -> CGRect {
        CGRect(x: imageRect.minX + CGFloat(crop.x) * imageRect.width,
               y: imageRect.minY + CGFloat(crop.y) * imageRect.height,
               width: CGFloat(crop.width) * imageRect.width,
               height: CGFloat(crop.height) * imageRect.height)
    }

    private func logoFrameForCrop(size: CGSize, aspect: Double) -> CGRect {
        let available = CGRect(origin: .zero, size: size).insetBy(dx: 24, dy: 24)
        var w = max(20, available.width), h = w / CGFloat(aspect)
        if h > available.height { h = max(20, available.height); w = h * CGFloat(aspect) }
        return CGRect(x: size.width/2-w/2, y: size.height/2-h/2, width: w, height: h)
    }

    private func logoRect(in frame: CGRect, logo: SessionLogo, asset: CGImage) -> CGRect {
        let inset = logo.mode == "template" ? 0.0 : 0.03
        let area = frame.insetBy(dx: frame.width * inset, dy: frame.height * inset)
        let aspect = CGFloat(asset.height) / CGFloat(max(1, asset.width))
        let w = min(frame.width * CGFloat(logo.width), area.width, area.height / aspect)
        let h = w * aspect
        return CGRect(x: area.minX + (area.width - w) * CGFloat(logo.x),
                      y: area.minY + (area.height - h) * CGFloat(logo.y),
                      width: w, height: h)
    }

    private var canvasArea: some View {
        GeometryReader { geo in
            ZStack {
                V1Checkerboard()
                Group {
                    if model.cropMode, let crop = model.crop, let image = model.cropImage, let header = current {
                        CropCanvas(image: image, crop: crop, outputAspect: model.outputAspect,
                                   documentSize: CGSize(width: header.width, height: header.height),
                                   onChange: { model.setCrop($0) })
                        V1CanvasGuides(imageSize: CGSize(width: header.width, height: header.height),
                                       imageRect: cropImageRect(size: geo.size, crop: crop,
                                                                documentSize: CGSize(width: header.width, height: header.height)),
                                       crop: crop, backingScale: displayScale)
                    } else if let image = model.displayImage, let header = current {
                        BrushCanvas(image: image, strokes: model.strokes, tool: model.tool,
                                    brushWidth: model.brushWidth, showMask: model.showMask,
                                    documentSize: CGSize(width: header.width, height: header.height),
                                    viewport: model.canvasView, panEnabled: false,
                                    drawingEnabled: tool == .brush || tool == .eraser,
                                    cursorEnabled: tool == .brush || tool == .eraser,
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
                    let ir = viewImageRect(size: geo.size, imageSize: CGSize(width: header.width, height: header.height))
                    V1CanvasGuides(imageSize: CGSize(width: header.width, height: header.height),
                                   imageRect: ir,
                                   crop: model.effectiveCrop(for: selected),
                                   backingScale: displayScale)
                    if let logo = model.logo, logo.enabled, logo.opacity > 0, let asset = model.logoAsset {
                        V1LogoOverlay(logo: logo, asset: asset,
                                      frame: logoFrame(imageRect: ir, crop: model.effectiveCrop(for: selected)),
                                      outputWidth: CGFloat(model.sessionOutputWidth),
                                      editable: tool == .logo,
                                      onMove: { dx, dy, frameRect, logoRect in
                                          moveLogo(dx: dx, dy: dy, frame: frameRect, logoRect: logoRect)
                                      })
                    }
                }
                if model.cropMode, let logo = model.logo, logo.enabled, logo.opacity > 0,
                   let asset = model.logoAsset {
                    V1LogoOverlay(logo: logo, asset: asset,
                                  frame: logoFrameForCrop(size: geo.size, aspect: model.outputAspect),
                                  outputWidth: CGFloat(model.sessionOutputWidth),
                                  editable: tool == .logo,
                                  onMove: { dx, dy, frameRect, logoRect in
                                      moveLogo(dx: dx, dy: dy, frame: frameRect, logoRect: logoRect)
                                  })
                }
                if model.busy { ProgressView().controlSize(.large) }
            }
            .onAppear { canvasSize = geo.size }
            .onChange(of: geo.size) { _, size in canvasSize = size }
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

    private var fitZoom: Double {
        guard canvasSize.width > 0, canvasSize.height > 0, let header = current else { return 1 }
        let available = CGRect(origin: .zero, size: canvasSize).insetBy(dx: 8, dy: 8)
        guard available.width > 0, available.height > 0 else { return 1 }
        let fit = min(available.width / CGFloat(header.width), available.height / CGFloat(header.height))
        return Double(fit) * Double(max(1, displayScale))
    }
    private func cropImageRect(size: CGSize, crop: SessionCrop, documentSize: CGSize) -> CGRect {
        let available = CGRect(origin: .zero, size: size).insetBy(dx: 24, dy: 24)
        var fw = max(20, available.width), fh = fw / CGFloat(model.outputAspect)
        if fh > available.height { fh = max(20, available.height); fw = fh * CGFloat(model.outputAspect) }
        let frame = CGRect(x: (size.width-fw)/2, y: (size.height-fh)/2, width: fw, height: fh)
        let dw = frame.width / CGFloat(max(0.01, crop.width))
        let dh = frame.height / CGFloat(max(0.01, crop.height))
        return CGRect(x: frame.minX - CGFloat(crop.x)*dw,
                      y: frame.minY - CGFloat(crop.y)*dh,
                      width: dw, height: dh)
    }

    private var zoomPercent: Int {
        let value = model.canvasView.fit ? fitZoom : model.canvasView.zoom
        return Int((value * 100).rounded())
    }
    private func setZoom(_ value: Double) {
        var next = model.canvasView
        next.fit = false
        next.zoom = min(8, max(0.1, value))
        model.setCanvasView(next)
    }
    private func zoomStep(_ factor: Double) {
        let base = model.canvasView.fit ? fitZoom : model.canvasView.zoom
        setZoom(base * factor)
    }

    private var filmstrip: some View {
        VStack(spacing: 6) {
            HStack(spacing: 8) {
                Text(t("Фотографии", "Photos")).font(.system(size: 11, weight: .semibold))
                    .lineLimit(1).fixedSize()
                Text("· \(model.photos.count)").font(.system(size: 11)).foregroundStyle(.secondary)
                    .lineLimit(1).fixedSize()
                Spacer()
            }.font(.system(size: 11)).padding(.horizontal, 12)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(model.photos) { photo in
                        ZStack {
                            V1PhotoThumb(photo: photo)
                                .contentShape(Rectangle())
                                .onTapGesture { model.selected = photo.url }
                            LinearGradient(colors: [.clear, .black.opacity(0.65)],
                                           startPoint: .top, endPoint: .bottom)
                                .frame(height: 24).frame(maxHeight: .infinity, alignment: .bottom)
                                .allowsHitTesting(false)
                            Text(photo.url.lastPathComponent)
                                .font(.system(size: 9, weight: .medium))
                                .foregroundStyle(.white)
                                .lineLimit(1).truncationMode(.middle)
                                .padding(.leading, 4).padding(.trailing, 26)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .frame(maxHeight: .infinity, alignment: .bottom)
                                .allowsHitTesting(false)
                            VStack {
                                HStack {
                                    Spacer()
                                    Button { model.closePhoto(photo.url) } label: {
                                        Image(systemName: "xmark")
                                            .font(.system(size: 9, weight: .bold))
                                            .foregroundStyle(.white)
                                            .frame(width: 22, height: 22)
                                            .background(Circle().fill(.black.opacity(0.58)))
                                            .contentShape(Circle())
                                    }.buttonStyle(.plain)
                                        .help(t("Закрыть фотографию", "Close photo"))
                                }
                                Spacer()
                                HStack {
                                    Spacer()
                                    V1PhotoInfoButton(photo: photo,
                                                      exportWidth: model.sessionOutputWidth,
                                                      exportHeight: model.sessionOutputHeight)
                                }
                            }.padding(3)
                        }
                        .frame(width: 120, height: 80)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .overlay(RoundedRectangle(cornerRadius: 6)
                            .stroke(model.selected == photo.url ? Color.yellow : Color.clear, lineWidth: 1))
                    }
                }.padding(.horizontal, 12)
            }.frame(height: 96)
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
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(t("Параметры", "Parameters")).font(.system(size: 13, weight: .semibold))
                    Spacer()
                    SettingsLink { Image(systemName: "gearshape") }
                        .help(t("Настройки оформления", "Appearance settings"))
                }
                VStack(spacing: 6) {
                    Button { model.importPhotos() } label: {
                        Label(t("Открыть фото", "Open Photos"), systemImage: "photo")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(InspectorButtonStyle(primary: true))
                    .disabled(model.busy || model.pressure != .normal)
                    Button { model.importFolder() } label: {
                        Label(t("Открыть папку", "Open Folder"), systemImage: "folder")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(InspectorButtonStyle())
                    .disabled(model.busy || model.pressure != .normal)
                }.font(.system(size: 11))
            }.padding(12)
            Divider().overlay(Color(white: 0.22))
            zoomInspector
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
                    case .logo: logoControls
                    }
                }.padding(12)
            }
            .frame(maxHeight: .infinity)
            Divider().overlay(Color(white: 0.22))
            exportControls
                .padding(12)
        }.background(Color(white: 0.155))
    }

    private func moveLogo(dx: CGFloat, dy: CGFloat, frame: CGRect, logoRect: CGRect) {
        guard var value = model.logo else { return }
        let sx = Double(model.sessionOutputWidth) / max(1, Double(frame.width))
        let sy = Double(model.sessionOutputHeight) / max(1, Double(frame.height))
        value.x += Double(dx) * sx
        value.y += Double(dy) * sy
        model.updateLogo(x: value.x, y: value.y)
    }

    private var zoomInspector: some View {
        HStack(spacing: 5) {
            Text(t("Масштаб", "Zoom")).font(.system(size: 10)).foregroundStyle(.secondary).fixedSize()
            Spacer(minLength: 2)
            Button { zoomStep(1 / 1.15) } label: { Image(systemName: "minus.magnifyingglass") }
                .buttonStyle(InspectorButtonStyle(height: 26)).fixedSize()
            Text("\(zoomPercent)%").font(.system(size: 10, weight: .medium)).frame(width: 38)
            Button { zoomStep(1.15) } label: { Image(systemName: "plus.magnifyingglass") }
                .buttonStyle(InspectorButtonStyle(height: 26)).fixedSize()
            Button("100%") { setZoom(1) }.buttonStyle(InspectorButtonStyle(height: 26)).fixedSize()
            ViewThatFits(in: .horizontal) {
                Button(t("Вписать", "Fit")) {
                    var next = model.canvasView; next.fit = true; next.zoom = 1; next.centerX = 0.5; next.centerY = 0.5
                    model.setCanvasView(next)
                }.buttonStyle(InspectorButtonStyle(height: 26)).font(.system(size: 10)).fixedSize()
                Button {
                    var next = model.canvasView; next.fit = true; next.zoom = 1; next.centerX = 0.5; next.centerY = 0.5
                    model.setCanvasView(next)
                } label: { Image(systemName: "arrow.up.left.and.arrow.down.right") }
                .buttonStyle(InspectorButtonStyle(height: 26))
                .help(t("Вписать", "Fit"))
                .accessibilityLabel(t("Вписать", "Fit"))
            }
        }.padding(.horizontal, 12).frame(height: 32)
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
                Text("\(Int((model.brushWidth * Double(current?.width ?? 0)).rounded())) px")
                    .font(.system(size: 10)).monospacedDigit().frame(width: 46)
            }
            Toggle(t("Показывать маску", "Show mask"), isOn: $model.showMask)
                .font(.system(size: 11))
            HStack {
                Button(t("Отменить штрих", "Undo stroke")) { model.undoLastStroke() }
                    .buttonStyle(InspectorButtonStyle()).disabled(!model.canUndoStroke)
                Button(t("Очистить", "Clear")) { model.clearMask() }
                    .buttonStyle(InspectorButtonStyle()).disabled(model.strokes.isEmpty || model.retouchBusy)
            }.font(.system(size: 11))
            Button { model.processMask() } label: {
                Text(t("Удалить выделенное", "Remove selection")).frame(maxWidth: .infinity)
            }.buttonStyle(InspectorButtonStyle(primary: true, height: 32))
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
                    Button(t("Готово", "Done")) { model.commitCrop(); tool = .brush }
                        .buttonStyle(InspectorButtonStyle(primary: true))
                        .keyboardShortcut(.defaultAction)
                    Button(t("Отмена", "Cancel")) { model.cancelCrop() }
                        .buttonStyle(InspectorButtonStyle())
                        .keyboardShortcut(.cancelAction)
                    Button(t("Сбросить", "Reset")) { model.resetCrop() }
                        .buttonStyle(InspectorButtonStyle())
                }.font(.system(size: 11))
            } else {
                Button(t("Начать кадрирование", "Start crop")) { model.beginCrop() }
            }
        }
    }

    private var moveControls: some View {
        VStack(alignment: .leading, spacing: 8) {
            section(t("Перемещение", "Move"))
            Text(t("Перетаскивайте холст. Space — временное перемещение.", "Drag the canvas. Space — temporary pan."))
                .font(.system(size: 10)).foregroundStyle(.secondary)
            Text(t("Viewport меняется, кадрирование и рецепт не меняются.", "Only the viewport changes; crop recipe is untouched."))
                .font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }

    private var logoPercent: Double {
        guard let logo = model.logo, let asset = model.logoAsset, asset.width > 0 else { return 100 }
        return Double(logo.width) * Double(model.sessionOutputWidth) / Double(asset.width) * 100
    }

    private func setLogoPercent(_ percent: Double) {
        guard let asset = model.logoAsset, asset.width > 0, model.logo != nil else { return }
        let p = min(10_000, max(1, percent))
        model.updateLogo(width: p / 100 * Double(asset.width) / Double(model.sessionOutputWidth))
    }

    private var logoScalePosition: Double {
        let p = max(1, min(10_000, logoPercent))
        return (log10(p) - 0) / 4
    }

    private var logoScaleBinding: Binding<Double> {
        Binding(get: { logoScalePosition }, set: { pos in
            setLogoPercent(pow(10, max(0, min(1, pos)) * 4))
        })
    }

    private var logoControls: some View {
        VStack(alignment: .leading, spacing: 10) {
            section(t("Логотип", "Logo"))
            if let logo = model.logo {
                Text(URL(fileURLWithPath: logo.path).lastPathComponent).font(.system(size: 10)).lineLimit(1)
                    .truncationMode(.middle)
                Toggle(t("Показывать", "Visible"), isOn: Binding(get: { logo.enabled }, set: { model.updateLogo(enabled: $0) }))
                    .font(.system(size: 11))
                HStack(spacing: 6) {
                    Text(t("Масштаб", "Scale")).font(.system(size: 11))
                    Slider(value: logoScaleBinding, in: 0...1)
                    TextField("", value: Binding(get: { Int(logoPercent.rounded()) }, set: { setLogoPercent(Double($0)) }), format: .number)
                        .textFieldStyle(.roundedBorder).frame(width: 48)
                        .multilineTextAlignment(.trailing)
                    Text("%").font(.system(size: 10))
                }
                HStack {
                    Text(t("100% — исходный размер", "100% — source size"))
                        .font(.system(size: 9)).foregroundStyle(.secondary)
                    Spacer()
                    Button("100%") { setLogoPercent(100) }.font(.system(size: 9))
                }
                HStack(spacing: 6) {
                    Text("X").font(.system(size: 10)).frame(width: 12)
                    TextField("", value: Binding(get: { logo.x }, set: { model.updateLogo(x: $0) }),
                              format: .number.precision(.fractionLength(0)))
                        .textFieldStyle(.roundedBorder).frame(width: 64)
                    Text("px").font(.system(size: 9)).foregroundStyle(.secondary)
                    Button("−10") { model.updateLogo(x: logo.x - 10) }.buttonStyle(InspectorButtonStyle(height: 22))
                    Button("+10") { model.updateLogo(x: logo.x + 10) }.buttonStyle(InspectorButtonStyle(height: 22))
                }
                HStack(spacing: 6) {
                    Text("Y").font(.system(size: 10)).frame(width: 12)
                    TextField("", value: Binding(get: { logo.y }, set: { model.updateLogo(y: $0) }),
                              format: .number.precision(.fractionLength(0)))
                        .textFieldStyle(.roundedBorder).frame(width: 64)
                    Text("px").font(.system(size: 9)).foregroundStyle(.secondary)
                    Button("−10") { model.updateLogo(y: logo.y - 10) }.buttonStyle(InspectorButtonStyle(height: 22))
                    Button("+10") { model.updateLogo(y: logo.y + 10) }.buttonStyle(InspectorButtonStyle(height: 22))
                }
                HStack {
                    Button(t("Применить ко всем", "Apply to all")) { model.applyLogoToAll() }
                        .buttonStyle(InspectorButtonStyle())
                    Button(t("Убрать", "Remove")) { model.removeLogo() }
                        .buttonStyle(InspectorButtonStyle())
                }.font(.system(size: 11))
                Button(t("Другой PNG…", "Another PNG…")) { model.chooseLogo() }
                    .buttonStyle(InspectorButtonStyle())
            } else {
                if let saved = model.persistedLogoName {
                    Text(saved).font(.system(size: 10)).lineLimit(1).truncationMode(.middle)
                    Button(t("Применить сохранённый логотип", "Apply saved logo")) { model.applyPersistedLogo() }
                        .buttonStyle(InspectorButtonStyle(primary: true))
                    Text(t("Логотип не накладывается автоматически на новые фото.", "The logo is not applied automatically to new photos."))
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                Button(t("Выбрать PNG-логотип…", "Choose PNG logo…")) { model.chooseLogo() }
                    .buttonStyle(InspectorButtonStyle())
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
            HStack(spacing: 6) {
                Button("PNG") { exportFormat = .png }
                    .buttonStyle(InspectorButtonStyle(primary: exportFormat == .png, height: 26))
                Button("JPEG") { exportFormat = .jpeg }
                    .buttonStyle(InspectorButtonStyle(primary: exportFormat == .jpeg, height: 26))
            }
            if exportFormat == .jpeg {
                HStack { Text(t("Качество", "Quality")); Slider(value: $exportQuality, in: 0.5...1) }
                    .font(.system(size: 10))
            }
            Button { model.exportPanel(format: exportFormat, quality: exportQuality) } label: {
                Text(t("Экспорт", "Export")).frame(maxWidth: .infinity)
            }.buttonStyle(InspectorButtonStyle(primary: true, height: 36))
                .disabled(model.photos.isEmpty || model.exportBusy || model.sessionReadOnly != nil || model.sourceNeedsDecision)
            if let error = model.exportError {
                Text(error).font(.system(size: 10)).foregroundStyle(.orange).lineLimit(2)
            }
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



private struct V1LogoOverlay: View {
    let logo: SessionLogo
    let asset: CGImage
    let frame: CGRect
    let outputWidth: CGFloat
    let editable: Bool
    let onMove: (CGFloat, CGFloat, CGRect, CGRect) -> Void
    @State private var hovering = false
    @State private var lastTranslation: CGSize = .zero

    var body: some View {
        let aw = CGFloat(asset.width), ah = CGFloat(asset.height)
        let w = frame.width * CGFloat(logo.width)
        let h = w * ah / max(1, aw)
        let sx = frame.width / max(1, outputWidth)
        let cx = frame.midX + CGFloat(logo.x) * sx
        let cy = frame.midY + CGFloat(logo.y) * sx
        let rect = CGRect(x: cx - w/2, y: cy - h/2, width: w, height: h)
        ZStack {
            Canvas { context, _ in
                context.draw(Image(decorative: asset, scale: 1), in: rect)
            }.allowsHitTesting(false)
            if editable && hovering {
                RoundedRectangle(cornerRadius: 2)
                    .stroke(Color.white.opacity(0.35), lineWidth: 1)
                    .frame(width: max(12, rect.width), height: max(12, rect.height))
                    .position(x: rect.midX, y: rect.midY)
                    .allowsHitTesting(false)
            }
            if editable {
                Rectangle().fill(Color.clear)
                    .frame(width: max(12, rect.width), height: max(12, rect.height))
                    .position(x: rect.midX, y: rect.midY)
                    .contentShape(Rectangle())
                    .onHover { inside in
                        hovering = inside
                        if inside { NSCursor.openHand.set() } else { NSCursor.arrow.set() }
                    }
                    .gesture(DragGesture(minimumDistance: 1)
                        .onChanged { value in
                            NSCursor.closedHand.set()
                            let dx = value.translation.width - lastTranslation.width
                            let dy = value.translation.height - lastTranslation.height
                            lastTranslation = value.translation
                            onMove(dx, dy, frame, rect)
                        }
                        .onEnded { _ in
                            lastTranslation = .zero
                            NSCursor.openHand.set()
                        })
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
        Canvas { context, size in
            let strip: CGFloat = 22
            // Fixed ruler bands, independent of image pan.
            context.fill(Path(CGRect(x: 0, y: 0, width: size.width, height: strip)), with: .color(Color(white: 0.14)))
            context.fill(Path(CGRect(x: 0, y: 0, width: strip, height: size.height)), with: .color(Color(white: 0.14)))
            context.draw(Text("px").font(.system(size: 8, weight: .semibold)).foregroundStyle(.secondary),
                         at: CGPoint(x: 11, y: 11))
            guard imageRect.width > 1, imageRect.height > 1 else { return }
            let label = Color(white: 0.66)
            let tick = Color(white: 0.45)
            let scale = imageRect.width / imageSize.width
            var step: CGFloat = 100
            while step * scale < 48 { step *= 2 }
            var px: CGFloat = 0
            while px <= imageSize.width {
                let x = imageRect.minX + px * scale
                if x >= strip && x <= size.width {
                    context.stroke(Path { p in p.move(to: CGPoint(x:x,y:0)); p.addLine(to: CGPoint(x:x,y:8)) },
                                   with: .color(tick), lineWidth: 0.7)
                    context.draw(Text("\(Int(px))").font(.system(size: 8)).foregroundStyle(label),
                                 at: CGPoint(x:x+10,y:12))
                }
                px += step
            }
            let yscale = imageRect.height / imageSize.height
            var ypx: CGFloat = 0
            var ystep: CGFloat = 100
            while ystep * yscale < 36 { ystep *= 2 }
            while ypx <= imageSize.height {
                let y = imageRect.minY + ypx * yscale
                if y >= strip && y <= size.height {
                    context.stroke(Path { p in p.move(to: CGPoint(x:0,y:y)); p.addLine(to: CGPoint(x:8,y:y)) },
                                   with: .color(tick), lineWidth: 0.7)
                    context.draw(Text("\(Int(ypx))").font(.system(size: 8)).foregroundStyle(label),
                                 at: CGPoint(x:12,y:y+5), anchor: .leading)
                }
                ypx += ystep
            }
            let frame = CGRect(x: imageRect.minX + CGFloat(crop.x)*imageRect.width,
                               y: imageRect.minY + CGFloat(crop.y)*imageRect.height,
                               width: CGFloat(crop.width)*imageRect.width,
                               height: CGFloat(crop.height)*imageRect.height)
            var outside = Path(); outside.addRect(imageRect); outside.addRect(frame)
            context.fill(outside, with: .color(.black.opacity(0.24)), style: FillStyle(eoFill: true))
            context.stroke(Path(frame.insetBy(dx:-1,dy:-1)), with: .color(.black.opacity(0.8)), lineWidth: 3)
            context.stroke(Path(frame), with: .color(.yellow), lineWidth: 2)
        }.allowsHitTesting(false)
    }
}


private struct WindowTitleAccessor: NSViewRepresentable {
    let title: String
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async { view.window?.title = title }
        return view
    }
    func updateNSView(_ view: NSView, context: Context) {
        DispatchQueue.main.async { view.window?.title = title }
    }
}


private struct InspectorButtonStyle: ButtonStyle {
    var primary = false
    var height: CGFloat = 28
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 11, weight: .medium))
            .lineLimit(1)
            .padding(.horizontal, 7)
            .frame(height: height)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(primary ? Color.yellow : Color(white: configuration.isPressed ? 0.28 : 0.21))
            )
            .foregroundStyle(primary ? Color.black : Color(white: 0.88))
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .opacity(configuration.isPressed ? 0.78 : 1)
    }
}

private struct LogoGlyph: View {
    var body: some View {
        Group {
            if let url = Bundle.main.url(forResource: "LogoGlyph", withExtension: "png"),
               let image = NSImage(contentsOf: url) {
                Image(nsImage: image)
                    .renderingMode(.template)
                    .resizable()
                    .scaledToFit()
            } else {
                Image(systemName: "signature")
            }
        }
        .frame(width: 36, height: 24)
        .accessibilityLabel("Логотип")
    }
}
