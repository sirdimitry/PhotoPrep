import SwiftUI

@MainActor enum NativeIdentity {
    static let identifier = "com.sirdimitry.PhotoPrep.Native"
    // Standard defaults already use this app's distinct bundle identity/container.
    // A named suite can be unavailable under App Sandbox; never force unwrap it.
    static let preferences = UserDefaults.standard
}

@main
struct PhotoPrepNativeApp: App {
    @StateObject private var workspace = WorkspaceModel()
    @AppStorage("ui/language", store: NativeIdentity.preferences) private var language = "ru"
    @AppStorage("ui/appearance", store: NativeIdentity.preferences) private var appearance = "dark"

    var body: some Scene {
        Window("PhotoPrep Native", id: "workspace") {
            WorkspaceView(model: workspace, language: language)
                .preferredColorScheme(appearance == "light" ? .light : .dark)
                .frame(minWidth: 880, minHeight: 600)
                .onDisappear { workspace.suspend() }
                .onAppear { workspace.resume() }
                .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
                    workspace.cancel()
                }
        }
        .defaultSize(width: 1160, height: 760)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button(language == "ru" ? "Открыть фотографии…" : "Open Photos…") { workspace.importPhotos() }
                    .keyboardShortcut("o").disabled(workspace.busy || workspace.pressure != .normal)
                Button(language == "ru" ? "Новая коллекция" : "New Collection") { workspace.clear() }
                    .keyboardShortcut("n")
            }
        }
        Settings {
            Form {
                Picker(language == "ru" ? "Язык" : "Language", selection: $language) {
                    Text("Русский").tag("ru")
                    Text("English").tag("en")
                }
                Picker(language == "ru" ? "Оформление" : "Appearance", selection: $appearance) {
                    Text(language == "ru" ? "Тёмное" : "Dark").tag("dark")
                    Text(language == "ru" ? "Светлое" : "Light").tag("light")
                }
            }.padding(24).frame(width: 360)
        }
    }
}

private struct WorkspaceView: View {
    @ObservedObject var model: WorkspaceModel
    let language: String
    private var ru: Bool { language == "ru" }
    private func text(_ russian: String, _ english: String) -> String { ru ? russian : english }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 24) {
                Text("PhotoPrep Native").font(.headline)
                Text(text("Ретушь  →  Кадрирование  →  Логотип  →  Экспорт",
                          "Retouch  →  Crop  →  Logo  →  Export"))
                    .font(.callout).foregroundStyle(.secondary)
                Spacer()
                Text(text("В разработке", "In development")).font(.caption).foregroundStyle(.secondary)
            }.padding(18)
            Divider()
            HSplitView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(text("Коллекция", "Collection")).font(.headline).padding(.horizontal)
                    List(model.photos, selection: $model.selected) { photo in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(photo.url.lastPathComponent).lineLimit(1)
                            Text("\(photo.width) × \(photo.height)").font(.caption).foregroundStyle(.secondary)
                        }.padding(.vertical, 4).tag(photo.url)
                    }.listStyle(.sidebar)
                }.padding(.top, 18).frame(minWidth: 180, idealWidth: 230, maxWidth: 310)
                ZStack {
                    Color(nsColor: .underPageBackgroundColor)
                    if let preview = model.preview {
                        Image(decorative: preview.image, scale: 1)
                            .resizable().scaledToFit().padding(24)
                            .accessibilityLabel(preview.header.url.lastPathComponent)
                    } else if !model.busy {
                        ContentUnavailableView {
                            Label(text("Откройте фотографии", "Open your photos"), systemImage: "photo.on.rectangle")
                        } description: {
                            Text(text("Оригиналы остаются неизменными. Обработка будет выполняться на вашем Mac.",
                                      "Originals stay unchanged. Processing will run on your Mac."))
                        } actions: {
                            Button(text("Открыть фотографии…", "Open Photos…")) { model.importPhotos() }
                                .buttonStyle(.borderedProminent).tint(.yellow)
                                .disabled(model.pressure != .normal)
                        }
                    }
                    if model.busy { ProgressView().controlSize(.large) }
                }.frame(minWidth: 400)
                VStack(alignment: .leading, spacing: 16) {
                    Label(text("Ретушь", "Retouch"), systemImage: "paintbrush.pointed").font(.headline)
                    Text(text("Удаление логотипов и восстановление фона",
                              "Logo removal and background restoration")).font(.subheadline)
                    Text(text("Движок Core ML ещё не подключён. Сейчас доступен безопасный просмотр фотографий.",
                              "The Core ML engine is not connected yet. Photo preview is available."))
                        .font(.callout).foregroundStyle(.secondary)
                    Divider()
                    Label(text("Локальная обработка", "Local processing"), systemImage: "lock.shield")
                    Text(text("Просмотр до 2048 пикселей. При нехватке памяти загрузка останавливается.",
                              "Preview up to 2048 pixels. Loading stops when memory is low."))
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                }.padding(20).frame(minWidth: 220, idealWidth: 260, maxWidth: 300)
            }
            Divider()
            HStack {
                if model.busy {
                    Text(text("Загрузка…", "Loading…"))
                    Button(text("Отменить", "Cancel")) { model.cancel() }
                } else {
                    Text("\(model.photos.count) " + text("фото", model.photos.count == 1 ? "photo" : "photos"))
                }
                Spacer()
                if let issue = model.issue { Text(message(issue)).foregroundStyle(.orange).lineLimit(2) }
            }.font(.caption).padding(12)
        }
        .toolbar {
            Button { model.importPhotos() } label: {
                Label(text("Открыть фотографии", "Open Photos"), systemImage: "plus")
            }.disabled(model.busy || model.pressure != .normal)
        }
    }

    private func message(_ failure: ResourceFailure) -> String {
        switch failure {
        case .imageTooLarge, .invalidDimensions:
            text("Фото превышает предел просмотра: 40 Мп.", "Photo exceeds the 40 MP preview limit.")
        case .insufficientMemory:
            text("Недостаточно свободной памяти. Закройте другие задачи и повторите.",
                 "Not enough available memory. Close other tasks and try again.")
        case .memoryPressure:
            text("Загрузка остановлена: системе нужна память. Откройте фото повторно после освобождения памяти.",
                 "Loading stopped: the system needs memory. Reopen the photo when memory is available.")
        case .invalidImage:
            text("Не удалось прочитать фото. Поддерживаются однокадровые JPEG, PNG, TIFF, BMP и WebP.",
                 "Cannot read photo. Single-frame JPEG, PNG, TIFF, BMP and WebP are supported.")
        }
    }
}
