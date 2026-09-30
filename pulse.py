#!/usr/bin/env python3
"""Project Pulse, phase 1: one local page that shows where each project stands.

It reads each project's own files (the roadmap, NEXT-UP, the step write-ups, the
step prompts, KNOWN-ISSUES, the speed reports, CLAUDE.md) and its git history,
works out what is done, in progress, ready, parked and out of date, and writes
out/index.html. Then it opens that page.

- No AI and no network: everything comes from files on this Mac.
- Read-only on every project: it only reads files and runs read-only git
  commands, with git's optional locks off, so it never rewrites a repo's index.
- It writes only inside this folder: out/ (the page) and state/ (snapshots for
  "Since …", and runs.jsonl with one line per run).

    python3 pulse.py             write the page and open it
    python3 pulse.py --no-open   write the page only
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

import pulse_any
import pulse_briefing
import pulse_claude
import pulse_groups
import pulse_obsidian
import pulse_prompts
from pulse_base import (clean, commits_since, git, git_facts, headline, iso, norm, read_text, stage_title_note,
                        strip_parens)

HERE = Path(__file__).resolve().parent
UNITS = {"S": 1, "M": 2, "L": 4}
# A step id: SF-1, RT-3c-B, RT-3c-0b, A11Y-1, CM-1b, BIG-0.
ID_PATTERN = r"[A-Z][A-Z0-9]*(?:-[0-9A-Za-z]+)+"
ID_ONLY = re.compile(rf"^{ID_PATTERN}$")
# Words in a roadmap "After" cell that are notes, not something the step waits for.
AFTER_NOTES = ("before ", "ships with ", "with ")
STATUS_LABELS = {"done": "done", "in-progress": "in progress", "ready": "prompt ready",
                 "outlined": "outlined", "to-write": "prompt to write"}
UNCOMMITTED_WARN_HOURS = 24
BASELINE_MIN_AGE = dt.timedelta(minutes=60)  # "Since …" compares with a run at least this old
SNAPSHOTS_KEPT = 60


def step_name(what: str) -> str:
    """A roadmap "What" cell as a name: "#19 + #20: a ▶ on Review's video tiles; P = …" → "A ▶ on Review's video tiles"."""
    text = strip_parens(clean(what))
    text = re.sub(r"^(?:(?:#[\d.]+|Step [\d-]+)(?:\s*\+\s*#[\d.]+)*\s*[:,]\s*)+", "", text)
    return headline(text, limit=70, cut_at_colon=False)


def join_ids(ids: list[str]) -> str:
    return ", ".join(ids)


# ---------------------------------------------------------------- step write-ups and prompts

def parse_title_line(line: str, fallback_id: str) -> dict:
    """ "# SF-1 — Safety fixes: the four one-liners (2026-09-29)" → id, name, date, status."""
    title = re.sub(r"^#+\s*", "", line).strip()
    step_id, name = fallback_id, title
    m = re.match(rf"^({ID_PATTERN})\s+[—–-]\s+(.*)$", title)
    if m:
        step_id, name = m.group(1), m.group(2)
    status, note = "done", None
    progress = re.search(r"\((IN PROGRESS[^)]*)\)", name, re.I)
    if progress:
        status = "in-progress"
        note = re.sub(r"^IN PROGRESS\s*[—–-]?\s*", "", progress.group(1), flags=re.I).strip() or None
    dated = re.search(r"\((\d{4}-\d{2}-\d{2})\)\s*$", name)
    return {"id": step_id, "name": strip_parens(clean(name)), "status": status, "note": note,
            "date": dated.group(1) if dated else None}


def first_line(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as handle:
            return handle.readline().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def read_step_files(folder: Path, repo: Path) -> dict[str, dict]:
    """Finished (or in-progress) steps: one write-up per step, named after its id."""
    found: dict[str, dict] = {}
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.md")):
        info = parse_title_line(first_line(path), path.stem)
        info["id"] = path.stem  # the file name is the id
        if info["date"] is None and info["status"] == "done":
            day = git(repo, "log", "-1", "--format=%cs", "--", str(path.relative_to(repo)))
            info["date"] = (day or "").strip() or None
        info["path"] = str(path)
        found[path.stem.lower()] = info
    return found


def prompt_for(step_id: str, prompts: list[Path]) -> Path | None:
    prefix = step_id.lower() + "-"
    for path in prompts:
        if path.name.lower().startswith(prefix):
            return path
    return None


# ---------------------------------------------------------------- the roadmap

def split_sections(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    title, lines = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if title is not None:
                sections.append((title, lines))
            title, lines = line[3:].strip(), []
        elif title is not None:
            lines.append(line)
    if title is not None:
        sections.append((title, lines))
    return sections


def find_section(sections: list[tuple[str, list[str]]], keyword: str) -> tuple[str, list[str]] | None:
    for title, lines in sections:
        if keyword.lower() in title.lower():
            return title, lines
    return None


def read_blocks(lines: list[str]) -> list[dict]:
    """The road split into blocks, one per bold heading ("**Stage 1 — safety first.**"),
    each with its table rows and its bullets."""
    blocks: list[dict] = []
    block = None
    columns = None
    for raw in lines:
        line = raw.rstrip()
        bold = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", line)
        if bold:
            block = {"name": bold.group(1).strip().rstrip(".:").strip(), "rest": bold.group(2).strip(), "rows": [],
                     "bullets": []}
            blocks.append(block)
            columns = None
            continue
        if block is None:
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if columns is None:
                if "Step" in cells and "Status" in cells:
                    columns = {name: at for at, name in enumerate(cells)}
                continue
            if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                continue
            block["rows"].append({name: (cells[at] if at < len(cells) else "") for name, at in columns.items()})
        elif line.startswith("- "):
            block["bullets"].append(line[2:].strip())
        elif line.startswith("  ") and line.strip() and block["bullets"]:
            block["bullets"][-1] += " " + line.strip()
    return blocks


def gate_name(bullet: str) -> str:
    bold = re.match(r"^\*\*(.+?)\*\*", bullet)
    text = bold.group(1) if bold else re.split(r"\.\s|:\s|\.$", clean(bullet))[0]
    text = strip_parens(clean(text)).strip(" .:").split(", ")[0]  # "ONB, last" → "ONB"
    return re.sub(r"^→\s*", "", text)


def parse_ideas(title: str, lines: list[str]) -> list[dict]:
    group = strip_parens(re.sub(r"^\d+\.\s*", "", title))
    ideas: list[dict] = []
    current = None
    for raw in lines:
        line = raw.rstrip()
        bold = re.match(r"^\*\*(.+?)\*\*", line)
        if bold:
            group = clean(bold.group(1)).rstrip(":. ")
            current = None
            continue
        item = re.match(r"^(?:\d+\.|-)\s+(.*)$", line)
        if item:
            current = {"group": group, "text": item.group(1).strip()}
            ideas.append(current)
        elif line.startswith("  ") and line.strip() and current:
            current["text"] += " " + line.strip()
        elif not line.strip():
            current = None
    for idea in ideas:
        idea["title"] = headline(idea["text"], limit=100, cut_at_colon=False)
        idea["text"] = clean(idea["text"])
    return ideas


def parse_roadmap(text: str, road_keyword: str, ideas_keyword: str) -> dict:
    sections = split_sections(text)
    road = find_section(sections, road_keyword)
    stages: list[dict] = []
    gates: list[dict] = []
    errands: list[str] = []
    for block in read_blocks(road[1] if road else []):
        name = block["name"]
        title, note = stage_title_note(name, block.get("rest", ""))
        if block["rows"]:
            stage = {"name": name, "title": title, "note": note, "steps": []}
            for row in block["rows"]:
                step_id = clean(row.get("Step", ""))
                if not ID_ONLY.match(step_id):
                    continue
                stage["steps"].append({
                    "id": step_id,
                    "what": clean(row.get("What", "")),
                    "statusText": clean(row.get("Status", "")),
                    "size": (clean(row.get("Size", "")) or "M")[:1].upper(),
                    "after": clean(row.get("After", "")),
                })
            stages.append(stage)
        elif re.match(r"^Stage 0\b", name):
            errands += [headline(b, cut_at_colon=False) for b in block["bullets"]]
        elif re.match(r"^Stage \d", name):
            stage = {"name": name, "title": title, "note": note, "steps": []}
            for bullet in block["bullets"]:
                bold = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", bullet)
                label = bold.group(1).strip().rstrip(".").strip() if bold else ""
                size = re.search(r"\((S|M|L)\)", bullet)
                if bold and ID_ONLY.match(label) and size:
                    stage["steps"].append({"id": label, "what": clean(bold.group(2)), "statusText": "",
                                           "size": size.group(1), "after": "", "fromBullet": True})
                else:
                    gates.append({"stage": name, "name": gate_name(bullet), "text": clean(bullet),
                                  "arrow": bool(re.match(r"^(\*\*)?→", bullet)),
                                  "done": bool(re.match(r"^(\*\*)?DONE\b", bullet))})
            if stage["steps"]:
                stages.append(stage)
        else:
            lead = re.match(rf"^({ID_PATTERN})\b", name)
            if lead:  # e.g. "**BIG-0 — early proof (#44).**": a proof step between stages
                gates.append({"stage": None, "name": lead.group(1), "done": False, "arrow": False,
                              "text": clean(" ".join([block.get("rest", "")] + block["bullets"]))})
    ideas_section = find_section(sections, ideas_keyword)
    ideas = parse_ideas(*ideas_section) if ideas_section else []
    return {"found": road is not None, "stages": stages, "gates": gates, "errands": errands, "ideas": ideas}


def parse_after(after: str, known_ids: list[str]) -> tuple[list[str], list[str], bool]:
    """ "B, SF-3" → steps it waits for; "owner OK" → waits on you; "(cut line 2)" → cut line."""
    cut = "cut line" in after.lower()
    deps: list[str] = []
    outside: list[str] = []
    for token in re.split(r"[,;]", strip_parens(after)):
        token = token.strip().strip(".")
        low = token.lower()
        if not token or token in ("—", "–", "-") or low.startswith(AFTER_NOTES):
            continue
        exact = [i for i in known_ids if i.lower() == low]
        by_suffix = sorted({i for i in known_ids if i.lower().endswith("-" + low)})
        if exact:
            deps.append(exact[0])
        elif len(by_suffix) == 1:
            deps.append(by_suffix[0])  # "B" is RT-3c-B, "0b" is RT-3c-0b
        else:
            outside.append(token)
    return deps, outside, cut


def says_prompt_written(status_text: str, step_id: str) -> bool:
    """Does a roadmap Status cell already say this step's own prompt exists (or it's done)?"""
    if re.search(r"\bdone\b", status_text, re.I):
        return True
    if not re.search(r"\bwritten\b", status_text, re.I):
        return False
    others = [i for i in re.findall(ID_PATTERN, status_text) if not i.lower().startswith(step_id.lower())]
    return not others  # "NU-21 / NU-22 written — merge" is about other prompts


# ---------------------------------------------------------------- NEXT-UP, KNOWN-ISSUES, CLAUDE.md

def parse_next_up(text: str) -> dict:
    errands: list[dict] = []
    items: list[dict] = []
    in_stage0 = False
    for line in text.splitlines():
        if re.match(r"^- \*\*Stage 0\b", line):
            in_stage0 = True
            continue
        if in_stage0:
            errand = re.match(r"^\s{2,}- (.*)$", line)
            if errand:
                errands.append({"raw": errand.group(1)})
                continue
            if re.match(r"^\s{4,}\S", line) and errands:
                errands[-1]["raw"] += " " + line.strip()
                continue
            in_stage0 = False
        item = re.match(r"^(\d+)\.\s+(.*)$", line)
        if not item:
            continue
        body = item.group(2)
        done = body.startswith("DONE")
        found = (re.match(rf"^DONE[^(]*\(({ID_PATTERN})", body) if done
                 else re.match(rf"^({ID_PATTERN})\b", body))
        rest = re.split(r"\):\s|\s—\s|:\s", body, maxsplit=1)[-1]
        items.append({"num": int(item.group(1)), "id": found.group(1) if found else None, "done": done,
                      "toWrite": "(to write)" in body[:80], "what": headline(rest, limit=90)})
    for errand in errands:
        raw = errand.pop("raw")
        errand["done"] = bool(re.search(r"\bDONE\b|~~", raw))
        errand["text"] = headline(re.sub(r"\bDONE\b\s*[—–:-]?\s*", "", raw), cut_at_colon=False)
    return {"errands": errands, "items": items}


def parse_known_issues(text: str) -> list[dict]:
    raw_issues: list[dict] = []
    area = None
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            area, current = strip_parens(clean(line[3:])), None
        elif area is None:
            continue
        elif line.startswith("- "):
            current = {"area": area, "raw": line[2:].strip()}
            raw_issues.append(current)
        elif line.startswith("  ") and line.strip() and current:
            current["raw"] += " " + line.strip()
        elif not line.strip():
            current = None
    issues = []
    for issue in raw_issues:
        raw = issue["raw"]
        state, note, body = "open", None, raw
        lead = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", raw)
        if lead and lead.group(1).lower().startswith("fixed by"):
            head = clean(lead.group(1))
            fixer = re.search(rf"Fixed by ({ID_PATTERN})", head)
            confirm = re.search(r"once (.+?) confirms", head)
            state, body = "confirm", lead.group(2)
            note = "Fixed" + (f" by {fixer.group(1)}" if fixer else "") + (
                f" — confirm in {confirm.group(1)}" if confirm else " — waiting to be confirmed")
        issues.append({"area": issue["area"], "title": headline(body), "text": clean(raw),
                       "state": state, "note": note})
    return issues


def next_starts_with_done(next_line: str, status_of: dict[str, str]) -> str | None:
    """The step a "Next:" line starts with, if it's already done. Later mentions can rightly name
    finished steps ("the owed benches for SRC-1"), so only the first one counts."""
    first = re.search(ID_PATTERN, next_line)
    return first.group(0) if first and status_of.get(first.group(0)) == "done" else None


def memory_facts(root: Path, file_name: str, check_script: str | None) -> dict | None:
    path = root / file_name
    text = read_text(path)
    if text is None:
        return None
    facts: dict = {"path": str(path), "bytes": len(text.encode("utf-8")), "lines": text.count("\n"),
                   "next": None}
    nxt = re.search(r"^- Next:\s*(.+)$", text, re.M)
    if nxt:
        facts["next"] = clean(nxt.group(1))
    if check_script:
        script = read_text(root / check_script) or ""
        limit_bytes = re.search(r"^LIMIT_BYTES=(\d+)", script, re.M)
        limit_lines = re.search(r"^LIMIT_LINES=(\d+)", script, re.M)
        if limit_bytes and limit_lines:
            facts["limitBytes"], facts["limitLines"] = int(limit_bytes.group(1)), int(limit_lines.group(1))
            facts["leftBytes"] = facts["limitBytes"] - facts["bytes"]
            facts["leftLines"] = facts["limitLines"] - facts["lines"]
    return facts


# ---------------------------------------------------------------- speed reports

def parse_perf_report(path: Path) -> dict | None:
    text = read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    when = None
    for line in lines[:6]:
        stamp = re.match(r"^(\d{1,2} \w{3} \d{4} at \d{1,2}:\d{2} [ap]m)", line.strip(), re.I)
        if stamp:
            try:
                when = dt.datetime.strptime(stamp.group(1), "%d %b %Y at %I:%M %p")
            except ValueError:
                pass
            break
    if when is None:
        when = dt.datetime.fromtimestamp(path.stat().st_mtime)
    metrics: list[dict] = []
    stalls, longest = 0, 0
    for line in lines:
        timed = re.match(r"^- (.+?): median (\d+) ms, worst (\d+) ms\s*$", line)
        if timed:
            metrics.append({"name": strip_parens(timed.group(1)), "median": int(timed.group(2)),
                            "worst": int(timed.group(3))})
            continue
        single = re.match(r"^- (.+?): (\d+) ms\s*$", line)
        if single:
            metrics.append({"name": strip_parens(single.group(1)), "median": int(single.group(2)), "worst": None})
            continue
        phase = re.match(r"^\|\s*[^|]+?\s*\|[^|]*\|\s*(\d+) / (\d+) / (\d+)\s*\|\s*(\d+) ms\s*\|", line)
        if phase:
            stalls += int(phase.group(1))
            longest = max(longest, int(phase.group(4)))
    return {"file": path.name, "path": str(path), "when": when.isoformat(timespec="minutes"),
            "valid": "window visible for the whole run" in text,
            "metrics": metrics, "stalls100": stalls, "longestStall": longest}


def perf_summary(folder: Path, pattern: str) -> list[dict]:
    if not folder.is_dir():
        return []
    reports = [r for r in (parse_perf_report(p) for p in sorted(folder.glob("*.md"))
                           if fnmatch.fnmatch(p.name, pattern)) if r]
    kinds = []
    for label, during_scan in (("While browsing", False), ("During a scan", True)):
        group = sorted((r for r in reports if ("-scan" in r["file"]) == during_scan),
                       key=lambda r: (r["when"], r["file"]))
        if group:
            kinds.append({"label": label, "latest": group[-1],
                          "previous": group[-2] if len(group) > 1 else None, "reports": len(group)})
    return kinds


# ---------------------------------------------------------------- one project

def build_project(cfg: dict, now: dt.datetime) -> dict:
    root = Path(cfg["path"]).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"can't find the project folder {root}")
    where = cfg.get("map", {})

    def at(key: str, default: str) -> Path:
        return root / where.get(key, default)

    warnings: list[dict] = []

    def warn(key: str, text: str, file: Path | None = None) -> None:
        warnings.append({"key": key, "text": text, "file": str(file) if file else None})

    roadmap_path = at("roadmap", "docs/design/roadmap-v1.md")
    next_up_path = at("nextUp", "docs/NEXT-UP.md")
    issues_path = at("knownIssues", "docs/KNOWN-ISSUES.md")
    steps_dir = at("stepsDone", "docs/history/steps")
    prompts_dir = at("prompts", "docs/prompts")
    perf_dir = at("perfReports", "docs/testing")

    step_files = read_step_files(steps_dir, root)
    prompts = sorted(prompts_dir.glob("*.md")) if prompts_dir.is_dir() else []

    # The road: the roadmap's stages, with each step's real status taken from the files.
    roadmap_text = read_text(roadmap_path)
    road = parse_roadmap(roadmap_text or "", where.get("roadHeading", "road"), where.get("ideasHeading", "v1.1"))
    if roadmap_text is None:
        if "roadmap" in where:  # only a file the map names is missed; a new folder simply has no roadmap
            warn("missing-roadmap", f"Couldn't read the roadmap ({roadmap_path.relative_to(root)}).")
    elif not any(stage["steps"] for stage in road["stages"]):
        warn("parse-roadmap", "Found no step tables in the roadmap. Has its layout changed?", roadmap_path)

    steps = [s for stage in road["stages"] for s in stage["steps"]]
    known_ids = [s["id"] for s in steps] + [v["id"] for v in step_files.values()]
    for s in steps:
        written = step_files.get(s["id"].lower())
        prompt = prompt_for(s["id"], prompts)
        s["prompt"] = str(prompt) if prompt else None
        s["name"] = step_name(s["what"])
        if prompt:
            s["name"] = parse_title_line(first_line(prompt), s["id"])["name"] or s["name"]
        if written:
            s.update(status=written["status"], date=written["date"], note=written["note"],
                     link=written["path"], name=written["name"] or s["name"])
        elif prompt:
            s.update(status="ready", link=str(prompt))
        else:
            s["status"] = "outlined" if re.search(r"outlined|written", s["statusText"], re.I) else "to-write"
            s["link"] = str(roadmap_path)
        s["deps"], s["outside"], s["cut"] = parse_after(s["after"], known_ids)

    status_of = {v["id"]: v["status"] for v in step_files.values()}
    status_of.update({s["id"]: s["status"] for s in steps})
    for s in steps:
        s["blockedBy"] = [d for d in s["deps"] if status_of.get(d) != "done"]
        if s["status"] in ("done", "in-progress"):
            s["readiness"] = s["status"]
        elif s.get("fromBullet"):
            s["readiness"] = "later"
        elif s["blockedBy"]:
            s["readiness"] = "blocked"
        else:
            s["readiness"] = "waits-on-you" if s["outside"] else "ready"

    table_steps = [s for s in steps if not s.get("fromBullet")]
    behind_done = [s["id"] for s in table_steps
                   if s["status"] == "done" and not re.search(r"\bdone\b", s["statusText"], re.I)]
    behind_prompt = [s["id"] for s in table_steps
                     if s["status"] == "ready" and not says_prompt_written(s["statusText"], s["id"])]
    if behind_done or behind_prompt:
        parts = []
        if behind_done:
            parts.append(f"{len(behind_done)} are finished ({join_ids(behind_done)})")
        if behind_prompt:
            parts.append(f"{len(behind_prompt)} have a prompt but don't say so ({join_ids(behind_prompt)})")
        warn("roadmap-status", f"The roadmap's Status column is out of date for "
             f"{len(behind_done) + len(behind_prompt)} of {len(table_steps)} steps: " + "; ".join(parts) + ".",
             roadmap_path)

    # Steps that have a write-up but aren't in the roadmap (found or added along the way).
    roadmap_ids = {s["id"].lower() for s in steps}
    other_steps = sorted(
        ({"id": v["id"], "name": v["name"], "status": v["status"], "date": v["date"], "note": v["note"],
          "link": v["path"]} for k, v in step_files.items() if k not in roadmap_ids),
        key=lambda v: (v["status"] == "in-progress", v["date"] or ""), reverse=True)

    # Proofs and gates: statuses from the write-ups where there is one.
    gates = road["gates"]
    for gate in gates:
        written = step_files.get(gate["name"].lower())
        if gate["done"]:
            gate["status"] = "done"
        elif written:
            gate.update(status=written["status"], note=written["note"], link=written["path"])
        else:
            gate["status"] = "pending"
    upcoming = next((g for g in gates if g["status"] != "done"), None)
    if upcoming and upcoming["status"] == "pending":
        upcoming["status"] = "next"

    # NEXT-UP: the live list — errands, "(to write)" labels, newly proposed steps.
    next_up_text = read_text(next_up_path)
    next_up = parse_next_up(next_up_text or "")
    if next_up_text is None and "nextUp" in where:
        warn("missing-next-up", f"Couldn't read NEXT-UP ({next_up_path.relative_to(root)}).")
    errands = next_up["errands"] or [{"text": e, "done": False} for e in road["errands"]]
    stale = [it for it in next_up["items"] if it["toWrite"] and it["id"]
             and (prompt_for(it["id"], prompts) or status_of.get(it["id"]) == "done")]
    if stale:
        warn("next-up-to-write", "NEXT-UP still says “to write” for "
             f"{join_ids([it['id'] for it in stale])} ({', '.join('#' + str(it['num']) for it in stale)}), "
             f"but {'its prompt exists' if len(stale) == 1 else 'their prompts exist'}.", next_up_path)
    everything = roadmap_ids | set(step_files)
    proposed = [{"id": it["id"], "num": it["num"], "name": it["what"]} for it in next_up["items"]
                if it["id"] and not it["done"] and it["id"].lower() not in everything]

    # Parked problems.
    issues_text = read_text(issues_path)
    issues = parse_known_issues(issues_text or "")
    if issues_text is None and "knownIssues" in where:
        warn("missing-issues", f"Couldn't read the known-issues list ({issues_path.relative_to(root)}).")

    # CLAUDE.md: its "Next:" line and its size. Being nearly full is normal (each step replaces
    # "Where we are" and runs the size check itself), so only being over the limit is a warning.
    memory = memory_facts(root, where.get("memoryFile", "CLAUDE.md"), where.get("memoryCheck"))
    if memory and "limitBytes" in memory and (memory["leftBytes"] < 0 or memory["leftLines"] < 0):
        memory_path = Path(memory["path"])
        warn("memory-size", f"{memory_path.name} is over its size limit ({memory['bytes']:,} of "
             f"{memory['limitBytes']:,} bytes, {memory['lines']} of {memory['limitLines']} lines), "
             "so its size check fails.", memory_path)
    finished_next = next_starts_with_done(memory["next"], status_of) if memory and memory.get("next") else None
    if finished_next:
        warn("memory-next", f"CLAUDE.md's “Next:” starts with {finished_next}, which is already done.",
             Path(memory["path"]))

    # Git.
    facts = git_facts(root, now)
    if not facts["ok"]:
        warn("git", "Couldn't read this folder's git history.")
    else:
        oldest = facts["uncommitted"]["oldestEdit"]
        if oldest:
            hours = (now - dt.datetime.fromisoformat(oldest)).total_seconds() / 3600
            if hours > UNCOMMITTED_WARN_HOURS:
                warn("uncommitted-old", f"Some changes have been left uncommitted for {round(hours)} hours "
                     f"({len(facts['uncommitted']['files'])} files in all).")

    # Speed reports.
    perf = perf_summary(perf_dir, where.get("perfPattern", "perf-*-release*.md"))
    for kind in perf:
        if not kind["latest"]["valid"]:
            warn(f"perf-invalid-{kind['label']}", f"The newest speed report ({kind['latest']['file']}) doesn't "
                 "say the window was visible for the whole run, so it doesn't count.", Path(kind["latest"]["path"]))

    waits = [{"id": s["id"], "name": s["name"], "outside": s["outside"], "blockedBy": s["blockedBy"],
              "link": s["link"]} for s in steps if s["outside"] and s["status"] != "done"]
    units_total = sum(UNITS.get(s["size"], 2) for s in steps)
    units_done = sum(UNITS.get(s["size"], 2) for s in steps if s["status"] == "done")
    verb = pulse_groups.prompt_verb([read_text(root / "README.md") or "", next_up_text or "",
                                     read_text(prompts_dir / "README.md") or "",
                                     read_text(root / where.get("memoryFile", "CLAUDE.md")) or ""])
    return {
        "name": cfg["name"],
        "path": str(root),
        "promptVerb": verb,
        "obsidian": (root / ".obsidian").is_dir(),
        "summary": {
            "stepsDone": sum(1 for s in steps if s["status"] == "done"),
            "stepsTotal": len(steps),
            "workDonePct": round(100 * units_done / units_total) if units_total else 0,
            "readyNow": [s["id"] for s in steps if s["readiness"] in ("ready", "in-progress")],
        },
        "git": facts,
        "memory": memory,
        "stages": road["stages"],
        "otherSteps": other_steps,
        "proposed": proposed,
        "gates": gates,
        "errands": errands,
        "waitsOnYou": waits,
        "issues": issues,
        "ideas": road["ideas"],
        "perf": perf,
        "warnings": warnings,
        "sources": {
            "roadmap": str(roadmap_path), "nextUp": str(next_up_path), "knownIssues": str(issues_path),
            "memory": memory["path"] if memory else None, "steps": str(steps_dir),
            "prompts": str(prompts_dir), "perf": str(perf_dir),
        },
    }


# ---------------------------------------------------------------- "Since …": snapshots and changes

def snapshot(project: dict) -> dict:
    steps = {s["id"]: {"status": s["status"], "name": s["name"]}
             for stage in project["stages"] for s in stage["steps"]}
    steps.update({s["id"]: {"status": s["status"], "name": s["name"]} for s in project["otherSteps"]})
    return {
        "head": (project["git"].get("head") or {}).get("hash"),
        "steps": steps,
        "proposed": {p["id"]: p["name"] for p in project["proposed"]},
        # Keyed by the note's own opening words, so a change in how titles are shortened isn't a "change".
        "issues": {norm(i["text"]): {"title": i["title"], "state": i["state"]} for i in project["issues"]},
        "warnings": {w["key"]: w["text"] for w in project["warnings"]},
        "gates": {g["name"]: g["status"] for g in project["gates"]},
        "errands": {e["text"]: e["done"] for e in project["errands"]},
    }


CHANGE_ORDER = ["finished", "started", "ready", "added", "proposed", "progress", "parked", "warning",
                "cleared", "commit"]


def compare(old: dict, new: dict, repo: Path | None) -> list[dict]:
    changes: list[dict] = []

    def note(kind: str, text: str, name: str | None = None) -> None:
        changes.append({"kind": kind, "text": text, **({"name": name} if name else {})})

    old_steps, new_steps = old.get("steps", {}), new.get("steps", {})
    for sid, step in new_steps.items():
        was = old_steps.get(sid)
        status, name = step["status"], step["name"]
        if was is None:
            if status == "done":
                note("finished", f"{sid} finished (a new step): {name}", sid)
            elif status == "in-progress":
                note("started", f"{sid} started (a new step): {name}")
            else:
                note("added", f"New step {sid}: {name}")
        elif was["status"] != status:
            if status == "done":
                note("finished", f"{sid} finished: {name}", sid)
            elif status == "in-progress":
                note("started", f"{sid} started: {name}")
            elif status == "ready":
                note("ready", f"Prompt written for {sid}: {name}")
            else:
                note("progress", f"{sid}: {STATUS_LABELS.get(was['status'], was['status'])} → "
                                 f"{STATUS_LABELS.get(status, status)}")
    for sid in sorted(old_steps.keys() - new_steps.keys()):
        note("cleared", f"{sid} is no longer listed")
    for pid, name in new.get("proposed", {}).items():
        if pid not in old.get("proposed", {}):
            note("proposed", f"Proposed in NEXT-UP: {pid}: {name}")

    old_issues, new_issues = old.get("issues", {}), new.get("issues", {})
    for key, issue in new_issues.items():
        was = old_issues.get(key)
        if was is None:
            note("parked", issue["title"])
        elif was["state"] != issue["state"] and issue["state"] == "confirm":
            note("progress", f"Fixed, waiting to be confirmed: {issue['title']}")
    for key in sorted(old_issues.keys() - new_issues.keys()):
        note("cleared", f"Off the problem list: {old_issues[key]['title']}")

    old_warnings, new_warnings = old.get("warnings", {}), new.get("warnings", {})
    for key, text in new_warnings.items():
        if key not in old_warnings:
            note("warning", text)
    for key in sorted(old_warnings.keys() - new_warnings.keys()):
        note("cleared", f"Warning cleared: {old_warnings[key]}")

    for name, status in new.get("gates", {}).items():
        was = old.get("gates", {}).get(name)
        if was and was != status and {was, status} != {"pending", "next"}:
            note("progress", f"{name}: {was} → {status}")
    old_errands = old.get("errands", {})
    for text, done in new.get("errands", {}).items():
        if done and not old_errands.get(text, False):
            note("finished", f"Errand done: {text}")
    for text in sorted(old_errands.keys() - new.get("errands", {}).keys()):
        note("cleared", f"Errand no longer listed: {text}")

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
    return changes


def stamp_name(moment: dt.datetime) -> str:
    return moment.strftime("%Y%m%d-%H%M%S")


def pick_baseline(folder: Path, now: dt.datetime) -> tuple[dict | None, str | None]:
    """The newest snapshot at least an hour old (so a quick second refresh still shows
    today's changes); failing that, the oldest one there is."""
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    if not files:
        return None, None
    cutoff = stamp_name(now - BASELINE_MIN_AGE)
    older = [f for f in files if f.stem <= cutoff]
    chosen = older[-1] if older else files[0]
    try:
        data = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    return data.get("snapshot"), data.get("generatedAt")


def save_snapshot(folder: Path, now: dt.datetime, snap: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stamp_name(now)}.json").write_text(
        json.dumps({"generatedAt": now.isoformat(timespec="seconds"), "snapshot": snap}, ensure_ascii=False),
        encoding="utf-8")
    for old in sorted(folder.glob("*.json"))[:-SNAPSHOTS_KEPT]:
        old.unlink()  # Pulse's own snapshots only


