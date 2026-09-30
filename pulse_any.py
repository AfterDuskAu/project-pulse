"""Pulse's reader for any folder: works out how a project is set up and where it stands, with no map to follow.

Pick a folder and Pulse looks for what people commonly use to plan and track work: a step list (a table of steps,
or numbered step prompts, with a CHANGELOG or commits saying which are finished), checklists in notes ("- [ ]"),
a known-issues list, sections such as "Next steps" or "Known issues", a CHANGELOG, TODO and FIXME notes in the
code, failed tests, errors in recent logs, and the layouts of Spec Kit, Kiro, Task Master, Backlog.md and BMAD.
It also lists how the project is set up: the files that guide AI assistants (CLAUDE.md, AGENTS.md, Cursor
rules…), its plan, docs, code, tests and checks.

Read-only, no AI, no network. Every reader is fenced off: one that fails is reported, and the others carry on.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path

from pulse_base import clean, commits_since, git, git_facts, headline, iso, norm, stage_title_note, strip_parens
from pulse_groups import SUSPECT, command_for, day, home_summary, prompt_verb

MAX_FILES = 20000           # a bigger folder is read in part, and says so
MAX_NOTE_BYTES = 1_000_000  # notes bigger than this are skipped
MAX_CODE_BYTES = 400_000    # and source files bigger than this
MAX_NOTES = 600
MAX_CODE_FILES = 6000
SLOW_SECONDS = 6.0          # the code and log readers stop after this long (per project)
SHOW = 40                   # items shown from one list before "…and N more"
LOG_DAYS = 7
RECENT_EDIT_HOURS = 48
UNCOMMITTED_WARN_HOURS = 24
COMMITS_READ = 400
MAX_CHANGES = 80

# Folders never worth reading in a folder walk: tools' caches, installed packages, build output.
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", ".build", "build", "dist", "out", "target",
    "DerivedData", "Pods", "Carthage", ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", ".tox", ".nox", ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache", ".gradle", ".idea",
    ".swiftpm", "coverage", ".cache", ".terraform", "site-packages", ".dart_tool", "vendor", "third_party",
    "third-party", ".yarn", ".pnpm-store", ".expo", "bin", "obj",
}
# Hidden folders that say how a project is set up (a folder walk skips every other hidden folder).
KEEP_HIDDEN = {
    ".claude", ".cursor", ".github", ".kiro", ".specify", ".taskmaster", ".bmad-core", ".bmad", ".windsurf", ".roo",
    ".junie", ".amazonq", ".continue", ".githooks", ".husky", ".gitlab", ".circleci", ".clinerules", ".gemini",
    ".codex", ".opencode", ".devcontainer", ".vscode", ".obsidian",
}
# Other people's code inside a repo: not this project's notes or TODOs.
VENDORED = {"node_modules", "vendor", "third_party", "third-party", "Pods", "Carthage", "bower_components",
            "site-packages", ".venv", "venv", "DerivedData", ".build"}
DEFAULT_BRANCHES = {"main", "master", "trunk", "develop", "dev", "default"}
# Folders of made-up inputs (a syntax highlighter's sample files, snapshots): never the project's notes or TODOs.
FIXTURE_DIRS = {"fixtures", "fixture", "__fixtures__", "testdata", "test-data", "test_data", "syntax-tests",
                "snapshots", "__snapshots__", "golden", "samples", "sample-data"}
# Folders of what a project makes rather than work on it: not "recently edited" in a folder outside git.
OUTPUT_DIRS = {"out", "output", "build", "dist", "tmp", "temp", "cache", ".cache", "logs", "log", "state",
               "snapshots", "__pycache__", ".build", "node_modules", ".venv", "venv", "derived", "results"}
# Folders a planning tool owns; its reader reads them.
TOOL_DIRS = ("specs/", ".specify/", ".kiro/", ".taskmaster/", "backlog/", ".bmad-core/", "docs/stories/")


def in_fixtures(rel: str) -> bool:
    return any(part.lower() in FIXTURE_DIRS for part in rel.split("/")[:-1])


def in_tests_or_examples(rel: str) -> bool:
    return any(part.lower() in ("test", "tests", "__tests__", "examples", "example") for part in rel.split("/")[:-1])

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
CHECKBOX = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+\[([ xX/~\-])\]\s+(.+?)\s*$")
TASK_EMOJI = re.compile(r"\s*(?:[✅📅⏳🛫➕❌]\s*\d{4}-\d{2}-\d{2}|🔁[^📅⏳🛫✅➕]*|[⏫🔼🔽🔺⏬])")
DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

CODE_EXT = {
    ".py", ".swift", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs", ".rb", ".java", ".kt", ".kts", ".c",
    ".h", ".m", ".mm", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".cs", ".php", ".sh", ".bash", ".zsh", ".fish", ".lua",
    ".dart", ".scala", ".ex", ".exs", ".erl", ".hs", ".ml", ".r", ".jl", ".sql", ".css", ".scss", ".sass", ".less",
    ".html", ".vue", ".svelte", ".yml", ".yaml", ".toml", ".gradle", ".cmake", ".pl", ".ps1", ".tf", ".proto", ".zig",
    ".nim", ".clj", ".groovy", ".fs",
}
CODE_NAMES = {"Makefile", "Dockerfile", "Rakefile", "Gemfile", "Podfile", "Fastfile", "Justfile", "CMakeLists.txt"}
LANGUAGES = {
    ".py": "Python", ".swift": "Swift", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".cjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".c": "C", ".h": "C", ".m": "Objective-C",
    ".mm": "Objective-C", ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++", ".cs": "C#", ".php": "PHP",
    ".dart": "Dart", ".scala": "Scala", ".ex": "Elixir", ".exs": "Elixir", ".lua": "Lua", ".sh": "Shell",
    ".zsh": "Shell", ".bash": "Shell", ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".vue": "Vue",
    ".svelte": "Svelte", ".sql": "SQL", ".r": "R", ".jl": "Julia", ".hs": "Haskell", ".zig": "Zig",
}
TEST_FILE = re.compile(
    r"(^|/)(tests?|__tests__|testing)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|Tests?\.swift$|Test\.(java|kt)$|_spec\.rb$|(^|/)spec/.+_spec\.rb$", re.I)


# ---------------------------------------------------------------- small helpers

def plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def shorten(text: str, limit: int = 24) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def display(rel: str) -> str:
    """A file as a person names it: "TODO.md" at the top, "docs/ROADMAP.md" further down."""
    return rel.rsplit("/", 1)[-1] if "/" not in rel else rel


def id_key(raw: str) -> str:
    """One spelling per step id: "Step 09c" → "9c", "01" → "1", "SF-1" → "sf-1"."""
    text = clean(raw).strip().lower()
    text = re.sub(r"^(?:step|phase|milestone|stage)\s*", "", text).lstrip("#").strip()
    return re.sub(r"^0+(?=\d)", "", text)


def natural(text: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def iso_day(text: str | None) -> str | None:
    found = DATE.search(text or "")
    return found.group(1) if found else None


def md_lines(text: str):
    """The lines of a Markdown file outside ``` code blocks, with their numbers."""
    fence = False
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fence = not fence
            continue
        if not fence:
            yield number, line


def parse_checkboxes(text: str, dash: str = "skipped") -> list[dict]:
    """Every "- [ ]" line outside code blocks: its state, text, heading, and whether it has sub-tasks.
    "[x]" is done, "[/]" or "[~]" in progress, "[-]" cancelled (or in progress where a tool says so)."""
    tasks: list[dict] = []
    heading = ""
    for number, line in md_lines(text):
        found_heading = HEADING.match(line)
        if found_heading:
            heading = strip_parens(clean(found_heading.group(2)))
            continue
        box = CHECKBOX.match(line)
        if not box:
            continue
        mark = box.group(2)
        state = ("done" if mark in "xX" else "doing" if mark in "/~" else dash if mark == "-" else "todo")
        raw = box.group(3)
        done_day = re.search(r"✅\s*(\d{4}-\d{2}-\d{2})", raw)
        body = TASK_EMOJI.sub("", raw).strip()
        tasks.append({"indent": len(box.group(1).expandtabs(4)), "state": state, "text": clean(body),
                      "heading": heading, "line": number, "parent": None, "children": 0,
                      "doneDay": done_day.group(1) if done_day else None})
    stack: list[int] = []
    for i, task in enumerate(tasks):
        if i and task["heading"] != tasks[i - 1]["heading"]:
            stack = []
        while stack and tasks[stack[-1]]["indent"] >= task["indent"]:
            stack.pop()
        if stack:
            tasks[stack[-1]]["children"] += 1
            task["parent"] = tasks[stack[-1]]["text"]
        stack.append(i)
    return tasks


def leaves(tasks: list[dict]) -> list[dict]:
    """The tasks that count: a task with sub-tasks is finished when they are."""
    return [t for t in tasks if not t["children"]]


def parse_frontmatter(text: str) -> dict:
    """The simple YAML block at the top of a note ("---" … "---"): key: value, key: [a, b], and "- item" lists."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    data: dict = {}
    key = None
    for line in text[3:end].splitlines():
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key:
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(item.group(1).strip().strip("'\""))
            continue
        pair = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not pair:
            continue
        key, value = pair.group(1), pair.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            data[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
        else:
            data[key] = value.strip("'\"")
    return data


def first_heading(text: str) -> str:
    for _, line in md_lines(text):
        found = re.match(r"^#\s+(.*)$", line)
        if found:
            return clean(found.group(1))
    return ""


# ---------------------------------------------------------------- the folder

def list_files(root: Path, in_git: bool) -> tuple[list[str], bool]:
    """Every file worth reading, relative to root ("docs/NOTES.md"), and whether the list was cut short.
    In a git repo that's what git lists (tracked, plus new files it doesn't ignore); elsewhere a folder walk."""
    files: list[str] = []
    if in_git:
        listed = git(root, "ls-files", "-co", "--exclude-standard", "-z")
        if listed is not None:
            for rel in listed.split("\0"):
                if rel and not any(part in VENDORED for part in rel.split("/")[:-1]):
                    files.append(rel)
                    if len(files) >= MAX_FILES:
                        return files, True
            return files, False
    for here, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and (not d.startswith(".") or d in KEEP_HIDDEN)
                         and not d.endswith((".app", ".xcarchive", ".dSYM")))  # built apps: not the project's files
        where = os.path.relpath(here, root).replace(os.sep, "/")
        for name in sorted(names):
            if name == ".DS_Store":
                continue
            files.append(name if where == "." else f"{where}/{name}")
            if len(files) >= MAX_FILES:
                return files, True
    return files, False


class Folder:
    """One project folder, read once: its file list, its git facts, and what the readers have already used."""

    def __init__(self, root: Path, now: dt.datetime):
        self.root = root
        self.now = now
        self.in_git = (git(root, "rev-parse", "--is-inside-work-tree") or "").strip() == "true"
        self.git = git_facts(root, now) if self.in_git else {"ok": False}
        self.files, self.partial = list_files(root, self.in_git)
        self.file_set = set(self.files)
        self.claimed: set[str] = set()       # files a layout reader owns: checklists and sections skip them
        self.plan_found = False              # a step list or a planning tool: checklists then show one line each
        self.changelog_used: set[str] = set()  # CHANGELOG headings the step list already counted
        self.deadline = time.monotonic() + SLOW_SECONDS
        self.slow_stopped = False
        self.secret_scan: dict[str, list] = {}  # files the code reader already checked for keys
        self.newest_edit: str | None = None     # a folder outside git: when a file last changed
        self._texts: dict[str, str | None] = {}
        self._commits: list[dict] | None = None

    def text(self, rel: str, limit: int = MAX_NOTE_BYTES, keep: bool = True) -> str | None:
        if rel in self._texts:
            return self._texts[rel]
        path = self.root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace") if path.stat().st_size <= limit else None
        except OSError:
            text = None
        if keep:
            self._texts[rel] = text
        return text

    def exists(self, rel: str) -> bool:
        return (self.root / rel).exists()

    def mtime(self, rel: str) -> float | None:
        try:
            return (self.root / rel).stat().st_mtime
        except OSError:
            return None

    def under(self, folder: str, depth: int | None = None) -> list[str]:
        """Files inside a folder; depth 1 = directly inside it."""
        prefix = folder.rstrip("/") + "/"
        found = [f for f in self.files if f.startswith(prefix)]
        if depth is not None:
            found = [f for f in found if f[len(prefix):].count("/") < depth]
        return found

    def named(self, *names: str, depth: int = 9) -> list[str]:
        """Files with one of these names (any case), no more than depth folders down."""
        wanted = {n.lower() for n in names}
        return sorted((f for f in self.files if f.rsplit("/", 1)[-1].lower() in wanted and f.count("/") <= depth),
                      key=lambda f: (f.count("/"), f.lower()))

    def claim(self, files) -> None:
        self.claimed.update(files)

    def slow_time_left(self) -> bool:
        if time.monotonic() > self.deadline:
            self.slow_stopped = True
            return False
        return True

    def commits(self) -> list[dict]:
        """The newest commits and the files each one changed (read once, and only when a reader asks)."""
        if self._commits is None:
            self._commits = []
            if self.git.get("ok"):
                log = git(self.root, "log", f"-{COMMITS_READ}", "--no-merges", "--relative", "--name-only",
                          "--format=%x1e%h%x1f%cI%x1f%s") or ""
                for record in log.split("\x1e"):
                    head, _, rest = record.strip("\n").partition("\n")
                    parts = head.split("\x1f", 2)
                    if len(parts) == 3:
                        self._commits.append({"short": parts[0], "date": parts[1], "subject": parts[2],
                                              "files": [f for f in rest.splitlines() if f.strip()]})
        return self._commits


_FOLDERS: dict[tuple[str, str], Folder] = {}
SHARE_FOLDERS = False  # pulse.py turns this on for a refresh; tests read a changed folder again, so they don't


def folder_for(root: Path, now: dt.datetime) -> Folder:
    """The folder, read once per refresh: the checklists, crash names and prompts reuse the same file list."""
    if not SHARE_FOLDERS:
        return Folder(root, now)
    key = (str(root), now.isoformat())
    if key not in _FOLDERS:
        _FOLDERS.clear()  # one project at a time: the previous one's folder is done with
        _FOLDERS[key] = Folder(root, now)
    return _FOLDERS[key]


class Board:
    """What one reader found: items for the groups, progress stages, and lines for "How it's set up"."""

    def __init__(self):
        self.items: list[dict] = []
        self.stages: list[dict] = []
        self.setup: list[dict] = []
        self.chips: list[str] = []
        self.found = ""  # a few words for the "What Pulse reads" menu: "42 tasks in 3 notes"
        self.road: list[dict] = []    # the Roadmap: stages, each with its rows in order
        self.later: list[dict] = []   # what comes after: later versions
        self.legend: dict[str, str] = {}  # what each colour means here ("ready" → "Prompt written")
        self.road_path: str | None = None  # the plan's own file, for "Open the roadmap"

    def add(self, group: str, key: str, label: str, title: str, detail: str = "", path: str | None = None,
            when: str | None = None, command: str | None = None, you: bool = False) -> None:
        self.items.append({"group": group, "key": key, "label": label, "title": title, "detail": detail,
                           "path": path, "time": when, "command": command, "you": you})

    def road_stage(self, name: str, note: str, rows: list[dict]) -> None:
        if rows:
            self.road.append({"stageID": name, "name": name, "note": note, "rows": rows})

    def more(self, group: str, key: str, count: int, what: str, path: str | None) -> None:
        self.add(group, f"more:{key}", "more", f"…and {count} more {what}", "Open the file to see them all.", path)

    def stage(self, name: str, done: int, total: int, unit: str, primary: bool = True) -> None:
        """A progress bar. A checklist beside a real plan isn't primary: it doesn't count in the headline."""
        if total:
            self.stages.append({"name": name, "done": done, "total": total, "unit": unit, "primary": primary})

    def set_up(self, key: str, label: str, title: str, detail: str = "", path: str | None = None) -> None:
        self.setup.append({"group": "setup", "key": f"setup:{key}", "label": label, "title": title,
                           "detail": detail, "path": path, "time": None, "command": None, "you": False})


def road_row(key: str, label: str, name: str, state: str, detail: str = "", path: str | None = None,
             command: str | None = None, size: str | None = None, you: bool = False, cut: bool = False,
             done: int | None = None, total: int | None = None) -> dict:
    """One line of the Roadmap: a step (with its size bar) or a whole list (with its progress)."""
    return {"key": key, "label": label, "name": name, "state": state, "size": size, "you": you, "cut": cut,
            "detail": detail, "path": path, "command": command, "done": done, "total": total}


def progress_state(done: int, total: int, started: bool = False) -> str:
    if total and done == total:
        return "done"
    if done or started:
        return "doing"
    return "ready" if total else "todo"


MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


def status_day(text: str, now: dt.datetime) -> str | None:
    """A date written in a status: "DONE 29 Sep" → this year's 29 Sep (last year's, if that's still ahead)."""
    written = iso_day(text)
    if written:
        return written
    found = re.search(r"\b(\d{1,2}) (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", text or "", re.I)
    if not found:
        return None
    try:
        when = dt.date(now.year, MONTHS.index(found.group(2).lower()) + 1, int(found.group(1)))
    except ValueError:
        return None
    if when > now.date():
        when = when.replace(year=when.year - 1)
    return when.isoformat()


def status_word(text: str) -> str | None:
    """A status as a person wrote it ("DONE 29 Sep", "🚧 in progress", "to write") → done, doing, blocked,
    skipped or todo."""
    low = clean(text).lower()
    if not low or low in ("—", "-", "–"):
        return None
    if re.search(r"\bnot (yet )?(done|started|complete|finished)\b", low):
        return "todo"
    if re.search(r"\b(cancel+ed|dropped|won'?t do|wontfix|abandoned|skipped|obsolete)\b", low) or "❌" in low:
        return "skipped"
    if re.search(r"\b(done|complete|completed|finished|shipped|merged|released|closed|resolved)\b", low) \
            or any(mark in low for mark in "✅✔☑"):
        return "done"
    if re.search(r"\b(blocked|on hold|stuck)\b", low) or any(mark in low for mark in "⛔🛑"):
        return "blocked"
    if re.search(r"\b(in[ -]progress|wip|doing|started|underway|ongoing|in review|reviewing|testing|active)\b", low) \
            or any(mark in low for mark in "🚧⏳🔄"):
        return "doing"
    if re.search(r"\b(to ?do|planned|not started|pending|open|backlog|next|later|to write|outlined|written|draft"
                 r"|ready|queued|proposed|idea)\b", low) or any(mark in low for mark in "⬜🔲"):
        return "todo"
    return None


# ---------------------------------------------------------------- git

def read_git(folder: Folder, board: Board) -> None:
    facts = folder.git
    if not facts.get("ok"):
        if folder.in_git:
            board.found = "a git repo with no commits yet"
            return
        cutoff = folder.now.timestamp() - RECENT_EDIT_HOURS * 3600
        recent = []
        for rel in folder.files:
            if rel.endswith((".log", ".pyc", ".sqlite-wal", ".sqlite-shm")) or any(
                    part.lower() in OUTPUT_DIRS for part in rel.split("/")[:-1]):
                continue  # what the project makes (logs, caches, output), not work on it
            stamp = folder.mtime(rel)
            if stamp and stamp >= cutoff:
                recent.append((stamp, rel))
        recent.sort(reverse=True)
        newest = max((folder.mtime(rel) or 0 for rel in folder.files[:5000]), default=0)
        folder.newest_edit = iso(newest) if newest else None
        for stamp, rel in recent[:8]:
            board.add("now", f"edit:{rel}", "edited", display(rel), "Edited", rel, iso(stamp))
        if len(recent) > 8:
            board.more("now", "edits", len(recent) - 8, "files edited in the last two days", ".")
        board.found = f"not a git repo · {plural(len(recent), 'file')} edited in the last two days"
        return

    root = folder.root
    changed = facts["uncommitted"]
    if changed["files"]:
        count = len(changed["files"])
        board.add("now", "uncommitted", "git", f"{plural(count, 'file')} not committed yet",
                  f"+{changed['added']} −{changed['removed']} lines · last edit", None, changed.get("newestEdit"))
        oldest = changed.get("oldestEdit")
        if oldest:
            hours = (folder.now - dt.datetime.fromisoformat(oldest)).total_seconds() / 3600
            if hours > UNCOMMITTED_WARN_HOURS:
                board.add("could", "warning:uncommitted-old", "git",
                          f"Changes left uncommitted for {round(hours)} hours",
                          f"{plural(count, 'file')} in all. A commit keeps a copy you can go back to.", you=True)
    for entry in changed["files"]:
        if entry["code"] in ("UU", "AA", "DD", "AU", "UA", "DU", "UD"):
            board.add("could", f"git:conflict:{entry['path']}", "conflict", f"Merge conflict in {entry['path']}",
                      "Both sides changed it; git is waiting for you to choose.", entry["path"])
    branch = facts.get("branch") or ""
    if branch == "HEAD":
        board.add("could", "git:detached", "git", "Not on any branch (a “detached HEAD”)",
                  "New commits made here are easy to lose.")
    elif branch and branch not in DEFAULT_BRANCHES:
        board.add("now", "git:branch", "branch", f"Working on the branch “{branch}”", "Not the main branch.")
    for extra in git_extras(root, facts):
        board.items.append(extra)
    git_dir = (git(root, "rev-parse", "--git-dir") or "").strip()
    if git_dir:
        where = root / git_dir
        for marker, what in (("MERGE_HEAD", "A merge"), ("rebase-merge", "A rebase"), ("rebase-apply", "A rebase"),
                             ("CHERRY_PICK_HEAD", "A cherry-pick"), ("REVERT_HEAD", "A revert")):
            if (where / marker).exists():
                board.add("could", f"git:unfinished:{marker}", "git", f"{what} was started and not finished",
                          "Git is waiting for it to be completed or aborted.")
                break
    board.found = f"branch {branch or '?'} · {plural(len(changed['files']), 'file')} not committed"


def git_extras(root: Path, facts: dict) -> list[dict]:
    """Work that's easy to forget: commits not pushed, stashes, and other branches with commits of their own."""
    found: list[dict] = []

    def add(group: str, key: str, label: str, title: str, detail: str, when: str | None = None,
            you: bool = False) -> None:
        found.append({"group": group, "key": key, "label": label, "title": title, "detail": detail, "path": None,
                      "time": when, "command": None, "you": you})

    ahead = (git(root, "rev-list", "--count", "@{upstream}..HEAD") or "").strip()
    if ahead.isdigit() and int(ahead):
        add("next", "git:unpushed", "git", f"{plural(int(ahead), 'commit')} not pushed yet",
            "Waiting on you: pushing keeps a copy off this Mac.", you=True)
    stashes = [line.split("\x1f") for line in (git(root, "stash", "list", "--format=%gd%x1f%cI%x1f%gs") or "")
               .splitlines() if line.count("\x1f") == 2]
    if stashes:
        add("could", "git:stash", "git", f"{plural(len(stashes), 'stash', 'stashes')}: work set aside, not committed",
            f"Newest: {shorten(stashes[0][2], 90)} · saved", stashes[0][1])
    current = facts.get("branch") or "HEAD"
    refs = git(root, "for-each-ref", "--sort=-committerdate", "--count=30",
               "--format=%(refname:short)%1f%(upstream:short)%1f%(upstream:track)%1f%(committerdate:iso-strict)",
               "refs/heads") or ""
    branches = 0
    for line in refs.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4 or parts[0] == current:
            continue
        name, upstream, track, when = parts
        own = (git(root, "rev-list", "--count", f"{current}..{name}") or "").strip()
        if not own.isdigit() or not int(own):
            continue  # everything on it is already in the current branch
        ahead_up = re.search(r"ahead (\d+)", track)
        pushed = "never pushed" if not upstream else (f"{plural(int(ahead_up.group(1)), 'commit')} not pushed"
                                                      if ahead_up else "pushed")
        add("could", f"git:branch:{name}", "branch", f"Branch “{name}” has {plural(int(own), 'commit')} "
            f"that {'isn’t' if int(own) == 1 else 'aren’t'} in {current}", f"{pushed} · last commit", when)
        branches += 1
        if branches >= 6:
            break
    return found


def latest_commits(folder: Folder, count: int = 15) -> list[dict]:
    commits = []
    for line in (git(folder.root, "log", f"-{count}", "--format=%h%x1f%cI%x1f%s") or "").splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) == 3:
            commits.append({"short": parts[0], "date": parts[1], "subject": parts[2]})
    return commits


# ---------------------------------------------------------------- a step list

STEP_DIRS = ("prompts", "steps", "docs/prompts", "docs/steps", "plans", "docs/plans", "phases", "docs/phases",
             "milestones", "briefs", "docs/briefs")
STEP_FILE = re.compile(r"^(?:step[-_ ]?)?(\d{1,3}[a-z]?)(?:[-_. ]+(.*))?\.md$", re.I)
PLAN_DOC = re.compile(r"(^|/)(roadmap|plan|project-plan|build-plan|implementation-plan|steps|milestones|phases)"
                      r"[^/]*\.md$", re.I)
OLD_DOC = re.compile(r"(^|/|[-_. ])(archive|archived|old|superseded|draft|proposal|obsolete|deprecated)"
                     r"([-_./ ]|$)", re.I)
STAGE_LIKE = re.compile(r"\b(stage|phase|milestone|sprint|part|week|release|version|epic)s?\b|\bv\d", re.I)
WRITEUP_DIR = re.compile(r"(^|/)(history/steps|steps/done|done|completed|finished)$", re.I)
STRONG_ID = ("step", "phase", "milestone", "stage")
WEAK_ID = ("#", "id", "no", "no.", "number")
NAME_COLS = ("what you get", "what", "description", "title", "name", "goal", "deliverable", "summary", "focus",
             "task", "feature", "scope")
STATUS_COLS = ("status", "state", "done", "done?", "progress", "result")
FILE_COLS = ("file", "prompt", "prompt file", "brief", "doc", "document", "spec", "link")
SIZE_COLS = ("size", "effort", "estimate")
AFTER_COLS = ("after", "depends on", "dependencies", "needs", "waits on", "blocked by", "requires")
LATER_COLS = ("what", "what you get", "description", "scope", "features", "focus", "goal", "summary", "contents", "notes")
STEP_REF = re.compile(r"^\s*(?:step|phase|milestone|stage)\s+#?(\d+[a-z]?(?:\.\d+)?)\b", re.I)
ID_REF = re.compile(r"^\s*([A-Z][A-Z0-9]*(?:-[0-9A-Za-z]+)+)\b")
NUM_REF = re.compile(r"^\s*(\d{1,3}[a-z]?)\s*[:.)]\s")


def leading_step(text: str) -> str | None:
    """The step a commit subject or CHANGELOG heading starts with: "Step 09c: …" → "9c", "SF-1: …" → "sf-1"."""
    for pattern in (STEP_REF, ID_REF, NUM_REF):
        found = pattern.match(text)
        if found:
            return id_key(found.group(1))
    return None


def md_tables(text: str) -> list[dict]:
    """Markdown tables: header cells, rows, and the heading (or bold line) above each."""
    tables: list[dict] = []
    heading = rest = ""
    lines = list(md_lines(text))
    i = 0
    while i < len(lines):
        number, line = lines[i]
        titled = HEADING.match(line) or re.match(r"^(\*\*)(.+?)\*\*\s*(.*)$", line)
        if titled:
            heading = strip_parens(clean(titled.group(2))).rstrip(".:")
            rest = titled.group(3).strip() if titled.lastindex and titled.lastindex >= 3 else ""
        if line.lstrip().startswith("|") and i + 1 < len(lines) \
                and re.match(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", lines[i + 1][1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j][1].lstrip().startswith("|"):
                rows.append([c.strip() for c in lines[j][1].strip().strip("|").split("|")])
                j += 1
            tables.append({"header": header, "rows": rows, "heading": heading, "rest": rest, "line": number})
            i = j
            continue
        i += 1
    return tables


def pick_column(header: list[str], names: tuple, avoid: int | None = None) -> int | None:
    low = [clean(h).lower().strip(" *_:") for h in header]
    for name in names:
        if name in low and low.index(name) != avoid:
            return low.index(name)
    return None


def plan_docs(folder: Folder) -> list[str]:
    """Where a step table or a table of versions may be: roadmap and plan notes, a step folder's README, the README."""
    found = []
    for rel in folder.files:
        low = rel.lower()
        in_step_dir = "/" in low and low.rsplit("/", 1)[0] in STEP_DIRS
        if low.startswith(TOOL_DIRS) or in_fixtures(rel) or in_tests_or_examples(rel):
            continue
        if low.endswith(".md") and ((PLAN_DOC.search(low) and rel.count("/") <= 2) or low == "readme.md"
                                    or (in_step_dir and low.endswith("/readme.md"))):
            found.append(rel)
    return sorted(found, key=lambda r: (r.lower() == "readme.md", r.count("/"), r))


def step_tables(folder: Folder) -> list[dict]:
    """Step tables in plan documents: a column of step ids, what each step is, and maybe its status, size and
    what it waits for."""
    found = []
    for rel in plan_docs(folder):
        for table in md_tables(folder.text(rel) or ""):
            header = table["header"]
            strong = pick_column(header, STRONG_ID)
            id_col = strong if strong is not None else (None if rel.lower() == "readme.md"
                                                         else pick_column(header, WEAK_ID))
            if id_col is None or len(table["rows"]) < 3:
                continue
            ids = [clean(row[id_col]) if id_col < len(row) else "" for row in table["rows"]]
            if len(set(filter(None, ids))) < len([i for i in ids if i]):
                continue  # repeated values group rows ("Phase 1" on every task): not a list of steps
            columns = {"name": pick_column(header, NAME_COLS, avoid=id_col),
                       "status": pick_column(header, STATUS_COLS, avoid=id_col),
                       "file": pick_column(header, FILE_COLS, avoid=id_col),
                       "size": pick_column(header, SIZE_COLS, avoid=id_col),
                       "after": pick_column(header, AFTER_COLS, avoid=id_col)}
            steps = []
            for row, raw_id in zip(table["rows"], ids):
                shown = re.sub(r"^(?:step|phase|milestone|stage)\s+", "", raw_id, flags=re.I).strip()
                if not shown or shown in ("—", "-", "–") or len(shown) > 24:
                    continue
                cell = {name: (clean(row[col]) if col is not None and col < len(row) else "")
                        for name, col in columns.items()}
                size = cell["size"][:1].upper()
                steps.append({"id": shown, "key": id_key(shown), "name": cell["name"], "status": cell["status"],
                              "file": cell["file"], "size": size if size in ("S", "M", "L") else None,
                              "after": cell["after"]})
            if len(steps) >= 3:
                found.append({"doc": rel, "heading": table["heading"], "rest": table.get("rest", ""),
                              "steps": steps, "strong": strong is not None})
    current = [t for t in found if not OLD_DOC.search(t["doc"])]
    found = current or found  # an old roadmap or a proposal only counts when there's nothing newer
    if any(t["strong"] for t in found):
        found = [t for t in found if t["strong"]]  # a "Step" column beats a plain "#" column
    return found


def later_versions(folder: Folder) -> list[dict]:
    """A table of versions ("| Version | What |"): what comes after the current plan."""
    rows = []
    for rel in plan_docs(folder):
        for table in md_tables(folder.text(rel) or ""):
            version = pick_column(table["header"], ("version", "release"))
            what = pick_column(table["header"], LATER_COLS, avoid=version)
            if version is None or what is None or len(table["rows"]) < 2:
                continue
            for row in table["rows"]:
                if max(version, what) >= len(row) or not clean(row[version]):
                    continue
                named = re.search(r"`([^`]+\.md)`", row[what])
                rows.append({"group": table["heading"] or "Later versions", "label": clean(row[version]),
                             "text": headline(clean(row[what]), limit=170, cut_at_colon=False),
                             "path": named.group(1) if named and named.group(1) in folder.file_set else None})
        if rows:
            break
    return rows


def step_files(folder: Folder) -> dict[str, dict[str, str]]:
    """Numbered step files ("prompts/03a-library-core.md"), by folder, keyed by their step id."""
    by_dir: dict[str, dict[str, str]] = {}
    for folder_name in STEP_DIRS:
        for rel in folder.under(folder_name, depth=1):
            found = STEP_FILE.match(rel.rsplit("/", 1)[-1])
            if found:
                by_dir.setdefault(folder_name, {}).setdefault(id_key(found.group(1)), rel)
    return by_dir


def step_title(text: str, fallback: str, step_id: str = "") -> str:
    title = first_heading(text) or fallback
    title = re.sub(r"^(?:step|phase|milestone)\s+[\w.-]+\s*[:—–-]\s*", "", title, flags=re.I)
    if step_id:
        title = re.sub(rf"^{re.escape(step_id)}\s*[:—–-]\s*", "", title, flags=re.I)
    title = re.sub(r"\s*\(IN PROGRESS[^)]*\)", "", title, flags=re.I)
    return headline(title, limit=80, cut_at_colon=False)


def project_verb(folder: Folder) -> str:
    texts = [folder.text(rel) or "" for rel in ["README.md", "CLAUDE.md", "AGENTS.md", "docs/NEXT-UP.md"]
             + [f"{d}/README.md" for d in STEP_DIRS] if rel in folder.file_set]
    return prompt_verb(texts)


def read_steps(folder: Folder, board: Board) -> None:
    board.later = later_versions(folder)
    tables = step_tables(folder)
    numbered = step_files(folder)
    plans: list[dict] = []  # each: stage name, note, doc, steps in order
    if tables:
        for n, table in enumerate(tables):
            staged = STAGE_LIKE.search(table["heading"] or "")
            name, note = stage_title_note(table["heading"], table.get("rest", "")) if staged else ("Steps", "")
            if name == "Steps" and n:
                name = f"Steps ({display(table['doc'])})"
            plans.append({"name": name, "note": note, "doc": table["doc"], "steps": table["steps"]})
    else:
        for folder_name, files in numbered.items():
            if len(files) >= 3:
                steps = []
                for key, rel in sorted(files.items(), key=lambda kv: natural(kv[1])):
                    number = STEP_FILE.match(rel.rsplit("/", 1)[-1]).group(1)
                    steps.append({"id": number, "key": key, "name": "", "status": "", "file": rel, "size": None,
                                  "after": ""})
                plans.append({"name": "Steps", "doc": f"{folder_name}/", "steps": steps})
                break
    if not plans:
        if board.later:
            board.found = plural(len(board.later), "later version")
        return

    # Each step's own file: the table's File cell, else a numbered or id-named file in a step folder.
    all_files = {key: rel for files in numbered.values() for key, rel in files.items()}
    prompt_like = [f for d in STEP_DIRS for f in folder.under(d, depth=1) if f.endswith(".md")]
    uses_files = False
    for plan in plans:
        for step in plan["steps"]:
            named = step["file"].strip("`") if step["file"] else ""
            if named and named in folder.file_set:
                step["file"] = named
            elif step["key"] in all_files:
                step["file"] = all_files[step["key"]]
            else:
                prefix = step["id"].lower()
                step["file"] = next((f for f in prompt_like if f.rsplit("/", 1)[-1].lower().startswith(prefix + "-")
                                     or f.rsplit("/", 1)[-1].lower() == prefix + ".md"), "")
            uses_files = uses_files or bool(step["file"])
            text = folder.text(step["file"]) if step["file"] else None
            if not step["name"]:
                step["name"] = step_title(text or "", step["id"], step["id"])
            elif text:
                step["name"] = step_title(text, step["name"], step["id"])
            else:
                step["name"] = headline(step["name"], limit=80, cut_at_colon=False)
            status_line = re.search(r"^\**status\**\s*[:：]\s*(.+)$", "\n".join((text or "").splitlines()[:30]),
                                    re.I | re.M)
            step["explicit"] = status_word(step["status"]) or (status_word(status_line.group(1)) if status_line
                                                               else None)
    plan_files = {plan["doc"] for plan in plans} | set(prompt_like)
    known = {step["key"]: step for plan in plans for step in plan["steps"]}

    # Evidence 1: a write-up per finished step ("docs/history/steps/SF-1.md").
    writeups: dict[str, dict] = {}
    for rel in folder.files:
        parent, _, name = rel.rpartition("/")
        if name.lower().endswith(".md") and WRITEUP_DIR.search(parent):
            first = (folder.text(rel) or "").split("\n", 1)[0]
            writeups[id_key(name[:-3])] = {"path": rel, "doing": "IN PROGRESS" in first.upper(),
                                           "day": iso_day(first)}

    # Evidence 2: CHANGELOG headings that start with a step ("### Step 09c: Keep your own audio").
    logged: dict[str, dict] = {}
    extra: dict[str, dict] = {}
    for rel in changelog_files(folder)[:1]:
        for heading in changelog_headings(folder.text(rel) or ""):
            key = leading_step(heading["text"])
            if not key:
                continue
            target = logged if key in known else extra
            target.setdefault(key, {"heading": heading["text"], "day": iso_day(heading["text"]), "path": rel})
            folder.changelog_used.add(norm(heading["text"]))

    # Evidence 3: commits whose subject starts with the step and that changed more than the plan itself
    # ("Step 10 brief: …" only edited the step's prompt, so the step hasn't started).
    work: dict[str, list[dict]] = {}
    for commit in folder.commits():
        key = leading_step(commit["subject"])
        if key and (key in known or key in extra) and any(f not in plan_files for f in commit["files"]):
            work.setdefault(key, []).append(commit)

    uses_changelog = bool(logged)
    ordered = [step for plan in plans for step in plan["steps"]]
    last_worked = max((i for i, step in enumerate(ordered) if step["key"] in work), default=-1)
    for i, step in enumerate(ordered):
        key, explicit = step["key"], step["explicit"]
        commits = work.get(key, [])
        step["when"] = (commits[0]["date"] if commits else None) or status_day(step["status"], folder.now) \
            or (writeups.get(key) or {}).get("day") or (logged.get(key) or {}).get("day")
        if explicit in ("done", "blocked", "skipped"):
            step["state"] = explicit
        elif key in writeups:
            step["state"] = "doing" if writeups[key]["doing"] else "done"
            step["when"] = step["when"] or writeups[key]["day"]
        elif key in logged:
            step["state"] = "done"
            step["when"] = step["when"] or logged[key]["day"]
        elif explicit == "doing":
            step["state"] = "doing"
        elif commits:
            step["state"] = "doing" if uses_changelog or i == last_worked else "done"
        else:
            step["state"] = "todo"

    verb = project_verb(folder)
    first_todo = True
    total = done = 0
    for plan in plans:
        plan_done = plan_total = 0
        rows = []
        for step in plan["steps"]:
            state = step["state"]
            if state == "skipped":
                continue
            plan_total += 1
            key = f"step:{step['id']}"
            path = step["file"] or plan["doc"]
            command = command_for(step["file"], None, verb) if step["file"] and state != "done" else None
            after = step.get("after") or ""
            you = bool(re.search(r"\b(owner|you|me|my)\b", after, re.I))
            cut = "cut line" in after.lower()
            waits = [t.strip() for t in re.split(r"[,;]", strip_parens(after))
                     if t.strip() and t.strip() not in ("—", "-", "–")]
            open_waits = [t for t in waits if id_key(t) in known and known[id_key(t)]["state"] != "done"]
            prompt = (" · prompt written" if step["file"] else " · prompt not written yet") if uses_files else ""
            if state == "done":
                plan_done += 1
                detail = "Done"
                board.add("done", key, step["id"], step["name"], detail, path, step["when"])
            elif state == "doing":
                detail = "In progress · last worked on"
                board.add("now", key, step["id"], step["name"], detail, path, step["when"], command)
            elif state == "blocked":
                detail = "Marked blocked in the plan"
                board.add("could", key, step["id"], step["name"], detail, path)
            else:
                if you:
                    where = "Waits on you: " + after
                elif open_waits:
                    where = "After " + ", ".join(open_waits)
                else:
                    where = "Up next" if first_todo else "Later"
                detail = where + prompt + (" · on the cut line" if cut else "")
                if uses_files and not step["file"] and not you:
                    board.add("missing", key, step["id"], step["name"], detail, plan["doc"])
                else:
                    board.add("next", key, step["id"], step["name"], detail, path, command=command, you=you)
                first_todo = False
            road_state = state if state in ("done", "doing", "blocked") else (
                "ready" if uses_files and step["file"] else "todo")
            rows.append(road_row(key, step["id"], step["name"], road_state,
                                 detail if state != "done" else ("Done " + day(step["when"]) if step["when"]
                                                                 else "Done"),
                                 path, command, step.get("size"), you and state != "done", cut))
        board.stage(plan["name"], plan_done, plan_total, "steps")
        board.road_stage(plan["name"], "all done" if plan_total and plan_done == plan_total else plan.get("note", ""),
                         rows)
        total, done = total + plan_total, done + plan_done
    for key, info in extra.items():
        commits = work.get(key, [])
        label = re.sub(r"^step\s+", "", info["heading"].split(":", 1)[0], flags=re.I).strip()
        name = info["heading"].split(":", 1)[1] if ":" in info["heading"] else info["heading"]
        board.add("done", f"step:{label}", label, headline(strip_parens(name), limit=80, cut_at_colon=False),
                  "Done · not in the step list", info["path"], commits[0]["date"] if commits else info["day"])
    if uses_files:
        board.legend = {"ready": "Prompt written", "todo": "Prompt still to write"}
    folder.claim(plan_files)
    docs = ", ".join(sorted({plan["doc"] for plan in plans}))
    board.found = f"{plural(total, 'step')} ({done} done) in {docs}"
    detail = f"The plan is in {docs}"
    dirs = sorted({step["file"].rsplit("/", 1)[0] + "/" for step in ordered if "/" in step["file"]})
    if dirs:
        detail += f"; each step has its own prompt in {', '.join(dirs)}, started with “{verb} <prompt>”"
    if uses_changelog:
        detail += "; finished steps are recorded in the CHANGELOG"
    elif writeups:
        detail += "; each finished step has a write-up"
    board.road_path = plans[0]["doc"].rstrip("/")
    folder.plan_found = True
    board.set_up("steps", "plan", f"Step list: {plural(total, 'step')}", detail + ".", plans[0]["doc"].rstrip("/"))
    later_docs = sorted({f for f in folder.files if re.match(r"^(docs/)?(roadmap|future|later)/[^/]+\.md$", f, re.I)})
    if later_docs:
        board.set_up("later", "plan", f"Plans for later: {plural(len(later_docs), 'note')}",
                     ", ".join(display(f) for f in later_docs), later_docs[0].rsplit("/", 1)[0])
    board.chips.append("Step list")


# ---------------------------------------------------------------- Spec Kit, Kiro, Task Master, Backlog.md, BMAD

GENERIC_HEADINGS = {"tasks", "task list", "implementation plan", "implementation tasks", "implementation",
                    "todo", "to do", "progress", "checklist"}


def spec_task_items(board: Board, tasks: list[dict], key_prefix: str, where: str, path: str,
                    number: re.Pattern) -> tuple[int, int]:
    """Items for a spec's tasks.md (Spec Kit or Kiro); returns (done, total)."""
    counted = [t for t in leaves(tasks) if t["state"] != "skipped"]
    shown_next = 0
    for task in counted:
        found = number.match(task["text"])
        label = found.group(1) if found else "task"
        title = headline(re.sub(r"^(\[[^\]]+\]\s*)+", "", found.group(2) if found else task["text"]),
                         limit=100, cut_at_colon=False)
        key = f"{key_prefix}:{label if found else norm(task['text'])}"
        heading = task["heading"] if task["heading"].lower().strip(" :") not in GENERIC_HEADINGS else ""
        detail = where + (f" · {heading}" if heading else "")
        if task["state"] == "done":
            board.add("done", key, label, title, detail, path, task["doneDay"])
        elif task["state"] == "doing":
            board.add("now", key, label, title, "In progress · " + detail, path)
        elif shown_next < SHOW:
            board.add("next", key, label, title, detail, path)
            shown_next += 1
    left = sum(1 for t in counted if t["state"] == "todo") - shown_next
    if left > 0:
        board.more("next", key_prefix, left, "open tasks", path)
    return sum(1 for t in counted if t["state"] == "done"), len(counted)


def read_speckit(folder: Folder, board: Board) -> None:
    features = sorted({f.split("/")[1] for f in folder.under("specs")
                       if f.count("/") == 2 and f.rsplit("/", 1)[-1] in ("spec.md", "plan.md", "tasks.md")})
    specify = [f for f in folder.files if f.startswith(".specify/")]
    if not features and not specify:
        return
    folder.claim(specify)
    branch = folder.git.get("branch") if folder.git.get("ok") else None
    total_tasks = 0
    rows = []
    for feature in features:
        base = f"specs/{feature}/"
        folder.claim(folder.under(base.rstrip("/")))
        has = {name: base + name in folder.file_set for name in ("spec.md", "plan.md", "tasks.md")}
        title = re.sub(r"^feature specification:\s*", "", first_heading(folder.text(base + "spec.md") or ""),
                       flags=re.I) or feature
        for name in ("spec.md", "plan.md"):
            for question in re.findall(r"\[NEEDS CLARIFICATION:?\s*([^\]]*)\]", folder.text(base + name) or ""):
                board.add("could", f"speckit:{feature}:q:{norm(question)}", "question",
                          headline(question, cut_at_colon=False) or "A question is still open",
                          f"Marked “needs clarification” in {feature}/{name}", base + name)
        if has["spec.md"] and not has["plan.md"]:
            board.add("missing", f"speckit:{feature}:plan", shorten(feature), f"No plan yet for “{title}”",
                      "Spec Kit's next step for this feature is to plan it.", base + "spec.md", command="/speckit.plan")
            rows.append(road_row(f"speckit:{feature}", feature, title, "todo", "Spec written; no plan yet",
                                 base + "spec.md", "/speckit.plan"))
        elif has["plan.md"] and not has["tasks.md"]:
            board.add("missing", f"speckit:{feature}:tasks", shorten(feature), f"No task list yet for “{title}”",
                      "Spec Kit's next step for this feature is its task list.", base + "plan.md",
                      command="/speckit.tasks")
            rows.append(road_row(f"speckit:{feature}", feature, title, "todo", "Planned; no task list yet",
                                 base + "plan.md", "/speckit.tasks"))
        if has["tasks.md"]:
            tasks = parse_checkboxes(folder.text(base + "tasks.md") or "")
            done, total = spec_task_items(board, tasks, f"speckit:{feature}", feature, base + "tasks.md",
                                          re.compile(r"^(T\d{2,})\b[\s:.-]*(.*)$"))
            board.stage(feature, done, total, "tasks")
            total_tasks += total
            building = 0 < done < total or (branch == feature and done < total)
            if building:
                board.add("now", f"speckit:{feature}", "feature", f"Building “{title}”",
                          f"{done} of {total} tasks done" + (" · its branch is checked out" if branch == feature
                                                             else ""), base + "tasks.md", command="/speckit.implement")
            state = progress_state(done, total, building)
            rows.append(road_row(f"speckit:{feature}", feature, title, state, f"{done} of {total} tasks done",
                                 base + "tasks.md", "/speckit.implement" if state != "done" else None,
                                 done=done, total=total))
    board.road_stage("Spec Kit features", "", rows)
    folder.plan_found = folder.plan_found or bool(rows)
    board.legend = {"ready": "Task list written", "todo": "Spec or plan still to finish"}
    constitution = next((f for f in (".specify/memory/constitution.md", "memory/constitution.md")
                         if f in folder.file_set), None)
    if not features:
        board.add("missing", "speckit:first", "Spec Kit", "Spec Kit is set up, but no feature is written yet",
                  "Describe the first feature with /speckit.specify.", ".specify", command="/speckit.specify")
    board.found = f"{plural(len(features), 'feature')}, {plural(total_tasks, 'task')}"
    board.set_up("speckit", "plan", f"Spec Kit: {plural(len(features), 'feature')}" if features
                 else "Spec Kit (no features yet)",
                 "Each feature has a spec, a plan and a task list in specs/"
                 + ("; the project's principles are in its constitution" if constitution else "") + ".",
                 constitution or "specs")
    board.chips.append("Spec Kit")


def read_kiro(folder: Folder, board: Board) -> None:
    specs = sorted({f.split("/")[2] for f in folder.under(".kiro/specs") if f.count("/") >= 3})
    steering = [f for f in folder.under(".kiro/steering") if f.endswith(".md")]
    hooks = folder.under(".kiro/hooks")
    if not (specs or steering or hooks):
        return
    folder.claim(folder.under(".kiro"))
    total_tasks = 0
    rows = []
    for spec in specs:
        base = f".kiro/specs/{spec}/"
        has = {name: base + name in folder.file_set for name in ("requirements.md", "design.md", "tasks.md")}
        if has["requirements.md"] and not has["design.md"]:
            board.add("missing", f"kiro:{spec}:design", shorten(spec), f"No design yet for “{spec}”",
                      "Kiro writes the design after the requirements.", base + "requirements.md")
            rows.append(road_row(f"kiro:{spec}", spec, spec, "todo", "Requirements written; no design yet",
                                 base + "requirements.md"))
        elif has["design.md"] and not has["tasks.md"]:
            board.add("missing", f"kiro:{spec}:tasks", shorten(spec), f"No task list yet for “{spec}”",
                      "Kiro writes the task list after the design.", base + "design.md")
            rows.append(road_row(f"kiro:{spec}", spec, spec, "todo", "Designed; no task list yet", base + "design.md"))
        if has["tasks.md"]:
            tasks = parse_checkboxes(folder.text(base + "tasks.md") or "", dash="doing")
            done, total = spec_task_items(board, tasks, f"kiro:{spec}", spec, base + "tasks.md",
                                          re.compile(r"^(\d+[a-z]?(?:\.\d+[a-z]?)*)\.?\s+(.*)$"))
            board.stage(spec, done, total, "tasks")
            total_tasks += total
            doing = any(t["state"] == "doing" for t in tasks)
            if 0 < done < total and not doing:
                board.add("now", f"kiro:{spec}", "spec", f"Building “{spec}”", f"{done} of {total} tasks done",
                          base + "tasks.md")
            rows.append(road_row(f"kiro:{spec}", spec, spec, progress_state(done, total, doing),
                                 f"{done} of {total} tasks done", base + "tasks.md", done=done, total=total))
    board.road_stage("Kiro specs", "", rows)
    folder.plan_found = folder.plan_found or bool(rows)
    board.legend = {"ready": "Task list written", "todo": "Requirements or design still to finish"}
    parts = [plural(len(specs), "spec")]
    if steering:
        parts.append(plural(len(steering), "steering doc"))
    if hooks:
        parts.append(plural(len(hooks), "hook"))
    board.found = f"{', '.join(parts)}, {plural(total_tasks, 'task')}"
    board.set_up("kiro", "plan", f"Kiro: {', '.join(parts)}",
                 "Specs (requirements → design → tasks) in .kiro/specs; steering docs tell the agent about the "
                 "product, the tech and the layout.", ".kiro")
    board.chips.append("Kiro")


TM_DONE = ("done", "completed")


def read_taskmaster(folder: Folder, board: Board) -> None:
    path = next((f for f in (".taskmaster/tasks/tasks.json", "tasks/tasks.json") if folder.exists(f)), None)
    prd = next((f for f in (".taskmaster/docs/prd.txt", ".taskmaster/docs/prd.md", "scripts/prd.txt")
                if folder.exists(f)), None)
    if not path and not (folder.root / ".taskmaster").is_dir():
        return
    folder.claim(folder.under(".taskmaster") + ([path] if path else [])
                 + [f for f in folder.under("tasks", depth=1) if re.search(r"/task_\d+\.txt$", f)])
    if not path:
        if prd:
            board.add("missing", "tm:tasks", "tasks", "No tasks yet: the PRD hasn't been turned into tasks",
                      "Task Master makes them with “task-master parse-prd”.", prd)
        board.set_up("taskmaster", "plan", "Task Master (no tasks yet)", "", ".taskmaster")
        board.chips.append("Task Master")
        return
    data = json.loads(folder.text(path, limit=20_000_000, keep=False) or "{}")
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        tags = {"master": data}
    else:
        tags = {name: block for name, block in (data.items() if isinstance(data, dict) else [])
                if isinstance(block, dict) and isinstance(block.get("tasks"), list)}
    total_tasks = 0
    for tag, block in tags.items():
        tasks = [t for t in block["tasks"] if isinstance(t, dict)]
        status_of = {str(t.get("id")): str(t.get("status") or "pending").lower() for t in tasks}
        ready, waiting, later = [], [], []
        rows = []
        done = total = 0
        for task in tasks:
            tid, status = str(task.get("id")), status_of[str(task.get("id"))]
            if status in ("cancelled", "canceled"):
                continue
            total += 1
            title = headline(clean(str(task.get("title") or "")), limit=100, cut_at_colon=False) or f"Task {tid}"
            subtasks = [s for s in task.get("subtasks") or [] if isinstance(s, dict)]
            sub_done = sum(1 for s in subtasks if str(s.get("status") or "").lower() in TM_DONE)
            extra = f" · {sub_done} of {len(subtasks)} subtasks done" if subtasks else ""
            priority = f" · {task['priority']} priority" if task.get("priority") else ""
            where = "" if len(tags) == 1 else f" · tag {tag}"
            key, label = f"tm:{tag}:{tid}", f"#{tid}"
            show = f"task-master show {tid}"
            if status in TM_DONE:
                done += 1
                board.add("done", key, label, title, "Done" + extra + where, path)
                rows.append(road_row(key, label, title, "done", "Done" + extra, path))
            elif status in ("in-progress", "in_progress", "active", "review"):
                detail = ("In review" if status == "review" else "In progress") + extra
                board.add("now", key, label, title, detail + where, path, command=show)
                rows.append(road_row(key, label, title, "doing", detail, path, show))
            elif status == "blocked":
                board.add("could", key, label, title, "Marked blocked" + extra + where, path, command=show)
                rows.append(road_row(key, label, title, "blocked", "Marked blocked", path, show))
            elif status == "deferred":
                later.append((key, label, title, "Put off for later" + priority + where))
                rows.append(road_row(key, label, title, "todo", "Put off for later", path, show))
            else:
                deps = [str(d) for d in task.get("dependencies") or []]
                open_deps = [d for d in deps if status_of.get(d) not in TM_DONE]
                if open_deps:
                    detail = "Waits on #" + ", #".join(open_deps)
                    waiting.append((key, label, title, detail + priority + where))
                    rows.append(road_row(key, label, title, "todo", detail, path, show))
                else:
                    rank = {"high": 0, "medium": 1, "low": 2}.get(str(task.get("priority") or "").lower(), 1)
                    ready.append((rank, key, label, title, "Ready to start" + priority + extra + where))
                    rows.append(road_row(key, label, title, "ready", "Ready to start" + priority, path, show))
        for _, key, label, title, detail in sorted(ready, key=lambda r: r[0]):
            board.add("next", key, label, title, detail, path, command=f"task-master show {key.rsplit(':', 1)[-1]}")
        for key, label, title, detail in waiting + later:
            board.add("next", key, label, title, detail, path, command=f"task-master show {key.rsplit(':', 1)[-1]}")
        board.road_stage("Task Master" if len(tags) == 1 else f"Task Master · {tag}",
                         "all done" if total and done == total else "", rows)
        board.stage("Task Master" if len(tags) == 1 else f"Task Master · {tag}", done, total, "tasks")
        total_tasks += total
    board.legend = {"ready": "Ready to start", "todo": "Waiting on other tasks, or put off"}
    folder.plan_found = folder.plan_found or total_tasks > 0
    board.found = plural(total_tasks, "task")
    board.set_up("taskmaster", "plan", f"Task Master: {plural(total_tasks, 'task')}",
                 f"Tasks with statuses and dependencies in {path}" + (f", made from the PRD in {prd}" if prd else "")
                 + ".", path)
    board.chips.append("Task Master")


def read_backlog(folder: Folder, board: Board) -> None:
    active = [f for f in folder.under("backlog/tasks") if f.endswith(".md")]
    finished = [f for f in folder.under("backlog/completed") if f.endswith(".md")]
    drafts = [f for f in folder.under("backlog/drafts") if f.endswith(".md")]
    if not (active or finished or drafts or "backlog/config.yml" in folder.file_set):
        return
    folder.claim(folder.under("backlog"))
    config = folder.text("backlog/config.yml") or ""
    listed = re.search(r"^statuses:\s*\[(.*?)\]", config, re.M)
    statuses = [s.strip().strip("'\"") for s in listed.group(1).split(",")] if listed else ["To Do", "In Progress",
                                                                                           "Done"]
    done_status = statuses[-1].lower()
    tasks = []
    for rel in active + finished + drafts:
        text = folder.text(rel) or ""
        meta = parse_frontmatter(text)
        stem = rel.rsplit("/", 1)[-1][:-3]
        tid = str(meta.get("id") or stem.split(" - ", 1)[0])
        title = headline(clean(str(meta.get("title") or (stem.split(" - ", 1)[1] if " - " in stem else stem))),
                         limit=100, cut_at_colon=False)
        boxes = leaves(parse_checkboxes(text))
        criteria = (f" · {sum(1 for b in boxes if b['state'] == 'done')} of {len(boxes)} criteria met"
                    if boxes else "")
        status = str(meta.get("status") or "").lower()
        deps = meta.get("dependencies") or []
        tasks.append({"id": tid, "title": title, "status": status, "path": rel, "criteria": criteria,
                      "deps": deps if isinstance(deps, list) else [deps],
                      "when": iso_day(str(meta.get("updated_date") or meta.get("created_date") or "")),
                      "done": rel in finished or status == done_status or status == "done",
                      "draft": rel in drafts})
    def number(tid: str) -> str:
        found = re.search(r"(\d+(?:\.\d+)*)$", str(tid))
        return found.group(1) if found else str(tid).lower()

    done_ids = {number(t["id"]) for t in tasks if t["done"]}
    done = total = 0
    rows = []
    for task in tasks:
        key, label = f"backlog:{task['id']}", shorten(task["id"], 12)
        if task["draft"]:
            board.add("missing", key, label, task["title"], "A draft: not on the board yet", task["path"])
            continue
        total += 1
        if task["done"]:
            done += 1
            board.add("done", key, label, task["title"], "Done" + task["criteria"], task["path"], task["when"])
            rows.append(road_row(key, label, task["title"], "done", "Done" + task["criteria"], task["path"]))
        elif re.search(r"progress|doing|review", task["status"]):
            detail = task["status"].capitalize() + task["criteria"]
            board.add("now", key, label, task["title"], detail, task["path"])
            rows.append(road_row(key, label, task["title"], "doing", detail, task["path"]))
        else:
            waiting = [d for d in task["deps"] if number(d) not in done_ids]
            detail = ("Waits on " + ", ".join(map(str, waiting)) if waiting else "Ready to start") + task["criteria"]
            board.add("next", key, label, task["title"], detail, task["path"])
            rows.append(road_row(key, label, task["title"], "todo" if waiting else "ready", detail, task["path"]))
    board.stage("Backlog", done, total, "tasks")
    board.road_stage("Backlog", "all done" if total and done == total else "", rows)
    folder.plan_found = folder.plan_found or bool(rows)
    board.legend = {"ready": "Ready to start", "todo": "Waiting on other tasks"}
    docs = len(folder.under("backlog/docs"))
    decisions = len(folder.under("backlog/decisions"))
    board.found = plural(total, "task") + (f", {plural(len(drafts), 'draft')}" if drafts else "")
    board.set_up("backlog", "plan", f"Backlog.md: {plural(total, 'task')}",
                 "One file per task in backlog/, with a status each"
                 + (f"; {plural(docs, 'doc')}" if docs else "") + (f"; {plural(decisions, 'decision')}" if decisions
                                                                     else "") + ".", "backlog")
    board.chips.append("Backlog.md")


def bmad_status(text: str) -> str:
    """A story's status → done, review, doing, ready, draft or backlog ("Ready for Done" is waiting for review)."""
    low = re.sub(r"[^a-z ]+", " ", clean(text).lower())
    low = re.sub(r"\s+", " ", low).strip()
    if re.search(r"\bready for (done|review|qa)\b|\breview\b|\bqa\b", low):
        return "review"
    if re.search(r"\b(done|complete|completed|finished|shipped|closed)\b", low):
        return "done"
    if re.search(r"\bin ?progress\b|\bin dev|\bdoing\b|\bdeveloping\b", low):
        return "doing"
    if re.search(r"\b(approved|ready)\b", low):
        return "ready"
    if re.search(r"\bdraft", low):
        return "draft"
    return "backlog"


def read_bmad(folder: Folder, board: Board) -> None:
    core_dirs = (".bmad-core/", "bmad-core/", ".bmad/", "bmad/", "_bmad/")
    core = [f for f in folder.files if f.startswith(core_dirs)]
    config = folder.text(".bmad-core/core-config.yaml") or ""
    location = re.search(r"^\s*devStoryLocation:\s*(\S+)", config, re.M)
    story_dir = location.group(1).strip("'\"").rstrip("/") if location else "docs/stories"
    stories = [f for f in folder.under(story_dir) if f.endswith(".md")]
    sprint = [f for f in folder.files if f.rsplit("/", 1)[-1] == "sprint-status.yaml"]
    if not (core or stories or sprint):
        return
    folder.claim(core + stories + sprint)
    entries = []  # story number, title, status, path
    for rel in stories:
        text = folder.text(rel) or ""
        heading = first_heading(text)
        numbered = re.match(r"^(?:story\s+)?(\d+(?:\.\d+)+)\s*[:.—–-]?\s*(.*)$", heading, re.I) \
            or re.match(r"^(\d+(?:\.\d+)+)", rel.rsplit("/", 1)[-1])
        number = numbered.group(1) if numbered else rel.rsplit("/", 1)[-1][:-3]
        title = (numbered.group(2) if numbered and numbered.lastindex and numbered.lastindex >= 2 else "") or heading
        status = ""
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if re.match(r"^#{2,4}\s+status\s*$", line.strip(), re.I):
                status = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
                break
            inline = re.match(r"^(?:#{2,4}\s+)?\**\s*status\s*:?\s*\**\s*:?\s*(\S.*)$", line.strip(), re.I)
            if inline:
                status = inline.group(1)
                break
        boxes = leaves(parse_checkboxes(text))
        entries.append({"number": number, "title": headline(clean(title) or number, limit=100, cut_at_colon=False),
                        "status": bmad_status(status), "path": rel,
                        "tasks": (f" · {sum(1 for b in boxes if b['state'] == 'done')} of {len(boxes)} tasks done"
                                  if boxes else "")})
    if not entries:
        for rel in sprint:
            in_block = False
            for line in (folder.text(rel) or "").splitlines():
                if re.match(r"^development_status:\s*$", line):
                    in_block = True
                    continue
                if in_block and line and not line.startswith((" ", "\t")):
                    in_block = False
                pair = re.match(r"^\s+([\w.-]+):\s*([\w-]+)", line) if in_block else None
                if pair and re.match(r"^\d+-\d+-", pair.group(1)):
                    number = ".".join(pair.group(1).split("-")[:2])
                    words = " ".join(pair.group(1).split("-")[2:])
                    entries.append({"number": number, "title": words[:1].upper() + words[1:], "path": rel,
                                    "status": bmad_status(pair.group(2)), "tasks": ""})
    epics: dict[str, list[int]] = {}
    epic_rows: dict[str, list[dict]] = {}
    for entry in sorted(entries, key=lambda e: natural(e["number"])):
        status, key, label = entry["status"], f"story:{entry['number']}", entry["number"]
        epic = f"Epic {entry['number'].split('.')[0]}"
        tally = epics.setdefault(epic, [0, 0])
        tally[1] += 1
        if status == "done":
            tally[0] += 1
            group, state, detail = "done", "done", "Done"
        elif status in ("review", "doing"):
            group, state, detail = "now", "doing", "In review" if status == "review" else "In progress"
        elif status == "ready":
            group, state, detail = "next", "ready", "Approved, ready to start"
        elif status == "draft":
            group, state, detail = "next", "todo", "Draft: waiting for approval"
        else:
            group, state, detail = "next", "todo", "In the backlog"
        board.add(group, key, label, entry["title"], detail + entry["tasks"], entry["path"], you=status == "draft")
        epic_rows.setdefault(epic, []).append(road_row(key, label, entry["title"], state, detail + entry["tasks"],
                                                       entry["path"]))
    for epic, (done, total) in epics.items():
        board.stage(epic, done, total, "stories")
        board.road_stage(epic, "all done" if total and done == total else "", epic_rows.get(epic, []))
    board.legend = {"ready": "Approved, ready to start", "todo": "Draft or in the backlog"}
    folder.plan_found = folder.plan_found or bool(entries)
    prd = next((f for f in ("docs/prd.md", "docs/PRD.md") if f in folder.file_set), None) \
        or next((f for f in folder.under("docs/prd")), None)
    architecture = next((f for f in ("docs/architecture.md",) if f in folder.file_set), None) \
        or next((f for f in folder.under("docs/architecture")), None)
    if prd and not architecture:
        board.add("missing", "bmad:architecture", "BMAD", "No architecture document yet",
                  "BMAD's architect writes it after the PRD.", prd)
    board.found = f"{plural(len(entries), 'story', 'stories')} in {plural(len(epics), 'epic')}"
    board.set_up("bmad", "plan", f"BMAD Method: {plural(len(entries), 'story', 'stories')}",
                 "Stories with a status each" + (", a PRD" if prd else "") + (" and an architecture doc"
                                                                              if architecture else "") + ".",
                 story_dir if stories else (prd or ".bmad-core"))
    board.chips.append("BMAD")


# ---------------------------------------------------------------- notes: checklists, sections, known issues

INSTRUCTION_FILES = {"claude.md", "claude.local.md", "agents.md", "gemini.md", "conventions.md",
                     "copilot-instructions.md"}
NOT_NOTES = {"changelog.md", "changes.md", "history.md", "releases.md", "news.md", "license.md", "licence.md",
             "code_of_conduct.md", "code-of-conduct.md", "security.md"}


def note_files(folder: Folder, max_depth: int | None = None, instructions: bool = True) -> list[str]:
    found = []
    for rel in folder.files:
        low = rel.lower()
        name = low.rsplit("/", 1)[-1]
        if rel in folder.claimed or name in NOT_NOTES or "template" in low or low.startswith(".github/") \
                or in_fixtures(rel) or in_tests_or_examples(rel):
            continue
        if not (name.endswith((".md", ".markdown", ".mdx"))
                or (name.endswith(".txt") and re.search(r"todo|task|checklist", name))):
            continue
        if not instructions and (name in INSTRUCTION_FILES or low.startswith((".claude/", ".cursor/", ".windsurf/",
                                                                              ".clinerules", ".kiro/"))):
            continue
        if max_depth is not None and rel.count("/") > max_depth:
            continue
        found.append(rel)
    found.sort(key=lambda r: (r.count("/"), r.lower()))
    return found[:MAX_NOTES]


TODO_NAME = re.compile(r"^(todo|to-do|to_do|todos|tasks?|next|next[-_ ]steps|plan)\.(md|markdown|txt)$", re.I)


def plain_tasks(text: str, lines_are_tasks: bool) -> list[dict]:
    """A to-do list written without boxes: its list items (or, in a .txt, its lines). "x " at the start (the
    todo.txt way), "[x]", "✓" or "DONE" marks one done."""
    tasks: list[dict] = []
    heading = ""
    for number, line in md_lines(text):
        found = HEADING.match(line)
        if found:
            heading = strip_parens(clean(found.group(2)))
            continue
        item = BULLET.match(line)
        if item and len(item.group(1).expandtabs(4)) == 0:
            body = item.group(2)
        elif lines_are_tasks and line.strip() and not line.startswith((" ", "\t")):
            body = line.strip()
        else:
            continue
        done = re.match(r"^(?:x\s+(?:\d{4}-\d{2}-\d{2}\s+)?|\[x\]\s*|[✓✔✅]\s*|done[:\s-]+|~~)", body, re.I)
        body = re.sub(r"^\([A-Z]\)\s+", "", body[done.end():] if done else body).strip(" ~")  # "(A) " priority
        if body:
            tasks.append({"indent": 0, "state": "done" if done else "todo", "text": clean(body),
                          "heading": heading, "line": number, "parent": None, "children": 0, "doneDay": None})
    return tasks


def read_checklists(folder: Folder, board: Board) -> None:
    lists = tasks_total = 0
    rows = []
    for rel in note_files(folder):
        text = folder.text(rel) or ""
        counted = [t for t in leaves(parse_checkboxes(text)) if t["state"] != "skipped"] if "[" in text else []
        if not counted and TODO_NAME.match(rel.rsplit("/", 1)[-1]):
            counted = plain_tasks(text, rel.lower().endswith(".txt"))  # "todo.txt": a list without boxes
        if not counted:
            continue
        if rel.rsplit("/", 1)[-1].lower() in INSTRUCTION_FILES and not any(t["state"] == "done" for t in counted):
            continue  # a checklist in AGENTS.md that nobody ticks is a rule for pull requests, not work
        lists += 1
        tasks_total += len(counted)
        name = display(rel)
        finished = sum(1 for t in counted if t["state"] == "done")
        title = first_heading(text) or rel.rsplit("/", 1)[-1]
        label = shorten(rel.rsplit("/", 1)[-1], 22)
        procedure = bool(re.search(r"checklist|template|release|runbook|procedure", rel.rsplit("/", 1)[-1], re.I))
        board.stage(name, finished, len(counted), "tasks", primary=not (folder.plan_found or procedure))
        rows.append(road_row(f"list:{rel}", label, title,
                             progress_state(finished, len(counted), any(t["state"] == "doing" for t in counted)),
                             f"{finished} of {len(counted)} ticked", rel, done=finished, total=len(counted)))
        if folder.plan_found or procedure:  # the plan comes first; a checklist is one line with its progress
            group = "done" if finished == len(counted) else "now" if finished else "next"
            board.add(group, f"list:{rel}", label, title, f"A checklist: {finished} of {len(counted)} ticked", rel)
            continue
        shown = {"next": 0, "done": 0}
        hidden = {"next": 0, "done": 0}
        for task in counted:
            where = f"In {name}" + (f" › {task['heading']}" if task["heading"] else "")
            if task["parent"]:
                where += f" · part of “{shorten(task['parent'], 60)}”"
            key = f"task:{rel}:{norm(task['text'])}"
            task_title = headline(task["text"], limit=110, cut_at_colon=False)
            group = {"todo": "next", "doing": "now", "done": "done"}[task["state"]]
            if group in shown and shown[group] >= SHOW:
                hidden[group] += 1
                continue
            if group in shown:
                shown[group] += 1
            board.add(group, key, label, task_title, ("In progress · " if group == "now" else "") + where, rel,
                      task["doneDay"])
        for group, count in hidden.items():
            if count:
                board.more(group, f"{rel}:{group}", count, "open tasks" if group == "next" else "done tasks", rel)
    board.road_stage("Checklists", "", rows)
    if lists:
        board.found = f"{plural(tasks_total, 'task')} in {plural(lists, 'note')}"
        board.set_up("checklists", "plan", f"To-do lists: {plural(tasks_total, 'task')} in {plural(lists, 'note')}",
                     "“- [ ]” boxes in notes (“- [x]” is done), or a plain list in a file called TODO or todo.txt "
                     "(“x ” in front is done).", None)
        board.chips.append("Checklists")


SECTION_CLASSES = [
    ("now", {"in progress", "work in progress", "wip", "currently working on", "current work", "current focus",
             "current work focus", "active work", "active tasks", "doing", "now", "right now", "this week",
             "this sprint", "current sprint", "current task", "current tasks", "working on", "active context"}),
    ("next", {"next", "next steps", "next step", "next up", "up next", "what's next", "whats next", "what is next",
              "to do", "todo", "todos", "to-do", "to-dos", "to do list", "todo list", "planned", "backlog",
              "upcoming", "what's left", "what's left to build", "whats left", "what is left", "left to do",
              "remaining", "remaining work", "remaining tasks", "open tasks", "roadmap", "future work",
              "coming soon", "next milestone", "next milestones", "not done yet", "still to do"}),
    ("known", {"known issues", "known bugs", "known problems", "known limitations", "limitations", "caveats",
               "bugs", "issues", "open issues", "problems", "tech debt", "technical debt", "known gaps", "gaps",
               "workarounds"}),
    ("could", {"open questions", "questions", "unknowns", "risks", "concerns", "to verify", "needs checking",
               "needs verification", "needs review", "to check", "unresolved", "decisions needed", "to decide"}),
    ("done", {"done", "completed", "complete", "finished", "shipped", "what works", "recent changes",
              "recently done", "recently completed", "recently fixed", "accomplished", "progress so far"}),
]


def section_class(heading: str) -> str | None:
    text = clean(heading).lower().replace("’", "'")
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = re.sub(r"^[^a-z]+", "", text)  # "2. ", "🚧 ", "✅ "
    text = re.sub(r"[\s:.!?—–-]+$", "", text).strip()
    for group, names in SECTION_CLASSES:
        if text in names:
            return group
    return None


def read_sections(folder: Folder, board: Board) -> None:
    notes = sections = 0
    for rel in [f for f in note_files(folder, max_depth=1, instructions=False) if f.count("/") == 0
                or f.lower().startswith(("docs/", "doc/", "memory-bank/"))][:200]:
        text = folder.text(rel) or ""
        if "#" not in text:
            continue
        active: tuple[int, str, str] | None = None  # heading level, group, heading
        base: int | None = None
        current = None
        count = 0
        for _, line in md_lines(text):
            found = HEADING.match(line)
            if found:
                level, group = len(found.group(1)), section_class(found.group(2))
                if group:
                    active, base, current, count = (level, group, clean(found.group(2)).rstrip(":")), None, None, 0
                    sections += 1
                elif active and level <= active[0]:
                    active, current = None, None
                continue
            if not active:
                continue
            bullet = BULLET.match(line)
            if bullet and not CHECKBOX.match(line):
                indent = len(bullet.group(1).expandtabs(4))
                if base is None:
                    base = indent
                if indent <= base:
                    count += 1
                    if count > 25:
                        continue
                    current = {"text": bullet.group(2)}
                    key = f"note:{rel}:{norm(current['text'])}"
                    board.add(active[1], key, shorten(rel.rsplit("/", 1)[-1], 22), headline(current["text"]),
                              f"Under “{active[2]}” in {display(rel)}", rel)
                    notes += 1
            elif current and line.startswith((" ", "\t")) and line.strip() and not bullet:
                pass  # a wrapped line of the same point: its title already came from the first line
    if notes:
        board.found = f"{plural(notes, 'note')} under {plural(sections, 'heading')}"


ISSUE_FILES = ("known-issues.md", "known_issues.md", "knownissues.md", "known-bugs.md", "known_bugs.md", "bugs.md",
               "issues.md", "known-problems.md", "problems.md", "limitations.md", "known-limitations.md")


def parse_issue_list(text: str) -> list[dict]:
    """A known-issues note: "## Area" headings, one top-level bullet per problem, sub-points under it."""
    issues: list[dict] = []
    area, current, base = "", None, None
    for _, line in md_lines(text):
        found = HEADING.match(line)
        if found:
            area = "" if len(found.group(1)) == 1 else strip_parens(clean(found.group(2))).rstrip(":")
            current, base = None, None
            continue
        bullet = BULLET.match(line)
        if bullet:
            indent = len(bullet.group(1).expandtabs(4))
            if base is None or indent <= base:
                base = indent if base is None else min(base, indent)
                current = {"area": area, "lines": [bullet.group(2)]}
                issues.append(current)
            elif current:
                current["lines"].append(bullet.group(2))
        elif current and line.strip() and line.startswith((" ", "\t")):
            current["lines"][-1] += " " + line.strip()
        elif line.strip():
            current = None  # a paragraph ends the list
    return issues


def read_issues(folder: Folder, board: Board) -> None:
    files = [f for f in folder.named(*ISSUE_FILES, depth=2) if f not in folder.claimed]
    total = 0
    for rel in files:
        folder.claim([rel])
        for issue in parse_issue_list(folder.text(rel) or ""):
            first = issue["lines"][0]
            ticked = re.match(r"^\[([ xX])\]\s+(.*)$", first)
            if ticked:
                first = ticked.group(2)
            bold = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", first)
            lead = clean(bold.group(1)) if bold else ""
            prefix = ""
            if bold and lead.endswith(":") and bold.group(2).strip():
                prefix = strip_parens(lead.rstrip(":"))  # "Step 11 (RPC):" labels the problem that follows
                title = headline(bold.group(2))
            else:
                title = headline(bold.group(1) if bold and len(lead) > 12 else first)
            if lead.lower().startswith("fixed") and bold and bold.group(2):
                title = headline(bold.group(2))
            everything = clean(" ".join(issue["lines"]))
            subs = [clean(line) for line in issue["lines"][1:]]
            decide = next((s for s in subs if re.match(r"^(decide|decision|needs (a )?decision)\b", s, re.I)), "")
            proposal = next((s for s in subs if re.match(r"^(proposed( fix)?|fix|workaround)\b", s, re.I)), "")
            area = issue["area"]
            fixed = bool(ticked and ticked.group(1) in "xX") or bool(re.search(r"\b(fixed|resolved|closed)\b",
                                                                              area, re.I))
            to_confirm = lead.lower().startswith("fixed") and re.search(r"confirm|verify|check", lead, re.I)
            key = f"issue:{norm(clean(first))}"
            label = shorten(area or display(rel), 22)
            if fixed or (lead.lower().startswith("fixed") and not to_confirm):
                board.add("done", key, label, title, "Fixed", rel)
            elif to_confirm:
                board.add("could", key, label, title, "Fixed, waiting to be confirmed: " + lead, rel)
            else:
                needs_you = bool(decide) or bool(re.search(r"\bneeds?\b.*\b(decision|decide|owner|you)\b"
                                                           r"|\bowner'?s (decision|call)\b|\bto decide\b", area, re.I))
                detail = decide or proposal or ""
                if needs_you and not decide:
                    detail = "Needs your decision" + (f" · {detail}" if detail else "")
                if prefix:
                    detail = prefix + (f" · {detail}" if detail else "")
                group = "could" if SUSPECT.search(everything) else "known"
                board.add(group, key, label, title, detail[:240], rel, you=needs_you)
            total += 1
    if total:
        board.found = f"{plural(total, 'problem')} in {', '.join(files)}"


# ---------------------------------------------------------------- the CHANGELOG

CHANGELOG_NAMES = ("changelog.md", "changelog", "changes.md", "history.md", "releases.md", "news.md",
                   "release-notes.md", "release_notes.md", "changelog.txt")
CATEGORY_WORDS = {"added", "changed", "deprecated", "removed", "fixed", "fixes", "security", "features",
                  "new features", "bug fixes", "improvements", "performance", "breaking changes", "breaking",
                  "documentation", "docs", "other", "misc", "miscellaneous", "chores", "chore", "refactor",
                  "refactoring", "tests", "build", "ci", "dependencies", "deps", "internal", "highlights", "notes",
                  "upgrade notes", "known issues", "enhancements", "bugfixes", "new", "updates", "minor changes",
                  "patch changes", "major changes", "fixed bugs", "new features", "breaking", "deprecations"}
VERSION = re.compile(r"^(?:(?:new in|what's new in|version|release|released)\s+)?\[?v?(\d+(?:\.\d+){1,3}"
                     r"(?:[-+][0-9A-Za-z.]+)?)\]?(?=\s|$|[:—–(,-])", re.I)
IN_PROGRESS = re.compile(r"\b(in progress|unreleased|not released|upcoming|wip|draft)\b", re.I)


def changelog_files(folder: Folder) -> list[str]:
    return [f for f in folder.named(*CHANGELOG_NAMES, depth=1) if "/" not in f or f.lower().startswith(("docs/",
                                                                                                       "doc/"))]


def changelog_headings(text: str) -> list[dict]:
    headings: list[dict] = []
    for _, line in md_lines(text):
        found = HEADING.match(line)
        if found:
            headings.append({"level": len(found.group(1)), "text": clean(found.group(2)), "bullets": 0})
        elif headings and BULLET.match(line):
            headings[-1]["bullets"] += 1
    return headings


def category_key(text: str) -> str:
    return re.sub(r"[^a-z ]+", "", text.lower()).strip()


def read_changelog(folder: Folder, board: Board) -> None:
    files = changelog_files(folder)
    if not files:
        return
    rel = files[0]
    headings = changelog_headings(folder.text(rel) or "")
    seen: dict[str, int] = {}
    for heading in headings:
        if not VERSION.match(heading["text"]):
            seen[category_key(heading["text"])] = seen.get(category_key(heading["text"]), 0) + 1
    repeated = {key for key, count in seen.items() if count > 1}  # "Features" under every release: a category
    releases = entries = 0
    pending: dict | None = None
    unreleased_sections: list[dict] = []
    for index, heading in enumerate(headings):
        text = heading["text"]
        unreleased = re.match(r"^\[?(unreleased|upcoming|next)\]?\s*$", text, re.I)
        if heading["level"] == 1 and index == 0 and not VERSION.match(text) and not unreleased:
            continue  # the file's title
        version = VERSION.match(text)
        if unreleased or (version and IN_PROGRESS.search(text)):
            name = version.group(1) if version else None
            pending = {"key": f"changelog:{norm(name or 'unreleased')}", "name": name, "entries": 0,
                       "bullets": heading["bullets"]}
            unreleased_sections.append(pending)
            board.add("now", pending["key"], "changelog", f"Version {name} is in progress" if name
                      else "Changes not released yet", "", rel)
            continue
        if version:
            pending = None
            releases += 1
            if releases <= 20:
                board.add("done", f"changelog:{norm(version.group(1))}", "release", f"Released {version.group(1)}",
                          "Done", rel, iso_day(text))
            continue
        category = category_key(text) in CATEGORY_WORDS or category_key(text) in repeated
        if pending is not None:
            pending["bullets"] += heading["bullets"]
            if not category:
                pending["entries"] += 1
        if heading["level"] < 2 or category or norm(text) in folder.changelog_used:
            continue
        entries += 1
        if entries <= 60:
            board.add("done", f"changelog:{norm(strip_parens(text))}", "changelog",
                      headline(strip_parens(text), limit=90, cut_at_colon=False), "In the CHANGELOG", rel,
                      iso_day(text))
    for section in unreleased_sections:
        item = next((i for i in board.items if i["key"] == section["key"]), None)
        if item is None:
            continue
        if section["entries"]:
            item["detail"] = f"{plural(section['entries'], 'entry', 'entries')} in the CHANGELOG so far"
        elif section["bullets"]:
            item["detail"] = f"{plural(section['bullets'], 'change')} written down so far"
        else:
            board.items.remove(item)  # an empty "Unreleased" heading: nothing waiting
    parts = [plural(releases, "release")] if releases else []
    if entries:
        parts.append(plural(entries, "entry", "entries"))
    board.found = ", ".join(parts) or "nothing new"


# ---------------------------------------------------------------- code, tests, logs, basics

CODE_NOTE = re.compile(r"(?:^|[\s(;{,])(?:#+|//+|/\*+|\*|--|;+|<!--)\s*(TODO|FIXME|FIX ME|HACK|XXX|BUG|BUGBUG)\b"
                       r"\s*(?:\([^)]*\))?\s*[:\-–—]?\s*(.*)$")
MARKED = re.compile(r"\b(TODO|FIXME|FIX ME|HACK|XXX|BUG|BUGBUG)\b|#warning")
MARKED_LINE = re.compile(r"^.*(?:\b(?:TODO|FIXME|FIX ME|HACK|XXX|BUG|BUGBUG)\b|#warning).*$", re.M)
WARNING_NOTE = re.compile(r"^\s*#warning\s*\(?\s*\"?(.*?)\"?\s*\)?\s*$")


def is_code(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return (os.path.splitext(name)[1].lower() in CODE_EXT or name in CODE_NAMES) \
        and not re.search(r"\.min\.(js|css)$|\.generated\.|_pb2\.py$|\.pb\.\w+$", name)


def read_code_notes(folder: Folder, board: Board) -> None:
    todos: list[tuple] = []
    problems: list[tuple] = []
    files_with = scanned = 0
    for rel in folder.files:
        if scanned >= MAX_CODE_FILES or not folder.slow_time_left():
            break
        if rel in folder.claimed or not is_code(rel) or in_fixtures(rel):
            continue
        scanned += 1
        text = folder.text(rel, MAX_CODE_BYTES, keep=False)
        if not text or "\0" in text[:2000]:
            continue
        folder.secret_scan[rel] = secret_hits(text)  # one read of each file serves both readers
        if not MARKED.search(text):
            continue
        before = len(todos) + len(problems)
        for marked in MARKED_LINE.finditer(text):
            line = marked.group(0)
            number = text.count("\n", 0, marked.start()) + 1
            found = CODE_NOTE.search(line)
            lead = line[:found.start()] if found else ""
            if found and (lead.count('"') % 2 or lead.count("'") % 2 or lead.count("`") % 2):
                found = None  # the marker is inside a string ("# TODO" in a test's sample text), not a comment
            if found:
                marker = found.group(1).replace("FIX ME", "FIXME").replace("BUGBUG", "BUG")
                note = re.sub(r"\s*(\*/|-->)\s*$", "", found.group(2).split("\\n")[0]).strip()
                (todos if marker == "TODO" else problems).append((marker, note, rel, number))
                continue
            warned = WARNING_NOTE.match(line) if rel.endswith((".swift", ".c", ".h", ".m", ".mm")) else None
            if warned:
                problems.append(("#warning", warned.group(1).strip(), rel, number))
        if len(todos) + len(problems) > before:
            files_with += 1
    for group, notes, what in (("missing", todos, "TODO notes"), ("could", problems, "FIXME / HACK notes")):
        for marker, note, rel, number in notes[:60]:
            title = headline(note, limit=100, cut_at_colon=False) if note else f"{marker} (no note written)"
            board.add(group, f"code:{rel}:{norm(note) or marker.lower()}", marker, title, f"{rel}, line {number}",
                      rel)
        if len(notes) > 60:
            board.more(group, f"code:{group}", len(notes) - 60, what, ".")
    if todos or problems:
        board.found = f"{len(todos)} TODO, {len(problems)} FIXME/HACK in {plural(files_with, 'file')}"


def read_failed_tests(folder: Folder, board: Board) -> None:
    caches = [folder.root / ".pytest_cache"]
    try:
        caches += [entry.path and Path(entry.path) / ".pytest_cache" for entry in os.scandir(folder.root)
                   if entry.is_dir(follow_symlinks=False) and entry.name not in SKIP_DIRS
                   and not entry.name.startswith(".")]
    except OSError:
        pass
    head = folder.git.get("head") if folder.git.get("ok") else None
    committed = dt.datetime.fromisoformat(head["date"]).timestamp() if head else None
    failed_total = 0
    for cache in caches:
        record = cache / "v" / "cache" / "lastfailed"
        try:
            failed = [k for k, v in json.loads(record.read_text(encoding="utf-8")).items() if v]
            stamp = record.stat().st_mtime
        except (OSError, ValueError, AttributeError):
            continue
        if not failed or (committed and committed > stamp):
            continue  # nothing failed, or a commit came after the failing run
        where = os.path.relpath(cache.parent, folder.root).replace(os.sep, "/")
        names = ", ".join(f.split("::")[-1] for f in failed[:2]) + (f" and {len(failed) - 2} more"
                                                                     if len(failed) > 2 else "")
        first_file = failed[0].split("::")[0]
        path = f"{where}/{first_file}" if where != "." else first_file
        board.add("could", f"tests:pytest:{where}", "pytest",
                  f"{plural(len(failed), 'test')} failed the last time pytest ran"
                  + (f" in {where}/" if where != "." else ""),
                  names + (" · after the last commit" if committed else ""),
                  path if folder.exists(path) else (where if where != "." else None), iso(stamp))
        failed_total += len(failed)
    if failed_total:
        board.found = plural(failed_total, "failed test")


LOG_ERROR = re.compile(r"\b(?:ERROR|CRITICAL|FATAL)\b|Traceback \(most recent call last\)"
                       r"|^\s*(?:[\w.]+\.)?[A-Z]\w*(?:Error|Exception)\b:|\bpanic: |\bUnhandled(?:PromiseRejection| exception)")


def read_logs(folder: Folder, board: Board) -> None:
    candidates = {f for f in folder.files if f.endswith(".log")}
    for extra in ("", "logs", "log"):  # logs are usually ignored by git, so look for them too
        try:
            for entry in os.scandir(folder.root / extra if extra else folder.root):
                if entry.name.endswith(".log") and entry.is_file():
                    candidates.add(f"{extra}/{entry.name}" if extra else entry.name)
        except OSError:
            continue
    cutoff = folder.now.timestamp() - LOG_DAYS * 86400
    recent = sorted(((folder.mtime(rel) or 0, rel) for rel in candidates), reverse=True)
    with_errors = 0
    for stamp, rel in recent[:12]:
        if stamp < cutoff or not folder.slow_time_left():
            break
        try:
            with (folder.root / rel).open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 512_000))
                tail = handle.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        errors = [line for line in tail.splitlines() if LOG_ERROR.search(line)]
        if not errors:
            continue
        telling = [line for line in errors if not line.strip().startswith("Traceback")] or errors  # the error itself
        with_errors += 1
        board.add("could", f"log:{rel}", "log", f"{display(rel)}: {plural(len(errors), 'error line')}"
                  + (" in its newest 500 KB" if size > 512_000 else ""),
                  "Newest: " + shorten(clean(telling[-1]), 180), rel, iso(stamp))
    if with_errors:
        board.found = f"{plural(with_errors, 'log')} with errors"


SECRETS = [
    ("an Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}")),
    ("an OpenAI key", re.compile(r"\bsk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,}")),
    ("a GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{50,}")),
    ("an AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("a Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{34,}\b")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}")),
    ("a Stripe secret key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}")),
    ("a private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----[ \t]*\r?\n"
                                 r"(?:Proc-Type:|[A-Za-z0-9+/=]{40,})")),  # the key's body follows, not just its name
]
SECRET_EXT = CODE_EXT | {".env", ".json", ".ini", ".cfg", ".txt", ".md", ".ipynb", ".xcconfig", ".properties",
                         ".conf", ".pem", ".key"}


