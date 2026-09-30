import AppKit
import PulseCore
import SwiftUI

// MARK: - The roadmap

/// The whole road, like the first chart: tiles, what the colours mean, every stage and step with a bar (its size and
/// how far it is), the proofs and release gates, the owner's errands, and what comes after. Everything is clickable:
/// a step opens in place (its prompt, the commands that start it, your notes), a gate shows what it means, a tile
/// jumps to its list.
struct RoadmapView: View {
    let roadmap: Roadmap
    @Environment(PulseStore.self) private var store

    private var rows: [RoadRow] { roadmap.stages.flatMap(\.rows) }

    var body: some View {
        ScrollViewReader { reader in
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    HStack(alignment: .firstTextBaseline) {
                        Text("Roadmap").font(.title2.bold())
                        Text("Click a step to see its prompt, copy the command that starts it, or add a note.")
                            .foregroundStyle(.secondary)
                        Spacer()
                        if let path = roadmap.path {
                            OpenButton(path: path)
                        }
                    }
                    if roadmap.stages.isEmpty && (roadmap.later ?? []).isEmpty {
                        EmptyRoadmap()
                    } else {
                        if !rows.isEmpty {
                            HStack(alignment: .top, spacing: 16) {
                                ForEach(Array(roadmap.tiles.enumerated()), id: \.offset) { index, tile in
                                    TileView(tile: tile, target: index == 0 ? "done" : index == 1 ? "next" : nil)
                                }
                            }
                            Legend(roadmap: roadmap, rows: rows)
                        }
                        ForEach(roadmap.stages) { stage in
                            StageSection(stage: stage, sized: roadmap.sized)
                                .id("stage:\(stage.id)")
                        }
                        if let gates = roadmap.gates, !gates.isEmpty {
                            GatesSection(title: roadmap.gatesTitle ?? "Gates", note: roadmap.gatesNote, gates: gates)
                        }
                        if let errands = roadmap.errands, !errands.isEmpty {
                            ErrandsSection(errands: errands)
                        }
                        if let later = roadmap.later, !later.isEmpty {
                            LaterSection(title: roadmap.laterTitle ?? "Later", rows: later)
                        }
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onAppear { scroll(reader) }
            .onChange(of: store.roadmapTarget) { scroll(reader) }
        }
    }

    /// Goes to the stage picked in the header, or to the step opened from elsewhere (the homepage).
    private func scroll(_ reader: ScrollViewProxy) {
        if let target = store.roadmapTarget {
            let match = roadmap.stages.first { $0.id == target || $0.name == target || target.hasPrefix($0.name) }
            if let match {
                withAnimation { reader.scrollTo("stage:\(match.id)", anchor: .top) }
            } else if let row = rows.first(where: { $0.label == target || $0.name == target }) {
                store.expandedRow = row.key  // a bar for one feature or list: open its row
                withAnimation { reader.scrollTo("row:\(row.key)", anchor: .top) }
            }
            store.roadmapTarget = nil
        } else if let row = store.expandedRow, rows.contains(where: { $0.key == row }) {
            reader.scrollTo("row:\(row)", anchor: .center)
        }
    }
}

/// The colours of the road: done (grey), in progress (blue), prompt written (green), prompt still to write (purple).
enum RoadStyle {
    static func color(_ state: String) -> Color {
        switch state {
        case "done": return Color.gray.opacity(0.55)
        case "doing": return .blue
        case "ready": return Color(red: 0.11, green: 0.62, blue: 0.46)
        case "todo": return Color(red: 0.49, green: 0.44, blue: 0.88)
        case "blocked": return .orange
        case "next": return .accentColor
        default: return .secondary
        }
    }

    /// A bar's length by size: S = 1, M = 2, L = 4.
    static func units(_ size: String?) -> CGFloat {
        switch size {
        case "S": return 1
        case "L": return 4
        default: return 2
        }
    }
}

/// A number at the top ("Build steps left 17"); a click shows its list.
struct TileView: View {
    let tile: Tile
    let target: String?
    @Environment(PulseStore.self) private var store

