import AppKit
import PulseCore
import SwiftUI

// The briefing: "Good evening. We're on BIG-0, which waits on you. Next up: AS-1…", read aloud on request, with the
// gauges and panels an assistant would glance at. The homepage has one for every project; each project has its own.

/// The briefing's look: dark, calm, one accent colour, colours that mean something.
enum HUD {
    static let top = Color(red: 0.03, green: 0.05, blue: 0.10)
    static let bottom = Color(red: 0.05, green: 0.09, blue: 0.16)
    static let accent = Color(red: 0.25, green: 0.84, blue: 0.96)
    static let panel = Color.white.opacity(0.045)
    static let edge = accent.opacity(0.20)

    static var background: some View {
        LinearGradient(colors: [top, bottom], startPoint: .top, endPoint: .bottom).ignoresSafeArea()
    }

    static func tone(_ tone: String) -> Color {
        switch tone {
        case "good": return Color(red: 0.30, green: 0.86, blue: 0.60)
        case "bad": return Color(red: 1.00, green: 0.40, blue: 0.43)
        case "warn": return Color(red: 1.00, green: 0.72, blue: 0.30)
        case "busy": return Color(red: 0.53, green: 0.60, blue: 1.00)
        case "you": return Color(red: 0.75, green: 0.55, blue: 1.00)
        case "none": return Color.white.opacity(0.35)
        default: return Color.white.opacity(0.85)
        }
    }

    static func icon(_ kind: String, tone: String) -> String {
        switch kind {
        case "status": return "chart.pie"
        case "working": return "sparkles"
        case "now": return tone == "you" ? "person.fill" : "play.fill"
        case "next": return "arrow.right.circle"
        case "you": return "person.2"
        case "error": return tone == "busy" ? "hourglass" : "exclamationmark.triangle.fill"
        case "clear": return "checkmark.seal"
        case "since": return "clock.arrow.circlepath"
        case "release": return "shippingbox"
        case "project": return "folder"
        default: return "circle"
        }
    }
}

/// What the voice reads: each line's spoken form, then the first move.
enum Spoken {
    static func lines(of brief: Brief?) -> [(id: String, text: String)] {
        guard let brief else { return [] }
        var spoken: [(id: String, text: String)] = brief.lines.map { (id: $0.id, text: $0.say) }
        if let move = brief.close { spoken.append((id: "close", text: move.text)) }
        return spoken
    }
}

/// A panel: a small title in capitals, then what it shows.
struct HUDPanel<Content: View>: View {
    let title: String
    let systemImage: String
    var trailing: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: systemImage).font(.caption)
                Text(title.uppercased()).font(.caption.weight(.semibold)).tracking(1.4)
                Spacer(minLength: 0)
                if let trailing {
                    Text(trailing).font(.caption).monospacedDigit()
                }
            }
            .foregroundStyle(HUD.accent.opacity(0.85))
            content
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 14).fill(HUD.panel))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(HUD.edge))
    }
}

/// A progress ring, like an arc reactor: how much is done.
struct Ring: View {
    let fraction: Double
    var size: CGFloat = 96
    var line: CGFloat = 9
    var label: String
    var caption: String?

    var body: some View {
        ZStack {
            Circle().stroke(Color.white.opacity(0.07), lineWidth: line)
            Circle().stroke(HUD.accent.opacity(0.12), lineWidth: 1).padding(line + 5)
            Circle()
                .trim(from: 0, to: max(0.001, min(1, fraction)))
                .stroke(AngularGradient(colors: [HUD.accent.opacity(0.45), HUD.accent], center: .center),
                        style: StrokeStyle(lineWidth: line, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .shadow(color: HUD.accent.opacity(0.55), radius: 6)
            VStack(spacing: 0) {
                Text(label).font(.system(size: size * 0.24, weight: .semibold, design: .rounded)).monospacedDigit()
                if let caption {
                    Text(caption).font(.system(size: max(9, size * 0.1))).foregroundStyle(.secondary)
                }
            }
        }
        .frame(width: size, height: size)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(label) done")
    }
}

/// The briefing's sentences. The one being read aloud lights up; a click goes to where it came from.
struct BriefScript: View {
    let lines: [BriefLine]
    var go: (BriefLine) -> Void
    @Environment(PulseStore.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(lines) { line in
                Button {
                    go(line)
                } label: {
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Image(systemName: HUD.icon(line.kind, tone: line.tone))
                            .font(.callout)
                            .foregroundStyle(HUD.tone(line.tone))
                            .frame(width: 18)
                        Text(line.text)
                            .font(.title3)
                            .foregroundStyle(.primary.opacity(store.speaker.current == nil
                                                              || store.speaker.current == line.id ? 1 : 0.55))
                            .fixedSize(horizontal: false, vertical: true)
                            .multilineTextAlignment(.leading)
                        Spacer(minLength: 0)
                        if let label = line.source?.label {
                            Text(label)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Capsule().strokeBorder(Color.white.opacity(0.15)))
                                .lineLimit(1)
                                .help("Where this comes from")
                        }
                    }
                    .padding(.vertical, 4)
                    .padding(.horizontal, 8)
                    .background(RoundedRectangle(cornerRadius: 8).fill(store.speaker.current == line.id
                                                                        ? HUD.accent.opacity(0.14) : .clear))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help(line.target == nil ? "" : "Show where this comes from")
            }
        }
    }
}