SECRET_HINT = re.compile(r"sk-|gh[pousr]_|github_pat_|AKIA|AIza|hf_|xox[abprs]-|_live_|PRIVATE KEY")


def secret_hits(text: str) -> list[tuple[str, int]]:
    """The kinds of key written in a text, with the line of the first of each (the key itself is never kept)."""
    if not SECRET_HINT.search(text):
        return []
    hits = []
    for kind, pattern in SECRETS:
        match = next((m for m in pattern.finditer(text) if kind == "a private key" or looks_real(m.group(0))), None)
        if match:
            hits.append((kind, text.count("\n", 0, match.start()) + 1))
    return hits


def looks_real(token: str) -> bool:
    """A made-up key ("sk-xxxxxxxx…", "ghp_1234567890…", "sk-your-key-here…") repeats itself or counts up; a real
    one is a jumble."""
    body = re.sub(r"^[a-z]+[-_](?:ant-|proj-|svcacct-|admin-|pat_)?", "", token, flags=re.I)
    if len(set(body)) < 12 or re.search(r"x{6,}|0{6,}|your|example|dummy|fake|placeholder|redacted|test|sample",
                                        token, re.I):
        return False
    run = 1
    for before, after in zip(body, body[1:]):
        run = run + 1 if ord(after) == ord(before) + 1 else 1
        if run >= 5:  # "12345", "abcde": typed by a person, not made by a key generator
            return False
    return True


