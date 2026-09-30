import Foundation

public struct Comment: Codable, Sendable, Identifiable, Hashable {
    public var id: String
    public var text: String
    public var at: String
    /// Ticked off: a note that was a to-do and is done. nil for a plain note (and for every note written before).
    public var done: Bool?

    public init(id: String = UUID().uuidString, text: String, at date: Date, done: Bool? = nil) {
        self.id = id
        self.text = text
        self.done = done
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        at = formatter.string(from: date)
    }
}

/// One project's comments, by item key, in `comments/<project>.json`. Only the app writes this file; Pulse's reader
/// never touches it. Each save keeps the previous version as `.bak`, and a file that can't be read is set aside,
/// never overwritten.
public struct CommentBook: Sendable {
    public let file: URL
    public private(set) var byItem: [String: [Comment]]
    /// Set when the file couldn't be read and was set aside.
    public private(set) var problem: String?

    public static func load(_ file: URL, now: Date = Date()) -> CommentBook {
        let manager = FileManager.default
        guard let data = manager.contents(atPath: file.path) else {
            return CommentBook(file: file, byItem: [:], problem: nil)
        }
        if let decoded = try? JSONDecoder().decode([String: [Comment]].self, from: data) {
            return CommentBook(file: file, byItem: decoded, problem: nil)
        }
        let stamp = Int(now.timeIntervalSince1970)
        let aside = file.deletingPathExtension().appendingPathExtension("unreadable-\(stamp).json")
        try? manager.moveItem(at: file, to: aside)
        return CommentBook(file: file, byItem: [:],
                           problem: "Your comments file couldn't be read, so Pulse kept it as \(aside.lastPathComponent) and started a new one.")
    }

    public func comments(for key: String) -> [Comment] { byItem[key] ?? [] }

    public mutating func add(_ text: String, to key: String, at date: Date = Date()) throws {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        byItem[key, default: []].append(Comment(text: trimmed, at: date))
        try save()
    }

    public mutating func remove(_ id: String, from key: String) throws {
        byItem[key]?.removeAll { $0.id == id }
        if byItem[key]?.isEmpty == true { byItem[key] = nil }
        try save()
    }

    /// Ticks a note off, or back on.
    public mutating func setDone(_ id: String, in key: String, done: Bool) throws {
        guard let index = byItem[key]?.firstIndex(where: { $0.id == id }) else { return }
        byItem[key]?[index].done = done
        try save()
    }

    /// Every note, the item it's on, newest note first.
    public var newestFirst: [(key: String, comment: Comment)] {
        byItem.flatMap { key, comments in comments.map { (key: key, comment: $0) } }
            .sorted { $0.comment.at > $1.comment.at }
    }

    public var count: Int { byItem.values.reduce(0) { $0 + $1.count } }

    /// Keys that have comments but aren't on the list any more (a problem that was fixed, a step that was renamed).
    public func orphans(present: Set<String>) -> [String] {
        byItem.keys.filter { !present.contains($0) }.sorted()
    }

    func save() throws {
        let manager = FileManager.default
        try manager.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        if manager.fileExists(atPath: file.path) {
            let backup = file.appendingPathExtension("bak")
            try? manager.removeItem(at: backup)  // Pulse's own backup only
            try? manager.copyItem(at: file, to: backup)
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(byItem).write(to: file, options: .atomic)
    }
}
