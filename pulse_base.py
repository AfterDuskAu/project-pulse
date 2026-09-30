"""Small helpers every Pulse reader shares: turning Markdown into short plain titles, and asking git
(read-only, with its optional locks off, so it never rewrites a repo's index)."""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from pathlib import Path


# ---------------------------------------------------------------- text

def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def clean(text: str) -> str:
    """Markdown to plain text: links, code marks, bold, strikethrough, extra spaces."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").replace("**", "").replace("~~", "")
    return re.sub(r"\s+", " ", text).strip()


def strip_parens(text: str) -> str:
    """Drop (bracketed asides), innermost first: "(L20–21)", "(#46)", "(29 Sep)"."""
    before = None
    while before != text:
        before = text
        text = re.sub(r"\s*\([^()]*\)", "", text)
    text = re.sub(r"\s+([,.;:])(?=\s|$)", r"\1", text)  # "folders ." → "folders.", but ".claude/" keeps its space
    return re.sub(r"\s+", " ", text).strip()


def headline(text: str, limit: int = 110, cut_at_colon: bool = True) -> str:
    """A short title from a long note: its first clause, without the asides."""
    text = strip_parens(clean(text))
    stops = [". ", " — ", "; "] + ([": "] if cut_at_colon else [])
    end = len(text)
    for stop in stops:
        at = text.find(stop, 20)
        if stop == ": " and at < 45:
            continue  # "Convert › Move converted originals: …" — the problem comes after the colon
        if at != -1:
            end = min(end, at)
    text = text[:end].rstrip(" .;:—")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—") + "…"
    first_word = text.split(" ", 1)[0]
    if first_word.isalpha() and first_word.islower():  # never "Asset.protected"
        text = text[:1].upper() + text[1:]
    return text


def stage_title_note(name: str, rest: str) -> tuple[str, str]:
    """A stage's short title and its note: "Stage 2 — the grid, one step after another" → ("Stage 2 — the grid",
    "one step after another"); "Alongside stage 2" then "(no grid files; one builder…)" → note "no grid files"."""
    title, note = name, ""
    if " — " in name and ", " in name.split(" — ", 1)[1]:
        head, tail = name.split(" — ", 1)
        first, note = tail.split(", ", 1)
        title = f"{head} — {first}"
    inside = re.match(r"^\(([^)]*)\)", rest)
    if not note and inside:
        note = re.split(r"[;,]", inside.group(1))[0].strip()
    return title, note.rstrip(".")


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())[:60]


def iso(stamp: float) -> str:
    return dt.datetime.fromtimestamp(stamp).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- git (read-only)

def git(repo: Path, *args: str) -> str | None:
    """A read-only git command. Optional locks off: git never rewrites the index."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    try:
        done = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(repo), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def git_facts(repo: Path, now: dt.datetime) -> dict:
    head = git(repo, "log", "-1", "--format=%H%x1f%h%x1f%cI%x1f%s")
    if not head or "\x1f" not in head:
        return {"ok": False}
    full, short_hash, when, subject = head.rstrip("\n").split("\x1f", 3)
    facts: dict = {
        "ok": True,
        "branch": (git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "").strip(),
        "head": {"hash": full, "short": short_hash, "date": when, "subject": subject},
    }

    # Uncommitted work: what git status lists, with the lines git counts for each file.
    counts: dict[str, tuple[int, int]] = {}
    for line in (git(repo, "diff", "--numstat", "HEAD") or "").splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            added, removed, path = parts
            counts[path] = (int(added) if added.isdigit() else 0,
                            int(removed) if removed.isdigit() else 0)
    files = []
    entries = (git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=normal") or "").split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            i += 1  # a renamed file's old name comes next
        added, removed = counts.get(path, (0, 0))
        try:
            edited = iso((repo / path).stat().st_mtime)
        except OSError:
            edited = None  # deleted
        files.append({"path": path, "code": code.strip(), "added": added,
                      "removed": removed, "edited": edited})
    stamps = sorted(f["edited"] for f in files if f["edited"])
    facts["uncommitted"] = {
        "files": sorted(files, key=lambda f: f["path"]),
        "added": sum(f["added"] for f in files),
        "removed": sum(f["removed"] for f in files),
        "newestEdit": stamps[-1] if stamps else None,
        "oldestEdit": stamps[0] if stamps else None,
    }

    # Activity: commits per day for the last 14 days, and the newest few.
    first_day = (now - dt.timedelta(days=13)).date()
    per_day: dict[str, int] = {}
    for day in (git(repo, "log", f"--since={first_day.isoformat()} 00:00", "--format=%cs") or "").split():
        per_day[day] = per_day.get(day, 0) + 1
    days = [(first_day + dt.timedelta(days=k)).isoformat() for k in range(14)]
    facts["activity"] = [{"day": d, "commits": per_day.get(d, 0)} for d in days]
    recent = []
    for line in (git(repo, "log", "-8", "--format=%h%x1f%cs%x1f%s") or "").splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) == 3:
            recent.append({"short": parts[0], "day": parts[1], "subject": parts[2]})
    facts["recent"] = recent
    return facts


def commits_since(repo: Path, old_head: str | None) -> list[dict] | None:
    """Commits after old_head, newest first; None when old_head isn't in the history."""
    if not old_head or git(repo, "cat-file", "-e", f"{old_head}^{{commit}}") is None:
        return None
    commits = []
    for line in (git(repo, "log", "--format=%h%x1f%s", f"{old_head}..HEAD") or "").splitlines():
        parts = line.split("\x1f", 1)
        if len(parts) == 2:
            commits.append({"short": parts[0], "subject": parts[1]})
    return commits