def read_secrets(folder: Folder, board: Board) -> None:
    tracked = set((git(folder.root, "ls-files", "-z") or "").split("\0")) if folder.in_git else set()
    remote = bool((git(folder.root, "remote") or "").strip()) if folder.in_git else False
    found = 0
    for rel in folder.files:
        if found >= 20 or not folder.slow_time_left():
            break
        name = rel.rsplit("/", 1)[-1]
        ext = os.path.splitext(name)[1].lower() or (".env" if name.startswith(".env") else "")
        if rel in folder.secret_scan:
            hits = folder.secret_scan[rel]
        else:
            if ext not in SECRET_EXT or in_fixtures(rel) or rel.endswith(("package-lock.json", "yarn.lock", ".min.js")):
                continue
            text = folder.text(rel, 200_000, keep=False)
            hits = secret_hits(text) if text and "\0" not in text[:2000] else []
        for kind, line in hits[:1]:
            in_git = rel in tracked
            board.add("could", f"secret:{rel}:{norm(kind)}", "secret", f"{kind[0].upper() + kind[1:]} seems to be "
                      f"written in {display(rel)}",
                      f"Line {line}. A key belongs in a private settings file (like .env) that isn't shared."
                      + (" This file is in git" + (", and the repo is pushed somewhere, so the key may already be "
                                                   "online: replace it." if remote else ".") if in_git else ""),
                      rel, you=True)
            found += 1
    env_in_git = sorted(f for f in tracked if re.match(r"^(.*/)?\.env(\.[\w-]+)?$", f)
                        and not re.search(r"\.(example|sample|template|dist)$", f) and not in_fixtures(f)
                        and not in_tests_or_examples(f))
    for rel in env_in_git[:5]:
        board.add("could", f"secret:env:{rel}", "secret", f"{display(rel)} is in git",
                  "A .env file usually holds private keys. Add it to .gitignore and keep it off GitHub.", rel,
                  you=True)
    if found or env_in_git:
        board.found = plural(found + len(env_in_git[:5]), "possible key", "possible keys") + " (never shown)"