    var body: some View {
        Button {
            if let target { store.selectedGroup = target }
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                Text(tile.label).font(.callout).foregroundStyle(.secondary)
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(tile.value).font(.system(size: 30, weight: .bold)).monospacedDigit()
                    if !tile.suffix.isEmpty {
                        Text(tile.suffix).font(.title3).foregroundStyle(.secondary)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(target == "done" ? "Show what's done" : target == "next" ? "Show the next steps" : tile.label)
    }
}

struct Legend: View {
    let roadmap: Roadmap
    let rows: [RoadRow]

    var body: some View {
        FlowLayout(spacing: 18, lineSpacing: 8) {
            ForEach(roadmap.legend, id: \.self) { entry in
                HStack(spacing: 6) {
                    RoundedRectangle(cornerRadius: 3).fill(RoadStyle.color(entry.state)).frame(width: 13, height: 13)
                    Text(entry.text)
                }
            }
            if roadmap.sized {
                Text("Bar length: S = 1, M = 2, L = 4").foregroundStyle(.secondary)
            }
            if rows.contains(where: { $0.you == true }) || (roadmap.gates ?? []).contains(where: { $0.you == true }) {
                Label("waits on you", systemImage: "person")
            }
            if rows.contains(where: { $0.cut == true }) {
                Text("cut line: first to go if time runs short").foregroundStyle(.orange)
            }
            if rows.contains(where: { $0.command != nil }) {
                Label("copy the command that starts a step", systemImage: "doc.on.doc").foregroundStyle(.secondary)
            }
        }
        .font(.callout)
    }
}

/// A stage: its name and note, then its steps. A long stage folds its finished steps away.
struct StageSection: View {
    let stage: RoadStage
    let sized: Bool
    @State private var showDone = false

    private var finished: [RoadRow] { stage.rows.filter { $0.state == "done" } }
    private var folds: Bool { stage.rows.count > 30 && finished.count > 10 }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(stage.name).font(.headline)
                if let note = stage.note, !note.isEmpty {
                    Text(note).foregroundStyle(.secondary)
                }
                Spacer()
                if folds {
                    Button(showDone ? "Hide the \(finished.count) done" : "Show the \(finished.count) done") {
                        showDone.toggle()
                    }
                    .buttonStyle(.borderless)
                }
            }
            .padding(.bottom, 6)
            Divider()
            ForEach(stage.rows.filter { !folds || showDone || $0.state != "done" }) { row in
                RoadRowView(row: row, sized: sized)
                    .id("row:\(row.key)")
            }
        }
    }
}

/// One step: its id, its name (with who it waits on), where it stands, and a bar. A click opens it in place.
struct RoadRowView: View {
    let row: RoadRow
    let sized: Bool
    @Environment(PulseStore.self) private var store
    @State private var hovering = false

    private var finished: Bool { row.state == "done" }
    private var open: Bool { store.expandedRow == row.key }
    private var noteCount: Int { store.comments(for: row.key).count }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center, spacing: 12) {
                Button {
                    withAnimation(.easeOut(duration: 0.15)) { store.expandedRow = open ? nil : row.key }
                } label: {
                    HStack(alignment: .center, spacing: 12) {
                        Image(systemName: open ? "chevron.down" : "chevron.right")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .frame(width: 10)
                        Text(row.label)
                            .font(.system(.body, design: .monospaced))
                            .foregroundStyle(finished ? .secondary : .primary)
                            .lineLimit(1)
                            .frame(width: 108, alignment: .leading)
                        rowText
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("\(row.label) \(row.name)")
                .accessibilityHint(open ? "Closes this step" : "Shows its prompt, its command and your notes")
                if let command = row.command {
                    CopyButton(text: command, compact: true)
                        .help("Copy “\(command)”. Paste it into Claude Code, in this project's folder, to start the step.")
                }
                bar.frame(width: 250, alignment: .leading)
                Text(row.size ?? "")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .frame(width: 16, alignment: .leading)
            }
            .padding(.vertical, 6)
            .padding(.horizontal, 6)
            .background(RoundedRectangle(cornerRadius: 6).fill(open ? Color.accentColor.opacity(0.08)
                                                              : hovering ? Color.primary.opacity(0.05) : .clear))
            .onHover { hovering = $0 }
            .contextMenu {
                if let path = row.path {
                    Button("Open") { store.open(path) }
                    Button("Show in Finder") { store.showInFinder(path) }
                }
                if let command = row.command {
                    Button("Copy “\(command)”") { store.copy(command) }
                }
            }
            if open {
                RoadRowDetail(row: row)
                    .padding(.leading, 34)
                    .padding(.vertical, 8)
            }
        }
    }

    private var rowText: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(row.name)
                    .foregroundStyle(finished ? .secondary : .primary)
                    .lineLimit(1)
                if row.you == true {
                    Image(systemName: "person").foregroundStyle(.secondary).help("Waits on you")
                }
                if row.cut == true {
                    Text("· cut line").font(.callout).foregroundStyle(.orange)
                }
                if noteCount > 0 {
                    Label("\(noteCount)", systemImage: "text.bubble")
                        .font(.caption)
                        .foregroundStyle(.blue)
                        .help("\(noteCount) note\(noteCount == 1 ? "" : "s")")
                }
            }
            if let detail = row.detail, !detail.isEmpty {
                Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder private var bar: some View {
        if let total = row.total, total > 0 {
            HStack(spacing: 8) {
                ProgressBar(fraction: Double(row.done ?? 0) / Double(total), height: 9, color: RoadStyle.color(row.state))
                    .frame(width: 170)
                Text("\(row.done ?? 0) of \(total)").font(.caption).foregroundStyle(.secondary).monospacedDigit()
            }
        } else {
            RoundedRectangle(cornerRadius: 5)
                .fill(RoadStyle.color(row.state))
                .frame(width: 58 * (sized ? RoadStyle.units(row.size) : 2), height: 20)
        }
    }
}

