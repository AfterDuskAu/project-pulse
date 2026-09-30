import Foundation
import Testing
@testable import PulseCore

private func temporaryFolder() throws -> URL {
    let folder = FileManager.default.temporaryDirectory.appendingPathComponent("pulse-tests-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    return folder
}

@Suite struct ReadingPulsesData {
    @Test func decodesWhatThePythonReaderWrites() throws {
        let json = """
        {"generatedAt": "2026-09-30T15:32:01+10:00", "projects": [
          {"name": "Demo", "slug": "demo", "path": "/x",
           "summary": {"stepsDone": 1, "stepsTotal": 3, "workDonePct": 25},
           "stages": [{"name": "Stage 1 — first", "done": 1, "total": 3}],
           "since": {"comparedWith": null, "changes": [{"kind": "finished", "text": "A-1 finished: First"}]},
           "lastCommit": {"short": "abc1234", "subject": "A-1", "date": "2026-09-30T12:00:00+10:00"},
           "groups": [{"key": "next", "title": "Next", "hint": "Ready to start, or waiting on you.",
                       "items": [{"key": "step:B-1", "label": "B-1", "title": "Second", "detail": "Ready to start",
                                  "path": null, "time": null}]}]},
          {"name": "Broken", "slug": "broken", "error": "FileNotFoundError: gone"}]}
        """
        let data = try JSONDecoder().decode(PulseData.self, from: Data(json.utf8))
        #expect(data.projects.count == 2)
        #expect(data.projects[0].groups?.first?.items.first?.key == "step:B-1")
        #expect(data.projects[0].summary?.workDonePct == 25)
        #expect(data.projects[1].error == "FileNotFoundError: gone")
        #expect(PulseDate.parse(data.generatedAt) != nil)
        #expect(PulseDate.parse("2026-09-30") != nil)
    }

    /// The real file on this Mac, when there is one: the Python side and the Swift side agree.
    @Test(.enabled(if: FileManager.default.fileExists(atPath: PulseHome.find().appendingPathComponent("out/data.json").path)))
    func decodesTheRealReading() throws {
        let data = try PulseDataFile.load(from: PulseHome.find().appendingPathComponent("out/data.json"))
        #expect(!data.projects.isEmpty)
        for project in data.projects where project.error == nil {
            #expect(project.groups?.map(\.key) == ["now", "next", "could", "known", "missing", "done", "setup"])
            #expect(project.roadmap != nil)
        }
    }
}

@Suite struct ReadingTheRoadmap {
    @Test func decodesRoadmapCommandsAndReaders() throws {
        let json = """
        {"generatedAt": "2026-09-30T17:00:00+10:00", "projects": [
          {"name": "Music", "slug": "music", "path": "/m", "kind": "auto", "layout": ["Claude Code", "Step list"],
           "readers": [{"id": "codenotes", "name": "TODO and FIXME notes in the code", "found": "3 TODO", "on": true}],
           "notes": [],
           "summary": {"stepsDone": 13, "stepsTotal": 14, "workDonePct": 93, "unit": "steps", "weighted": false},
           "stages": [{"name": "Steps", "done": 13, "total": 14}],
           "since": {"comparedWith": "2026-09-30T15:00:00+10:00",
                     "changes": [{"kind": "finished", "text": "10 finished: Lyrics", "name": "10"}]},
           "lastCommit": null,
           "roadmap": {"path": "/m/prompts/README.md", "unit": "steps", "sized": false,
             "tiles": [{"label": "Steps done", "value": "13", "suffix": "of 14"}],
             "legend": [{"state": "done", "text": "Done"}, {"state": "ready", "text": "Prompt written"}],
             "stages": [{"name": "Steps", "note": "", "rows": [
               {"key": "step:11", "label": "11", "name": "JSON-RPC server", "state": "ready", "size": null,
                "you": false, "cut": false, "detail": "Up next · prompt written", "path": "/m/prompts/11-rpc.md",
                "command": "do prompts/11-rpc.md", "done": null, "total": null}]}],
             "gatesTitle": null, "gatesNote": null, "gates": [], "errands": [],
             "laterTitle": "Roadmap after v0.1", "later": [{"group": "Roadmap after v0.1", "label": "0.2",
                                                          "text": "Mac app", "path": null}]},
           "groups": [{"key": "next", "title": "Next steps", "hint": "", "items": [
             {"key": "step:11", "label": "11", "title": "JSON-RPC server", "detail": "Up next", "path": null,
              "time": null, "command": "do prompts/11-rpc.md"}]}]}]}
        """
        let project = try #require(try JSONDecoder().decode(PulseData.self, from: Data(json.utf8)).projects.first)
        #expect(project.kind == "auto")
        #expect(project.summary?.weighted == false)
        #expect(project.readers?.first?.on == true)
        #expect(project.since?.changes.first?.name == "10")
        #expect(project.roadmap?.stages.first?.rows.first?.command == "do prompts/11-rpc.md")
        #expect(project.roadmap?.later?.first?.label == "0.2")
        #expect(project.groups?.first?.items.first?.command == "do prompts/11-rpc.md")
    }
}

@Suite struct KeepingComments {
    @Test func commentsSurviveAReloadAndStayWithTheirItem() throws {
        let file = try temporaryFolder().appendingPathComponent("comments/demo.json")
        var book = CommentBook.load(file)
        try book.add("  Check ⌘A on the real catalog  ", to: "step:RT-3c-C")
        try book.add("", to: "step:RT-3c-C")  // empty: ignored
        try book.add("Ask about it in RT-3c-E", to: "issue:abc")

        let reloaded = CommentBook.load(file)
        #expect(reloaded.comments(for: "step:RT-3c-C").map(\.text) == ["Check ⌘A on the real catalog"])
        #expect(reloaded.comments(for: "issue:abc").count == 1)
        #expect(reloaded.orphans(present: ["step:RT-3c-C"]) == ["issue:abc"])
    }

    @Test func removingTheLastCommentForgetsTheItem() throws {
        let file = try temporaryFolder().appendingPathComponent("demo.json")
        var book = CommentBook.load(file)
        try book.add("one", to: "step:A-1")
        let id = try #require(book.comments(for: "step:A-1").first?.id)
        try book.remove(id, from: "step:A-1")
        #expect(CommentBook.load(file).byItem.isEmpty)
        #expect(FileManager.default.fileExists(atPath: file.appendingPathExtension("bak").path))
    }

    @Test func anUnreadableFileIsSetAsideNeverOverwritten() throws {
        let folder = try temporaryFolder()
        let file = folder.appendingPathComponent("demo.json")
        try Data("not json".utf8).write(to: file)
        let book = CommentBook.load(file, now: Date(timeIntervalSince1970: 1000))
        #expect(book.byItem.isEmpty)
        #expect(book.problem != nil)
        let aside = folder.appendingPathComponent("demo.unreadable-1000.json")
        #expect(try String(contentsOf: aside, encoding: .utf8) == "not json")
    }
}

@Suite struct NotesAsToDos {
    @Test func olderNotesStillLoadAndCanBeTickedOff() throws {
        let file = try temporaryFolder().appendingPathComponent("demo.json")
        try Data(#"{"step:A-1": [{"id": "n1", "text": "Check it on the real catalog", "at": "2026-09-30T10:00:00+10:00"}]}"#.utf8)
            .write(to: file)
        var book = CommentBook.load(file)
        #expect(book.comments(for: "step:A-1").first?.done == nil)  // written before notes could be ticked
        try book.setDone("n1", in: "step:A-1", done: true)
        #expect(CommentBook.load(file).comments(for: "step:A-1").first?.done == true)
        try book.add("Ask about the icon", to: Handoff.projectKey, at: Date(timeIntervalSince1970: 2_000_000_000))
        #expect(book.newestFirst.first?.key == Handoff.projectKey)
        #expect(book.count == 2)
    }
}

@Suite struct TextForAnAIChat {
    private func project() throws -> ProjectView {
        let json = """
        {"name": "Music", "slug": "music", "path": "/m", "kind": "auto",
         "summary": {"stepsDone": 13, "stepsTotal": 14, "workDonePct": 93, "unit": "steps", "weighted": false},
         "home": {"next": {"key": "step:11", "label": "11", "title": "JSON-RPC server", "detail": "Up next",
                           "command": "do prompts/11-rpc.md"},
                  "needsYou": 1, "lastActivity": "2026-09-30T16:00:00+10:00",
                  "flags": [{"text": "1 commit not pushed yet", "tone": "you"}]},
         "groups": [
           {"key": "next", "title": "Next steps", "hint": "", "items": [
             {"key": "step:11", "label": "11", "title": "JSON-RPC server", "detail": "Up next", "path": null,
              "time": null, "command": "do prompts/11-rpc.md", "you": false}]},
           {"key": "known", "title": "Known problems", "hint": "", "items": [
             {"key": "issue:moving", "label": "Needs the owner's decision", "title": "Moving the folder loses work",
              "detail": "Decide: now or later?", "path": null, "time": null, "command": null, "you": true}]}]}
        """
        return try JSONDecoder().decode(ProjectView.self, from: Data(json.utf8))
    }

    @Test func theStatusSaysWhereItStandsWithMyNotes() throws {
        let project = try project()
        #expect(project.home?.next?.command == "do prompts/11-rpc.md")
        #expect(project.home?.flags.first?.tone == "you")
        var book = CommentBook.load(try temporaryFolder().appendingPathComponent("music.json"))
        try book.add("Keep the old CLI working", to: "step:11")
        try book.add("Buy a bigger drive", to: Handoff.projectKey)
        let text = Handoff.status(of: project, notes: book)
        #expect(text.hasPrefix("# Music: where it stands"))
        #expect(text.contains("Progress: 13 of 14 steps done (93%)."))
        #expect(text.contains("- 11: JSON-RPC server (Up next) — start it with: do prompts/11-rpc.md"))
        #expect(text.contains("## Waiting on me\n- Moving the folder loses work (Decide: now or later?)"))
        #expect(text.contains("- On “11 — JSON-RPC server”: Keep the old CLI working"))
        #expect(text.contains("- On “The whole project”: Buy a bigger drive"))
    }

    @Test func aCommandCarriesTheNotesThatAreStillOpen() {
        let open = Comment(text: "Keep the old CLI working", at: Date())
        let finished = Comment(text: "Already checked", at: Date(), done: true)
        #expect(Handoff.command("do prompts/11-rpc.md", notes: []) == "do prompts/11-rpc.md")
        #expect(Handoff.command("do prompts/11-rpc.md", notes: [open, finished])
                == "do prompts/11-rpc.md\n\nMy notes on this step:\n- Keep the old CLI working")
        #expect(Handoff.promptText("# Step 11\nBuild it.\n", notes: [open])
                == "# Step 11\nBuild it.\n\n## My notes on this step\n- Keep the old CLI working\n")
    }
}

