import AppKit
import PulseCore
import SwiftUI

/// Everything the window shows, and the actions it offers. Lives as long as the app.
@MainActor @Observable
final class PulseStore {
    let home: URL
    private(set) var data: PulseData?
    /// The project on screen; nil shows the homepage.
    var selectedSlug: String?
    var selectedGroup: String? = "briefing"
    /// The roadmap row that's open, showing its prompt, commands and notes.
    var expandedRow: String?
    /// A stage the roadmap should scroll to (a click on one of the header's small bars).
    var roadmapTarget: String?
    private(set) var isRefreshing = false
    /// Shown in a banner until closed.
    var problem: String?
    private(set) var books: [String: CommentBook] = [:]
    /// The owner's checklist ticks, per project.
    private(set) var tickBooks: [String: TickBook] = [:]
    /// Reads briefings aloud.
    let speaker = Speaker()
    /// A project Claude is being asked to look at (the "Ask Claude" button), while it works.
    private(set) var asking: String?
    var schedule: RefreshSchedule {
        didSet {
            if schedule != oldValue, UserDefaults.standard.integer(forKey: Self.scheduleKey) != schedule.rawValue {
                UserDefaults.standard.set(schedule.rawValue, forKey: Self.scheduleKey)
            }
        }
    }
    let hasObsidian: Bool
    private var loop: Task<Void, Never>?
    private static let scheduleKey = "refreshSchedule"

