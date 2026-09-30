import Foundation

/// Pulse's home folder: the one holding pulse.py, projects.json, out/ and comments/.
public enum PulseHome {
    public static func find(environment: [String: String] = ProcessInfo.processInfo.environment,
                            bundleURL: URL = Bundle.main.bundleURL) -> URL {
        if let custom = environment["PULSE_HOME"], !custom.isEmpty {
            return URL(fileURLWithPath: custom, isDirectory: true)
        }
        if bundleURL.pathExtension == "app" {
            return bundleURL.deletingLastPathComponent()  // Pulse.app sits in the ProjectPulse folder
        }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Developer/ProjectPulse")
    }
}

/// Runs Pulse's reader (pulse.py). It reads each project read-only and writes out/data.json; no AI, no network.
public enum Engine {
    public struct Failure: Error, CustomStringConvertible {
        public let description: String
    }

    public static func run(home: URL, arguments: [String] = ["--no-open"],
                           python: URL = URL(fileURLWithPath: "/usr/bin/python3")) async throws {
        let script = home.appendingPathComponent("pulse.py")
        guard FileManager.default.fileExists(atPath: script.path) else {
            throw Failure(description: "Pulse can't find pulse.py in \(home.path).")
        }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let process = Process()
            process.executableURL = python
            process.arguments = [script.path] + arguments
            process.currentDirectoryURL = home
            let errors = Pipe()
            process.standardError = errors
            process.standardOutput = FileHandle.nullDevice
            process.terminationHandler = { finished in
                let text = String(decoding: errors.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                if finished.terminationStatus == 0 {
                    continuation.resume()
                } else {
                    continuation.resume(throwing: Failure(description: text.isEmpty
                        ? "Pulse's reader stopped with code \(finished.terminationStatus)." : text))
                }
            }
            do {
                try process.run()
            } catch {
                continuation.resume(throwing: Failure(description: "Pulse couldn't start Python: \(error.localizedDescription)"))
            }
        }
    }
}

/// How often the app refreshes by itself.
public enum RefreshSchedule: Int, CaseIterable, Sendable, Identifiable {
    case manual = 0, every3 = 3, every6 = 6, every9 = 9, every12 = 12, every24 = 24

    public var id: Int { rawValue }
    public var label: String { self == .manual ? "Only when I click Refresh" : "Every \(rawValue) hours" }

    public func isDue(lastRefresh: Date?, now: Date) -> Bool {
        guard self != .manual else { return false }
        guard let lastRefresh else { return true }
        return now.timeIntervalSince(lastRefresh) >= Double(rawValue) * 3600
    }

    public func next(after lastRefresh: Date?) -> Date? {
        guard self != .manual, let lastRefresh else { return nil }
        return lastRefresh.addingTimeInterval(Double(rawValue) * 3600)
    }
}

/// Adds and removes projects in projects.json, keeping everything else in the file as it is.
public enum ProjectsFile {
    public enum Problem: Error, CustomStringConvertible {
        case alreadyThere(String)
        public var description: String {
            switch self {
            case .alreadyThere(let name): return "\(name) is already in Pulse."
            }
        }
    }

    /// Adds a folder and returns the name it was given.
    @discardableResult
    public static func add(folder: URL, to file: URL) throws -> String {
        var root = try read(file)
        var projects = root["projects"] as? [[String: Any]] ?? []
        let path = folder.standardizedFileURL.path
        if let existing = projects.first(where: { ($0["path"] as? String) == path }) {
            throw Problem.alreadyThere(existing["name"] as? String ?? folder.lastPathComponent)
        }
        let names = Set(projects.compactMap { $0["name"] as? String })
        var name = folder.lastPathComponent
        var number = 2
        while names.contains(name) {
            name = "\(folder.lastPathComponent) \(number)"
            number += 1
        }
        projects.append(["name": name, "path": path])
        root["projects"] = projects
        try write(root, to: file)
        return name
    }

