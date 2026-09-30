import Foundation

/// Text to paste into an AI chat (Claude, ChatGPT, Meta AI…): where a project stands, and a step with your notes.
/// It's put together from what Pulse already read, so it costs nothing and guesses nothing.
public enum Handoff {
    /// The key a note on the whole project is kept under.
    public static let projectKey = "project"

    /// "Where it stands" for a new chat: progress, now, next steps, what waits on you, problems, recent work, notes.
    public static func status(of project: ProjectView, notes: CommentBook?, date: Date = Date()) -> String {
        var lines = ["# \(project.name): where it stands",
                     "(From Pulse, \(date.formatted(date: .abbreviated, time: .shortened)). Pulse reads the project's files and git history; nothing below is guessed.)",
                     ""]
        if let summary = project.summary, summary.stepsTotal > 0 {
            let unit = summary.unit ?? "steps"
            lines.append("Progress: \(summary.stepsDone) of \(summary.stepsTotal) \(unit) done (\(summary.workDonePct)%).")
            lines.append("")
        }
        if let gauges = project.gauges, !gauges.isEmpty {
            lines.append("## Health")
            for gauge in gauges {
                lines.append("- \(gauge.label): \(gauge.value)" + (gauge.detail.isEmpty ? "" : " (\(gauge.detail))")
                             + (gauge.why.map { ": \($0)" } ?? ""))
            }
            lines.append("")
        }
        if let move = project.brief?.close {
            lines.append("First move, as Pulse sees it: \(move.text)")
            lines.append("")
        }
        let groups = project.groups ?? []
        func section(_ key: String, _ title: String, limit: Int) {
            guard let items = groups.first(where: { $0.key == key })?.items, !items.isEmpty else { return }
            lines.append("## \(title)")
            for item in items.prefix(limit) {
                var line = "- \(item.label): \(item.title)"
                if !item.detail.isEmpty { line += " (\(item.detail))" }
                if let command = item.command { line += " — start it with: \(command)" }
                lines.append(line)
            }
            if items.count > limit { lines.append("- …and \(items.count - limit) more") }
            lines.append("")
        }
        section("now", "Now", limit: 8)
        section("next", "Next steps", limit: 10)
        let waiting = groups.filter { $0.key != "next" && $0.key != "setup" }
            .flatMap(\.items).filter { $0.you == true }
        if !waiting.isEmpty {
            lines.append("## Waiting on me")
            lines += waiting.prefix(8).map { "- \($0.title)" + ($0.detail.isEmpty ? "" : " (\($0.detail))") }
            lines.append("")
        }
        section("could", "Could be problems", limit: 8)
        section("known", "Known problems", limit: 8)
        section("missing", "Missing", limit: 6)
        section("done", "Recently done", limit: 5)
        if let release = project.checklists?.first(where: { $0.id != "basics" }) {
            let failing = release.items.filter { $0.state == "fail" }.map(\.text)
            lines.append("## \(release.title) checklist: \(release.done) of \(release.total) done")
            lines += failing.prefix(8).map { "- Not yet: \($0)" }
            lines.append("")
        }
        if let session = project.claude?.sessions.first, let words = session.lastWords {
            lines.append("## The last Claude session: \(session.title)")
            lines.append("Claude said at the end: \(words.prefix(700))")
            lines.append("")
        }
        let notes = noteLines(project: project, notes: notes)
        if !notes.isEmpty {
            lines.append("## My notes")
            lines += notes
            lines.append("")
        }
        return lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines) + "\n"
    }

    /// The command that starts a step, with your notes on it, so they reach the session doing the step.
    public static func command(_ command: String, notes: [Comment]) -> String {
        let open = notes.filter { $0.done != true }
        guard !open.isEmpty else { return command }
        return command + "\n\nMy notes on this step:\n" + open.map { "- \($0.text)" }.joined(separator: "\n")
    }

    /// A step's whole prompt, for a chat that can't read the project's files (ChatGPT, Meta AI), with your notes.
    public static func promptText(_ text: String, notes: [Comment]) -> String {
        let open = notes.filter { $0.done != true }
        guard !open.isEmpty else { return text }
        return text.trimmingCharacters(in: .whitespacesAndNewlines) + "\n\n## My notes on this step\n"
            + open.map { "- \($0.text)" }.joined(separator: "\n") + "\n"
    }

    /// Every note in a project as Markdown, grouped by what it's on.
    public static func notes(of project: ProjectView, notes: CommentBook?) -> String {
        let lines = noteLines(project: project, notes: notes)
        return lines.isEmpty ? "" : "# My notes on \(project.name)\n\n" + lines.joined(separator: "\n") + "\n"
    }

    /// The title of whatever a key points at ("step:RT-3c-D" → "RT-3c-D — The new grid's look…").
    public static func title(of key: String, in project: ProjectView) -> String? {
        if key == projectKey { return "The whole project" }
        if let item = (project.groups ?? []).flatMap(\.items).first(where: { $0.key == key }) {
            return item.label.isEmpty ? item.title : "\(item.label) — \(item.title)"
        }
        if let row = (project.roadmap?.stages ?? []).flatMap(\.rows).first(where: { $0.key == key }) {
            return "\(row.label) — \(row.name)"
        }
        return nil
    }

    static func noteLines(project: ProjectView, notes: CommentBook?) -> [String] {
        guard let notes else { return [] }
        var lines: [String] = []
        for key in notes.byItem.keys.sorted(by: { ($0 == projectKey ? "" : $0) < ($1 == projectKey ? "" : $1) }) {
            let comments = notes.comments(for: key)
            guard !comments.isEmpty else { continue }
            let what = title(of: key, in: project) ?? "Something no longer listed (\(key))"
            for comment in comments {
                lines.append("- \(comment.done == true ? "[done] " : "")On “\(what)”: \(comment.text)")
            }
        }
        return lines
    }
}
