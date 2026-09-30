import PulseCore
import SwiftUI

// MARK: - The window

struct ContentView: View {
    @Environment(PulseStore.self) private var store

    var body: some View {
        VStack(spacing: 0) {
            TopBar()
            Divider()
            if let problem = store.problem {
                ProblemBanner(text: problem) { store.problem = nil }
            }
            if let project = store.project {
                if let error = project.error {
                    ProjectError(name: project.name, error: error)
                } else {
                    ProjectScreen(project: project)
                }
            } else if let data = store.data, !data.projects.isEmpty {
                HomeView(data: data)
            } else if store.isRefreshing {
                ProgressView("Reading your projects…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                NoProjects()
            }
        }
    }
}

/// Home and the project tabs on the left; refresh and the schedule on the right.
struct TopBar: View {
    @Environment(PulseStore.self) private var store

    var body: some View {
        @Bindable var store = store
        HStack(spacing: 6) {
            Button {
                store.selectedSlug = nil
            } label: {
                Label("Home", systemImage: "house")
            }
            .buttonStyle(TabButtonStyle(selected: store.selectedSlug == nil))
            .help("Every project at a glance (⌘0)")
            ScrollView(.horizontal, showsIndicators: false) {  // many projects: the tabs scroll sideways
                HStack(spacing: 6) {
                    ForEach(store.data?.projects ?? []) { project in
                        Button(project.name) {
                            store.selectedSlug = project.slug
                            store.expandedRow = nil
                        }
                        .buttonStyle(TabButtonStyle(selected: project.slug == store.project?.slug))
                        .contextMenu {
                            Button("Remove from Pulse…") { store.confirmRemove(project) }
                        }
                    }
                    Button {
                        store.chooseFolderToAdd()
                    } label: {
                        Label("Add a project", systemImage: "plus")
                            .lineLimit(1)
                            .fixedSize()
                    }
                    .buttonStyle(.borderless)
                    .padding(.leading, 6)
                    .help("Pick any project folder. Pulse only reads it.")
                }
            }

            Spacer(minLength: 12)

            Text(status)
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .fixedSize()
            Button {
                Task { await store.refresh() }
            } label: {
                if store.isRefreshing {
                    ProgressView().controlSize(.small).frame(width: 60)
                } else {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
            .help("Read every project again now (⌘R)")
            Picker("Refresh by itself", selection: $store.schedule) {
                ForEach(RefreshSchedule.allCases) { schedule in
                    Text(schedule.label).tag(schedule)
                }
            }
            .labelsHidden()
            .fixedSize()
            .help("How often Pulse refreshes by itself")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
    }

    private var status: String {
        guard let at = store.generatedAt else { return "Not read yet" }
        var text = "Refreshed \(at.formatted(date: .omitted, time: .shortened))"
        if !Calendar.current.isDateInToday(at) { text += ", \(at.formatted(.dateTime.day().month()))" }
        if let next = store.schedule.next(after: at), next > Date() {
            text += " · next \(next.formatted(date: .omitted, time: .shortened))"
        }
        return text
    }
}

struct TabButtonStyle: ButtonStyle {
    let selected: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .lineLimit(1)
            .fixedSize()
            .font(.system(size: 13, weight: selected ? .semibold : .regular))
            .foregroundStyle(selected ? Color.primary : Color.secondary)
            .padding(.horizontal, 12)
            .padding(.vertical, 5)
            .background(RoundedRectangle(cornerRadius: 7).fill(selected ? Color.primary.opacity(0.08) : .clear))
            .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(selected ? Color.primary.opacity(0.15) : .clear))
            .opacity(configuration.isPressed ? 0.7 : 1)
            .contentShape(Rectangle())
    }
}

struct ProblemBanner: View {
    let text: String
    let close: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            Text(text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
            Button("Close", action: close).buttonStyle(.borderless)
        }
        .font(.callout)
        .padding(10)
        .background(Color.orange.opacity(0.14))
    }
}

struct NoProjects: View {
    @Environment(PulseStore.self) private var store