/// An open step: where it stands, the start of its prompt, the ways to start it, and your notes on it.
struct RoadRowDetail: View {
    let row: RoadRow
    @Environment(PulseStore.self) private var store

    private var prompt: String? { PromptFile.read(row.path) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let detail = row.detail, !detail.isEmpty {
                Text(detail).foregroundStyle(.secondary)
            }
            if let prompt {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(row.command != nil ? "Its prompt" : "Its file").font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                        Spacer()
                        if let path = row.path { OpenButton(path: path) }
                    }
                    Text(PromptFile.opening(prompt))
                        .font(.system(.callout, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(10)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
            } else if let path = row.path {
                HStack {
                    Text((path as NSString).lastPathComponent).foregroundStyle(.secondary)
                    OpenButton(path: path)
                }
            }
            if let command = row.command {
                PromptCommand(command: command, notes: store.comments(for: row.key), promptText: prompt)
            }
            ItemNotes(key: row.key, placeholder: "Add a note on this step")
        }
    }
}

/// A step's prompt, read from its file (small text files only), and its first lines for a preview.
enum PromptFile {
    static func read(_ path: String?) -> String? {
        guard let path, ["md", "markdown", "txt", "mdc"].contains((path as NSString).pathExtension.lowercased()),
              let size = (try? FileManager.default.attributesOfItem(atPath: path))?[.size] as? Int, size < 200_000
        else { return nil }
        return try? String(contentsOfFile: path, encoding: .utf8)
    }

    static func opening(_ text: String, lines: Int = 12) -> String {
        let kept = text.split(separator: "\n", omittingEmptySubsequences: false).prefix(lines)
        let joined = kept.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        return kept.count < text.split(separator: "\n", omittingEmptySubsequences: false).count ? joined + "\n…" : joined
    }
}

struct GatesSection: View {
    let title: String
    let note: String?
    let gates: [Gate]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(title).font(.headline)
                if let note { Text(note).foregroundStyle(.secondary) }
            }
            Divider()
            FlowLayout(spacing: 8, lineSpacing: 8) {
                ForEach(Array(gates.enumerated()), id: \.offset) { _, gate in
                    HStack(spacing: 8) {
                        if gate.arrowBefore == true {
                            Image(systemName: "arrow.right").foregroundStyle(.secondary)
                        }
                        GateChip(gate: gate)
                    }
                }
            }
        }
    }
}

/// A proof or release gate; a click shows what it means, with a way to open its document.
struct GateChip: View {
    let gate: Gate
    @Environment(PulseStore.self) private var store
    @State private var showing = false

    private var current: Bool { gate.state == "doing" || gate.state == "next" }

    var body: some View {
        Button {
            showing.toggle()
        } label: {
            HStack(spacing: 5) {
                if gate.state == "done" { Image(systemName: "checkmark") }
                if gate.you == true { Image(systemName: "person") }
                Text(gate.name)
                if current {
                    Text(gate.state == "doing" ? "in progress" : "next").font(.caption).foregroundStyle(.blue)
                }
            }
            .foregroundStyle(gate.state == "done" ? .secondary : .primary)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(RoundedRectangle(cornerRadius: 7).strokeBorder(
                current ? Color.blue.opacity(0.7) : Color.primary.opacity(0.18)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .popover(isPresented: $showing, arrowEdge: .bottom) {
            VStack(alignment: .leading, spacing: 8) {
                Text(gate.name).font(.headline)
                Text(gate.detail?.isEmpty == false ? gate.detail! : "No more detail in the roadmap.")
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                if gate.you == true {
                    Label("This one waits on you.", systemImage: "person").foregroundStyle(.blue)
                }
                if let path = gate.path {
                    OpenButton(path: path)
                }
            }
            .padding(14)
            .frame(width: 340, alignment: .leading)
        }
    }
}

struct ErrandsSection: View {
    let errands: [Errand]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Your errands").font(.headline)
            Divider()
            FlowLayout(spacing: 8, lineSpacing: 8) {
                ForEach(errands, id: \.self) { errand in
                    HStack(spacing: 5) {
                        if errand.done { Image(systemName: "checkmark") }
                        Text(errand.text).strikethrough(errand.done)
                    }
                    .foregroundStyle(errand.done ? .secondary : .primary)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(RoundedRectangle(cornerRadius: 7).strokeBorder(Color.primary.opacity(0.18)))
                }
            }
        }
    }
}

/// What comes after this plan: later versions ("0.2 Mac app…"), or ideas saved for later.
struct LaterSection: View {
    let title: String
    let rows: [LaterRow]
    @Environment(PulseStore.self) private var store

