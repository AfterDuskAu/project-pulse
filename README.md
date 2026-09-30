# Pulse

**A briefing for your Claude Code projects.** Open it and it tells you, in plain words, where each project stands:

> *Good evening. Trailmix is 40% done: 10 of 25 steps. Claude is working on “offline maps” right now.
> We're on the beta test on your own phone. It waits on you. Next up: step 11, App Store readiness; its prompt is
> written. Trailmix crashed today at 13:42: an uncaught exception in MapCache.load.
> iPhone & iPad App Store checklist: 6 of 17 done; first blocker: a signing team is set.
> First move is yours: the beta test.*

Press **Brief me** (⌘B) and a Mac voice reads it to you. Every sentence says where it comes from, and a click takes
you there.

Pulse is a native Mac app. It reads your project folders **read-only**, uses **no internet and no AI**, and costs
nothing to run. The one exception is a button you press yourself: *Ask Claude to look*.

It's made for people who build with Claude Code, including people new to programming. If you've ever lost track of
which prompt comes next, whether the tests still pass, or what Claude did while you were away, Pulse is for you.

## What you get

**Home**: every project briefed at once:
- who's working (a Claude session running right now);
- one sentence per project;
- everything that waits on you;
- the single most urgent first move;
- a progress ring per project.

**Each project** has:
- **Briefing**: the spoken summary, and four gauges:
  - **Build**: the last build Claude ran, or Xcode's own record.
  - **Tests**: the last test run, with how many tests ran and whether it was all of them.
  - **Crashes**: from macOS's crash reports.
  - **Safety**: keys written into files, work not committed or not pushed.

  Plus now / waits on you / next up (with commands to copy), what changed since last time, the road, what Claude did
  lately, and the release checklist.
- **Roadmap**: every stage and step, like a chart. Click a step for its prompt, its command and your notes.
- **Now, Next steps, Could be problems, Known problems, Missing, Done, How it's set up**: everything Pulse found,
  sorted.
- **Claude sessions**: each conversation with Claude Code on this project:
  - its title, and whether it's working, open, finished, or stopped (with the reason: usage limit, error,
    interrupted, stopped mid-way);
  - the files it changed and the tests and builds it ran, pass or fail;
  - what Claude said at the end, and your last prompt, ready to send again;
  - what Claude remembers about the project.
- **Prompts**:
  - **Written**: step prompts, slash commands, skills and agents, each with when it was last sent and which were
    never sent.
  - **Sent to Claude**: searchable, one click to reuse.
  - **Unfinished**: sessions that stopped, with the prompt to try again.
  - **Typed twice**: long prompts you keep retyping (make them a `/command`).
- **Checklists**:
  - the basics every project needs (README, git, pushed, tests passing, no keys in files, a CLAUDE.md, a plan…);
  - a **release checklist** for what the project is: Mac App Store, iPhone & iPad App Store, a Mac app shared
    outside the store, a website or web app, a Python package, an npm package, a browser extension, or an Android
    app.

  Pulse ticks what the files prove (the App Sandbox is on, the app icon has its pictures, the privacy manifest gives
  a reason for every API that needs one…). You tick the rest, or mark an item "doesn't apply". Add any other list
  from the menu.
- **Your notes** on anything, which you can tick off as to-dos. They're kept in Pulse's folder, never in your
  project.
- **Copy status**: where the project stands, as text to paste into a new chat with Claude, ChatGPT or Meta AI.

## Install

You need macOS 14 or later and Apple's free command line tools, which bring Swift, Python 3 and git:

```bash
xcode-select --install
```

Then:

```bash
git clone https://github.com/AfterDuskAu/project-pulse.git ~/Developer/project-pulse
cd ~/Developer/project-pulse
./App/build-app.sh
open Pulse.app
```

Keep `Pulse.app` in that folder: it runs the reader (`pulse.py`) that sits next to it.

On the first run, Pulse lists the folders you've used with Claude Code. Click **Add** (or **Add all**), or
**Choose a folder…** for any other. Pulse works out each project's layout by itself; there's nothing to set up.

## What Pulse reads

