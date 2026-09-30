"""Every prompt a project has: the ones written down (step prompts, slash commands, agents, skills), the ones you sent
Claude, which written ones were never sent, sessions that stopped before finishing (to try again), and long prompts
you've typed more than once (worth saving as a file).

Read-only, no network, no AI.
"""
from __future__ import annotations

import re
from pathlib import Path

from pulse_any import STEP_DIRS, TOOL_DIRS, in_fixtures

PROMPT_EXT = (".md", ".txt")
REPEAT_MIN_CHARS = 200     # a prompt this long, sent twice or more, is worth keeping as a file
MAX_WRITTEN = 200


def frontmatter(text: str) -> dict[str, str]:
    found = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    fields = {}
    for line in (found.group(1).splitlines() if found else []):
        key, _, value = line.partition(":")
        if value.strip():
            fields[key.strip().lower()] = value.strip().strip("\"'")
    return fields


def title_of(text: str, fallback: str) -> str:
    fields = frontmatter(text)
    if fields.get("description"):
        return fields["description"][:160]
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.S)
    heading = re.search(r"^#{1,3}\s+(.+?)\s*#*\s*$", body, re.M)
    if heading:
        return heading.group(1).strip()[:160]
    first = next((line.strip() for line in body.splitlines() if line.strip()), "")
    return (first or fallback)[:160]


def written_prompts(folder, verb: str) -> list[dict]:
    """The prompts written as files, each with how to use it."""
    found = []
    for rel in folder.files:
        low = rel.lower()
        name = rel.rsplit("/", 1)[-1]
        stem = name.rsplit(".", 1)[0]
        kind, use = None, None
        if low.startswith(".claude/commands/") and low.endswith(".md"):
            command = rel[len(".claude/commands/"):-3].replace("/", ":")
            kind, use = "command", f"/{command}"
        elif low.startswith(".claude/agents/") and low.endswith(".md"):
            kind, use = "agent", f"Use the {stem} agent to …"
        elif low.startswith(".claude/skills/") and name == "SKILL.md":
            skill = rel.split("/")[2]
            kind, use = "skill", f"/{skill}"
        elif low.endswith(".prompt.md") or low.startswith(".github/prompts/"):
            kind, use = "prompt", f"{verb} {rel}"
        elif low.endswith(PROMPT_EXT) and name.lower() not in ("readme.md", "index.md") and not in_fixtures(rel) \
                and any(low.startswith(d + "/") for d in STEP_DIRS) and not low.startswith(TOOL_DIRS):
            kind, use = "step", f"{verb} {rel}"
        if not kind:
            continue
        text = folder.text(rel, limit=200_000) or ""
        fields = frontmatter(text)
        if kind in ("agent", "skill") and fields.get("name"):
            use = f"/{fields['name']}" if kind == "skill" else f"Use the {fields['name']} agent to …"
        found.append({"kind": kind, "rel": rel, "path": str(folder.root / rel), "title": title_of(text, stem),
                      "use": use, "name": stem})
        if len(found) >= MAX_WRITTEN:
            break
    order = {"step": 0, "command": 1, "skill": 2, "agent": 3, "prompt": 4}
    return sorted(found, key=lambda p: (order[p["kind"]], p["rel"].lower()))


def global_prompts(claude_home: Path) -> list[dict]:
    """Your own slash commands and skills for every project (~/.claude/commands, ~/.claude/skills)."""
    found = []
    commands = claude_home / "commands"
    for path in sorted(commands.rglob("*.md")) if commands.is_dir() else []:
        text = path.read_text(encoding="utf-8", errors="replace")[:20_000]
        name = str(path.relative_to(commands))[:-3].replace("/", ":")
        found.append({"kind": "command", "title": title_of(text, name), "use": f"/{name}", "path": str(path)})
    skills = claude_home / "skills"
    for path in sorted(skills.glob("*/SKILL.md")) if skills.is_dir() else []:
        text = path.read_text(encoding="utf-8", errors="replace")[:20_000]
        name = frontmatter(text).get("name") or path.parent.name
        found.append({"kind": "skill", "title": title_of(text, name), "use": f"/{name}", "path": str(path)})
    return found[:MAX_WRITTEN]