# ---------------------------------------------------------------- the page

def render_page(data: dict) -> str:
    template = (HERE / "page_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\u0021--")
    return template.replace("__PULSE_DATA__", payload, 1)


def write_app_data(projects: list[dict], now: dt.datetime, extra: dict | None = None) -> Path:
    """out/data.json for the Pulse app: each project's view, and the briefing across them, written whole (the app
    never sees half a file)."""
    views = []
    for project in projects:
        if "error" in project:
            views.append({"name": project["name"], "slug": project["slug"], "error": project["error"]})
        else:
            views.append(project["view"])
    target = HERE / "out" / "data.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"generatedAt": now.isoformat(timespec="seconds"), "projects": views,
                                     **(extra or {})}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, target)
    return target


def log_run(now: dt.datetime, name: str, head: str | None, done: int, total: int, issues: int, warnings: int,
            changes: int) -> None:
    with (HERE / "state" / "runs.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({"at": now.isoformat(timespec="seconds"), "project": name, "head": head,
                              "stepsDone": done, "stepsTotal": total, "issues": issues, "warnings": warnings,
                              "changes": changes}) + "\n")


def read_mapped(cfg: dict, now: dt.datetime, slug: str) -> dict:
    """A project with a map in projects.json: its roadmap, NEXT-UP, write-ups, prompts and the rest."""
    name = cfg["name"]
    project = build_project(cfg, now)
    project["slug"] = slug
    try:  # "How it's set up" and forgotten git work never stop the reading
        root = Path(cfg["path"]).expanduser()
        project["setup"], project["layout"] = pulse_any.setup_for(root, now)
        project["extras"] = pulse_any.git_extras(root, project["git"]) if project["git"].get("ok") else []
    except Exception as error:
        project["setup"], project["layout"], project["extras"] = [], [], []
        print(f"{name}: “How it's set up” couldn't be read — {type(error).__name__}: {error}", file=sys.stderr)
    snap = snapshot(project)
    folder = HERE / "state" / slug / "snapshots"
    base, base_time = pick_baseline(folder, now)
    if base and base.get("kind") == "auto":
        base, base_time = None, None  # read another way last time: start afresh
    project["comparedWith"] = base_time
    project["changes"] = compare(base, snap, Path(cfg["path"]).expanduser()) if base else []
    save_snapshot(folder, now, snap)
    log_run(now, name, snap["head"], project["summary"]["stepsDone"], project["summary"]["stepsTotal"],
            len(project["issues"]), len(project["warnings"]), len(project["changes"]))
    count, changed = len(project["warnings"]), len(project["changes"])
    print(f"{name}: {project['summary']['stepsDone']} of {project['summary']['stepsTotal']} roadmap steps "
          f"done, {len(project['issues'])} parked problems, {count} warning{'' if count == 1 else 's'}, "
          f"{changed} change{'' if changed == 1 else 's'} since the last look.")
    if cfg.get("obsidian"):
        try:
            note = pulse_obsidian.update_note(cfg["obsidian"], project, now, HERE / "state" / slug)
        except Exception as error:  # the note never stops the page
            note = {"path": "", "status": "skipped", "moved": 0,
                    "message": f"Obsidian note not written: {type(error).__name__}: {error}"}
        project["obsidianNote"] = note
        print(f"{name}: Obsidian note {note['status']}"
              + (f", {note['moved']} line(s) you typed moved under “My notes”" if note["moved"] else "")
              + (f". {note['message']}" if note["message"] else "."))
    return project


