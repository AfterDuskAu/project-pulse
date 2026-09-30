# How Pulse reads a project

Pulse reads each project in `projects.json` on every refresh, read-only. Most projects need no setup: Pulse works out
the layout by itself. This page lists what it looks for.

## A folder with no map: how Pulse works out its layout
A project is read by `pulse_any.py` unless it has a `map` in `projects.json` (below). It looks for what people commonly use, and
shows whatever it finds:
- **A step list:** a table of steps (`| Step | What | Status |`, optionally Size and After) in a ROADMAP or PLAN note or
  in `prompts/README.md`, or numbered step prompts (`prompts/01-setup.md`, `prompts/02-…`). A step is done when its
  Status says so, when it has a write-up (`docs/history/steps/<ID>.md`), when the CHANGELOG has a heading for it
  ("### Step 09c: …"), or when commits named after it ("Step 09c: …") changed more than its own prompt. Old notes
  (a proposal, an archive) count only when there's nothing newer.
- **A table of versions** (`| Version | What |`): shown under the roadmap as what comes later.
- **Planning tools:** Spec Kit (`specs/…/tasks.md`, with `/speckit.plan`, `/speckit.tasks` and `/speckit.implement` as
  the commands), Kiro (`.kiro/specs`), Task Master (`tasks.json`, with `task-master show <id>`), Backlog.md
  (`backlog/`) and BMAD stories (`docs/stories`).
- **Checklists** (`- [ ]`, `- [x]`, `- [/]` in progress) in any note. When the project also has a plan, each checklist
  is one line with its progress.
- **Notes:** sections such as "Next steps", "Known issues", "Open questions" or "Done" in the README and top-level
  notes; a known-issues note (`KNOWN-ISSUES.md`, `BUGS.md`…) with its "Decide:" lines; the CHANGELOG.
- **The code:** TODO notes (Missing) and FIXME / HACK / XXX / BUG notes (Could be problems), only in comments (not in
  strings), and not in test fixtures (a syntax highlighter's sample files, snapshots).
- **Errors:** tests that failed in pytest's last run after the last commit, and error lines in logs from the last
  week.
- **Git:** work not committed, the branch, commits not pushed, an unfinished merge, and work that's easy to forget:
  stashes, and other branches with commits that aren't in yours. A folder that isn't in git shows the files edited in
  the last two days instead.
- **Keys written into files:** an OpenAI, Anthropic, GitHub, AWS, Google, Hugging Face, Slack or Stripe key, or a
  private key, typed into a file, and a `.env` file that's in git. Pulse says which file and line, never the key.
  Made-up test keys ("sk-xxxx…", "ghp_1234…") don't count.
- **Copies of a file next to it:** "app (1).py", "app_final.py", "app old.py" beside "app.py": which one is real?
- **How it's set up:** the files that guide AI assistants (CLAUDE.md and `.claude/`, AGENTS.md, GEMINI.md, Cursor,
  Windsurf, Cline, Copilot, Kiro steering, MCP servers…), the plan, docs, code and languages, tests, CI, git hooks and
  linters, and where the repo is pushed (never with a password or token).

It's quick (about half a second for a project like MusicOrganizer, three seconds for a 2,000-file monorepo), stops
reading code and logs after 6 seconds, and reads at most the first 20,000 files of a huge folder (and says so).

It was checked on 11 public projects, one per layout (Backlog.md, Task Master, two BMAD projects, two Kiro projects,
two Spec Kit projects, a Cursor project, an AGENTS.md project and bat), plus the owner's own; what they showed was
fixed (for example release notes written "### New in 7.3.3", or a CHANGELOG's "Features" heading under every
release). The downloads were deleted afterwards.

## Claude Code's conversations
Claude Code keeps every conversation in `~/.claude/projects/<the folder's path, every other character turned into
"-">/<session>.jsonl`, and the sessions that are open right now in `~/.claude/sessions/`. Pulse (`pulse_claude.py`)
reads them, and never writes them:
- **Your prompts:** what you typed (a prompt, a `/command`, a `!` command). Tool results, reminders, messages from
  other sessions and the summary after a compaction are left out, and a prompt that was queued and then sent counts
  once. Keys pasted into a prompt are hidden.
- **Each session:** its title, when it ran, and its state:
  - working now or open (from `~/.claude/sessions/`, only while its process is alive);
  - finished;
  - stopped, and why: a usage limit, an error, interrupted by you, in the middle of its work, or no answer to your
    last prompt.
