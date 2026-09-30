import Foundation

// What `pulse.py` adds to each project for the briefing: the spoken-style lines, the four gauges, Claude Code's
// conversations, crashes, checklists and prompts. All of it is read-only facts; the app only shows them.

/// A briefing: a few plain sentences, most important first, and the one first move.
public struct Brief: Codable, Sendable {
    public var lines: [BriefLine]
    public var close: FirstMove?
    public var at: String?
}

public struct BriefLine: Codable, Sendable, Hashable, Identifiable {
    public var id: String { "\(kind)|\(project ?? "")|\(text)" }
    /// status, working, now, next, you, error, clear, since, release, project
    public var kind: String
    public var text: String
    /// The same sentence for the voice: no file paths or symbols.
    public var say: String
    /// info, good, bad, busy or you: the colour it's shown in.
    public var tone: String
    public var source: BriefSource?
    public var target: BriefTarget?
    /// On the homepage: the project this line is about.
    public var project: String?
}

public struct BriefSource: Codable, Sendable, Hashable {
    public var label: String?
    public var path: String?
}

public struct BriefTarget: Codable, Sendable, Hashable {
    public var group: String?
    public var key: String?
}

public struct FirstMove: Codable, Sendable, Hashable {
    public var text: String
    public var group: String?
    public var key: String?
    /// What a click copies: a command or a prompt.
    public var copy: String?
    public var project: String?
}

/// Build, Tests, Crashes or Safety, as the briefing's gauges show them.
public struct HealthGauge: Codable, Sendable, Hashable, Identifiable {
    public var id: String { key }
    public var key: String
    public var label: String
    /// good, bad, warn, busy (Claude is working on it) or none (nothing on record).
    public var state: String
    public var value: String
    public var detail: String
    public var at: String?
    public var source: String?
    /// The line that says why (a failure's first error).
    public var why: String?
    public var path: String?
}

// MARK: Claude Code

public struct ClaudeInfo: Codable, Sendable {
    public var sessions: [ClaudeSession]
    public var sessionCount: Int
    public var prompts: [SentPrompt]
    public var promptCount: Int
    public var working: [String]
    public var open: [String]
    public var lastTest: Verdict?
    public var lastWholeTest: Verdict?
    public var lastBuild: Verdict?
    public var lastCheck: Verdict?
    public var lastBench: Verdict?
    public var stops: [ClaudeSession]
    public var week: ClaudeWeek
    public var memory: [ClaudeMemory]
    public var since: String?
}

public struct ClaudeSession: Codable, Sendable, Identifiable, Hashable {
    public var id: String
    public var title: String
    public var started: String?
    public var ended: String?
    /// working, open (waiting for you), finished or stopped.
    public var state: String
    public var stop: SessionStop?
    public var prompts: Int
    public var model: String?
    public var branch: String?
    public var app: String?
    /// What Claude said last, quoted.
    public var lastWords: String?
    public var lastWordsAt: String?
    public var lastPrompt: String?
    public var edited: [String]
    public var editedCount: Int
    public var editedElsewhere: Int
    public var startedHere: Bool
    public var startedIn: String?
    public var runs: [ClaudeRun]
    public var cost: SessionCost?
    public var compactions: Int?
    /// Claude Code cleaned it up; Pulse remembers it.
    public var gone: Bool?
}

public struct SessionStop: Codable, Sendable, Hashable {
    /// limit, api, interrupted, midwork, noreply or full.
    public var why: String
    public var text: String
    public var at: String?
}

public struct ClaudeRun: Codable, Sendable, Hashable {
    public var at: String?
    /// test, build, check or bench.
    public var kind: String
    public var command: String
    public var outcome: String
    public var detail: String
    public var scope: String?
    public var tests: Int?
}

public struct Verdict: Codable, Sendable, Hashable {
    public var at: String?
    public var kind: String
    public var command: String
    public var outcome: String
    public var detail: String
    public var scope: String?
    public var tests: Int?
    public var sessionTitle: String?
}

public struct SessionCost: Codable, Sendable, Hashable {
    public var usd: Double
    public var added: Int
    public var removed: Int
    public var tokens: Int
}