COPY_OF = re.compile(r"^(?P<base>.+?)(?:\s+copy(?:\s+\d+)?|\s*\((?:\d+|[^)]*cop(?:y|ie)[^)]*)\)|\s+\d"
                     r"|[-_ ](?:final|old|backup|bak|orig|copy|new|latest|fixed|working)(?:[-_ ]?\d+)?)+$", re.I)


def read_copies(folder: Folder, board: Board) -> None:
    """ "app (1).py", "app_final.py", "app old.py" next to "app.py": which one is the real one?"""
    groups: dict[tuple[str, str], list[str]] = {}
    for rel in folder.files:
        if in_fixtures(rel):
            continue
        parent, _, name = rel.rpartition("/")
        stem, ext = os.path.splitext(name)
        if ext.lower() in (".bak", ".orig") and "." in stem:  # "app.py.bak"
            stem, ext = os.path.splitext(stem)
        copy = COPY_OF.match(stem)
        base = copy.group("base").strip() if copy else stem
        groups.setdefault((parent, (base + ext).lower()), []).append(rel)
    shown = 0
    for (parent, _), files in sorted(groups.items()):
        copies = [f for f in files if COPY_OF.match(os.path.splitext(f.rsplit("/", 1)[-1])[0])
                  or f.endswith((".bak", ".orig"))]
        if not copies or len(files) < 2:
            continue
        names = ", ".join(f.rsplit("/", 1)[-1] for f in sorted(files, key=natural))
        board.add("could", f"copies:{parent}/{os.path.splitext(copies[0].rsplit('/', 1)[-1])[0]}", "copies",
                  f"{len(files)} versions of the same file" + (f" in {parent}/" if parent else ""),
                  f"{names}. Which one is the real one? Old copies next to it make it easy to edit the wrong file.",
                  parent or ".")
        shown += 1
        if shown >= 15:
            break
    if shown:
        board.found = plural(shown, "set of copies", "sets of copies")