/// The one thing to do first, with its command or prompt one click away.
struct FirstMoveCard: View {
    let move: FirstMove
    var go: () -> Void
    @Environment(PulseStore.self) private var store

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "scope").font(.title2).foregroundStyle(HUD.accent)
            Text(move.text).font(.headline).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            if let copy = move.copy, !copy.isEmpty {
                CopyButton(text: copy, label: "Copy")
                    .help("Copy: \(copy)")
            }
            Button("Show", action: go).buttonStyle(.bordered)
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 14).fill(HUD.accent.opacity(0.09)))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(HUD.accent.opacity(0.45)))
    }
}

/// "Good evening, sir." and the time; the button that reads the briefing aloud; how Pulse addresses the owner.
struct BriefHeader: View {
    let title: String?
    let readAt: String?
    let spoken: [(id: String, text: String)]
    let owner: String
    @Environment(PulseStore.self) private var store
    @AppStorage("callMe") private var callMe = Greeting.defaultName()
    @AppStorage("voiceID") private var voiceID = ""

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            HStack(alignment: .firstTextBaseline, spacing: 14) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(Greeting.text(at: context.date, callMe: callMe))
                        .font(.system(size: 34, weight: .semibold, design: .rounded))
                    HStack(spacing: 8) {
                        if let title {
                            Text(title).font(.title3.weight(.medium)).foregroundStyle(HUD.accent)
                        }
                        Text(subtitle(now: context.date)).foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 12)
                Button {
                    store.speaker.toggle(spokenWithGreeting(at: context.date), owner: owner, voiceID: voiceID)
                } label: {
                    Label(isMine ? "Stop" : "Brief me", systemImage: isMine ? "stop.fill" : "waveform")
                        .font(.headline)
                        .padding(.horizontal, 6)
                }
                .buttonStyle(.borderedProminent)
                .tint(HUD.accent.opacity(0.75))
                .keyboardShortcut("b", modifiers: .command)
                .help("Read the briefing aloud with a Mac voice (⌘B). Nothing leaves the Mac.")
                BriefSettings()
            }
        }
    }

    private var isMine: Bool { store.speaker.isSpeaking && store.speaker.owner == owner }

    private func spokenWithGreeting(at date: Date) -> [(id: String, text: String)] {
        [(id: "greeting", text: Greeting.text(at: date, callMe: callMe))] + spoken
    }

    private func subtitle(now: Date) -> String {
        let clock = now.formatted(date: .complete, time: .shortened)
        guard let read = PulseDate.parse(readAt) else { return clock }
        return "\(clock) · read \(read.formatted(.relative(presentation: .named))), no AI used"
    }
}

/// How Pulse calls you, and which voice reads the briefing.
struct BriefSettings: View {
    @AppStorage("callMe") private var callMe = Greeting.defaultName()
    @AppStorage("voiceID") private var voiceID = ""
    @State private var open = false

