import AppKit
import PulseCore
import SwiftUI

@main
struct PulseMain {
    static func main() {
        if CommandLine.arguments.contains("--selftest") {
            exit(SelfTest.run())
        }
        PulseApp.main()
    }
}

struct PulseApp: App {
    @State private var store = PulseStore(home: PulseHome.find())

    init() {
        NSApplication.shared.setActivationPolicy(.regular)
    }

    var body: some Scene {
        WindowGroup("Pulse") {
            ContentView()
                .environment(store)
                .frame(minWidth: 900, minHeight: 620)
                .onAppear { store.startIfNeeded() }
        }
        .defaultSize(width: 1140, height: 820)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Refresh") { Task { await store.refresh() } }
                    .keyboardShortcut("r")
                Button("Add a Project…") { store.chooseFolderToAdd() }
                    .keyboardShortcut("o")
                Button("Home") { store.selectedSlug = nil }
                    .keyboardShortcut("0")
            }
        }
    }
}

/// `Pulse --selftest`: reads the last data and comments without opening a window, prints what it found.
enum SelfTest {
    static func run() -> Int32 {
        let home = PulseHome.find()
        do {
            let data = try PulseDataFile.load(from: home.appendingPathComponent("out/data.json"))
            print("Pulse self-test: \(data.projects.count) project(s), read at \(data.generatedAt), home \(home.path)")
            for line in data.desk?.lines ?? [] { print("  » \(line.text)") }
            for project in data.projects {
                if let error = project.error {
                    print("  \(project.name): couldn't be read. \(error)")
                    continue
                }
                let groups = (project.groups ?? []).map { "\($0.title) \($0.items.count)" }.joined(separator: " · ")
                let summary = project.summary.map { "\($0.stepsDone) of \($0.stepsTotal) steps, \($0.workDonePct)%" } ?? ""
                print("  \(project.name): \(summary) · \(groups)")
                let rows = (project.roadmap?.stages ?? []).flatMap(\.rows).count
                let next = project.home?.next.map { "next: \($0.label) \($0.title)" } ?? "no next step"
                print("    roadmap: \(rows) rows · \(next) · waiting on you: \(project.home?.needsYou ?? 0)")
                let book = CommentBook.load(home.appendingPathComponent("comments/\(project.slug).json"))
                print("    comments on \(book.byItem.count) item(s)")
                let gauges = (project.gauges ?? []).map { "\($0.label) \($0.state)" }.joined(separator: " · ")
                print("    briefing: \(project.brief?.lines.count ?? 0) lines · \(gauges)")
                if let move = project.brief?.close { print("    \(move.text)") }
                let lists = (project.checklists ?? []).map { "\($0.title) \($0.done)/\($0.total)" }.joined(separator: " · ")
                print("    claude: \(project.claude?.sessionCount ?? 0) sessions · checklists: \(lists)")
            }
            return 0
        } catch {
            print("Pulse self-test failed: \(error)")
            return 1
        }
    }
}
