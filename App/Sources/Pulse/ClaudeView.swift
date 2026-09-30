import PulseCore
import SwiftUI

/// The project's Claude Code conversations: which one is working now, what each did (the files it changed, the tests
/// and builds it ran, what Claude said at the end), why one stopped, and what Claude remembers about the project.
struct ClaudeView: View {
    let project: ProjectView
    @State private var open: String?
    @State private var showCost = false

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 12) {
                Text("Claude sessions").font(.title2.bold())
                if let claude = project.claude {
                    Text(summary(claude)).foregroundStyle(.secondary)
                    ForEach(claude.sessions) { session in
                        SessionCard(session: session, project: project, open: open == session.id) {
                            open = open == session.id ? nil : session.id
                        }
                    }
                    if claude.sessionCount > claude.sessions.count {
                        Text("…and \(claude.sessionCount - claude.sessions.count) older sessions.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    if !claude.memory.isEmpty {
                        MemoryList(memory: claude.memory)
                    }
                    DisclosureGroup("What this week's work would cost at API prices", isExpanded: $showCost) {
                        Text(String(format: "About $%.2f across %ld sessions, from Claude Code's own counts. On a Pro "
                                    + "or Max plan you pay the monthly fee instead; this only shows how much work it was.",
                                    claude.week.usd, claude.week.sessions))
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .padding(.top, 4)
                    }
                    .font(.callout)
                    .padding(.top, 6)
                } else {
                    Text("Pulse found no Claude Code conversations for this folder. They appear here as soon as you "
                         + "work on it with Claude Code (in the Claude app or the terminal).")
                        .foregroundStyle(.secondary)
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func summary(_ claude: ClaudeInfo) -> String {
        var parts = ["\(claude.sessionCount) conversation\(claude.sessionCount == 1 ? "" : "s")",
                     "\(claude.week.sessions) this week", "\(claude.week.prompts) prompts this week"]
        if claude.week.added + claude.week.removed > 0 {
            parts.append("+\(claude.week.added) / −\(claude.week.removed) lines")
        }
        return parts.joined(separator: " · ") + ". Read from Claude Code's own files on this Mac; nothing is sent anywhere."
    }
}

struct SessionCard: View {
    let session: ClaudeSession
    let project: ProjectView
    let open: Bool
    var toggle: () -> Void
    @Environment(PulseStore.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(action: toggle) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: open ? "chevron.down" : "chevron.right").font(.caption).foregroundStyle(.secondary)
                    SessionBadge(session: session)
                    Text(session.title).font(.headline).lineLimit(1)
                    Spacer(minLength: 8)
                    Text(when).font(.caption).foregroundStyle(.secondary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            HStack(spacing: 10) {
                Text("\(session.prompts) prompt\(session.prompts == 1 ? "" : "s")")
                if session.editedCount > 0 { Text("\(session.editedCount) file\(session.editedCount == 1 ? "" : "s") changed") }
                if !session.startedHere, let folder = session.startedIn {
                    Text("started in \((folder as NSString).lastPathComponent)")
                }
                if let app = session.app { Text(app) }
                if session.gone == true { Text("Claude Code has cleaned it up; Pulse remembers it") }
                ForEach(Array(session.runs.enumerated()), id: \.offset) { _, run in RunChip(run: run) }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            if let stop = session.stop, session.state == "stopped" {
                Label(stop.text, systemImage: "exclamationmark.circle").font(.callout).foregroundStyle(.orange)
            }
            if open {
                SessionDetail(session: session)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.primary.opacity(0.04)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(session.state == "working"
                                                                  ? Color.indigo.opacity(0.5) : Color.primary.opacity(0.08)))
    }

    private var when: String {
        guard let ended = PulseDate.parse(session.ended) else { return "" }
        if session.state == "working" { return "working now" }
        return ended.formatted(date: .abbreviated, time: .shortened)
    }
}

struct SessionDetail: View {
    let session: ClaudeSession
    @Environment(PulseStore.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let words = session.lastWords {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Claude said at the end\(saidAt):").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    Text(Self.markdown(words))
                        .font(.callout)
                        .textSelection(.enabled)
                        .lineLimit(14)
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
                }
            }
            if !session.runs.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Tests, builds and checks it ran").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    ForEach(Array(session.runs.enumerated()), id: \.offset) { _, run in
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            RunChip(run: run)
                            Text(run.command).font(.system(.caption, design: .monospaced)).lineLimit(1)
                            if let scope = run.scope { Text("only \(scope)").font(.caption).foregroundStyle(.secondary) }
                            Text(run.detail.isEmpty ? "result not captured" : run.detail)
                                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                }
            }
            if !session.edited.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Files it changed here").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    Text(session.edited.prefix(14).joined(separator: "\n")
                         + (session.editedCount > 14 ? "\n…and \(session.editedCount - 14) more" : ""))
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                }
            }
            if let prompt = session.lastPrompt {
                HStack(alignment: .top, spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Your last prompt").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                        Text(prompt).font(.callout).lineLimit(4).textSelection(.enabled)
                    }
                    Spacer(minLength: 0)
                    CopyButton(text: prompt, label: "Copy to send again")
                }
            }
            HStack(spacing: 12) {
                if let model = session.model { Text(model).font(.caption).foregroundStyle(.secondary) }
                if let branch = session.branch { Text("branch \(branch)").font(.caption).foregroundStyle(.secondary) }
                if let started = PulseDate.parse(session.started) {
                    Text("started \(started.formatted(date: .abbreviated, time: .shortened))")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.leading, 18)
    }

    /// Claude writes Markdown: bold, code and links show as such; line breaks stay.
    static func markdown(_ text: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: text, options: options)) ?? AttributedString(text)
    }

    private var saidAt: String {
        guard let date = PulseDate.parse(session.lastWordsAt) else { return "" }
        return " (\(date.formatted(date: .omitted, time: .shortened)))"
    }
}

/// What Claude remembers about this project (Claude Code's auto-memory).
struct MemoryList: View {
    let memory: [ClaudeMemory]
    @Environment(PulseStore.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label("What Claude remembers about this project", systemImage: "brain").font(.headline)
            ForEach(memory) { note in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(note.name).font(.callout.weight(.medium))
                        if !note.about.isEmpty { Text(note.about).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                    }
                    Spacer(minLength: 0)
                    Button("Open") { store.open(note.path) }.buttonStyle(.borderless).font(.caption)
                }
            }
        }
        .padding(.top, 8)
    }
}