    private var found: [ClaudeFolder] { store.data?.claudeFolders ?? [] }

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "waveform.circle").font(.system(size: 46)).foregroundStyle(HUD.accent)
            Text("Welcome to Pulse").font(.largeTitle.bold())
            Text("Pulse reads your project folders and tells you where each one stands: what's next, what waits on "
                 + "you, what broke. It never changes a project, uses no internet and no AI.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .frame(maxWidth: 560)
            if !found.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("You've used Claude Code in \(found.count) folder\(found.count == 1 ? "" : "s"):").font(.headline)
                    ForEach(found.prefix(8)) { folder in
                        HStack {
                            Image(systemName: "folder").foregroundStyle(.secondary)
                            Text((folder.path as NSString).abbreviatingWithTildeInPath).lineLimit(1)
                            Spacer()
                            if let last = PulseDate.parse(folder.last) {
                                Text(last.formatted(.relative(presentation: .named))).font(.caption).foregroundStyle(.secondary)
                            }
                            Button("Add") { store.add(folders: [URL(fileURLWithPath: folder.path)]) }
                        }
                    }
                    if found.count > 1 {
                        Button("Add all \(found.count)") { store.add(folders: found.map { URL(fileURLWithPath: $0.path) }) }
                            .buttonStyle(.borderedProminent)
                    }
                }
                .padding(16)
                .frame(maxWidth: 560)
                .background(RoundedRectangle(cornerRadius: 12).fill(Color.primary.opacity(0.04)))
            }
            Button("Choose a folder…") { store.chooseFolderToAdd() }
                .controlSize(.large)
            Text("Pulse also reads your Claude Code conversations for these folders (on this Mac, never uploaded): "
                 + "your prompts, the tests Claude ran, sessions that stopped. You can turn that off per project.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 520)
        }
        .padding(30)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct ProjectError: View {
    let name: String
    let error: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Pulse couldn't read \(name)").font(.title2.bold())
            Text(error).textSelection(.enabled).foregroundStyle(.secondary)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

// MARK: - One project

struct ProjectScreen: View {
    let project: ProjectView
    @Environment(PulseStore.self) private var store

    private var groups: [ItemGroup] { project.groups ?? [] }

    var body: some View {
        VStack(spacing: 0) {
            if store.selectedGroup != "briefing" {  // the briefing has its own header
                ProgressHeader(project: project)
                    .padding(.horizontal, 20)
                    .padding(.top, 16)
                    .padding(.bottom, 10)
                SinceStrip(since: project.since)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 12)
                Divider()
            }
            HStack(spacing: 0) {
                GroupList(project: project, groups: groups, roadmap: project.roadmap,
                          noteCount: store.book(for: project.slug)?.count ?? 0)
                    .frame(width: 240)
                Divider()
                content
            }
        }
    }

    @ViewBuilder private var content: some View {
        switch store.selectedGroup ?? "briefing" {
        case "briefing":
            ProjectBriefing(project: project).id(project.slug)
        case "claude":
            ClaudeView(project: project).id(project.slug)
        case "prompts":
            PromptsView(project: project, global: store.data?.globalPrompts ?? []).id(project.slug)
        case "checklists":
            ChecklistsView(project: project).id(project.slug)
        case "notes", "gone":
            NotesView(project: project)
        case "roadmap" where project.roadmap != nil:
            RoadmapView(roadmap: project.roadmap!)
                .id(project.slug)  // another project's roadmap starts at the top
        default:
            if let group = groups.first(where: { $0.key == store.selectedGroup }) ?? groups.first {
                GroupItems(group: group)
            } else {
                Text("Nothing to show yet.").foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }
}

/// The big progress bar, one small bar per stage, and the last commit.
struct ProgressHeader: View {
    let project: ProjectView
    @Environment(PulseStore.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(project.name).font(.largeTitle.bold())
                LayoutChips(layout: project.layout ?? [])
                Spacer()
                if let summary = project.summary {
                    Text(summaryText(summary))
                        .font(.title3)
                        .foregroundStyle(.secondary)
                }
                Button {
                    store.copyStatus(of: project)
                } label: {
                    Label("Copy status", systemImage: "doc.on.clipboard")
                }
                .buttonStyle(.borderless)
                .help("Copies where this project stands, with your notes, to paste into a new chat with Claude, "
                      + "ChatGPT or Meta AI")
                if let readers = project.readers, !readers.isEmpty {
                    ReadersMenu(readers: readers)
                }
            }
            if let summary = project.summary, summary.stepsTotal > 0 {
                ProgressBar(fraction: Double(summary.workDonePct) / 100, height: 16)
            } else if project.kind == "auto" {
                Text("No plan found yet, so there's no progress bar. See Roadmap for what Pulse looks for.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            ForEach(project.notes ?? [], id: \.self) { note in
                Label(note, systemImage: "info.circle").font(.caption).foregroundStyle(.orange)
            }
            if let stages = project.stages, !stages.isEmpty {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 14)], alignment: .leading, spacing: 10) {
                    ForEach(stages) { stage in
                        Button {
                            store.selectedGroup = "roadmap"
                            store.roadmapTarget = stage.name
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Text(stage.name.components(separatedBy: " — ").first ?? stage.name).lineLimit(1)
                                    Spacer(minLength: 4)
                                    Text("\(stage.done) of \(stage.total)").foregroundStyle(.secondary).monospacedDigit()
                                }
                                .font(.caption)
                                ProgressBar(fraction: stage.total == 0 ? 0 : Double(stage.done) / Double(stage.total),
                                            height: 6)
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .help("\(stage.name): show it in the roadmap")
                    }
                }
            }
            if let commit = project.lastCommit {
                Text("Last commit \(commit.short) · \(commit.subject)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
    }

    private func summaryText(_ summary: Summary) -> String {
        let unit = summary.unit ?? "steps"
        let done = "\(summary.stepsDone) of \(summary.stepsTotal) \(unit) done"
        return summary.weighted == false ? "\(done) · \(summary.workDonePct)%"
            : "\(done) · \(summary.workDonePct)% of the work"
    }
}

/// How the project is set up, in a few words: "Claude Code", "Step list", "Python".
struct LayoutChips: View {
    let layout: [String]

    var body: some View {
        HStack(spacing: 5) {
            ForEach(layout, id: \.self) { chip in
                Text(chip)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Capsule().fill(Color.primary.opacity(0.07)))
            }
        }
        .help("How this project is set up. More under “How it's set up”.")
    }
}