    var body: some View {
        Button {
            open.toggle()
        } label: {
            Image(systemName: "person.crop.circle.badge.questionmark")
        }
        .buttonStyle(.borderless)
        .help("How Pulse greets you, and its voice")
        .popover(isPresented: $open, arrowEdge: .bottom) {
            VStack(alignment: .leading, spacing: 12) {
                Text("How should Pulse greet you?").font(.headline)
                HStack {
                    ForEach(choices, id: \.self) { choice in
                        Button(choice.isEmpty ? "No name" : choice) { callMe = choice }
                            .buttonStyle(.bordered)
                            .tint(callMe == choice ? .accentColor : nil)
                    }
                }
                TextField("Or type a name", text: $callMe).textFieldStyle(.roundedBorder).frame(width: 260)
                Divider()
                Picker("Voice", selection: $voiceID) {
                    Text("A British voice (Arthur or Daniel)").tag("")
                    ForEach(Speaker.englishVoices, id: \.identifier) { voice in
                        Text("\(voice.name) (\(voice.language))").tag(voice.identifier)
                    }
                }
                .frame(width: 320)
                Text("The Mac reads it with its own voices: nothing is sent anywhere.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(16)
        }
    }

    private var choices: [String] {
        var names = ["Sir", "Ma'am", "Boss"]
        let own = Greeting.defaultName()
        if !own.isEmpty { names.insert(own, at: 0) }
        return names + [""]
    }
}

/// Build, Tests, Crashes, Safety: a dot of colour, a word, and when.
struct GaugeTile: View {
    let gauge: HealthGauge
    var onTap: (() -> Void)?

    var body: some View {
        Button {
            onTap?()
        } label: {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 7) {
                    Circle()
                        .fill(HUD.tone(gauge.state))
                        .frame(width: 10, height: 10)
                        .shadow(color: HUD.tone(gauge.state).opacity(0.8), radius: gauge.state == "none" ? 0 : 4)
                    Text(gauge.label.uppercased()).font(.caption.weight(.semibold)).tracking(1.2)
                        .foregroundStyle(.secondary)
                }
                Text(gauge.value).font(.headline).foregroundStyle(HUD.tone(gauge.state == "none" ? "info" : gauge.state))
                    .lineLimit(2)
                if !gauge.detail.isEmpty {
                    Text(gauge.detail).font(.caption).foregroundStyle(.secondary).lineLimit(3)
                }
                if let why = gauge.why, gauge.state == "bad" || gauge.state == "busy" {
                    Text(why).font(.system(.caption2, design: .monospaced)).foregroundStyle(.secondary).lineLimit(2)
                }
                Spacer(minLength: 0)
                if let source = gauge.source {
                    Text(source).font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
                }
            }
            .padding(12)
            .frame(maxWidth: .infinity, minHeight: 118, alignment: .topLeading)
            .background(RoundedRectangle(cornerRadius: 12).fill(HUD.panel))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(HUD.tone(gauge.state).opacity(
                gauge.state == "none" ? 0.12 : 0.35)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(gauge.path != nil ? "Open the crash report" : "Show the details")
    }
}

// MARK: - The homepage

/// Every project, briefed: who's busy, each project in a sentence, what waits on you, the first move, and a ring
/// per project.
struct HomeView: View {
    let data: PulseData
    @Environment(PulseStore.self) private var store

    private var readable: [ProjectView] { data.projects.filter { $0.error == nil } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                BriefHeader(title: nil, readAt: data.generatedAt, spoken: Spoken.lines(of: data.desk), owner: "home")
                if let desk = data.desk {
                    BriefScript(lines: desk.lines) { line in
                        if let slug = line.project { store.go(to: slug, group: "briefing") }
                    }
                    if let move = desk.close {
                        FirstMoveCard(move: move) {
                            if let slug = move.project { store.go(to: slug, group: move.group, row: move.key) }
                        }
                    }
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), spacing: 14, alignment: .top)],
                          alignment: .leading, spacing: 14) {
                    ForEach(data.projects) { project in
                        ProjectReactor(project: project)
                    }
                }
                WaitingOnYou(projects: readable)
                RecentNotes(projects: readable)
            }
            .padding(24)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(HUD.background)
        .environment(\.colorScheme, .dark)
    }
}

/// One project on the homepage: its ring, its first line, its gauges. A click opens its briefing.
struct ProjectReactor: View {
    let project: ProjectView
    @Environment(PulseStore.self) private var store

    private var working: Bool { !(project.claude?.working.isEmpty ?? true) }

