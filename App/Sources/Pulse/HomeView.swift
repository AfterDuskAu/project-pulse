import PulseCore
import SwiftUI

/// Everything that waits on the owner, from every project: decisions, steps that need your OK, errands, pushes.
struct WaitingOnYou: View {
    let projects: [ProjectView]
    @Environment(PulseStore.self) private var store

    private struct Entry: Identifiable {
        let project: ProjectView
        let group: String
        let item: Item
        var id: String { "\(project.slug)|\(item.key)" }
    }

    private var entries: [Entry] {
        projects.flatMap { project in
            (project.groups ?? []).filter { $0.key != "setup" && $0.key != "done" }.flatMap { group in
                group.items.filter { $0.you == true }.map { Entry(project: project, group: group.key, item: $0) }
            }
        }
    }

    var body: some View {
        if !entries.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Label("Waiting on you", systemImage: "person").font(.headline)
                    Text("\(entries.count)").foregroundStyle(.secondary).monospacedDigit()
                }
                ForEach(entries.prefix(14)) { entry in
                    Button {
                        store.go(to: entry.project.slug, group: entry.group)
                    } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Text(entry.project.name)
                                .font(.caption.weight(.medium))
                                .padding(.horizontal, 7)
                                .padding(.vertical, 2)
                                .background(Capsule().fill(Color.blue.opacity(0.15)))
                            Text(entry.item.title).lineLimit(1)
                            Text(entry.item.detail)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 2)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .help("Open it in \(entry.project.name)")
                }
                if entries.count > 14 {
                    Text("…and \(entries.count - 14) more").font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12).fill(Color.blue.opacity(0.07)))
        }
    }
}

/// Your newest notes, from every project.
struct RecentNotes: View {
    let projects: [ProjectView]
    @Environment(PulseStore.self) private var store

    private struct Entry: Identifiable {
        let project: ProjectView
        let key: String
        let comment: Comment
        var id: String { comment.id }
    }

    private var entries: [Entry] {
        projects.flatMap { project in
            (store.book(for: project.slug)?.newestFirst ?? []).map { Entry(project: project, key: $0.key, comment: $0.comment) }
        }
        .sorted { $0.comment.at > $1.comment.at }
    }

    var body: some View {
        if !entries.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Label("Your latest notes", systemImage: "text.bubble").font(.headline)
                ForEach(entries.prefix(8)) { entry in
                    Button {
                        store.go(to: entry.project.slug, group: "notes")
                    } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Image(systemName: entry.comment.done == true ? "checkmark.circle.fill" : "circle")
                                .foregroundStyle(entry.comment.done == true ? .green : .blue)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(entry.comment.text).strikethrough(entry.comment.done == true).lineLimit(2)
                                Text("\(entry.project.name) · \(Handoff.title(of: entry.key, in: entry.project) ?? "something no longer listed")")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                            Spacer(minLength: 0)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12).fill(Color.primary.opacity(0.04)))
        }
    }
}