/// What Pulse reads in a folder it reads by itself; each part can be switched off.
struct ReadersMenu: View {
    let readers: [Reader]
    @Environment(PulseStore.self) private var store

    var body: some View {
        Menu {
            Section("What Pulse reads in this folder") {
                ForEach(readers) { reader in
                    Toggle(isOn: Binding(get: { reader.on }, set: { store.setReader(reader, on: $0) })) {
                        Text("\(reader.name) — \(reader.found)")
                    }
                }
            }
        } label: {
            Label("What Pulse reads", systemImage: "slider.horizontal.3")
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help("Switch parts of the reading on or off for this project")
    }
}

struct ProgressBar: View {
    let fraction: Double
    let height: CGFloat
    var color: Color = .green

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.1))
                Capsule().fill(color).frame(width: max(0, min(1, fraction)) * geometry.size.width)
            }
        }
        .frame(height: height)
        .accessibilityElement()
        .accessibilityLabel("\(Int((fraction * 100).rounded())) percent done")
    }
}

/// "Since 2:32 pm: RT-3c-C finished · 2 new problems · 1 commit", opening into the full list.
struct SinceStrip: View {
    let since: Since?
    @State private var open = false

    var body: some View {
        let changes = since?.changes ?? []
        Group {
            if since?.comparedWith == nil {
                Label("First reading. Changes show from the next refresh.", systemImage: "clock")
                    .foregroundStyle(.secondary)
            } else if changes.isEmpty {
                Label("Nothing has changed since \(when).", systemImage: "checkmark.circle")
                    .foregroundStyle(.secondary)
            } else {
                DisclosureGroup(isExpanded: $open) {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(changes, id: \.self) { change in
                            Text("• \(change.text)").textSelection(.enabled)
                        }
                    }
                    .padding(.top, 6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                } label: {
                    Label("Since \(when): \(summary(changes))", systemImage: "sparkles")
                }
            }
        }
        .font(.callout)
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.green.opacity(0.1)))
    }

    private var when: String {
        guard let date = PulseDate.parse(since?.comparedWith) else { return "last time" }
        if Calendar.current.isDateInToday(date) { return date.formatted(date: .omitted, time: .shortened) }
        return date.formatted(.dateTime.weekday().hour().minute())
    }

    private func summary(_ changes: [Change]) -> String {
        var parts: [String] = []
        let finished = changes.filter { $0.kind == "finished" }
        let names = finished.compactMap { change -> String? in
            if let name = change.name { return name }
            return change.text.contains(" finished") ? change.text.components(separatedBy: " finished").first : nil
        }
        if !finished.isEmpty {
            parts.append(names.count == finished.count && names.count <= 4
                         ? "\(names.joined(separator: ", ")) finished" : "\(finished.count) finished")
        }
        let counts: [(String, String, String)] = [
            ("started", "step started", "steps started"), ("ready", "prompt written", "prompts written"),
            ("added", "new step", "new steps"), ("proposed", "step proposed", "steps proposed"),
            ("parked", "new problem", "new problems"), ("warning", "new warning", "new warnings"),
            ("cleared", "thing cleared", "things cleared"), ("progress", "thing moved", "things moved"),
            ("commit", "commit", "commits"),
        ]
        for (kind, one, many) in counts {
            let count = changes.filter { $0.kind == kind }.count
            if count > 0 { parts.append("\(count) \(count == 1 ? one : many)") }
        }
        return parts.joined(separator: " · ")
    }
}