def test_files(folder: Folder) -> list[str]:
    return [f for f in folder.files if TEST_FILE.search(f) and is_code(f) and f not in folder.claimed]


def read_basics(folder: Folder, board: Board) -> None:
    top = {f.lower() for f in folder.files if "/" not in f}
    if not any(name.startswith("readme") for name in top):
        board.add("missing", "basic:readme", "README", "No README",
                  "A short README says what this is and how to run it, for others and for future you.", ".")
    code = [f for f in folder.files if is_code(f) and os.path.splitext(f)[1].lower() in LANGUAGES]
    if len(code) >= 3 and not test_files(folder):
        board.add("missing", "basic:tests", "tests", "No tests found",
                  "Pulse looked for test folders and files like test_*.py, *Tests.swift and *.test.js.", ".")
    if folder.in_git and ".gitignore" not in top:
        board.add("missing", "basic:gitignore", "git", "No .gitignore",
                  "Without one, build output and private files can end up in git.", ".")
    if not folder.in_git:
        board.add("missing", "basic:git", "git", "Not tracked by git",
                  "There's no history to go back to, so Pulse can't show commits or uncommitted work.", ".")
    missing = sum(1 for item in board.items if item["group"] == "missing")
    if missing:
        board.found = f"{missing} missing"


# ---------------------------------------------------------------- how it's set up