- **What it did:** the files it changed (by edits, and by commands, with Claude Code's own record), and what Claude
  said at the end.
- **Tests, builds, checks and speed benches it ran.** Only a command that *starts* with one counts:
  - a test: `swift test`, `pytest`, `npm test`, `xcodebuild … test`, `cargo test`, `go test`…
  - a build: `swift build`, `xcodebuild`, `npm run build`…
  - a check: `check-*.sh`, `eslint`, `ruff`…

  The verdict comes from the output (`** BUILD SUCCEEDED **`, `Test run with 212 tests passed`,
  `1 failed, 3 passed`…) and from the exit code when nothing piped it away. A run of only some tests (`--filter`,
  `-k`) says so. A run in the background gets its verdict when it reports back. No verdict means "result not
  captured", never "passed".
- **Which project a session belongs to:** the folder it started in, or any folder where it changed files or ran
  commands (a session started elsewhere that worked on this project counts too).
- **What Claude remembers** about the project: Claude Code's memory notes for that folder.

Each conversation file is read once, then only from where Pulse stopped (Claude Code only adds to the end). A small
digest of each is kept in `state/claude/`, which also remembers conversations after Claude Code cleans them up.
The first read of a large history takes a few seconds; after that, a refresh reads only what's new.

## Crashes and Xcode builds
`pulse_errors.py` finds the project's own crash reports in `~/Library/Logs/DiagnosticReports`:
- **Which reports:** those of its app (by the app's name or bundle ID, from the Xcode project or `Package.swift`), and
  of its test runs (a Swift package's test runner loads `<Package>PackageTests`).
- **What each says:** when; how, in plain words ("an uncaught exception", "a Swift runtime error", "a stack
  overflow"); and where (the first line of the project's own code).

It also reads the last build Xcode recorded for the project (builds made in the Xcode app; builds from the command
line are in Claude's sessions instead).

## Checklists
`pulse_checks.py` picks the lists that fit the folder, and says why:

| List | When |
|---|---|
| Project basics | always |
| Mac App Store | an Xcode app target for macOS with the App Sandbox on, or docs that talk of the App Store |
| Mac app outside the store | a Mac app without the sandbox, or a Swift package that builds a SwiftUI/AppKit app |
| iPhone & iPad App Store | an Xcode app target for iOS |
| Website or web app | `package.json` using React, Next, Vue, Svelte, Vite…; an `index.html`; Flask, Django, FastAPI, Streamlit |
| npm package | `package.json` that others can install (`main`, `exports` or `bin`, not private) |
| Python package | `pyproject.toml` with `[project]`, or `setup.py` |
| Browser extension | `manifest.json` with `manifest_version` |
| Android (Google Play) | an Android app module |

**What Pulse checks by itself in an Xcode project.** It reads the project file (each app target's Release
settings), the entitlements, the Info.plist keys, the asset catalog and the privacy manifest:
- the App Sandbox is on;
- no debug-only entitlements;
- the bundle ID, signing team, version and build number are set;
- the App Store category is chosen;
- the app icon has all its pictures;
- a usage sentence for each permission the code uses (Photos, the camera…);
- a reason in the privacy manifest for each required-reason API the code uses (UserDefaults, file dates, disk space,
  time since start-up);
- the export-compliance answer is set;
- the hardened runtime is on;
- other people's code is acknowledged;
- no `Process` / `dlopen` in the shipping code.

Code inside `#if DEBUG` is left out, since it doesn't ship. The other lists check `package.json`, `pyproject.toml`,
`manifest.json` and the Gradle files the same way.

Items Pulse can't check (screenshots, a privacy policy page, the store listing) are ticked by you. A tick is kept in
`comments/<project>.ticks.json`, and can also overrule what Pulse found ("I've checked it myself") or mark an item as
not applying.

## Warnings (things that drifted)
- The roadmap's Status column is behind the files (a step is written up, or has a prompt, but
  its row doesn't say so).
- NEXT-UP still says "(to write)" for a step whose prompt exists.
- CLAUDE.md is over the size limit in `scripts/check-memory.sh` (how much room is left always shows under "Now";
  being nearly full is normal, because each step replaces "Where we are" and runs that check itself).
- CLAUDE.md's "Next:" starts with a step that's already done.
- Changes left uncommitted for more than a day.
- The newest speed report wasn't a valid run (window not visible the whole time).
- A file Pulse expects is missing, or its layout changed so Pulse found nothing in it.
(These warnings are for a project read through a map; a folder read by itself shows its problems in the groups.)

## A map for extra detail (optional)
A project can instead be read through a `map` in `projects.json` that names its files. A map adds a NEXT-UP file's errands and proposals, the roadmap's proofs and gates, speed reports and drift
warnings.

| Key | What it is |
|---|---|
| `roadmap` | the plan with the stage tables (`| # | Step | What | Status | Size | After |`) |
| `roadHeading`, `ideasHeading` | words in the `## ` headings of the road and the ideas-for-later sections |
| `nextUp` | the live to-do list (errands under "Stage 0", numbered items) |
| `knownIssues` | the parked problems (`## Area` headings, `- ` bullets) |
| `stepsDone` | folder with one write-up per finished step, named `<ID>.md` |
| `prompts` | folder with step prompts, named `<ID>-something.md` |
| `perfReports`, `perfPattern` | folder and file pattern of the speed reports |
| `memoryFile`, `memoryCheck` | CLAUDE.md, and the script that holds its size limit |

## The Obsidian note (optional, per project)
Add `"obsidian": {"vault": "<vault folder>", "note": "Pulse/<Name>.md"}` to a project in `projects.json`, and each
refresh also writes one note into that Obsidian vault:
- a progress bar and one bar per stage;
- coloured boxes: **Since …** (what changed), **Now and next**, **Could be problems** (fixes to confirm, problems
  marked "suspected", "seen once" or "cause not proven", speed measures slower than the run before, docs out of step),
  and, folded, **Known problems**, **Missing** (prompts not written, your errands), **Done** and **Ideas for later**;
- every step name is a link that opens its document.

**Your notes are safe.** Write under "## My notes" at the bottom: Pulse copies that part back unchanged on every
refresh. If you type above it, Pulse moves those lines under "My notes" (and keeps a copy of the old note in
`state/<project>/obsidian-backups/`). It never overwrites a note it didn't make.

**Git never sees it.** If the vault is a git repo, Pulse writes only where git ignores the note, and otherwise tells you
the line to add to `.git/info/exclude` (this Mac only).
