import Foundation

/// What Pulse's reader (`pulse.py`) writes to `out/data.json`: everything the app shows.
public struct PulseData: Codable, Sendable {
    public var generatedAt: String
    public var projects: [ProjectView]
    /// The homepage's briefing across every project.
    public var desk: Brief?
    /// Your own slash commands and skills, for every project (~/.claude/commands, ~/.claude/skills).
    public var globalPrompts: [GlobalPrompt]?
    /// Folders Claude Code has worked in that aren't in Pulse yet: offered on the first run.
    public var claudeFolders: [ClaudeFolder]?
}

/// One project: its progress, its roadmap and its groups. `error` is set instead when it couldn't be read.
public struct ProjectView: Codable, Sendable, Identifiable {
    public var id: String { slug }
    public var name: String
    public var slug: String
    public var path: String?
    public var error: String?
    /// "map" (read through its map in projects.json) or "auto" (Pulse worked out the layout by itself).
    public var kind: String?
    public var summary: Summary?
    public var stages: [StageProgress]?
    public var since: Since?
    public var lastCommit: Commit?
    /// How it's set up, in a few words: "Claude Code", "Step list", "Python".
    public var layout: [String]?
    /// What Pulse reads in this folder, each one can be switched off (folders read without a map).
    public var readers: [Reader]?
    /// Things to know about this reading ("a big folder: Pulse read its first 20,000 files").
    public var notes: [String]?
    public var roadmap: Roadmap?
    /// What the homepage shows: the next step, how much waits on the owner, warning signs.
    public var home: HomeSummary?
    public var groups: [ItemGroup]?
    /// The briefing: a few plain sentences about where it stands, and the first move.
    public var brief: Brief?
    /// Build, Tests, Crashes and Safety.
    public var gauges: [HealthGauge]?
    /// Its Claude Code conversations (nil when there are none, or Pulse was told not to read them).
    public var claude: ClaudeInfo?
    public var crashes: [Crash]?
    public var xcodeBuild: XcodeBuild?
    public var checklists: [Checklist]?
    public var checklistCatalog: [CatalogEntry]?
    public var prompts: PromptLibrary?
    public var claudeReading: ClaudeReading?
}

public struct HomeSummary: Codable, Sendable {
    public var next: HomeNext?
    public var needsYou: Int
    public var lastActivity: String?
    public var flags: [HomeFlag]
}

public struct HomeNext: Codable, Sendable, Hashable {
    public var key: String
    public var label: String
    public var title: String
    public var detail: String?
    public var command: String?
}

public struct HomeFlag: Codable, Sendable, Hashable {
    public var text: String
    /// now, you or could: which colour the homepage gives it.
    public var tone: String
}

public struct Summary: Codable, Sendable {
    public var stepsDone: Int
    public var stepsTotal: Int
    public var workDonePct: Int
    /// "steps", "tasks" or "stories".
    public var unit: String?
    /// True when the percentage counts a step's size (S = 1, M = 2, L = 4).
    public var weighted: Bool?
}

public struct StageProgress: Codable, Sendable, Identifiable {
    public var id: String { name }
    public var name: String
    public var done: Int
    public var total: Int
}

public struct Since: Codable, Sendable {
    public var comparedWith: String?
    public var changes: [Change]
}

public struct Change: Codable, Sendable, Hashable {
    public var kind: String
    public var text: String
    /// The short name of what changed ("RT-3c-C"), when it has one.
    public var name: String?
}

public struct Commit: Codable, Sendable {
    public var short: String
    public var subject: String
    public var date: String
}

public struct Reader: Codable, Sendable, Identifiable, Hashable {
    public var id: String
    public var name: String
    public var found: String
    public var on: Bool
}

/// Now, Next steps, Could be problems, Known problems, Missing, Done or How it's set up.
public struct ItemGroup: Codable, Sendable, Identifiable {
    public var id: String { key }
    public var key: String
    public var title: String
    public var hint: String
    public var items: [Item]
}

/// One thing on the list. `key` never changes from refresh to refresh ("step:RT-3c-C"), so comments stay with it.
public struct Item: Codable, Sendable, Identifiable, Hashable {
    public var id: String { key }
    public var key: String
    public var label: String
    public var title: String
    public var detail: String
    public var path: String?
    public var time: String?
    /// What to type in Claude Code to start it ("do docs/prompts/RT-3c-D-look-only-grid.md").
    public var command: String?
    /// It waits on the owner (a decision, a push, an errand).
    public var you: Bool?
}

/// The whole road, like the first chart: tiles, every stage and step, the gates, the owner's errands, what's after.
public struct Roadmap: Codable, Sendable {
    public var path: String?
    public var unit: String?
    /// Steps have sizes (S, M, L), so a bar's length shows the size.
    public var sized: Bool
    public var tiles: [Tile]
    public var legend: [LegendEntry]
    public var stages: [RoadStage]
    public var gatesTitle: String?
    public var gatesNote: String?
    public var gates: [Gate]?
    public var errands: [Errand]?
    public var laterTitle: String?
    public var later: [LaterRow]?
}

public struct Tile: Codable, Sendable, Hashable {
    public var label: String
    public var value: String
    public var suffix: String
}

public struct LegendEntry: Codable, Sendable, Hashable {
    public var state: String
    public var text: String
}

public struct RoadStage: Codable, Sendable, Identifiable {
    public var id: String { stageID ?? name }
    /// The stage's full name, as the header's small bars name it.
    public var stageID: String?
    public var name: String
    public var note: String?
    public var rows: [RoadRow]
}

/// One step on the road (with its size bar), or a whole list (with its progress: `done` of `total`).
public struct RoadRow: Codable, Sendable, Identifiable, Hashable {
    public var id: String { key }
    public var key: String
    public var label: String
    public var name: String
    /// done, doing, ready (prompt written), todo (prompt still to write) or blocked.
    public var state: String
    public var size: String?
    /// It waits on the owner.
    public var you: Bool?
    /// It's on the cut line: the first to go if time runs short.
    public var cut: Bool?
    public var detail: String?
    public var path: String?
    public var command: String?
    public var done: Int?
    public var total: Int?
}

public struct Gate: Codable, Sendable, Hashable {
    public var name: String
    /// done, doing, next or todo.
    public var state: String
    public var you: Bool?
    public var detail: String?
    public var path: String?
    /// Draw an arrow before it: the gates before it come first.
    public var arrowBefore: Bool?
}

public struct Errand: Codable, Sendable, Hashable {
    public var text: String
    public var done: Bool
}

public struct LaterRow: Codable, Sendable, Hashable {
    public var group: String
    public var label: String
    public var text: String
    public var path: String?
}

public enum PulseDataFile {
    public static func load(from url: URL) throws -> PulseData {
        try JSONDecoder().decode(PulseData.self, from: Data(contentsOf: url))
    }
}

public enum PulseDate {
    /// "2026-09-30T15:32:01+10:00" or "2026-09-30".
    public static func parse(_ text: String?) -> Date? {
        guard let text, !text.isEmpty else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: text) { return date }
        formatter.formatOptions = [.withFullDate]
        return formatter.date(from: text)
    }
}