def count_in(folder: Path, suffixes: tuple = (".md", ".mdc")) -> int:
    try:
        return sum(1 for entry in os.scandir(folder) if entry.is_file() and entry.name.endswith(suffixes))
    except OSError:
        return 0


def line_count(folder: Folder, rel: str) -> int:
    return (folder.text(rel) or "").count("\n")


def safe_remote(url: str) -> str:
    """Where a repo is pushed, without any password or token that may be in the URL."""
    url = re.sub(r"^(\w+://)[^/@]*@", r"\1", url.strip())
    found = re.match(r"^(?:\w+://|git@)?([^/:]+)[:/](.+?)(?:\.git)?/?$", url)
    if not found:
        return ""
    host, where = found.group(1).lower(), found.group(2)
    names = {"github.com": "GitHub", "gitlab.com": "GitLab", "bitbucket.org": "Bitbucket", "codeberg.org": "Codeberg"}
    return f"{names[host]}: {where}" if host in names else host


def read_setup(folder: Folder) -> tuple[list[dict], list[dict], list[str]]:
    """How the project is set up: (the AI assistants' files, everything else, chips for the header)."""
    ai, other = Board(), Board()
    root, files = folder.root, folder.file_set
    chips: list[str] = []

    claude_files = [f for f in folder.files if f.rsplit("/", 1)[-1] == "CLAUDE.md"]
    dot_claude = root / ".claude"
    if claude_files or (dot_claude / "rules").is_dir() or (dot_claude / "commands").is_dir() \
            or (dot_claude / "settings.json").is_file() or (dot_claude / "agents").is_dir():
        parts = []
        if "CLAUDE.md" in files:
            parts.append(f"CLAUDE.md ({plural(line_count(folder, 'CLAUDE.md'), 'line')})")
        nested = len([f for f in claude_files if "/" in f])
        if nested:
            parts.append(f"{plural(nested, 'more CLAUDE.md', 'more CLAUDE.md files')} in subfolders")
        for sub, one in (("rules", "rule file"), ("commands", "command"), ("agents", "agent")):
            count = count_in(dot_claude / sub)
            if count:
                parts.append(plural(count, one))
        try:
            skills = sum(1 for entry in os.scandir(dot_claude / "skills") if (Path(entry.path) / "SKILL.md").is_file())
        except OSError:
            skills = 0
        if skills:
            parts.append(plural(skills, "skill"))
        try:
            settings = json.loads((dot_claude / "settings.json").read_text(encoding="utf-8"))
            hooks = sum(len(block.get("hooks") or []) for blocks in (settings.get("hooks") or {}).values()
                        for block in blocks if isinstance(block, dict))
        except (OSError, ValueError, AttributeError, TypeError):
            hooks = 0
        if hooks:
            parts.append(plural(hooks, "hook"))
        ai.set_up("claude", "AI", "Claude Code", " · ".join(parts) or "A .claude folder",
                  "CLAUDE.md" if "CLAUDE.md" in files else ".claude")
        chips.append("Claude Code")
    agents = [f for f in folder.files if f.rsplit("/", 1)[-1] == "AGENTS.md"]
    if agents:
        main = "AGENTS.md" if "AGENTS.md" in files else agents[0]
        ai.set_up("agents", "AI", "AGENTS.md", f"Instructions for Codex and other coding agents "
                  f"({plural(line_count(folder, main), 'line')})"
                  + (f" · {len(agents) - 1} more in subfolders" if len(agents) > 1 else ""), main)
        chips.append("AGENTS.md")
    simple = [
        ("gemini", "Gemini CLI", ["GEMINI.md"], "GEMINI.md: instructions for Gemini CLI"),
        ("cursor", "Cursor", [".cursorrules", ".cursor/rules"], "Cursor rules"),
        ("windsurf", "Windsurf", [".windsurfrules", ".windsurf/rules"], "Windsurf rules"),
        ("cline", "Cline", [".clinerules", "memory-bank"], "Cline rules and memory bank"),
        ("copilot", "Copilot", [".github/copilot-instructions.md", ".github/instructions", ".github/prompts",
                                ".github/chatmodes"], "GitHub Copilot instructions"),
        ("junie", "Junie", [".junie/guidelines.md"], "Junie guidelines"),
        ("roo", "Roo Code", [".roo", ".roomodes"], "Roo Code rules"),
        ("amazonq", "Amazon Q", [".amazonq/rules"], "Amazon Q rules"),
        ("aider", "Aider", ["CONVENTIONS.md", ".aider.conf.yml"], "Aider conventions"),
        ("continue", "Continue", [".continue/rules", ".continuerc.json"], "Continue rules"),
        ("zed", "Zed", [".rules"], "Zed rules"),
        ("opencode", "OpenCode", ["opencode.json", ".opencode"], "OpenCode setup"),
    ]
    for key, chip, paths, title in simple:
        present = [p for p in paths if (root / p).exists()]
        if present:
            counts = [f"{p} ({count_in(root / p)} files)" if (root / p).is_dir() else p for p in present]
            ai.set_up(key, "AI", title, " · ".join(counts), present[0])
            chips.append(chip)
    servers: list[str] = []
    for rel in (".mcp.json", ".cursor/mcp.json", ".vscode/mcp.json"):
        try:
            config = json.loads((root / rel).read_text(encoding="utf-8"))
            servers += list((config.get("mcpServers") or config.get("servers") or {}).keys())
        except (OSError, ValueError, AttributeError):
            continue
    if servers:
        ai.set_up("mcp", "AI", f"MCP servers: {', '.join(sorted(set(servers)))}",
                  "Tools the AI assistants can use in this project.", ".mcp.json" if (root / ".mcp.json").exists()
                  else None)
    if (root / ".obsidian").is_dir():
        ai.set_up("obsidian", "notes", "Obsidian vault", "This folder also opens as a vault in Obsidian.", None)

    # Docs.
    parts, docs_path = [], None
    readme = next((f for f in folder.files if "/" not in f and f.lower().startswith("readme")), None)
    if readme:
        parts.append(f"{readme} ({plural(line_count(folder, readme), 'line')})")
        docs_path = readme
    docs = [f for f in folder.files if f.lower().startswith(("docs/", "doc/")) and f.lower().endswith(".md")]
    if docs:
        parts.append(f"docs/: {plural(len(docs), 'note')}")
        docs_path = docs_path or "docs"
    changelog = changelog_files(folder)
    if changelog:
        parts.append(f"a changelog ({changelog[0]})")
    issues = folder.named(*ISSUE_FILES, depth=2)
    if issues:
        parts.append(f"a known-issues list ({issues[0]})")
    decisions = [f for f in folder.files if re.match(r"^(docs?/)?(adr|adrs|decisions)/", f, re.I)]
    if decisions:
        parts.append(plural(len(decisions), "decision record"))
    licence = next((f for f in folder.files if "/" not in f and re.match(r"^(licen[cs]e|copying)", f, re.I)), None)
    if licence:
        first = (folder.text(licence) or "").strip().split("\n", 1)[0].strip()
        parts.append(f"licence: {shorten(first, 40)}" if first else "a licence")
    if parts:
        other.set_up("docs", "docs", "Docs", " · ".join(parts), docs_path)

    # Code.
    languages: dict[str, int] = {}
    for rel in folder.files:
        language = LANGUAGES.get(os.path.splitext(rel)[1].lower())
        if language:
            languages[language] = languages.get(language, 0) + 1
    manifests = []
    for pattern, what in (("package.json", "Node.js package"), ("Package.swift", "Swift package"),
                          ("pyproject.toml", "Python project"), ("setup.py", "Python package"),
                          ("requirements.txt", "Python requirements"), ("Cargo.toml", "Rust crate"),
                          ("go.mod", "Go module"), ("Gemfile", "Ruby gems"), ("pom.xml", "Maven build"),
                          ("build.gradle", "Gradle build"), ("build.gradle.kts", "Gradle build"),
                          ("composer.json", "PHP package"), ("pubspec.yaml", "Flutter / Dart"),
                          ("CMakeLists.txt", "CMake build"), ("Makefile", "Makefile"), ("Dockerfile", "Docker"),
                          ("deno.json", "Deno")):
        for rel in folder.named(pattern, depth=2)[:1]:
            manifests.append(f"{what} ({rel})")
    xcode = sorted({f.split(".xcodeproj/")[0] + ".xcodeproj" for f in folder.files if ".xcodeproj/" in f})
    if xcode:
        manifests.append(f"Xcode project ({xcode[0]})")
    if languages or manifests:
        ranked = sorted(languages.items(), key=lambda kv: -kv[1])
        total = sum(languages.values())
        title = f"Code: {plural(total, 'file')}" + (f", mostly {ranked[0][0]}" if ranked else "")
        detail = " · ".join(f"{name} {count}" for name, count in ranked[:4])
        if manifests:
            detail += (" · " if detail else "") + "built with: " + ", ".join(manifests[:4])
        other.set_up("code", "code", title, detail, None)
        if ranked and ranked[0][1] >= 3:
            chips.append(ranked[0][0])

    # Tests and checks.
    tests = test_files(folder)
    if tests:
        kinds = []
        if any(f.endswith(".py") for f in tests):
            kinds.append("pytest" if folder.named("conftest.py", "pytest.ini") or "pytest" in (
                folder.text("pyproject.toml") or "") + (folder.text("engine/pyproject.toml") or "") else "Python")
        if any(f.endswith(".swift") for f in tests):
            kinds.append("Swift tests")
        if any(re.search(r"\.[cm]?[jt]sx?$", f) for f in tests):
            kinds.append("JavaScript tests")
        if any(f.endswith("_test.go") for f in tests):
            kinds.append("go test")
        other.set_up("tests", "tests", f"Tests: {plural(len(tests), 'file')}", ", ".join(kinds),
                     tests[0].rsplit("/", 1)[0] if "/" in tests[0] else tests[0])
    checks = []
    workflows = [f for f in folder.files if re.match(r"^\.github/workflows/[^/]+\.ya?ml$", f)]
    if workflows:
        checks.append(f"GitHub Actions ({', '.join(w.rsplit('/', 1)[-1] for w in workflows[:4])})")
    for rel, what in ((".gitlab-ci.yml", "GitLab CI"), (".circleci/config.yml", "CircleCI"),
                      ("azure-pipelines.yml", "Azure Pipelines"), ("Jenkinsfile", "Jenkins"),
                      ("bitbucket-pipelines.yml", "Bitbucket Pipelines"), (".travis.yml", "Travis CI")):
        if rel in files:
            checks.append(what)
    hooks = [f.rsplit("/", 1)[-1] for f in folder.files if f.startswith((".githooks/", ".husky/"))
             and not f.rsplit("/", 1)[-1].startswith((".", "_"))]
    if hooks:
        checks.append(f"git hooks ({', '.join(sorted(set(hooks))[:4])})")
    if ".pre-commit-config.yaml" in files:
        checks.append("pre-commit")
    linters = [name for rel, name in (("ruff.toml", "ruff"), (".ruff.toml", "ruff"), (".swiftlint.yml", "SwiftLint"),
                                      (".swiftformat", "SwiftFormat"), (".eslintrc.json", "ESLint"),
                                      ("eslint.config.js", "ESLint"), ("eslint.config.mjs", "ESLint"),
                                      (".prettierrc", "Prettier"), ("biome.json", "Biome"), ("mypy.ini", "mypy"),
                                      ("pyrightconfig.json", "Pyright"), (".golangci.yml", "golangci-lint"),
                                      (".rubocop.yml", "RuboCop"), ("rustfmt.toml", "rustfmt")) if rel in files]
    if linters:
        checks.append("linters: " + ", ".join(sorted(set(linters))))
    if checks:
        other.set_up("checks", "checks", "Checks", " · ".join(checks),
                     ".github/workflows" if workflows else None)

    # Git.
    facts = folder.git
    if facts.get("ok"):
        commits = (git(root, "rev-list", "--count", "HEAD") or "").strip()
        first = (git(root, "log", "--reverse", "--format=%cs", "--max-parents=0", "HEAD") or "").split("\n")[0]
        remote = safe_remote(git(root, "remote", "get-url", "origin") or "")
        detail = f"Branch {facts.get('branch')}"
        if commits.isdigit():
            detail += f" · {plural(int(commits), 'commit')}" + (f" since {first}" if first else "")
        other.set_up("git", "git", f"Git · {remote}" if remote else "Git (only on this Mac)", detail, None)
    if folder.partial:
        other.set_up("size", "size", f"A big folder: Pulse read the first {MAX_FILES:,} files",
                     "The rest isn't in this chart.", None)
    return ai.setup, other.setup, chips


