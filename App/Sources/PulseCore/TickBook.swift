import Foundation

/// The owner's ticks on checklist items: "ticked" (done, or checked by hand) or "skipped" (doesn't apply here).
public struct Tick: Codable, Sendable, Hashable {
    public var state: String
    public var at: String
}

/// One project's ticks, by checklist item key ("check:mac-app-store:screenshots"), in
/// `comments/<project>.ticks.json` next to the notes. Only the app writes it; pulse.py only reads it to count.
public struct TickBook: Sendable {
    public let file: URL
    public private(set) var ticks: [String: Tick]

    public static func load(_ file: URL) -> TickBook {
        guard let data = FileManager.default.contents(atPath: file.path),
              let decoded = try? JSONDecoder().decode([String: Tick].self, from: data) else {
            return TickBook(file: file, ticks: [:])
        }
        return TickBook(file: file, ticks: decoded)
    }

    /// The item's state with the owner's tick on top of what Pulse found.
    public func state(of item: CheckItem) -> String {
        ticks[item.key]?.state ?? (item.state == "ticked" || item.state == "skipped" ? (item.found ?? "todo") : item.state)
    }

    /// "ticked", "skipped", or nil to take the tick away.
    public mutating func set(_ key: String, to state: String?, at date: Date = Date()) throws {
        if let state {
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime]
            ticks[key] = Tick(state: state, at: formatter.string(from: date))
        } else {
            ticks[key] = nil
        }
        let manager = FileManager.default
        try manager.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        if manager.fileExists(atPath: file.path) {
            let backup = file.appendingPathExtension("bak")
            try? manager.removeItem(at: backup)  // Pulse's own backup only
            try? manager.copyItem(at: file, to: backup)
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(ticks).write(to: file, options: .atomic)
    }

    /// How many of a checklist's items are done, with the owner's ticks counted (a skipped item doesn't count).
    public func progress(of list: Checklist) -> (done: Int, total: Int) {
        let states = list.items.map { state(of: $0) }
        let counted = states.filter { $0 != "skipped" }
        return (counted.filter { $0 == "pass" || $0 == "ticked" }.count, counted.count)
    }
}