    private var groups: [String] {
        var seen: [String] = []
        for row in rows where !seen.contains(row.group) { seen.append(row.group) }
        return seen
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(groups, id: \.self) { group in
                Text(group).font(.headline).padding(.top, 4)
                Divider()
                ForEach(Array(rows.filter { $0.group == group }.enumerated()), id: \.offset) { _, row in
                    HStack(alignment: .firstTextBaseline, spacing: row.label.isEmpty ? 8 : 12) {
                        Text(row.label.isEmpty ? "•" : row.label)
                            .font(.system(.body, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .frame(width: row.label.isEmpty ? 10 : 44, alignment: .leading)
                        Text(row.text).frame(maxWidth: .infinity, alignment: .leading)
                        if let path = row.path { OpenButton(path: path) }
                    }
                    .padding(.vertical, 3)
                }
            }
        }
    }
}

struct EmptyRoadmap: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("No roadmap found yet").font(.title3.bold())
            Text("Pulse builds the roadmap from what a project already has. It looks for:")
            VStack(alignment: .leading, spacing: 4) {
                Text("• a table of steps (| Step | What | Status |) in a ROADMAP or PLAN note, or in prompts/README.md")
                Text("• numbered step prompts: prompts/01-setup.md, prompts/02-…")
                Text("• Spec Kit (specs/), Kiro (.kiro/specs), Task Master (tasks.json), Backlog.md (backlog/) or BMAD stories")
                Text("• checklists in notes: lines starting with “- [ ]”, and “- [x]” once done")
            }
            .foregroundStyle(.secondary)
            Text("No plan at all? Keep your own to-do list under “Your notes”: it stays in Pulse, not in the project.")
                .padding(.top, 4)
        }
        .textSelection(.enabled)
    }
}

// MARK: - Commands

/// The command that starts a step, with buttons to copy it: alone, with your notes on the step, or (for a chat
/// that can't read the project, like ChatGPT) the whole prompt with your notes.
struct PromptCommand: View {
    let command: String
    var notes: [Comment] = []
    var promptText: String? = nil

    private var openNotes: [Comment] { notes.filter { $0.done != true } }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Image(systemName: "terminal").foregroundStyle(.secondary)
                Text(command)
                    .font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
                    .lineLimit(1)
                    .truncationMode(.middle)
                CopyButton(text: command, compact: false)
                    .help("Paste this into Claude Code, in this project's folder, to start it")
                Spacer(minLength: 0)
            }
            if !openNotes.isEmpty || promptText != nil {
                HStack(spacing: 14) {
                    if !openNotes.isEmpty {
                        CopyButton(text: Handoff.command(command, notes: notes), compact: false,
                                   label: "Copy with my \(openNotes.count == 1 ? "note" : "\(openNotes.count) notes")")
                            .help("The command, then your notes on this step, so they reach the session doing it")
                    }
                    if let promptText {
                        CopyButton(text: Handoff.promptText(promptText, notes: notes), compact: false,
                                   label: "Copy the whole prompt")
                            .help("For a chat that can't open your files (ChatGPT, Meta AI): the prompt itself"
                                  + (openNotes.isEmpty ? "" : ", with your notes"))
                    }
                }
                .padding(.leading, 24)
            }
        }
    }
}

struct CopyButton: View {
    let text: String
    var compact = false
    var label = "Copy"
    @Environment(PulseStore.self) private var store
    @State private var copied = false

    var body: some View {
        Button {
            store.copy(text)
            copied = true
            Task { @MainActor in
                try? await Task.sleep(for: .seconds(1.5))
                copied = false
            }
        } label: {
            if compact {
                Image(systemName: copied ? "checkmark" : "doc.on.doc")
            } else {
                Label(copied ? "Copied" : label, systemImage: copied ? "checkmark" : "doc.on.doc")
            }
        }
        .buttonStyle(.borderless)
    }
}

// MARK: - Layout

/// Lays its children out in rows, wrapping to the next row when one is full (for chips).
struct FlowLayout: Layout {
    var spacing: CGFloat = 8
    var lineSpacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var lineHeight: CGFloat = 0
        var widest: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width {
                y += lineHeight + lineSpacing
                x = 0
                lineHeight = 0
            }
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
            widest = max(widest, x - spacing)
        }
        return CGSize(width: proposal.width ?? widest, height: y + lineHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var lineHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX {
                y += lineHeight + lineSpacing
                x = bounds.minX
                lineHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
    }
}
