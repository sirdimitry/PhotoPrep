import SwiftUI
import Darwin

@MainActor enum NativeIdentity {
    static let identifier = "com.sirdimitry.PhotoPrep.Native"
    // Standard defaults already use this app's distinct bundle identity/container.
    // A named suite can be unavailable under App Sandbox; never force unwrap it.
    static let preferences = UserDefaults.standard
}

#if DEBUG
enum DebugLaunchOptions {
    static var openPhoto: URL? {
        guard let index = CommandLine.arguments.firstIndex(of: "--photoprep-open"),
              CommandLine.arguments.indices.contains(index + 1) else { return nil }
        return URL(fileURLWithPath: CommandLine.arguments[index + 1])
    }

    static var panelDirectory: URL? {
        guard let index = CommandLine.arguments.firstIndex(of: "--photoprep-panel-dir"),
              CommandLine.arguments.indices.contains(index + 1) else { return nil }
        return URL(fileURLWithPath: CommandLine.arguments[index + 1], isDirectory: true)
    }
}
#endif

@MainActor
final class PhotoPrepAppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let workspace = WorkspaceModel.current else { return .terminateNow }
        return workspace.confirmTermination() ? .terminateNow : .terminateCancel
    }
}

@main
struct PhotoPrepMain {
    static func main() {
        if CommandLine.arguments.contains("--photoprep-worker") {
            exit(WorkerMain.run(arguments: CommandLine.arguments))
        }
        if CommandLine.arguments.contains("--photoprep-e1-selftest") {
            exit(WorkerMain.selfTest())
        }
        if CommandLine.arguments.contains("--photoprep-e1-timeout-selftest") {
            exit(WorkerMain.timeoutSelfTest())
        }
        if CommandLine.arguments.contains("--photoprep-e1-crash-selftest") {
            exit(WorkerMain.crashSelfTest())
        }
        if CommandLine.arguments.contains("--photoprep-e1-failure-selftest") {
            exit(WorkerMain.failureSelfTest())
        }
        if CommandLine.arguments.contains("--photoprep-e1-hang-selftest") {
            exit(WorkerMain.hangSelfTest())
        }
        if CommandLine.arguments.contains("--photoprep-e1-hard-kill-selftest") {
            exit(WorkerMain.hardKillSelfTest())
        }
        if CommandLine.arguments.contains("--photoprep-e1-cancel-before-start-selftest") {
            exit(WorkerMain.cancelBeforeStartSelfTest())
        }
        if CommandLine.arguments.contains("--photoprep-e1-cancel-selftest") {
            exit(WorkerMain.cancelSelfTest())
        }
        if CommandLine.arguments.contains("--photoprep-e1-file-selftest") {
            exit(WorkerMain.fileSelfTest())
        }
        if CommandLine.arguments.contains("--photoprep-e1-pressure-selftest") {
            exit(WorkerMain.pressureSelfTest())
        }
        if CommandLine.arguments.contains("--photoprep-e1-stress-selftest") {
            exit(WorkerMain.stressSelfTest())
        }
        if CommandLine.arguments.contains("--photoprep-e1-cancel-latency-selftest") {
            exit(WorkerMain.cancelLatencySelfTest())
        }
        if CommandLine.arguments.contains("--photoprep-session-selftest") {
            exit(WorkerMain.sessionSelfTest())
        }
        PhotoPrepNativeApp.main()
    }
}

struct PhotoPrepNativeApp: App {
    @NSApplicationDelegateAdaptor(PhotoPrepAppDelegate.self) private var appDelegate
    @StateObject private var workspace = WorkspaceModel()
    @AppStorage("ui/language", store: NativeIdentity.preferences) private var language = "ru"
    @AppStorage("ui/appearance", store: NativeIdentity.preferences) private var appearance = "dark"

    var body: some Scene {
        Window("PhotoPrep Native", id: "workspace") {
            V1WorkspaceView(model: workspace, language: language)
                .preferredColorScheme(appearance == "light" ? .light : .dark)
                .frame(minWidth: 880, minHeight: 560)
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
                Button(language == "ru" ? "Новая коллекция" : "New Collection") { workspace.newCollection() }
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
