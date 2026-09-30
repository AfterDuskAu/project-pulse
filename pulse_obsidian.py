"""Pulse's Obsidian note: one page per project, inside an Obsidian vault.

Pulse writes everything above the "## My notes" heading and rewrites it on every refresh. Everything from that
heading down belongs to the person and is copied back unchanged. Nothing they write is ever lost:
- lines typed above the heading are moved under it, and a copy of the old note is kept in Pulse's own state folder;
- a note Pulse didn't make is never overwritten;
- inside a git repo, Pulse writes only where git is told to ignore it, so the note never shows up as a change.
No AI and no network, like the rest of Pulse.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import urllib.parse
from pathlib import Path

from pulse_groups import categorize  # the same groups as the Pulse app

MARKER = "%% Made by Pulse"
NOTES_HEADING = "## My notes"
NOTES_HINT = ("Pulse keeps everything under this heading, however often it refreshes. Write whatever you like here: "
              "thoughts, questions, reminders.")
HEADING_RE = re.compile(r"^## My notes[ \t]*$", re.M)
BACKUPS_KEPT = 20
CHANGE_WORDS = {"finished": "Finished", "started": "Started", "ready": "Prompt written", "added": "New",
                "proposed": "Proposed", "progress": "Moved", "parked": "New problem", "warning": "Warning",
                "cleared": "", "commit": "Commit"}  # a "cleared" line already says what was cleared


# ---------------------------------------------------------------- the note's text

def bar(fraction: float, width: int) -> str:
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return "█" * filled + "░" * (width - filled)


def esc(text: object) -> str:
    """Plain text that Obsidian shows as written (no stray HTML, bold, comments or links)."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text.replace("<", "&lt;").replace("*", "\\*").replace("%%", "%\\%").replace("[[", "[\\[")


def when(moment: dt.datetime | str) -> str:
    if isinstance(moment, str):
        moment = dt.datetime.fromisoformat(moment)
    return f"{moment:%a} {moment.day} {moment:%b}, {moment:%H:%M}"


def day(iso_day: str) -> str:
    d = dt.date.fromisoformat(iso_day[:10])
    return f"{d.day} {d:%b}"


def ago(iso: str, now: dt.datetime) -> str:
    minutes = round((now - dt.datetime.fromisoformat(iso)).total_seconds() / 60)
    if minutes < 60:
        return f"{max(minutes, 0)} min ago"
    hours = round(minutes / 60)
    return f"{hours} h ago" if hours < 48 else f"{round(hours / 24)} days ago"


def link(path: str | None, label: str, vault: Path) -> str:
    """A link Obsidian opens: [[path|label]] inside the vault, an obsidian:// link outside it."""
    if not path:
        return esc(label)
    target = Path(path).resolve()
    try:
        inside = target.relative_to(vault.resolve()).as_posix()
    except ValueError:
        return f"[{esc(label)}](obsidian://open?path={urllib.parse.quote(str(target))})"
    if inside.endswith(".md"):
        inside = inside[:-3]
    return f"[[{inside}|{esc(label)}]]"


def callout(kind: str, title: str, lines: list[str], folded: bool = False,
            empty: str = "Nothing here right now.") -> list[str]:
    return [f"> [!{kind}]{'-' if folded else ''} {title}"] + [f"> {line}" for line in (lines or [empty])] + [""]


def render(project: dict, vault: Path, now: dt.datetime) -> str:
    """Everything above "My notes". Ends with a rule and a blank line."""
    cats = categorize(project)
    summary = project["summary"]
    out = [f"{MARKER} on {now.isoformat(timespec='seconds')}. Everything above “My notes” is rewritten on each "
           "refresh. %%",
           f"> [!info] Made by Pulse · {when(now)} · double-click Pulse.command to refresh · write your own notes "
           "under “My notes” at the bottom",
           "",
           f"# {esc(project['name'])}: where you are",
           "",
           f"**{summary['stepsDone']} of {summary['stepsTotal']} roadmap steps done** · "
           f"{summary['workDonePct']}% of the work",
           "",
           f"`{bar(summary['workDonePct'] / 100, 30)}`",
           ""]
    if project["stages"]:
        out += ["| Stage | Progress | Done |", "|---|---|---|"]
        for stage in project["stages"]:
            total = len(stage["steps"])
            done = sum(1 for s in stage["steps"] if s["status"] == "done")
            out.append(f"| {esc(stage['name']).replace('|', '/')} | `{bar(done / total if total else 0, 12)}` | "
                       f"{done} of {total} |")
        out.append("")

    if project.get("comparedWith"):
        lines = []
        for change in project.get("changes", []):
            label = CHANGE_WORDS.get(change["kind"], change["kind"])
            lines.append(f"- **{label}:** {esc(change['text'])}" if label else f"- {esc(change['text'])}")
        out += callout("tip", f"Since {when(project['comparedWith'])}", lines, empty="Nothing has changed.")
    else:
        out += callout("tip", "Since the last refresh", [],
                       empty="This is the first run. Changes show from the next refresh.")

    lines = [f"- **Now:** {link(s.get('link'), s['id'], vault)} {esc(s['name'])}"
             + (f" · {esc(s['note'])}" if s.get("note") else "") for s in cats["now"]]
    git = project["git"]
    if git.get("ok") and git["uncommitted"]["files"]:
        u = git["uncommitted"]
        lines.append(f"- **Not committed yet:** {len(u['files'])} files, +{u['added']} −{u['removed']} lines"
                     + (f" · last edit {ago(u['newestEdit'], now)}" if u.get("newestEdit") else ""))
    memory = project.get("memory") or {}
    if memory.get("next"):
        lines.append(f"- **Next, from {link(memory.get('path'), 'CLAUDE.md', vault)}:** {esc(memory['next'])}")
    if cats["ready"]:
        lines.append("- **Ready to start:**")
        lines += [f"    - {link(s.get('prompt') or s.get('link'), s['id'], vault)} {esc(s['name'])}"
                  + ("" if s.get("prompt") else " · prompt not written yet")
                  + (" · cut line" if s.get("cut") else "") for s in cats["ready"]]
    if cats["waits"]:
        lines.append("- **Waits on you:**")
        lines += [f"    - {link(w.get('link'), w['id'], vault)} {esc(', '.join(w['outside']))}"
                  + (f" · also after {esc(', '.join(w['blockedBy']))}" if w["blockedBy"] else "")
                  for w in cats["waits"]]
    out += callout("todo", "Now and next", lines)

    out += callout("warning", f"Could be problems ({len(cats['could'])})",
                   [f"- **{esc(c['why'])}:** {esc(c['text'])}"
                    + (f" · {link(c['path'], 'open', vault)}" if c.get("path") else "") for c in cats["could"]])

    lines = [f"- Full notes: {link((project.get('sources') or {}).get('knownIssues'), 'KNOWN-ISSUES', vault)}"]
    for area in dict.fromkeys(i["area"] for i in cats["known"]):
        lines.append(f"- **{esc(area)}**")
        lines += [f"    - {esc(i['title'])}" for i in cats["known"] if i["area"] == area]
    out += callout("bug", f"Known problems ({len(cats['known'])})", lines, folded=True)

    lines = [f"- **Prompt not written yet:** {link(s.get('link'), s['id'], vault)} {esc(s['name'])}"
             + (" · outlined" if s["status"] == "outlined" else "") for s in cats["missingPrompts"]]
    lines += [f"- **Your errand:** {esc(e['text'])}" for e in cats["errands"]]
    out += callout("question", f"Missing ({len(cats['missingPrompts']) + len(cats['errands'])})", lines, folded=True)

    finished = sorted(cats["done"], key=lambda s: s.get("date") or "", reverse=True)
    out += callout("success", f"Done ({len(finished)})",
                   [f"- {link(s.get('link'), s['id'], vault)} {esc(s['name'])}"
                    + (f" · {day(s['date'])}" if s.get("date") else "") for s in finished], folded=True)

    if project.get("ideas"):
        lines = []
        for group in dict.fromkeys(i["group"] for i in project["ideas"]):
            lines.append(f"- **{esc(group)}**")
            lines += [f"    - {esc(i['title'])}" for i in project["ideas"] if i["group"] == group]
        out += callout("quote", f"Ideas for later ({len(project['ideas'])})", lines, folded=True)

    return "\n".join(out + ["---", "", ""])


# ---------------------------------------------------------------- keeping the person's writing

def split_note(text: str) -> tuple[str, str | None]:
    """(Pulse's part, the person's part from "## My notes" down — or None if that heading is gone)."""
    found = HEADING_RE.search(text)
    return (text[:found.start()], text[found.start():]) if found else (text, None)


def merge(existing: str | None, generated: str, last_generated: str | None, now: dt.datetime) -> tuple[str, list[str]]:
    """The new note: Pulse's new part, then the person's part unchanged. Lines they typed in Pulse's part
    (anything Pulse didn't write last time) are moved under "My notes", never dropped."""
    if existing is None:
        return f"{generated}{NOTES_HEADING}\n{NOTES_HINT}\n", []
    above, mine = split_note(existing)
    if mine is None:
        mine = f"{NOTES_HEADING}\n"
    moved: list[str] = []
    if last_generated is not None and above != last_generated:
        written = set(last_generated.splitlines())
        moved = [line for line in above.splitlines() if line.strip() and line not in written]
    if moved:
        mine = (mine.rstrip("\n") + f"\n\n*Moved here by Pulse on {when(now)}: you wrote these above “My notes”, "
                "which Pulse rewrites.*\n" + "\n".join(moved) + "\n")
    elif not mine.endswith("\n"):
        mine += "\n"
    return generated + mine, moved


# ---------------------------------------------------------------- writing the file safely

def _git(vault: Path, *args: str) -> subprocess.CompletedProcess | None:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    try:
        return subprocess.run(["git", "--no-optional-locks", "-C", str(vault), *args],
                              capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_would_see(vault: Path, relative: Path) -> bool:
    """True when the vault is a git repo and git doesn't ignore this path (so the note would show as a change)."""
    inside = _git(vault, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return False
    ignored = _git(vault, "check-ignore", "-q", relative.as_posix())
    return ignored is None or ignored.returncode != 0


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
        return info.st_mtime_ns, info.st_size
    except OSError:
        return None


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def update_note(settings: dict, project: dict, now: dt.datetime, state_dir: Path) -> dict:
    """Writes (or leaves alone) the project's Obsidian note. Returns what happened, for the page and the console."""
    vault = Path(settings["vault"]).expanduser()
    note = vault / settings.get("note", f"Pulse/{project['name']}.md")
    result = {"path": str(note), "status": "skipped", "message": "", "moved": 0}
    if not vault.is_dir():
        result["message"] = f"The Obsidian vault {vault} doesn't exist."
        return result
    try:
        relative = note.relative_to(vault)
    except ValueError:
        result["message"] = "The note has to be inside the vault."
        return result
    if git_would_see(vault, relative):
        folder = relative.parent.as_posix() + "/"
        result["message"] = (f"Obsidian note not written: git would see {folder}. Add the line “{folder}” to "
                             f"{vault / '.git' / 'info' / 'exclude'} to hide it on this Mac only.")
        return result

    generated = render(project, vault, now)
    before = _stamp(note)
    existing = _read(note)
    if existing is not None and MARKER not in existing:
        result["message"] = f"Obsidian note not written: {relative.as_posix()} already exists and wasn't made by Pulse."
        return result
    last_path = state_dir / "obsidian-last.md"
    last = _read(last_path)
    text, moved = merge(existing, generated, last, now)
    result["moved"] = len(moved)

    state_dir.mkdir(parents=True, exist_ok=True)
    edited = existing is not None and (last is None or split_note(existing)[0] != last)
    if edited:  # the person changed Pulse's part (or Pulse lost its record): keep a copy of the old note
        backups = state_dir / "obsidian-backups"
        backups.mkdir(exist_ok=True)
        (backups / f"{now:%Y%m%d-%H%M%S}.md").write_text(existing, encoding="utf-8")
        for old in sorted(backups.glob("*.md"))[:-BACKUPS_KEPT]:
            old.unlink()  # Pulse's own copies only
        if last is None:
            result["message"] = (f"Pulse had no record of its last version of the note, so it kept a copy of the old "
                                 f"one in {backups}.")

    if text == existing:
        result["status"] = "unchanged"
    else:
        temporary = state_dir / "obsidian-note.tmp"
        temporary.write_text(text, encoding="utf-8")
        if _stamp(note) != before:  # the note changed while Pulse worked (someone typing): try next time
            temporary.unlink()
            result["message"] = "Obsidian note not written this time: it changed while Pulse was working. Refresh again."
            return result
        note.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(temporary, note)
        except OSError:  # a different disk: write in place instead
            note.write_text(text, encoding="utf-8")
            temporary.unlink(missing_ok=True)
        result["status"] = "written"
    last_path.write_text(generated, encoding="utf-8")
    return result