// MARK: - The groups

enum GroupStyle {
    static func color(_ key: String) -> Color {
        switch key {
        case "now": return .blue
        case "next": return .green
        case "could": return .orange
        case "known": return .red
        case "missing": return .purple
        case "done": return .gray
        case "setup": return .teal
        default: return .secondary
        }
    }
}

struct GroupList: View {
    let project: ProjectView
    let groups: [ItemGroup]
    let roadmap: Roadmap?
    let noteCount: Int
    @Environment(PulseStore.self) private var store

    var body: some View {
        @Bindable var store = store
        List(selection: $store.selectedGroup) {
            special("Briefing", icon: "waveform", color: HUD.accent, count: nil).tag("briefing")
            if let roadmap {
                special("Roadmap", icon: "map", color: .accentColor, count: stepsLeft(roadmap)).tag("roadmap")
            }
            ForEach(groups) { group in
                row(title: group.title, count: group.items.count, color: GroupStyle.color(group.key))
                    .tag(group.key)
            }
            Section("Your work with Claude") {
                special("Claude sessions", icon: "sparkles", color: .indigo,
                        count: project.claude.map { "\($0.sessionCount)" } ?? "none").tag("claude")
                special("Prompts", icon: "text.quote", color: .teal,
                        count: "\(project.prompts?.written.count ?? 0)").tag("prompts")
                special("Checklists", icon: "checklist", color: .green, count: checklistCount).tag("checklists")
                special("Your notes", icon: "text.bubble", color: .blue, count: "\(noteCount)").tag("notes")
            }
        }
        .listStyle(.sidebar)
    }