def read_any(cfg: dict, now: dt.datetime, slug: str) -> dict:
    """A folder with no map: Pulse works out its layout by itself (pulse_any)."""
    name = cfg["name"]
    project = pulse_any.read_folder(cfg, now, slug)
    snap = pulse_any.snapshot(project)
    folder = HERE / "state" / slug / "snapshots"
    base, base_time = pick_baseline(folder, now)
    if base and base.get("kind") != "auto":
        base, base_time = None, None  # read another way last time: start afresh
    changes = pulse_any.compare(base, snap, Path(cfg["path"]).expanduser()) if base else []
    view = project["view"]
    view["since"] = {"comparedWith": base_time, "changes": changes}
    project["changes"], project["comparedWith"] = changes, base_time
    save_snapshot(folder, now, snap)
    counts = {group["key"]: len(group["items"]) for group in view["groups"]}
    summary = view["summary"]
    log_run(now, name, snap["head"], summary["stepsDone"], summary["stepsTotal"], counts["known"], counts["could"],
            len(changes))
    print(f"{name}: {summary['stepsDone']} of {summary['stepsTotal']} {summary['unit']} done, "
          f"{counts['known']} known problems, {counts['could']} could be problems, "
          f"{len(changes)} change{'' if len(changes) == 1 else 's'} since the last look "
          f"(read by itself in {project['seconds']} s).")
    return project