    var body: some View {
        Button {
            store.go(to: project.slug, group: "briefing")
        } label: {
            HStack(alignment: .top, spacing: 14) {
                if let summary = project.summary, summary.stepsTotal > 0 {
                    Ring(fraction: Double(summary.workDonePct) / 100, size: 78, line: 7,
                         label: "\(summary.workDonePct)%", caption: "\(summary.stepsDone)/\(summary.stepsTotal)")
                } else {
                    Ring(fraction: 0, size: 78, line: 7, label: "—", caption: "no plan")
                }
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        Text(project.name).font(.title3.bold())
                        if working {
                            Label("Claude working", systemImage: "sparkles")
                                .font(.caption)
                                .foregroundStyle(HUD.tone("busy"))
                        }
                    }
                    if let error = project.error {
                        Text("Couldn't be read: \(error)").font(.caption).foregroundStyle(HUD.tone("warn")).lineLimit(3)
                    } else if let line = headline {
                        Text(line.text).font(.callout).foregroundStyle(.secondary).lineLimit(3)
                    }
                    HStack(spacing: 10) {
                        ForEach(project.gauges ?? []) { gauge in
                            HStack(spacing: 4) {
                                Circle().fill(HUD.tone(gauge.state)).frame(width: 7, height: 7)
                                Text(gauge.label).font(.caption2).foregroundStyle(.secondary)
                            }
                            .help("\(gauge.label): \(gauge.value)")
                        }
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 14).fill(HUD.panel))
            .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(working ? HUD.tone("busy").opacity(0.6) : HUD.edge))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("Open \(project.name)'s briefing")
    }

    private var headline: BriefLine? {
        let lines = project.brief?.lines ?? []
        return lines.first { $0.kind == "now" } ?? lines.first { $0.kind == "next" } ?? lines.first
    }
}

// MARK: - A project's briefing

struct ProjectBriefing: View {
    let project: ProjectView
    @Environment(PulseStore.self) private var store

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                BriefHeader(title: project.name, readAt: project.brief?.at, spoken: Spoken.lines(of: project.brief),
                            owner: project.slug)
                ProjectBriefingActions(project: project)
                if let brief = project.brief {
                    BriefScript(lines: brief.lines) { line in
                        if let group = line.target?.group { store.go(to: project.slug, group: group, row: line.target?.key) }
                    }
                    if let move = brief.close {
                        FirstMoveCard(move: move) { store.go(to: project.slug, group: move.group ?? "roadmap", row: move.key) }
                    }
                }
                HStack(alignment: .top, spacing: 14) {
                    NowPanel(project: project).frame(maxWidth: .infinity)
                    NeedsYouPanel(project: project).frame(maxWidth: .infinity)
                }
                HStack(alignment: .top, spacing: 12) {
                    ForEach(project.gauges ?? []) { gauge in
                        GaugeTile(gauge: gauge) {
                            if let path = gauge.path {
                                store.open(path)
                            } else {
                                store.go(to: project.slug, group: gauge.key == "safety" ? "now" : "claude")
                            }
                        }
                    }
                }
                HStack(alignment: .top, spacing: 14) {
                    NextUpPanel(project: project).frame(maxWidth: .infinity)
                    SincePanel(project: project).frame(maxWidth: .infinity)
                }
                if let stages = project.stages, !stages.isEmpty {
                    RoadStrip(stages: stages) { stage in
                        store.roadmapTarget = stage.name
                        store.go(to: project.slug, group: "roadmap")
                    }
                }
                HStack(alignment: .top, spacing: 14) {
                    ClaudePanel(project: project).frame(maxWidth: .infinity)
                    ReleasePanel(project: project).frame(maxWidth: .infinity)
                }
                if let reading = project.claudeReading {
                    ClaudeReadingCard(reading: reading)
                }
                if let notes = project.notes, !notes.isEmpty {
                    ForEach(notes, id: \.self) { note in
                        Label(note, systemImage: "info.circle").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .padding(22)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(HUD.background)
        .environment(\.colorScheme, .dark)
    }
}

/// Ask Claude to look (the one thing that uses AI, only on request), and copy the status for any AI chat.
struct ProjectBriefingActions: View {
    let project: ProjectView
    @Environment(PulseStore.self) private var store