@Suite struct RefreshingBySchedule {
    @Test func manualIsNeverDue() {
        #expect(!RefreshSchedule.manual.isDue(lastRefresh: nil, now: Date()))
    }

    @Test func dueAfterItsHours() {
        let last = Date(timeIntervalSince1970: 0)
        #expect(!RefreshSchedule.every3.isDue(lastRefresh: last, now: last.addingTimeInterval(3 * 3600 - 1)))
        #expect(RefreshSchedule.every3.isDue(lastRefresh: last, now: last.addingTimeInterval(3 * 3600)))
        #expect(RefreshSchedule.every24.isDue(lastRefresh: nil, now: last))
        #expect(RefreshSchedule.every6.next(after: last) == last.addingTimeInterval(6 * 3600))
    }
}

@Suite struct EditingTheProjectList {
    @Test func addingKeepsEverythingElseAndRefusesTwins() throws {
        let folder = try temporaryFolder()
        let file = folder.appendingPathComponent("projects.json")
        try Data(#"{"projects": [{"name": "Trailmix", "path": "/p", "map": {"roadmap": "docs/r.md"}}], "note": "kept"}"#.utf8)
            .write(to: file)
        let project = folder.appendingPathComponent("Trailmix", isDirectory: true)
        let name = try ProjectsFile.add(folder: project, to: file)
        #expect(name == "Trailmix 2")  // the name is taken, the folder isn't

        let root = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
        let projects = try #require(root["projects"] as? [[String: Any]])
        #expect(root["note"] as? String == "kept")
        #expect((projects[0]["map"] as? [String: String])?["roadmap"] == "docs/r.md")
        #expect(projects.count == 2)
        #expect(throws: ProjectsFile.Problem.self) { try ProjectsFile.add(folder: project, to: file) }

        try ProjectsFile.remove(named: "Trailmix 2", from: file)
        let after = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
        #expect((after["projects"] as? [[String: Any]])?.count == 1)
    }

    @Test func readersCanBeSwitchedOffAndOnAgain() throws {
        let file = try temporaryFolder().appendingPathComponent("projects.json")
        try Data(#"{"projects": [{"name": "Music", "path": "/m"}, {"name": "Other", "path": "/o"}]}"#.utf8).write(to: file)
        try ProjectsFile.setReader("codenotes", on: false, project: "Music", in: file)
        try ProjectsFile.setReader("logs", on: false, project: "Music", in: file)
        func off() throws -> [String]? {
            let root = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
            let projects = try #require(root["projects"] as? [[String: Any]])
            #expect(projects[1]["off"] == nil)  // the other project is untouched
            return projects[0]["off"] as? [String]
        }
        #expect(try off() == ["codenotes", "logs"])
        try ProjectsFile.setReader("codenotes", on: true, project: "Music", in: file)
        try ProjectsFile.setReader("logs", on: true, project: "Music", in: file)
        #expect(try off() == nil)  // nothing left off: the key goes
    }

    @Test func addingSeveralFoldersSkipsTheOnesAlreadyThere() throws {
        let folder = try temporaryFolder()
        let file = folder.appendingPathComponent("projects.json")
        try Data(#"{"projects": []}"#.utf8).write(to: file)
        let one = folder.appendingPathComponent("One", isDirectory: true)
        let two = folder.appendingPathComponent("Two", isDirectory: true)
        _ = try ProjectsFile.add(folder: one, to: file)
        let result = try ProjectsFile.add(folders: [one, two], to: file)
        #expect(result.added == ["Two"])
        #expect(result.alreadyThere == ["One"])
    }

    @Test func aFolderOfProjectsIsNotItselfAProject() throws {
        let developer = try temporaryFolder()
        let manager = FileManager.default
        for (name, marker) in [("Beta", ".git"), ("alpha", "README.md"), ("Gamma", "Package.swift")] {
            let project = developer.appendingPathComponent(name, isDirectory: true)
            try manager.createDirectory(at: project, withIntermediateDirectories: true)
            if marker == ".git" {
                try manager.createDirectory(at: project.appendingPathComponent(marker), withIntermediateDirectories: true)
            } else {
                try Data().write(to: project.appendingPathComponent(marker))
            }
        }
        try manager.createDirectory(at: developer.appendingPathComponent("Empty"), withIntermediateDirectories: true)
        #expect(!ProjectFolders.isProject(developer))
        #expect(ProjectFolders.projectsInside(developer).map(\.lastPathComponent) == ["alpha", "Beta", "Gamma"])
        #expect(ProjectFolders.isProject(developer.appendingPathComponent("Beta")))
    }

    @Test func homeIsTheFolderHoldingTheApp() {
        let app = URL(fileURLWithPath: "/Users/someone/Developer/ProjectPulse/Pulse.app")
        #expect(PulseHome.find(environment: [:], bundleURL: app).path == "/Users/someone/Developer/ProjectPulse")
        #expect(PulseHome.find(environment: ["PULSE_HOME": "/tmp/p"], bundleURL: app).path == "/tmp/p")
    }
}

@Suite struct TheBriefing {
    static let json = """
    {"generatedAt": "2026-09-30T19:00:00+10:00", "projects": [
      {"name": "Demo", "slug": "demo", "path": "/x", "groups": [],
       "brief": {"lines": [{"kind": "now", "text": "We're on A-1.", "say": "We're on A-1.", "tone": "you",
                            "source": {"label": "NEXT-UP.md", "path": "/x/NEXT-UP.md"},
                            "target": {"group": "now", "key": "step:A-1"}}],
                 "close": {"text": "First move is yours: A-1.", "group": "now", "key": "step:A-1", "copy": null},
                 "at": "2026-09-30T19:00:00+10:00"},
       "gauges": [{"key": "tests", "label": "Tests", "state": "bad", "value": "Failed",
                   "detail": "3 tests picked by -k grid · today at 17:03", "at": "2026-09-30T17:03:00+10:00",
                   "source": "Claude Code: pytest -k grid", "why": "AssertionError: tile size"}],
       "claude": {"sessions": [{"id": "s1", "title": "Grid work", "started": null, "ended": "2026-09-30T18:00:00+10:00",
                                "state": "stopped", "stop": {"why": "limit", "text": "You've hit your session limit", "at": null},
                                "prompts": 3, "model": "claude-opus-5-5", "branch": null, "app": "Claude app",
                                "lastWords": "Done.", "lastWordsAt": null, "lastPrompt": "go on", "edited": ["a.py"],
                                "editedCount": 1, "editedElsewhere": 0, "startedHere": true, "startedIn": "/x",
                                "runs": [{"at": null, "kind": "test", "command": "pytest", "dir": "/x", "piped": false,
                                          "scope": null, "background": false, "outcome": "pass", "detail": "3 passed", "tests": 3}],
                                "cost": null, "compactions": 0, "gone": false, "readable": true}],
                  "sessionCount": 1, "prompts": [], "promptCount": 3, "working": [], "open": [],
                  "lastTest": null, "lastWholeTest": null, "lastBuild": null, "lastCheck": null, "lastBench": null,
                  "stops": [], "week": {"sessions": 1, "prompts": 3, "added": 10, "removed": 2, "usd": 1.5},
                  "memory": [], "unreadable": null, "since": "2026-09-22T06:00:00+10:00"},
       "crashes": [{"at": "2026-09-30T13:42:03+10:00", "app": "Demo", "tests": false, "version": "1.0",
                    "exception": "an uncaught exception", "where": "Grid.reload", "path": "/r/Demo.ips"}],
       "xcodeBuild": null,
       "checklists": [{"id": "mac-app-store", "title": "Mac App Store", "why": "Pulse found an Xcode project.",
                       "items": [{"key": "check:mac-app-store:icon", "text": "The app icon has all its pictures",
                                  "why": "Uploads are refused without it.", "state": "fail", "auto": true,
                                  "evidence": "0 of 10 pictures", "found": null, "path": null},
                                 {"key": "check:mac-app-store:screenshots", "text": "Screenshots are made", "why": "",
                                  "state": "todo", "auto": false, "evidence": "", "found": null, "path": null}],
                       "done": 0, "total": 2, "added": false}],
       "checklistCatalog": [{"id": "web", "title": "Website or web app"}],
       "prompts": {"written": [], "sent": [], "repeated": [], "unfinished": [], "sentCount": 3, "readsClaude": true,
                   "since": null},
       "claudeReading": null}],
     "desk": {"lines": [], "close": null, "at": "2026-09-30T19:00:00+10:00"},
     "globalPrompts": [], "claudeFolders": [{"path": "/Users/me/app", "last": "2026-09-30T18:00:00+10:00"}]}
    """

    @Test func decodesTheBriefingAndWhatComesWithIt() throws {
        let data = try JSONDecoder().decode(PulseData.self, from: Data(Self.json.utf8))
        let project = try #require(data.projects.first)
        #expect(project.brief?.lines.first?.target?.key == "step:A-1")
        #expect(project.gauges?.first?.why == "AssertionError: tile size")
        #expect(project.claude?.sessions.first?.stop?.why == "limit")
        #expect(project.claude?.sessions.first?.runs.first?.tests == 3)
        #expect(project.crashes?.first?.location == "Grid.reload")
        #expect(project.checklists?.first?.items.count == 2)
        #expect(data.claudeFolders?.first?.path == "/Users/me/app")
    }

    @Test func ticksCountAndCanBeTakenBack() throws {
        let data = try JSONDecoder().decode(PulseData.self, from: Data(Self.json.utf8))
        let list = try #require(data.projects.first?.checklists?.first)
        let folder = try temporaryFolder()
        var book = TickBook.load(folder.appendingPathComponent("demo.ticks.json"))
        #expect(book.progress(of: list) == (0, 2))
        try book.set("check:mac-app-store:screenshots", to: "ticked")
        try book.set("check:mac-app-store:icon", to: "skipped")
        #expect(book.progress(of: list) == (1, 1))
        let reloaded = TickBook.load(folder.appendingPathComponent("demo.ticks.json"))
        #expect(reloaded.state(of: list.items[1]) == "ticked")
        var again = reloaded
        try again.set("check:mac-app-store:icon", to: nil)
        #expect(again.state(of: list.items[0]) == "fail")
    }

    @Test func checklistsCanBeAddedAndHidden() throws {
        let folder = try temporaryFolder()
        let file = folder.appendingPathComponent("projects.json")
        try Data(#"{"projects": [{"name": "Demo", "path": "/p"}]}"#.utf8).write(to: file)
        try ProjectsFile.setChecklist("web", on: true, detected: false, project: "Demo", in: file)
        try ProjectsFile.setChecklist("mac-app-store", on: false, detected: true, project: "Demo", in: file)
        var root = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any]
        var project = (root?["projects"] as? [[String: Any]])?.first
        #expect(project?["checklists"] as? [String] == ["web"])
        #expect(project?["hiddenChecklists"] as? [String] == ["mac-app-store"])
        try ProjectsFile.setChecklist("web", on: false, detected: false, project: "Demo", in: file)
        try ProjectsFile.setChecklist("mac-app-store", on: true, detected: true, project: "Demo", in: file)
        root = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any]
        project = (root?["projects"] as? [[String: Any]])?.first
        #expect(project?["checklists"] == nil)
        #expect(project?["hiddenChecklists"] == nil)
    }

    @Test func greetsByTheTimeOfDay() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Australia/Sydney")!
        let evening = try #require(calendar.date(from: DateComponents(year: 2026, month: 9, day: 30, hour: 19)))
        let morning = try #require(calendar.date(from: DateComponents(year: 2026, month: 9, day: 30, hour: 8)))
        #expect(Greeting.text(at: evening, callMe: "Sir", calendar: calendar) == "Good evening, sir.")
        #expect(Greeting.text(at: evening, callMe: "Sam", calendar: calendar) == "Good evening, Sam.")
        #expect(Greeting.text(at: morning, callMe: "", calendar: calendar) == "Good morning.")
        #expect(Greeting.defaultName(fullName: "D") == "")
        #expect(Greeting.defaultName(fullName: "Sam Lee") == "Sam")
    }

    @Test func theStatusCarriesHealthAndTheFirstMove() throws {
        let data = try JSONDecoder().decode(PulseData.self, from: Data(Self.json.utf8))
        let text = Handoff.status(of: try #require(data.projects.first), notes: nil)
        #expect(text.contains("- Tests: Failed (3 tests picked by -k grid · today at 17:03): AssertionError: tile size"))
        #expect(text.contains("First move, as Pulse sees it: First move is yours: A-1."))
        #expect(text.contains("## Mac App Store checklist: 0 of 2 done"))
        #expect(text.contains("Claude said at the end: Done."))
    }
}