    init(home: URL) {
        self.home = home
        schedule = RefreshSchedule(rawValue: UserDefaults.standard.integer(forKey: Self.scheduleKey)) ?? .manual
        hasObsidian = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "md.obsidian") != nil
    }

    var dataURL: URL { home.appendingPathComponent("out/data.json") }
    var projectsURL: URL { home.appendingPathComponent("projects.json") }
    var generatedAt: Date? { PulseDate.parse(data?.generatedAt) }
    var project: ProjectView? {
        data?.projects.first { $0.slug == selectedSlug }
    }

    /// Loads the last reading at once, then refreshes whenever the schedule says so (checked every minute).
    func startIfNeeded() {
        guard loop == nil else { return }
        load()
        loop = Task { [weak self] in
            if let self, self.data == nil || self.schedule.isDue(lastRefresh: self.generatedAt, now: Date()) {
                await self.refresh()
            }
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(60))
                guard let self else { return }
                if self.schedule.isDue(lastRefresh: self.generatedAt, now: Date()) {
                    await self.refresh()
                }
            }
        }
    }

    func load() {
        guard FileManager.default.fileExists(atPath: dataURL.path) else { return }
        do {
            let loaded = try PulseDataFile.load(from: dataURL)
            data = loaded
            if selectedSlug != nil, !loaded.projects.contains(where: { $0.slug == selectedSlug }) {
                selectedSlug = nil  // it was removed: back to the homepage
            }
            for project in loaded.projects where tickBooks[project.slug] == nil {
                tickBooks[project.slug] = TickBook.load(home.appendingPathComponent("comments/\(project.slug).ticks.json"))
            }
            for project in loaded.projects where books[project.slug] == nil {
                let book = CommentBook.load(commentsURL(for: project.slug))
                books[project.slug] = book
                if let trouble = book.problem { problem = trouble }
            }
        } catch {
            problem = "Pulse couldn't read its last reading: \(error.localizedDescription)"
        }
    }

    func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            try await Engine.run(home: home)
            load()
        } catch {
            problem = "Refresh didn't finish. \(error)"
        }
    }

    // MARK: Comments

    func commentsURL(for slug: String) -> URL { home.appendingPathComponent("comments/\(slug).json") }

    func comments(for key: String) -> [Comment] {
        guard let slug = project?.slug else { return [] }
        return books[slug]?.comments(for: key) ?? []
    }

    func book(for slug: String) -> CommentBook? { books[slug] }

    /// Ticks a note off (or back on): notes double as your own to-dos.
    func setDone(_ comment: Comment, in key: String, done: Bool) {
        guard let slug = project?.slug, var book = books[slug] else { return }
        do {
            try book.setDone(comment.id, in: key, done: done)
            books[slug] = book
        } catch {
            problem = "Pulse couldn't save that: \(error.localizedDescription)"
        }
    }

    // MARK: Ask Claude

    /// The "Ask Claude" button: once the owner agrees, Claude reads the project (read-only) starting from what Pulse
    /// found, and its answer shows in a card of its own after a refresh.
    func askClaude(about project: ProjectView) {
        let alert = NSAlert()
        alert.messageText = "Ask Claude to look at \(project.name)?"
        alert.informativeText = "Claude reads the project's files, read-only (it can't change anything, run commands "
            + "or go online), for up to 4 minutes. It starts from what Pulse found and looks for what that misses, "
            + "then writes its findings in a card of its own.\n\nThis is the only part of Pulse that uses AI: it counts "
            + "toward your Claude plan (about a minute of work; roughly $0.40 at API prices)."
        alert.addButton(withTitle: "Ask Claude")
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        asking = project.slug
        Task {
            do {
                try await Engine.run(home: home, arguments: ["--ask", project.slug, "--no-open"])
                load()
            } catch {
                problem = "Claude couldn't look this time. \(error)"
            }
            asking = nil
        }
    }

    // MARK: Checklists

    /// Loaded with the data (never while a view is drawn); a project that just appeared reads its file once.
    func ticks(for slug: String) -> TickBook {
        tickBooks[slug] ?? TickBook.load(home.appendingPathComponent("comments/\(slug).ticks.json"))
    }

    /// Ticks a checklist item ("ticked"), says it doesn't apply ("skipped"), or takes the tick away (nil).
    func setTick(_ key: String, to state: String?, in slug: String) {
        var book = ticks(for: slug)
        do {
            try book.set(key, to: state)
            tickBooks[slug] = book
        } catch {
            problem = "Pulse couldn't save that tick: \(error.localizedDescription)"
        }
    }

    /// Adds a checklist to the project on screen, or takes one away; then reads the project again.
    func setChecklist(_ list: String, on: Bool, detected: Bool) {
        guard let project else { return }
        do {
            try ProjectsFile.setChecklist(list, on: on, detected: detected, project: project.name, in: projectsURL)
            Task { await refresh() }
        } catch {
            problem = "Pulse couldn't change the checklists: \(error.localizedDescription)"
        }
    }

    /// Opens a project on one of its lists (from the homepage).
    func go(to slug: String, group: String? = "roadmap", row: String? = nil) {
        selectedSlug = slug
        selectedGroup = group
        expandedRow = row
    }

    /// "Where it stands", ready to paste into a new chat with Claude, ChatGPT or Meta AI.
    func copyStatus(of project: ProjectView) {
        copy(Handoff.status(of: project, notes: books[project.slug]))
    }

    func addComment(_ text: String, to key: String) {
        guard let slug = project?.slug, var book = books[slug] else { return }
        do {
            try book.add(text, to: key)
            books[slug] = book
        } catch {
            problem = "Pulse couldn't save that comment: \(error.localizedDescription)"
        }
    }

    func removeComment(_ comment: Comment, from key: String) {
        guard let slug = project?.slug, var book = books[slug] else { return }
        do {
            try book.remove(comment.id, from: key)
            books[slug] = book
        } catch {
            problem = "Pulse couldn't remove that comment: \(error.localizedDescription)"
        }
    }

    /// Items that have comments but aren't on the list any more.
    var goneKeys: [String] {
        guard let project, let book = books[project.slug] else { return [] }
        var present = Set((project.groups ?? []).flatMap { $0.items.map(\.key) })
        present.formUnion((project.roadmap?.stages ?? []).flatMap { $0.rows.map(\.key) })
        present.insert(Handoff.projectKey)
        return book.orphans(present: present)
    }

    // MARK: Projects

    /// Pick one folder or several. A folder that holds projects (like ~/Developer) can add each one as its own tab.
    func chooseFolderToAdd() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = true
        panel.prompt = "Add to Pulse"
        panel.message = "Choose a project folder, yours or anyone's. Pulse only reads it and works out its layout by itself."
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Developer")
        guard panel.runModal() == .OK else { return }
        var folders: [URL] = []
        for folder in panel.urls {
            let inside = ProjectFolders.projectsInside(folder)
            guard !ProjectFolders.isProject(folder), inside.count >= 2 else {
                folders.append(folder)
                continue
            }
            let alert = NSAlert()
            alert.messageText = "“\(folder.lastPathComponent)” holds \(inside.count) projects"
            let names = inside.prefix(12).map(\.lastPathComponent).joined(separator: ", ")
            alert.informativeText = names + (inside.count > 12 ? ", …" : "")
                + "\n\nAdd each one as its own tab, or the whole folder as one project?"
            alert.addButton(withTitle: "Add \(inside.count) Projects")
            alert.addButton(withTitle: "Add as One")
            alert.addButton(withTitle: "Cancel")
            switch alert.runModal() {
            case .alertFirstButtonReturn: folders += inside
            case .alertSecondButtonReturn: folders.append(folder)
            default: continue
            }
        }
        add(folders: folders)
    }

    /// Adds folders to Pulse and opens the first one's briefing once it's read.
    func add(folders: [URL]) {
        guard !folders.isEmpty else { return }
        do {
            let result = try ProjectsFile.add(folders: folders, to: projectsURL)
            if !result.alreadyThere.isEmpty {
                problem = "Already in Pulse: \(result.alreadyThere.joined(separator: ", "))."
            }
            guard let first = result.added.first else { return }
            Task {
                await refresh()
                if let added = data?.projects.first(where: { $0.name == first }) {
                    selectedSlug = added.slug
                    selectedGroup = "briefing"
                }
            }
        } catch {
            problem = "Pulse couldn't update its project list: \(error.localizedDescription)"
        }
    }

    /// Switches one of Pulse's readers on or off for the project on screen, then reads it again.
    func setReader(_ reader: Reader, on: Bool) {
        guard let project else { return }
        do {
            try ProjectsFile.setReader(reader.id, on: on, project: project.name, in: projectsURL)
            Task { await refresh() }
        } catch {
            problem = "Pulse couldn't change what it reads: \(error.localizedDescription)"
        }
    }

    func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    func confirmRemove(_ project: ProjectView) {
        let alert = NSAlert()
        alert.messageText = "Remove \(project.name) from Pulse?"
        alert.informativeText = "Its folder isn't touched, and your comments on it are kept."
        alert.addButton(withTitle: "Remove")
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        do {
            try ProjectsFile.remove(named: project.name, from: projectsURL)
            Task { await refresh() }
        } catch {
            problem = "Pulse couldn't update its project list: \(error.localizedDescription)"
        }
    }

    // MARK: Opening files

    func open(_ path: String) {
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    func openInObsidian(_ path: String) {
        let encoded = path.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? path
        if let url = URL(string: "obsidian://open?path=\(encoded)") { NSWorkspace.shared.open(url) }
    }

    func showInFinder(_ path: String) {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }
}