def ask_claude(config: dict, slug: str, now: dt.datetime) -> None:
    """The "Ask Claude" button: Claude reads one project, read-only, with Pulse's last facts; its answer is kept in
    state/<project>/claude-reading.json and shows in the briefing after this refresh."""
    import pulse_ask
    cfg = next((c for c in config.get("projects", []) if re.sub(r"[^A-Za-z0-9]+", "-", c.get("name", "")).strip("-")
                .lower() == slug), None)
    if not cfg:
        print(f"No project called {slug} in projects.json.", file=sys.stderr)
        return
    try:
        data = json.loads((HERE / "out" / "data.json").read_text(encoding="utf-8"))
        view = next((p for p in data.get("projects", []) if p.get("slug") == slug), {})
    except (OSError, ValueError):
        view = {}
    reading = pulse_ask.ask(view, Path(cfg["path"]).expanduser(), now)
    pulse_ask.save(reading, HERE / "state" / slug)
    print(f"{cfg.get('name')}: Claude's reading " + (f"not finished — {reading['problem']}" if reading["problem"]
                                                     and not reading["items"] else
                                                     f"has {len(reading['items'])} findings."))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project Pulse: one page that shows where each project stands.")
    parser.add_argument("--no-open", action="store_true", help="write the page without opening it")
    parser.add_argument("--ask", metavar="PROJECT", help="ask Claude to look at one project (uses your Claude plan), "
                                                          "then refresh")
    args = parser.parse_args(argv)

    config_file = HERE / "projects.json"  # a first run has none yet: nothing to read
    config = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {"projects": []}
    now = dt.datetime.now().astimezone()
    if args.ask:
        ask_claude(config, args.ask, now)
    pulse_any.SHARE_FOLDERS = True  # one reading of each folder per refresh
    pulse_claude.forget_this_run()
    projects = []
    for cfg in config.get("projects", []):
        name = cfg.get("name", "Project")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "project"
        try:
            if cfg.get("map"):
                project = read_mapped(cfg, now, slug)
                project["view"] = pulse_groups.app_view(project, slug)
            else:
                project = read_any(cfg, now, slug)
        except Exception as error:  # one broken project never hides the others
            project = {"name": name, "slug": slug, "error": f"{type(error).__name__}: {error}",
                       "trace": traceback.format_exc(limit=4)}
            print(f"{name}: couldn't be read — {project['error']}", file=sys.stderr)
        if "view" in project:
            try:
                pulse_briefing.enrich(project["view"], cfg, now, HERE)
            except Exception as error:  # the briefing never hides the rest
                project["view"].setdefault("notes", []).append(
                    f"Pulse couldn't finish the briefing: {type(error).__name__}: {error}")
                print(f"{name}: briefing not finished — {type(error).__name__}: {error}\n"
                      f"{traceback.format_exc(limit=4)}", file=sys.stderr)
        projects.append(project)
    views = [p["view"] for p in projects if "view" in p]
    added = {str(Path(cfg.get("path", "")).expanduser()) for cfg in config.get("projects", [])}
    extra = {"desk": pulse_briefing.desk(views, now),
             "globalPrompts": pulse_prompts.global_prompts(pulse_claude.claude_home()),
             "claudeFolders": [f for f in pulse_claude.folders_used() if f["path"] not in added][:20]}

    out = HERE / "out" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(render_page({"generatedAt": now.isoformat(timespec="seconds"), "projects": projects}),
                   encoding="utf-8")
    print(f"Page written: {out}")
    write_app_data(projects, now, extra)
    if not args.no_open:
        subprocess.run(["open", str(out)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
