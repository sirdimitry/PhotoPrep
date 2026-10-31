import SwiftUI
import AppKit

final class WindowCloseGuard: NSObject, NSWindowDelegate {
    weak var workspace: WorkspaceModel?

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        guard let workspace else { return true }
        switch workspace.confirmUnsaved("Закрытие окна") {
        case .discard: return true
        case .save:
            workspace.saveSessionPanel()
            return false
        case .cancel: return false
        }
    }
}

struct WindowCloseGuardView: NSViewRepresentable {
    let workspace: WorkspaceModel

    func makeCoordinator() -> WindowCloseGuard {
        let guardObject = WindowCloseGuard()
        guardObject.workspace = workspace
        return guardObject
    }

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            view.window?.delegate = context.coordinator
        }
        return view
    }

    func updateNSView(_ view: NSView, context: Context) {
        context.coordinator.workspace = workspace
        DispatchQueue.main.async {
            if view.window?.delegate !== context.coordinator {
                view.window?.delegate = context.coordinator
            }
        }
    }
}