    var body: some View {
        HStack(spacing: 10) {
            Button {
                store.askClaude(about: project)
            } label: {
                if store.asking == project.slug {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text("Claude is looking…")
                    }
                } else {
                    Label("Ask Claude to look", systemImage: "text.magnifyingglass")
                }
            }
            .disabled(store.asking != nil)
            .help("Claude reads the project, read-only, for what Pulse's own reading misses. Uses your Claude plan.")
            Button {
                store.copyStatus(of: project)
            } label: {
                Label("Copy status for an AI chat", systemImage: "doc.on.doc")
            }
            .help("Where it stands, ready to paste into Claude, ChatGPT or Meta AI")
            Spacer()
            Text("Everything here is free and local, except Ask Claude.").font(.caption).foregroundStyle(.secondary)
        }
        .buttonStyle(.bordered)
    }
}

/// Where it stands: the ring, and what's being worked on.
struct NowPanel: View {
    let project: ProjectView

    var body: some View {
        HUDPanel(title: "Now", systemImage: "scope") {
            HStack(alignment: .top, spacing: 16) {
                if let summary = project.summary, summary.stepsTotal > 0 {
                    Ring(fraction: Double(summary.workDonePct) / 100, label: "\(summary.workDonePct)%",
                         caption: "\(summary.stepsDone) of \(summary.stepsTotal)")
                }
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(nowItems) { item in
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Image(systemName: item.key.hasPrefix("claude:") ? "sparkles" : (item.you == true ? "person.fill" : "play.fill"))
                                .foregroundStyle(item.key.hasPrefix("claude:") ? HUD.tone("busy") : (item.you == true ? HUD.tone("you") : HUD.accent))
                                .font(.caption)
                            Text(item.title).lineLimit(3)
                        }
                    }
                    if nowItems.isEmpty {
                        Text("Nothing in progress right now.").foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private var nowItems: [Item] {
        Array((project.groups?.first { $0.key == "now" }?.items ?? [])
            .filter { !$0.key.hasPrefix("edit:") && !$0.key.hasPrefix("more:") }
            .prefix(5))
    }
}

/// What waits on the owner in this project.
struct NeedsYouPanel: View {
    let project: ProjectView
    @Environment(PulseStore.self) private var store

    private struct Entry: Identifiable {
        let group: String
        let item: Item
        var id: String { item.key }
    }

    private var items: [Entry] {
        (project.groups ?? []).filter { $0.key != "done" && $0.key != "setup" }.flatMap { group in
            group.items.filter { $0.you == true }.map { Entry(group: group.key, item: $0) }
        }
    }

    var body: some View {
        HUDPanel(title: "Waits on you", systemImage: "person", trailing: "\(items.count)") {
            if items.isEmpty {
                Text("Nothing waits on you.").foregroundStyle(.secondary)
            }
            ForEach(items.prefix(6)) { entry in
                Button {
                    store.go(to: project.slug, group: entry.group, row: entry.item.key)
                } label: {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(entry.item.label).font(.system(.caption, design: .monospaced)).foregroundStyle(HUD.tone("you"))
                        Text(entry.item.title).lineLimit(2)
                        Spacer(minLength: 0)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            if items.count > 6 {
                Text("…and \(items.count - 6) more").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

/// The next steps on the road, each with its command.
struct NextUpPanel: View {
    let project: ProjectView
    @Environment(PulseStore.self) private var store

    private var rows: [RoadRow] {
        let all = (project.roadmap?.stages ?? []).flatMap(\.rows)
        let open = all.filter { $0.state == "doing" } + all.filter { $0.state == "ready" } + all.filter { $0.state == "todo" }
        return Array(open.prefix(4))
    }

    var body: some View {
        HUDPanel(title: "Next up", systemImage: "arrow.right.circle") {
            if rows.isEmpty {
                Text(project.roadmap == nil ? "No plan found yet." : "Nothing left on the road.").foregroundStyle(.secondary)
            }
            ForEach(rows) { row in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(row.label).font(.system(.caption, design: .monospaced)).foregroundStyle(HUD.accent)
                    Button {
                        store.go(to: project.slug, group: "roadmap", row: row.key)
                    } label: {
                        Text(row.name).lineLimit(2).multilineTextAlignment(.leading)
                    }
                    .buttonStyle(.plain)
                    Spacer(minLength: 0)
                    if row.you == true {
                        Image(systemName: "person.fill").font(.caption).foregroundStyle(HUD.tone("you")).help("Waits on you")
                    }
                    if let command = row.command {
                        CopyButton(text: Handoff.command(command, notes: store.book(for: project.slug)?.comments(for: row.key) ?? []),
                                   compact: true)
                            .help("Copy “\(command)” (with your notes on it)")
                    }
                }
            }
        }
    }
}

/// What changed since the last look.
struct SincePanel: View {
    let project: ProjectView

    var body: some View {
        HUDPanel(title: "Since last time", systemImage: "clock.arrow.circlepath") {
            let changes = project.since?.changes ?? []
            if changes.isEmpty {
                Text("Nothing changed since the last look.").foregroundStyle(.secondary)
            }
            ForEach(changes.prefix(6), id: \.self) { change in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Circle().fill(change.kind == "finished" ? HUD.tone("good") : HUD.accent.opacity(0.6)).frame(width: 6, height: 6)
                    Text(change.text).font(.callout).lineLimit(2)
                }
            }
            if changes.count > 6 {
                Text("…and \(changes.count - 6) more").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

/// The whole road in one strip: each stage as wide as its work, filled as far as it's done.
struct RoadStrip: View {
    let stages: [StageProgress]
    var go: (StageProgress) -> Void

    var body: some View {
        HUDPanel(title: "The road", systemImage: "map") {
            GeometryReader { geometry in
                let total = max(1, stages.reduce(0) { $0 + max(1, $1.total) })
                HStack(spacing: 4) {
                    ForEach(stages) { stage in
                        let width = max(24, (geometry.size.width - CGFloat(stages.count * 4)) * CGFloat(max(1, stage.total)) / CGFloat(total))
                        Button {
                            go(stage)
                        } label: {
                            ZStack(alignment: .leading) {
                                RoundedRectangle(cornerRadius: 4).fill(Color.white.opacity(0.07))
                                RoundedRectangle(cornerRadius: 4)
                                    .fill(stage.done >= stage.total ? HUD.tone("good") : HUD.accent)
                                    .frame(width: width * CGFloat(stage.done) / CGFloat(max(1, stage.total)))
                            }
                            .frame(width: width, height: 12)
                        }
                        .buttonStyle(.plain)
                        .help("\(stage.name): \(stage.done) of \(stage.total)")
                    }
                }
            }
            .frame(height: 12)
            HStack {
                Text(stages.first(where: { $0.done < $0.total }).map { "Now in: \($0.name)" } ?? "Every stage is done")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                Text("\(stages.filter { $0.done >= $0.total }.count) of \(stages.count) stages done")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

/// What Claude did lately: the newest sessions, what they ran, and what Claude said at the end.
struct ClaudePanel: View {
    let project: ProjectView
    @Environment(PulseStore.self) private var store

    var body: some View {
        HUDPanel(title: "Claude", systemImage: "sparkles",
                 trailing: project.claude.map { "\($0.week.sessions) sessions this week" }) {
            if let claude = project.claude {
                ForEach(claude.sessions.prefix(3)) { session in
                    SessionLine(session: session)
                }
                Button("All sessions and prompts") { store.go(to: project.slug, group: "claude") }
                    .buttonStyle(.link)
                    .font(.caption)
            } else {
                Text("No Claude Code conversations for this folder.").foregroundStyle(.secondary)
            }
        }
    }
}

/// One session in a line: its state, title, when, and what it ran.
struct SessionLine: View {
    let session: ClaudeSession

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                SessionBadge(session: session)
                Text(session.title).lineLimit(1)
                Spacer(minLength: 0)
                if let ended = PulseDate.parse(session.ended) {
                    Text(ended.formatted(.relative(presentation: .named))).font(.caption).foregroundStyle(.secondary)
                }
            }
            HStack(spacing: 8) {
                ForEach(Array(session.runs.suffix(4).enumerated()), id: \.offset) { _, run in
                    RunChip(run: run)
                }
                if session.editedCount > 0 {
                    Text("\(session.editedCount) file\(session.editedCount == 1 ? "" : "s") changed")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
    }
}

struct SessionBadge: View {
    let session: ClaudeSession

    var body: some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 6)
            .padding(.vertical, 1)
            .background(Capsule().fill(color.opacity(0.2)))
            .foregroundStyle(color)
    }

    private var text: String {
        switch session.state {
        case "working": return "Working"
        case "open": return "Open"
        case "stopped":
            switch session.stop?.why {
            case "limit": return "Usage limit"
            case "api": return "Error"
            case "interrupted": return "Stopped by you"
            case "midwork": return "Stopped mid-way"
            case "noreply": return "No answer"
            default: return "Stopped"
            }
        default: return "Finished"
        }
    }

    private var color: Color {
        switch session.state {
        case "working": return HUD.tone("busy")
        case "open": return HUD.accent
        case "stopped": return session.stop?.why == "noreply" || session.stop?.why == "interrupted" ? HUD.tone("warn") : HUD.tone("bad")
        default: return HUD.tone("good")
        }
    }
}

/// A test, build, check or bench run: ✓ or ✗ and what it was.
struct RunChip: View {
    let run: ClaudeRun

    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: run.outcome == "pass" ? "checkmark" : run.outcome == "fail" ? "xmark" : "questionmark")
            Text(run.kind)
        }
        .font(.caption2)
        .foregroundStyle(run.outcome == "pass" ? HUD.tone("good") : run.outcome == "fail" ? HUD.tone("bad") : HUD.tone("none"))
        .help("\(run.command)\(run.scope.map { " (only \($0))" } ?? ""): \(run.detail.isEmpty ? "the result wasn't captured" : run.detail)")
    }
}

/// The release checklist in a glance: how far, and the first blockers.
struct ReleasePanel: View {
    let project: ProjectView
    @Environment(PulseStore.self) private var store

    private var list: Checklist? {
        project.checklists?.first { $0.id != "basics" } ?? project.checklists?.first
    }

    var body: some View {
        HUDPanel(title: list?.title ?? "Checklist", systemImage: "shippingbox") {
            if let list {
                let ticks = store.ticks(for: project.slug)
                let progress = ticks.progress(of: list)
                HStack(alignment: .top, spacing: 14) {
                    Ring(fraction: progress.total == 0 ? 0 : Double(progress.done) / Double(progress.total), size: 70,
                         line: 6, label: "\(progress.done)/\(progress.total)")
                    VStack(alignment: .leading, spacing: 5) {
                        ForEach(list.items.filter { ticks.state(of: $0) == "fail" }.prefix(4)) { item in
                            HStack(alignment: .firstTextBaseline, spacing: 5) {
                                Image(systemName: "xmark.circle.fill").foregroundStyle(HUD.tone("bad")).font(.caption)
                                Text(item.text).font(.callout).lineLimit(2)
                            }
                        }
                        Button("Open the checklists") { store.go(to: project.slug, group: "checklists") }
                            .buttonStyle(.link)
                            .font(.caption)
                    }
                }
            } else {
                Text("No checklist yet.").foregroundStyle(.secondary)
            }
        }
    }
}

/// What Claude said when you asked it to look: its own card, marked as Claude's view.
struct ClaudeReadingCard: View {
    let reading: ClaudeReading

    var body: some View {
        HUDPanel(title: "Claude's reading", systemImage: "text.magnifyingglass", trailing: trailing) {
            if let problem = reading.problem {
                Label(problem, systemImage: "exclamationmark.triangle").foregroundStyle(HUD.tone("warn"))
            }
            Text(reading.headline).font(.headline)
            ForEach(reading.items) { item in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(item.kind.replacingOccurrences(of: "-", with: " "))
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(HUD.accent)
                            .frame(width: 92, alignment: .leading)
                        Text(item.text)
                    }
                    if let evidence = item.evidence, !evidence.isEmpty {
                        Text(evidence).font(.caption).foregroundStyle(.secondary).padding(.leading, 98)
                    }
                }
            }
            Text("Claude's own words: it can be wrong, and it never changes what the files say.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var trailing: String {
        var parts: [String] = []
        if let date = PulseDate.parse(reading.at) { parts.append(date.formatted(date: .abbreviated, time: .shortened)) }
        if let seconds = reading.seconds { parts.append("\(Int(seconds)) s") }
        if let cost = reading.costUSD { parts.append(String(format: "about $%.2f at API prices", cost)) }
        return parts.joined(separator: " · ")
    }
}