public struct ClaudeWeek: Codable, Sendable, Hashable {
    public var sessions: Int
    public var prompts: Int
    public var added: Int
    public var removed: Int
    public var usd: Double
}

public struct ClaudeMemory: Codable, Sendable, Hashable, Identifiable {
    public var id: String { path }
    public var name: String
    public var about: String
    public var path: String
}

public struct SentPrompt: Codable, Sendable, Hashable, Identifiable {
    public var id: String { "\(session)|\(at ?? "")|\(text.prefix(40))" }
    public var at: String?
    public var text: String
    public var session: String
    public var sessionTitle: String?
    public var startedHere: Bool?
}

// MARK: Crashes

public struct Crash: Codable, Sendable, Hashable, Identifiable {
    public var id: String { path }
    public var at: String
    public var app: String
    /// A crash of a test run, not of the app.
    public var tests: Bool
    public var version: String?
    public var exception: String
    public var location: String?
    public var path: String

    enum CodingKeys: String, CodingKey {
        case at, app, tests, version, exception, path
        case location = "where"
    }
}

public struct XcodeBuild: Codable, Sendable, Hashable {
    public var at: String
    public var outcome: String
    public var title: String
    public var errors: Int
    public var warnings: Int
}

// MARK: Checklists

public struct Checklist: Codable, Sendable, Identifiable {
    public var id: String
    public var title: String
    public var why: String
    public var items: [CheckItem]
    public var done: Int
    public var total: Int
    public var added: Bool?
}

public struct CheckItem: Codable, Sendable, Hashable, Identifiable {
    public var id: String { key }
    public var key: String
    public var text: String
    public var why: String
    /// pass, fail, warn, todo, ticked or skipped.
    public var state: String
    /// Pulse checks it from the files; otherwise the owner ticks it.
    public var auto: Bool
    public var evidence: String
    /// What Pulse found before the owner's tick overruled it.
    public var found: String?
    public var path: String?
}

public struct CatalogEntry: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var title: String
}

// MARK: Prompts

public struct PromptLibrary: Codable, Sendable {
    public var written: [WrittenPrompt]
    public var sent: [SentPrompt]
    public var repeated: [RepeatedPrompt]
    public var unfinished: [UnfinishedSession]
    public var sentCount: Int
    public var readsClaude: Bool
    /// The oldest conversation Pulse can see: "never sent" means since then.
    public var since: String?
}

public struct WrittenPrompt: Codable, Sendable, Hashable, Identifiable {
    public var id: String { key }
    /// step, command, skill, agent or prompt.
    public var kind: String
    public var rel: String
    public var path: String
    public var title: String
    /// How to use it: "do docs/prompts/AS-1.md", "/review".
    public var use: String
    public var name: String
    public var step: String?
    public var state: String?
    public var sent: Int
    public var lastSent: String?
    public var key: String
    public var neverSent: Bool
}

public struct RepeatedPrompt: Codable, Sendable, Hashable, Identifiable {
    public var id: String { text }
    public var text: String
    public var times: Int
    public var last: String
}

public struct UnfinishedSession: Codable, Sendable, Hashable, Identifiable {
    public var id: String { session }
    public var session: String
    public var title: String
    public var why: String?
    public var text: String?
    public var at: String?
    public var lastPrompt: String?
}

public struct GlobalPrompt: Codable, Sendable, Hashable, Identifiable {
    public var id: String { path }
    public var kind: String
    public var title: String
    public var use: String
    public var path: String
}

/// A folder Claude Code has worked in on this Mac that isn't in Pulse yet.
public struct ClaudeFolder: Codable, Sendable, Hashable, Identifiable {
    public var id: String { path }
    public var path: String
    public var last: String
}

/// What Claude said when the owner asked it to look (the "Ask Claude" button): its own card, never a status.
public struct ClaudeReading: Codable, Sendable {
    public var at: String
    public var model: String?
    public var seconds: Double?
    public var costUSD: Double?
    public var headline: String
    public var items: [ReadingItem]
    public var problem: String?
}

public struct ReadingItem: Codable, Sendable, Hashable, Identifiable {
    public var id: String { "\(kind)|\(text)" }
    /// now, next, needs-you, problem, risk, contradiction or idea.
    public var kind: String
    public var text: String
    public var evidence: String?
    public var sure: String?
}
