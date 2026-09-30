import PulseCore
import SwiftUI

/// The project's checklists: the basics every project needs, and the release checklist for what it's made for
/// (the Mac App Store, the iPhone App Store, a website…). Pulse ticks what the files prove; you tick the rest.
struct ChecklistsView: View {
    let project: ProjectView
    @Environment(PulseStore.self) private var store

    private var lists: [Checklist] { project.checklists ?? [] }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Checklists").font(.title2.bold())
                        Text("Pulse ticks what the files prove by itself. The rest you tick here: Pulse keeps your ticks "
                             + "in its own folder, never in the project.")
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Menu {
                        ForEach(project.checklistCatalog ?? []) { entry in
                            let present = lists.first { $0.id == entry.id }
                            Button {
                                store.setChecklist(entry.id, on: present == nil, detected: present.map { $0.added != true } ?? false)
                            } label: {
                                Label(present == nil ? "Add “\(entry.title)”" : "Take away “\(entry.title)”",
                                      systemImage: present == nil ? "plus" : "minus")
                            }
                        }
                    } label: {
                        Label("Add a checklist", systemImage: "checklist")
                    }
                    .fixedSize()
                }
                if lists.isEmpty {
                    Text("No checklist yet.").foregroundStyle(.secondary)
                }
                ForEach(lists) { list in
                    ChecklistSection(list: list, slug: project.slug)
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct ChecklistSection: View {
    let list: Checklist
    let slug: String
    @Environment(PulseStore.self) private var store

    var body: some View {
        let ticks = store.ticks(for: slug)
        let progress = ticks.progress(of: list)
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 12) {
                ProgressBar(fraction: progress.total == 0 ? 0 : Double(progress.done) / Double(progress.total), height: 8)
                    .frame(width: 120)
                Text(list.title).font(.title3.bold())
                Text("\(progress.done) of \(progress.total)").foregroundStyle(.secondary).monospacedDigit()
                Spacer()
            }
            Text(list.why).font(.caption).foregroundStyle(.secondary)
            ForEach(sorted(ticks)) { item in
                CheckRow(item: item, state: ticks.state(of: item), slug: slug)
            }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.primary.opacity(0.035)))
    }

    /// What's wrong first, then what you tick, then what's done.
    private func sorted(_ ticks: TickBook) -> [CheckItem] {
        let order = ["fail": 0, "warn": 1, "todo": 2, "pass": 3, "ticked": 4, "skipped": 5]
        return list.items.enumerated().sorted { a, b in
            let left = order[ticks.state(of: a.element)] ?? 9
            let right = order[ticks.state(of: b.element)] ?? 9
            return left == right ? a.offset < b.offset : left < right
        }.map(\.element)
    }
}

struct CheckRow: View {
    let item: CheckItem
    let state: String
    let slug: String
    @Environment(PulseStore.self) private var store

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: icon).foregroundStyle(color).frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.text).strikethrough(state == "skipped").foregroundStyle(state == "skipped" ? .secondary : .primary)
                Text(item.why).font(.caption).foregroundStyle(.secondary)
                if !item.evidence.isEmpty, state != "ticked", state != "skipped" {
                    Text(item.evidence).font(.system(.caption2, design: .monospaced)).foregroundStyle(.secondary)
                        .lineLimit(2).textSelection(.enabled)
                }
                if state == "ticked", item.auto, let found = item.found ?? (item.state == "fail" ? "fail" : nil), found == "fail" {
                    Text("You ticked it; Pulse still sees: \(item.evidence)").font(.caption2).foregroundStyle(.orange)
                }
            }
            Spacer(minLength: 8)
            if let path = item.path {
                Button {
                    store.open(path)
                } label: {
                    Image(systemName: "doc.text.magnifyingglass")
                }
                .buttonStyle(.borderless)
                .help("Open where Pulse looked")
            }
            if !item.auto && state != "skipped" {
                Button(state == "ticked" ? "Untick" : "Tick") {
                    store.setTick(item.key, to: state == "ticked" ? nil : "ticked", in: slug)
                }
                .buttonStyle(.bordered)
            }
            Menu {
                if state == "ticked" || state == "skipped" {
                    Button("Undo my mark") { store.setTick(item.key, to: nil, in: slug) }
                }
                if item.auto && state != "ticked" {
                    Button("I've checked it myself") { store.setTick(item.key, to: "ticked", in: slug) }
                }
                if state != "skipped" {
                    Button("Doesn't apply to this project") { store.setTick(item.key, to: "skipped", in: slug) }
                }
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.button)
            .buttonStyle(.borderless)
            .fixedSize()
        }
        .padding(.vertical, 3)
    }

    private var icon: String {
        switch state {
        case "pass": return "checkmark.circle.fill"
        case "fail": return "xmark.circle.fill"
        case "warn": return "exclamationmark.triangle.fill"
        case "ticked": return "checkmark.square.fill"
        case "skipped": return "minus.circle"
        default: return "circle"
        }
    }

    private var color: Color {
        switch state {
        case "pass": return .green
        case "fail": return .red
        case "warn": return .orange
        case "ticked": return .blue
        default: return .secondary
        }
    }
}