# ---------------------------------------------------------------- putting it together

READERS = [
    ("git", "Git: work not committed, the branch, commits not pushed", read_git),
    ("steps", "A step list (a table of steps, or numbered step prompts)", read_steps),
    ("speckit", "Spec Kit (specs/…/tasks.md)", read_speckit),
    ("kiro", "Kiro specs (.kiro/specs)", read_kiro),
    ("taskmaster", "Task Master (tasks.json)", read_taskmaster),
    ("backlog", "Backlog.md (backlog/tasks)", read_backlog),
    ("bmad", "BMAD stories", read_bmad),
    ("issues", "A known-issues list", read_issues),
    ("checklists", "Checklists in notes (“- [ ]” and “- [x]”)", read_checklists),
    ("sections", "Sections such as “Next steps” or “Known issues” in notes", read_sections),
    ("changelog", "The CHANGELOG", read_changelog),
    ("codenotes", "TODO and FIXME notes in the code", read_code_notes),
    ("tests", "Tests that failed (pytest's last run)", read_failed_tests),
    ("secrets", "Keys and passwords written into files (never shown)", read_secrets),
    ("copies", "Copies of a file next to it (“app (1).py”, “app_final.py”)", read_copies),
    ("logs", "Errors in recent log files", read_logs),
    ("basics", "Missing basics (a README, tests, git)", read_basics),
]
SLOW = {"codenotes", "tests", "logs", "secrets"}  # skipped when turned off; the others always run, so they claim their files

