import PulseCore
import SwiftUI

/// Every prompt: the ones written as files (step prompts, slash commands, skills, agents) with when each was last
/// sent, the prompts you sent Claude, sessions that stopped before finishing, and long prompts you've typed twice.
struct PromptsView: View {
    let project: ProjectView
    let global: [GlobalPrompt]
    @State private var tab = "written"
    @State private var search = ""

    private var library: PromptLibrary? { project.prompts }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Prompts").font(.title2.bold())
                Picker("", selection: $tab) {
                    Text("Written (\(library?.written.count ?? 0))").tag("written")
                    Text("Sent to Claude (\(library?.sentCount ?? 0))").tag("sent")
                    Text("Unfinished (\(library?.unfinished.count ?? 0))").tag("unfinished")
                    Text("Typed twice (\(library?.repeated.count ?? 0))").tag("repeated")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                if tab == "sent" {
                    TextField("Search your prompts", text: $search).textFieldStyle(.roundedBorder)
                }
            }
            .padding([.horizontal, .top], 20)
            .padding(.bottom, 10)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    switch tab {
                    case "sent": SentList(prompts: filtered)
                    case "unfinished": UnfinishedList(sessions: library?.unfinished ?? [])
                    case "repeated": RepeatedList(prompts: library?.repeated ?? [])
                    default: WrittenList(project: project, global: global)
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var filtered: [SentPrompt] {
        let all = library?.sent ?? []
        let words = search.lowercased().split(separator: " ")
        guard !words.isEmpty else { return all }
        return all.filter { prompt in words.allSatisfy { prompt.text.lowercased().contains($0) } }
    }
}

struct WrittenList: View {
    let project: ProjectView
    let global: [GlobalPrompt]

    private struct Kind: Identifiable {
        let id: String
        let title: String
    }

    private let kinds = [Kind(id: "step", title: "Step prompts"), Kind(id: "command", title: "Slash commands"),
                         Kind(id: "skill", title: "Skills"), Kind(id: "agent", title: "Agents"),
                         Kind(id: "prompt", title: "Other prompts")]

    var body: some View {
        let written = project.prompts?.written ?? []
        if written.isEmpty && global.isEmpty {
            Text("No prompts written as files yet. A prompt you'll use again is worth keeping: save it in a prompts/ "
                 + "folder, or as .claude/commands/<name>.md to make it a /<name> command.")
                .foregroundStyle(.secondary)
        }
        if let since = PulseDate.parse(project.prompts?.since), written.contains(where: \.neverSent) {
            Text("“Not sent yet” means it isn't in any Claude conversation since \(since.formatted(date: .abbreviated, time: .omitted)) (the oldest one Claude Code kept).")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        ForEach(kinds) { kind in
            let rows = written.filter { $0.kind == kind.id }
            if !rows.isEmpty {
                Text(kind.title).font(.headline).padding(.top, 8)
                ForEach(rows) { prompt in WrittenRow(prompt: prompt) }
            }
        }
        if !global.isEmpty {
            Text("Your own commands (every project)").font(.headline).padding(.top, 8)
            ForEach(global) { prompt in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(prompt.use).font(.system(.callout, design: .monospaced))
                    Text(prompt.title).foregroundStyle(.secondary).lineLimit(1)
                    Spacer(minLength: 0)
                    CopyButton(text: prompt.use, compact: true)
                }
            }
        }
    }
}

struct WrittenRow: View {
    let prompt: WrittenPrompt
    @Environment(PulseStore.self) private var store

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    if let step = prompt.step {
                        Text(step).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary)
                    }
                    Text(prompt.title).lineLimit(2)
                }
                HStack(spacing: 8) {
                    Text(prompt.rel).font(.system(.caption2, design: .monospaced)).foregroundStyle(.tertiary).lineLimit(1)
                    chip
                }
            }
            Spacer(minLength: 8)
            CopyButton(text: prompt.use, label: prompt.kind == "command" || prompt.kind == "skill" ? prompt.use : "Copy")
                .help("Copy “\(prompt.use)”")
            Button {
                store.open(prompt.path)
            } label: {
                Image(systemName: "doc.text")
            }
            .buttonStyle(.borderless)
            .help("Open the prompt file")
        }
        .padding(.vertical, 5)
        .padding(.horizontal, 10)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.035)))
    }

    @ViewBuilder private var chip: some View {
        if prompt.state == "done" {
            tag("done", .green)
        } else if prompt.neverSent {
            tag("not sent yet", .orange)
        }
        if prompt.sent > 0, let last = PulseDate.parse(prompt.lastSent) {
            tag("sent \(prompt.sent)× · last \(last.formatted(date: .abbreviated, time: .omitted))", .blue)
        }
    }

    private func tag(_ text: String, _ color: Color) -> some View {
        Text(text)
            .font(.caption2)
            .padding(.horizontal, 6)
            .padding(.vertical, 1)
            .background(Capsule().fill(color.opacity(0.15)))
            .foregroundStyle(color)
    }
}

struct SentList: View {
    let prompts: [SentPrompt]

    var body: some View {
        if prompts.isEmpty {
            Text("No prompts to show.").foregroundStyle(.secondary)
        }
        ForEach(prompts) { prompt in
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(prompt.text).lineLimit(4).textSelection(.enabled)
                    HStack(spacing: 6) {
                        if let at = PulseDate.parse(prompt.at) {
                            Text(at.formatted(date: .abbreviated, time: .shortened))
                        }
                        if let title = prompt.sessionTitle { Text("· \(title)").lineLimit(1) }
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                CopyButton(text: prompt.text, compact: true).help("Copy it to use again")
            }
            .padding(.vertical, 6)
            .padding(.horizontal, 10)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.035)))
        }
    }
}

struct UnfinishedList: View {
    let sessions: [UnfinishedSession]

    var body: some View {
        if sessions.isEmpty {
            Text("No session stopped half-way in the last week.").foregroundStyle(.secondary)
        }
        ForEach(sessions) { session in
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(session.title).font(.headline).lineLimit(1)
                    Spacer()
                    if let at = PulseDate.parse(session.at) {
                        Text(at.formatted(date: .abbreviated, time: .shortened)).font(.caption).foregroundStyle(.secondary)
                    }
                }
                if let text = session.text { Label(text, systemImage: "exclamationmark.circle").foregroundStyle(.orange) }
                if let prompt = session.lastPrompt {
                    HStack(alignment: .top) {
                        Text(prompt).font(.callout).foregroundStyle(.secondary).lineLimit(3)
                        Spacer(minLength: 8)
                        CopyButton(text: prompt, label: "Copy to try again")
                    }
                }
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.035)))
        }
    }
}

struct RepeatedList: View {
    let prompts: [RepeatedPrompt]

    private func times(_ prompt: RepeatedPrompt) -> String {
        guard let last = PulseDate.parse(prompt.last) else { return "typed \(prompt.times) times" }
        return "typed \(prompt.times) times · last \(last.formatted(date: .abbreviated, time: .omitted))"
    }

    var body: some View {
        if prompts.isEmpty {
            Text("No long prompt was typed twice.").foregroundStyle(.secondary)
        } else {
            Text("You typed these more than once. Saved as .claude/commands/<name>.md, a prompt becomes a /<name> "
                 + "command: one word instead of a paragraph.")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        ForEach(prompts) { prompt in
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(prompt.text).lineLimit(5).textSelection(.enabled)
                    Text(times(prompt)).font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                CopyButton(text: prompt.text, compact: true)
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.035)))
        }
    }
}