| Where | What Pulse takes from it |
|---|---|
| The project's files | Plans and step lists (step tables, numbered prompts, a TODO.md, a CHANGELOG), Spec Kit, Kiro, Task Master, Backlog.md and BMAD, checklists in notes, known-issues notes, TODO and FIXME in code, failed pytest runs, errors in logs, the Xcode project's settings |
| git | Commits, work not committed or pushed, stashes, other branches (with its optional locks off, so it never changes the repo) |
| Claude Code's conversation files (`~/.claude/projects/`) | Your prompts, each session's title and state, the files it changed, the tests and builds it ran and what they said, what Claude said at the end, and which sessions are open right now (`~/.claude/sessions/`) |
| macOS crash reports (`~/Library/Logs/DiagnosticReports`) | Crashes of the project's app and of its test runs: when, how, and where in your code |
| Xcode's build records (`~/Library/Developer/Xcode/DerivedData`) | The last build made in the Xcode app: errors and warnings |

Details, and how each layout is recognised: [docs/how-pulse-reads.md](docs/how-pulse-reads.md).

## Privacy and safety

- **Read-only.** Pulse never changes, commits or deletes anything in a project. It writes only inside its own folder:
  - `projects.json`: your list of projects.
  - `comments/`: your notes and checklist ticks.
  - `state/`: what it read last time, for "since last time", and a small digest of each Claude conversation.
  - `out/`: what the window shows.

  All four are in `.gitignore`: they're yours, never published.
- **No internet, no AI, no accounts, no telemetry.** The voice is macOS's own speech.
- **Keys stay secret.** A key found in a file or a pasted prompt is never shown, only what kind it was ("an OpenAI key
  in config.py, line 3").
- **Claude's conversations stay on your Mac.** Pulse reads the conversation files Claude Code keeps, and never opens
  `~/.claude.json`, key files, shell snapshots or file backups. You can switch off reading them for any project
  ("What Pulse reads").

### Ask Claude to look (optional, uses your Claude plan)

The one part that uses AI, and only when you press it. Claude reads the project's files **read-only**, starting from
what Pulse found, and looks for what that misses:
- a fix that's done only on paper;
- two documents that disagree;
- a release risk buried in a rules file.

Its findings go in a card of their own, dated and priced. They never change a status the files prove.

It runs Claude Code with only the Read, Glob and Grep tools, and in safe mode, so the folder's own hooks, plugins,
MCP servers and instructions don't load. It isn't saved as a session, and it stops after 4 minutes or $1 of API-priced
work. Tested on a 470-file project, it took 52 seconds, about $0.40 at API prices; on a Pro or Max plan it counts
toward your plan instead.

## How it words things

Pulse never says more than it can prove:
- **A status** ("done", "next") comes only from the project's own plan and write-ups.
- **What Claude said** is quoted as Claude's words, never turned into a fact.
- **A test or build result** is in the past tense, with its time and scope ("14 tests picked by `--filter`, today at
  19:19"), and says when files changed since.
- **No result on record** is said as "no test run on record", never as "no errors".
- **A crash** is an event with its time, not a state.

## Tips for building with Claude Code

- **Give each project a plan.** Pulse turns it into the roadmap. Either works:
  - a `TODO.md` with one `- [ ] …` line per task;
  - a step table in `prompts/README.md`, with numbered prompts (`prompts/01-setup.md`).
- **Write prompts you'll reuse as files.** Save them in `prompts/`, or as `.claude/commands/<name>.md` to make them a
  `/<name>` command. Pulse shows each one with its command, and whether it was ever sent.
- **Keep a `CLAUDE.md`.** Claude reads it at the start of every session. Pulse warns when it grows past the size
  Claude Code itself warns about.
- **Keep known problems in one file** (`KNOWN-ISSUES.md`), not only in chats.

## For developers

```bash
python3 -m unittest            # the reader: tests on small made-up projects and conversations
cd App && swift test           # the app's model
python3 pulse.py --no-open     # a refresh from the command line (writes out/data.json and out/index.html)
python3 pulse.py --ask <name>  # Ask Claude about one project, then refresh
```

- `projects.json` lists the projects (see `projects.example.json`). Per project you can add:
  - `"off": [...]`: readers switched off;
  - `"checklists": [...]`: lists added by hand;
  - `"hiddenChecklists": [...]`: lists taken away;
  - `"map"`: for a project with a fixed layout ([docs/how-pulse-reads.md](docs/how-pulse-reads.md)).
- The reader is plain Python 3.9+ with no packages to install. The app is SwiftUI, built by `App/build-app.sh` with
  Swift Package Manager (no Xcode project needed).

Pulse is ad-hoc signed when you build it yourself, so it runs on your Mac without a warning.

## Licence

MIT: see [LICENSE](LICENSE).