    /// Adds several folders; the ones already in Pulse are skipped and named.
    public static func add(folders: [URL], to file: URL) throws -> (added: [String], alreadyThere: [String]) {
        var added: [String] = []
        var alreadyThere: [String] = []
        for folder in folders {
            do {
                added.append(try add(folder: folder, to: file))
            } catch Problem.alreadyThere(let name) {
                alreadyThere.append(name)
            }
        }
        return (added, alreadyThere)
    }

    public static func remove(named name: String, from file: URL) throws {
        var root = try read(file)
        let projects = root["projects"] as? [[String: Any]] ?? []
        root["projects"] = projects.filter { ($0["name"] as? String) != name }
        try write(root, to: file)
    }

    /// Switches one of Pulse's readers on or off for a project (its "off" list in projects.json).
    public static func setReader(_ reader: String, on: Bool, project name: String, in file: URL) throws {
        var root = try read(file)
        var projects = root["projects"] as? [[String: Any]] ?? []
        guard let index = projects.firstIndex(where: { ($0["name"] as? String) == name }) else { return }
        var off = (projects[index]["off"] as? [String]) ?? []
        off.removeAll { $0 == reader }
        if !on { off.append(reader) }
        if off.isEmpty {
            projects[index].removeValue(forKey: "off")
        } else {
            projects[index]["off"] = off.sorted()
        }
        root["projects"] = projects
        try write(root, to: file)
    }

    /// Adds a checklist to a project by hand, or takes one away (one Pulse picked by itself is then hidden):
    /// the project's "checklists" and "hiddenChecklists" in projects.json.
    public static func setChecklist(_ list: String, on: Bool, detected: Bool, project name: String,
                                    in file: URL) throws {
        var root = try read(file)
        var projects = root["projects"] as? [[String: Any]] ?? []
        guard let index = projects.firstIndex(where: { ($0["name"] as? String) == name }) else { return }
        var added = (projects[index]["checklists"] as? [String]) ?? []
        var hidden = (projects[index]["hiddenChecklists"] as? [String]) ?? []
        added.removeAll { $0 == list }
        hidden.removeAll { $0 == list }
        if on, !detected { added.append(list) }
        if !on, detected { hidden.append(list) }
        for (key, value) in [("checklists", added), ("hiddenChecklists", hidden)] {
            if value.isEmpty {
                projects[index].removeValue(forKey: key)
            } else {
                projects[index][key] = value.sorted()
            }
        }
        root["projects"] = projects
        try write(root, to: file)
    }

    private static func read(_ file: URL) throws -> [String: Any] {
        guard let data = FileManager.default.contents(atPath: file.path) else { return [:] }
        return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }

    private static func write(_ root: [String: Any], to file: URL) throws {
        let data = try JSONSerialization.data(withJSONObject: root, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: file, options: .atomic)
    }
}

/// Is a folder a project, or a folder of projects (like ~/Developer)?
public enum ProjectFolders {
    static let markers = [".git", "README.md", "readme.md", "README", "CLAUDE.md", "AGENTS.md", "package.json",
                          "Package.swift", "pyproject.toml", "Cargo.toml", "go.mod", "Gemfile", "pom.xml",
                          "build.gradle", "composer.json", "pubspec.yaml", "Makefile"]

    public static func isProject(_ folder: URL) -> Bool {
        let manager = FileManager.default
        if markers.contains(where: { manager.fileExists(atPath: folder.appendingPathComponent($0).path) }) {
            return true
        }
        let names = (try? manager.contentsOfDirectory(atPath: folder.path)) ?? []
        return names.contains { $0.hasSuffix(".xcodeproj") }
    }

    /// The projects directly inside a folder, in Finder's order.
    public static func projectsInside(_ folder: URL) -> [URL] {
        let children = (try? FileManager.default.contentsOfDirectory(
            at: folder, includingPropertiesForKeys: [.isDirectoryKey], options: [.skipsHiddenFiles])) ?? []
        return children
            .filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
                && $0.pathExtension != "app" && isProject($0) }
            .sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
    }
}