    private var checklistCount: String {
        let lists = project.checklists ?? []
        let ticks = store.ticks(for: project.slug)
        let done = lists.map { ticks.progress(of: $0) }
        return lists.isEmpty ? "" : "\(done.reduce(0) { $0 + $1.done })/\(done.reduce(0) { $0 + $1.total })"
    }

    private func special(_ title: String, icon: String, color: Color, count: String?) -> some View {
        HStack(spacing: 8) {
            Image(systemName: icon).foregroundStyle(color).frame(width: 14)
            Text(title)
            Spacer()
            if let count { Text(count).foregroundStyle(.secondary).monospacedDigit() }
        }
        .padding(.vertical, 3)
    }

    private func stepsLeft(_ roadmap: Roadmap) -> String {
        let rows = roadmap.stages.flatMap(\.rows)
        let left = rows.filter { $0.state != "done" }.count
        return rows.isEmpty ? "" : "\(left) left"
    }

    private func row(title: String, count: Int, color: Color) -> some View {
        HStack(spacing: 8) {
            Circle().fill(color).frame(width: 9, height: 9)
            Text(title)
            Spacer()
            Text("\(count)").foregroundStyle(.secondary).monospacedDigit()
        }
        .padding(.vertical, 3)
    }
}

struct GroupItems: View {
    let group: ItemGroup

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 10) {
                Text(group.title).font(.title2.bold())
                Text(group.hint).foregroundStyle(.secondary).padding(.bottom, 4)
                if group.items.isEmpty {
                    Text("Nothing here right now.").foregroundStyle(.secondary).padding(.top, 8)
                }
                ForEach(group.items) { item in
                    ItemCard(item: item, color: GroupStyle.color(group.key))
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// One thing on the list: what it is, a way to open it, the command that starts it, and your notes on it.
struct ItemCard: View {
    let item: Item
    let color: Color
    @Environment(PulseStore.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Circle().fill(color).frame(width: 8, height: 8)
                Text(item.label)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .fixedSize()
                Text(item.title)
                    .font(.headline)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if item.you == true {
                    Label("Waits on you", systemImage: "person").font(.caption).foregroundStyle(.blue)
                }
                if let path = item.path {
                    OpenButton(path: path)
                }
            }
            if !details.isEmpty {
                Text(details).font(.callout).foregroundStyle(.secondary).padding(.leading, 16)
            }
            if let command = item.command {
                PromptCommand(command: command, notes: store.comments(for: item.key)).padding(.leading, 16)
            }
            ItemNotes(key: item.key).padding(.leading, 16)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.primary.opacity(0.04)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08)))
    }

    private var details: String {
        var text = item.detail
        if let time = PulseDate.parse(item.time) {
            text += " " + time.formatted(.relative(presentation: .named))
        }
        return text.trimmingCharacters(in: .whitespaces)
    }
}

/// Your notes on one thing, and a box to add one. The same notes show wherever the thing shows.
struct ItemNotes: View {
    let key: String
    var placeholder = "Add a note"
    @Environment(PulseStore.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(store.comments(for: key)) { comment in
                CommentRow(comment: comment, key: key)
            }
            CommentComposer(key: key, placeholder: placeholder)
        }
    }
}

struct CommentComposer: View {
    let key: String
    let placeholder: String
    @Environment(PulseStore.self) private var store
    @State private var draft = ""

    var body: some View {
        HStack(spacing: 6) {
            TextField(placeholder, text: $draft)
                .textFieldStyle(.roundedBorder)
                .onSubmit(add)
            Button("Add", action: add)
        }
    }

    private func add() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        store.addComment(text, to: key)
        draft = ""
    }
}

/// A note: tick it off when it's done (notes double as your own to-dos), or delete it.
struct CommentRow: View {
    let comment: Comment
    let key: String
    @Environment(PulseStore.self) private var store