def file_id(name: str) -> str | None:
    """The step ID a prompt file's name starts with: "20c-library-add" → "20c", "RT-3c-D-look-only-grid" → "RT-3c-D",
    "25b-3-review-tabs" → "25b-3". A bare number ("01-setup") is too common to look for on its own."""
    parts = re.split(r"[-_ ]", name)
    lead = []
    for part in parts:
        if not part or (part.isalpha() and part.islower() and len(part) > 1):
            break
        lead.append(part)
    found = "-".join(lead)
    return found if found and re.search(r"\d", found) and re.search(r"[A-Za-z]", found) else None


def mentions(prompt: str, written: dict, step_id: str | None) -> bool:
    text = prompt.lower()
    if written["kind"] in ("command", "skill"):
        return text.startswith(written["use"].lower() + " ") or text == written["use"].lower() \
            or f" {written['use'].lower()} " in f" {text} "
    if written["rel"].lower() in text or re.search(rf"(?<![\w-]){re.escape(written['name'].lower())}(?![\w-])", text):
        return True
    for known in (step_id, file_id(written["name"])):
        if known and re.search(rf"(?<![\w-]){re.escape(known.lower())}(?![\w-])", text):
            return True
    return False


def first_seen(folder, rels: list[str]) -> dict[str, str]:
    """When git first saw each file (its first commit), in one git call. A copied or moved project resets the
    files' own dates, but not their history."""
    if not folder.in_git or not rels:
        return {}
    from pulse_base import git
    log = git(folder.root, "log", "--diff-filter=A", "--format=%x1e%cI", "--name-only", "--", *rels[:200]) or ""
    seen: dict[str, str] = {}
    for record in log.split("\x1e"):
        stamp, _, names = record.strip("\n").partition("\n")
        for name in names.splitlines():
            if name.strip():
                seen[name.strip()] = stamp  # newest commits come first: the last one written is the first add
    return seen


def library(folder, view: dict, claude: dict | None, verb: str) -> dict:
    """What the Prompts page shows."""
    written = written_prompts(folder, verb)
    added = first_seen(folder, [w["rel"] for w in written])
    rows = {row["path"]: row for stage in (view.get("roadmap") or {}).get("stages") or [] for row in stage["rows"]
            if row.get("path")}
    sent = (claude or {}).get("prompts") or []
    since = (claude or {}).get("since")
    for prompt in written:
        row = rows.get(prompt["path"])
        step_id = row["label"] if row and row.get("label") else None
        times = [p["at"] for p in sent if mentions(p["text"], prompt, step_id)]
        prompt["step"] = step_id
        prompt["state"] = row["state"] if row else None
        prompt["sent"] = len(times)
        prompt["lastSent"] = max(times) if times else None
        prompt["key"] = row["key"] if row else f"prompt:{prompt['rel']}"
        mtime = folder.mtime(prompt["rel"])
        written_at = added.get(prompt["rel"]) or (iso_of(mtime) if mtime else None)  # git's date, else the file's
        newer = bool(since) and written_at is not None and written_at >= since
        prompt["neverSent"] = not times and (not row or row["state"] != "done") and newer
    return {"written": written, "sent": sent, "repeated": repeated(sent), "unfinished": unfinished(claude),
            "sentCount": (claude or {}).get("promptCount", 0), "readsClaude": claude is not None, "since": since}


def iso_of(stamp: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(stamp).astimezone().isoformat(timespec="seconds")


def repeated(sent: list[dict]) -> list[dict]:
    """Long prompts typed more than once: a file (or a slash command) would make them one click."""
    groups: dict[str, list[dict]] = {}
    for prompt in sent:
        text = prompt["text"]
        if len(text) < REPEAT_MIN_CHARS or text.startswith(("/", "!")):
            continue
        key = re.sub(r"\s+", " ", text.lower())[:160]
        groups.setdefault(key, []).append(prompt)
    found = [{"text": items[0]["text"], "times": len(items), "last": max(p["at"] or "" for p in items)}
             for items in groups.values() if len(items) >= 2]
    return sorted(found, key=lambda r: (-r["times"], r["last"]))[:10]


def unfinished(claude: dict | None) -> list[dict]:
    """Sessions that stopped before they finished, with the last prompt, to try again."""
    found = []
    for session in (claude or {}).get("stops") or []:
        stop = session.get("stop") or {}
        if stop.get("why") == "noreply" and not session.get("lastPrompt"):
            continue
        found.append({"session": session["id"], "title": session["title"], "why": stop.get("why"),
                      "text": stop.get("text"), "at": stop.get("at") or session.get("ended"),
                      "lastPrompt": session.get("lastPrompt")})
    return found