GROUPS = [
    ("now", "Now", "Being worked on: tasks in progress, and changes not committed yet."),
    ("next", "Next steps", "What's left to do, in order: steps and tasks still open, and things waiting on you. A "
                           "step whose prompt is written shows the command that starts it."),
    ("could", "Could be problems", "Worth a look: FIXME notes, failed tests, errors in logs, blocked tasks, "
                                   "open questions."),
    ("known", "Known problems", "Problems already written down, parked for later."),
    ("missing", "Missing", "Not there yet: TODO notes in the code, plans or prompts not written, and basics such as "
                           "a README or tests."),
    ("done", "Done", "Finished work, newest first."),
    ("setup", "How it's set up", "How this project is organised: the files that guide AI assistants, its plan, docs, "
                                 "code, tests and checks."),
]


def read_folder(cfg: dict, now: dt.datetime, slug: str) -> dict:
    """Reads a folder that has no map: returns the project, with the view the app shows under "view"."""
    root = Path(cfg["path"]).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"can't find the project folder {root}")
    try:
        with os.scandir(root) as listing:
            next(listing, None)
    except PermissionError:
        raise PermissionError("macOS didn't let Pulse read this folder. Allow it in System Settings › Privacy & "
                              "Security › Files and Folders, then refresh.") from None
    started = time.monotonic()
    folder = folder_for(root, now)
    off = {str(name) for name in cfg.get("off", [])}
    items: list[dict] = []
    stages: list[dict] = []
    plan_setup: list[dict] = []
    chips: list[str] = []
    readers: list[dict] = []
    road: list[dict] = []
    later: list[dict] = []
    legend_words: dict[str, list[str]] = {}
    road_path = None
    for reader_id, name, reader in READERS:
        board = Board()
        on = reader_id not in off
        problem = None
        if on or reader_id not in SLOW:
            try:
                reader(folder, board)
            except Exception as error:  # one reader never stops the others
                problem = f"{type(error).__name__}: {error}"
        found_any = board.items or board.stages or board.setup or board.road or board.later
        readers.append({"id": reader_id, "name": name, "on": on,
                        "found": f"couldn't be read ({problem})" if problem
                        else "turned off" if not on
                        else (board.found or plural(len(board.items), "item")) if found_any else "nothing found"})
        plan_setup += board.setup
        chips += board.chips
        if on:
            items += board.items
            stages += board.stages
            road += board.road
            later += board.later
            road_path = road_path or board.road_path
            for state, words in board.legend.items():
                legend_words.setdefault(state, []).append(words)

    if "git" not in off and folder.git.get("ok") and not any(i["group"] == "done" for i in items):
        for commit in latest_commits(folder):
            items.append({"group": "done", "key": f"commit:{commit['short']}", "label": commit["short"],
                          "title": commit["subject"], "detail": "Committed", "path": None, "time": commit["date"],
                          "command": None, "you": False})
        commits_shown = True
    else:
        commits_shown = False
    ai_setup, other_setup, setup_chips = read_setup(folder)
    items += ai_setup + plan_setup + other_setup

    seen: dict[str, int] = {}
    for item in items:
        if item["key"] in seen:
            seen[item["key"]] += 1
            item["key"] = f"{item['key']}#{seen[item['key']]}"
        else:
            seen[item["key"]] = 1
        if item["path"]:
            item["path"] = str(root if item["path"] == "." else root / item["path"])
    by_group: dict[str, list[dict]] = {key: [] for key, _, _ in GROUPS}
    for item in items:
        group = item.pop("group")
        by_group[group].append(item)
    by_group["done"].sort(key=lambda item: item["time"] or "", reverse=True)
    for row in [r for stage in road for r in stage["rows"]] + later:
        if row.get("path"):
            row["path"] = str(root if row["path"] == "." else root / row["path"])

    counted = [s for s in stages if s.get("primary", True)] or stages
    done = sum(s["done"] for s in counted)
    total = sum(s["total"] for s in counted)
    units = {s["unit"] for s in counted}
    notes = []
    if folder.partial:
        notes.append(f"This folder is big: Pulse read its first {MAX_FILES:,} files.")
    if folder.slow_stopped:
        notes.append(f"Pulse stopped looking through the code and logs after {SLOW_SECONDS:.0f} seconds; "
                     "some notes may be missing.")
    head = folder.git.get("head") if folder.git.get("ok") else None
    unit = units.pop() if len(units) == 1 else "tasks"
    edits = [d for d in ((head or {}).get("date"), (folder.git.get("uncommitted") or {}).get("newestEdit"),
                         folder.newest_edit) if d]
    roadmap = roadmap_view(road, later, legend_words, done, total, unit, road_path and str(root / road_path))
    hints = {key: hint for key, _, hint in GROUPS}
    if commits_shown:
        hints["done"] = "No finished tasks found yet, so this shows the newest commits."
    view = {
        "name": cfg["name"],
        "slug": slug,
        "path": str(root),
        "kind": "auto",
        "home": home_summary(by_group, max(edits) if edits else None),
        "summary": {"stepsDone": done, "stepsTotal": total, "workDonePct": round(100 * done / total) if total else 0,
                    "unit": unit, "weighted": False},
        "stages": [{"name": s["name"], "done": s["done"], "total": s["total"]} for s in counted],
        "since": {"comparedWith": None, "changes": []},
        "lastCommit": {"short": head["short"], "subject": head["subject"], "date": head["date"]} if head else None,
        "layout": list(dict.fromkeys(setup_chips[:1] + chips + setup_chips[1:]))[:8],
        "readers": readers,
        "notes": notes,
        "roadmap": roadmap,
        "groups": [{"key": key, "title": title, "hint": hints[key], "items": by_group[key]}
                   for key, title, _ in GROUPS],
    }
    return {"kind": "auto", "name": cfg["name"], "slug": slug, "path": str(root), "git": folder.git,
            "view": view, "seconds": round(time.monotonic() - started, 2)}


def roadmap_view(road: list[dict], later: list[dict], legend_words: dict[str, list[str]], done: int, total: int,
                 unit: str, path: str | None) -> dict:
    """The Roadmap the app draws: tiles, what each colour means, every stage with its rows, and what comes after."""
    rows = [row for stage in road for row in stage["rows"]]
    seen = {row["state"] for row in rows}
    fallback = {"done": "Done", "doing": "In progress", "ready": "Ready to start", "todo": "Not started",
                "blocked": "Blocked"}
    legend = [{"state": state, "text": " · ".join(dict.fromkeys(legend_words.get(state, []))) or fallback[state]}
              for state in ("done", "doing", "ready", "todo", "blocked") if state in seen]
    sized = any(row["size"] for row in rows)
    word = unit.capitalize()
    tiles = [{"label": f"{word} done", "value": str(done), "suffix": f"of {total}"},
             {"label": f"{word} left", "value": str(total - done), "suffix": ""}]
    if sized:
        left = [row for row in rows if row["state"] != "done"]
        mix = [sum(1 for row in left if row["size"] == size) for size in "SML"]
        tiles.append({"label": "Mix left (S / M / L)", "value": " / ".join(map(str, mix)), "suffix": ""})
    tiles.append({"label": "Work done", "value": f"{round(100 * done / total) if total else 0}%", "suffix": ""})
    return {"path": path, "unit": unit, "sized": sized, "tiles": tiles, "legend": legend, "stages": road,
            "gatesTitle": None, "gatesNote": None, "gates": [], "errands": [],
            "laterTitle": later[0]["group"] if later else None, "later": later}


def setup_for(root: Path, now: dt.datetime) -> tuple[list[dict], list[str]]:
    """Just "How it's set up", for a project Pulse reads through its map (the rest comes from the map)."""
    folder = folder_for(root, now)
    ai_setup, other_setup, chips = read_setup(folder)
    items = []
    for item in ai_setup + other_setup:
        item = dict(item)
        item.pop("group", None)
        if item["path"]:
            item["path"] = str(root if item["path"] == "." else root / item["path"])
        items.append(item)
    return items, chips


# ---------------------------------------------------------------- "Since …"

GROUP_WORDS = {"now": "in progress", "next": "to do", "could": "could be a problem", "known": "a known problem",
               "missing": "missing", "done": "done"}
ID_LIKE = re.compile(r"^#?[A-Za-z]{0,6}[-_.]?\d[\w.-]{0,10}$")
CHANGE_ORDER = ["finished", "started", "ready", "added", "proposed", "progress", "parked", "warning", "cleared",
                "commit"]


def snapshot(project: dict) -> dict:
    """What a later refresh compares with: each item's group and title (not how it's set up, not commits)."""
    items = {}
    for group in project["view"]["groups"]:
        if group["key"] == "setup":
            continue
        for item in group["items"]:
            if not item["key"].startswith(("commit:", "more:")):
                items[item["key"]] = [group["key"], item["title"], item["label"]]
    head = (project.get("git") or {}).get("head") or {}
    return {"kind": "auto", "head": head.get("hash"), "items": items}


def compare(old: dict, new: dict, repo: Path | None) -> list[dict]:
    changes: list[dict] = []

    def note(kind: str, text: str, name: str | None = None) -> None:
        changes.append({"kind": kind, "text": text, **({"name": name} if name else {})})

    before, after = old.get("items", {}), new.get("items", {})
    for key, (group, title, label) in after.items():
        was = before.get(key)
        named = label if ID_LIKE.match(label or "") else None
        tag = f"{named} " if named else ""
        if was is not None and was[0] == group:
            continue
        if group == "done":
            note("finished", f"{named} finished: {title}" if named else f"Finished: {title}", named)
        elif group == "now":
            note("started", f"Started: {tag}{title}")
        elif was is not None:
            note("progress", f"{tag}{title}: {GROUP_WORDS.get(was[0], was[0])} → {GROUP_WORDS.get(group, group)}")
        elif group in ("next", "missing"):
            note("added", f"New: {tag}{title}")
        elif group == "could":
            note("warning", f"Could be a problem: {title}")
        elif group == "known":
            note("parked", f"New known problem: {title}")
    for key in sorted(before.keys() - after.keys()):
        group, title, _ = before[key]
        if group in ("could", "known"):
            note("cleared", f"Off the problem list: {title}")
        elif group in ("now", "next", "missing"):
            note("cleared", f"No longer listed: {title}")
    if repo and new.get("head") and old.get("head") and new["head"] != old["head"]:
        commits = commits_since(repo, old["head"])
        if commits is None:
            note("commit", "New commits (the previous one is no longer in this branch's history)")
        else:
            for commit in commits[:6]:
                note("commit", f"{commit['short']} {commit['subject']}")
            if len(commits) > 6:
                note("commit", f"…and {len(commits) - 6} more")
    changes.sort(key=lambda c: CHANGE_ORDER.index(c["kind"]))
    if len(changes) > MAX_CHANGES:
        hidden = len(changes) - MAX_CHANGES
        changes = changes[:MAX_CHANGES] + [{"kind": "progress", "text": f"…and {hidden} more changes"}]
    return changes