    private var done: Bool { comment.done == true }

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Button {
                store.setDone(comment, in: key, done: !done)
            } label: {
                Image(systemName: done ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(done ? Color.green : Color.blue)
            }
            .buttonStyle(.borderless)
            .help(done ? "Mark as not done" : "Tick it off")
            .accessibilityLabel(done ? "Done. Mark as not done" : "Tick it off")
            VStack(alignment: .leading, spacing: 2) {
                Text(comment.text)
                    .strikethrough(done)
                    .foregroundStyle(done ? .secondary : .primary)
                    .textSelection(.enabled)
                if let date = PulseDate.parse(comment.at) {
                    Text(date.formatted(date: .abbreviated, time: .shortened))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Button {
                store.removeComment(comment, from: key)
            } label: {
                Image(systemName: "xmark.circle")
            }
            .buttonStyle(.borderless)
            .foregroundStyle(.secondary)
            .help("Delete this note")
        }
        .font(.callout)
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.blue.opacity(done ? 0.04 : 0.08)))
        .contextMenu {
            Button(done ? "Mark as Not Done" : "Tick It Off") { store.setDone(comment, in: key, done: !done) }
            Button("Delete Note", role: .destructive) { store.removeComment(comment, from: key) }
        }
    }
}

struct OpenButton: View {
    let path: String
    @Environment(PulseStore.self) private var store

    var body: some View {
        Menu {
            Button("Open") { store.open(path) }
            if store.hasObsidian {
                Button("Open in Obsidian") { store.openInObsidian(path) }
            }
            Button("Show in Finder") { store.showInFinder(path) }
        } label: {
            Label("Open", systemImage: "arrow.up.forward.square")
        } primaryAction: {
            store.open(path)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help(path)
    }
}

/// Every note in a project: your own to-dos for the whole project, notes on items, and notes whose item has gone
/// (a problem that was fixed, a step that was renamed): kept, never lost. They live in Pulse's comments folder,
/// never in the project.
struct NotesView: View {
    let project: ProjectView
    @Environment(PulseStore.self) private var store

    private var itemKeys: [String] {
        let gone = Set(store.goneKeys)
        return (store.book(for: project.slug)?.byItem.keys.sorted() ?? [])
            .filter { $0 != Handoff.projectKey && !gone.contains($0) }
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Your notes").font(.title2.bold())
                    Spacer()
                    Button {
                        store.copy(Handoff.notes(of: project, notes: store.book(for: project.slug)))
                    } label: {
                        Label("Copy all notes", systemImage: "doc.on.doc")
                    }
                    .buttonStyle(.borderless)
                }
                Text("Notes stay in Pulse (its comments folder), never in the project. Tick one off when it's done. "
                     + "They travel with a step's command (“Copy with my notes”) and with “Copy status”.")
                    .foregroundStyle(.secondary)
                section("For the whole project", subtitle: "Your own to-do list, or anything to remember.") {
                    ItemNotes(key: Handoff.projectKey, placeholder: "Add a to-do or a note")
                }
                if !itemKeys.isEmpty {
                    Text("On items").font(.headline).padding(.top, 6)
                    ForEach(itemKeys, id: \.self) { key in
                        section(Handoff.title(of: key, in: project) ?? key, subtitle: nil) {
                            ItemNotes(key: key)
                        }
                    }
                }
                if !store.goneKeys.isEmpty {
                    Text("On things that are gone").font(.headline).padding(.top, 6)
                    Text("What these were written on isn't listed any more. They're kept until you delete them.")
                        .foregroundStyle(.secondary)
                    ForEach(store.goneKeys, id: \.self) { key in
                        section(key, subtitle: nil) {
                            ForEach(store.comments(for: key)) { comment in
                                CommentRow(comment: comment, key: key)
                            }
                        }
                    }
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func section<Content: View>(_ title: String, subtitle: String?,
                                        @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.callout.weight(.semibold))
            if let subtitle { Text(subtitle).font(.caption).foregroundStyle(.secondary) }
            content()
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.primary.opacity(0.04)))
    }
}
