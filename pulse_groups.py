"""Sorts Pulse's findings into the groups a person reads: Now, Next steps, Could be problems, Known problems,
Missing, Done and How it's set up — plus the roadmap (every stage and step, like the first chart) — and builds the
data the Pulse app shows (out/data.json).

Every item has a key that stays the same from refresh to refresh (a step keeps "step:RT-3c-C" as it moves from
Next to Done), so the app can keep comments attached to it.
"""
from __future__ import annotations

import os
import re

# Words in a known-issue note that make it "could be a problem" rather than a known one.
SUSPECT = re.compile(r"\b(suspected|unconfirmed|not tried|seen once|cause not proven|look again if it recurs)\b", re.I)
SLOWER_SHARE, SLOWER_MS = 0.05, 5  # a speed measure counts as slower past 5% and 5 ms
GROUPS = [
    ("now", "Now", "Being worked on, and work that isn't committed yet."),
    ("next", "Next steps", "Every step still to do, in the roadmap's order: ready to start, after another step, or "
                           "waiting on you. A step whose prompt is written shows the command that starts it."),
    ("could", "Could be problems", "Worth a look: fixes to confirm, suspected problems, slower speed, docs out of step."),
    ("known", "Known problems", "Parked for later."),
    ("missing", "Missing", "Steps whose prompt isn't written yet, and your errands."),
    ("done", "Done", "Finished steps, newest first."),
    ("setup", "How it's set up", "How this project is organised: the files that guide AI assistants, its plan, docs, "
                                 "code, tests and checks."),
]
# A gate that waits on the owner says so: "The owner runs it", "the owner decides", "owner's OK".
OWNER_DOES = re.compile(r"\b(the )?owner (runs|does|decides|tests|checks|signs|approves|enrols|buys|chooses)\b"
                        r"|\bwaits? on (the )?owner\b|\bowner'?s (decision|call|ok|approval)\b", re.I)
# A step's colour in the roadmap: done, in progress, prompt written (or outlined), prompt still to write.
ROAD_STATE = {"done": "done", "in-progress": "doing", "ready": "ready", "outlined": "ready", "to-write": "todo"}
LEGEND = [("done", "Done"), ("doing", "In progress"), ("ready", "Prompt written or outlined"),
          ("todo", "Prompt still to write"), ("blocked", "Blocked")]


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())[:60]


def day(iso_day: str) -> str:
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    year, month, dom = iso_day[:10].split("-")
    return f"{int(dom)} {months[int(month) - 1]}"


def prompt_verb(texts: list[str]) -> str:
    """How a project's docs say to start a step prompt ("say “do prompts/03a-library-core.md”" → "do")."""
    for text in texts:
        found = re.search(r"[\"“`]\s*([A-Za-z][\w ]{0,24}?)\s+@?[\w./-]*prompts?/[\w./-]+\.md\s*[\"”`]", text or "")
        if found:
            return found.group(1).strip()
    return "do"


def command_for(path: str | None, root: str | None, verb: str) -> str | None:
    """What to type in Claude Code, in the project's folder, to start a step: "do docs/prompts/RT-3c-D-….md"."""
    if not path:
        return None
    rel = os.path.relpath(path, root) if root and os.path.isabs(path) else path
    return f"{verb} {rel}"


def home_summary(items: dict[str, list[dict]], last_activity: str | None) -> dict:
    """What the homepage shows for a project: its next step, how much waits on the owner, and warning signs."""
    step = next((i for i in items["next"] if not i["key"].startswith(("git:", "note:", "list:"))), None)
    flags: list[dict] = []
    for item in items["now"]:
        if item["key"] == "uncommitted":
            flags.append({"text": item["title"], "tone": "now"})
    for item in items["next"]:
        if item["key"] == "git:unpushed":
            flags.append({"text": item["title"], "tone": "you"})
    for prefix, one, many in (("secret:", "possible key written in a file", "possible keys written in files"),
                              ("tests:", "failed test run", "failed test runs"), ("log:", "log with errors",
                                                                                   "logs with errors"),
                              ("git:stash", "stash of unsaved work", "stashes of unsaved work"),
                              ("git:branch:", "branch with work of its own", "branches with work of their own"),
                              ("copies:", "set of copies of a file", "sets of copies of a file")):
        count = sum(1 for item in items["could"] if item["key"].startswith(prefix))
        if count:
            flags.append({"text": f"{count} {one if count == 1 else many}", "tone": "could"})
    waiting = [item for key in ("now", "next", "could", "known", "missing") for item in items[key] if item.get("you")]
    return {"next": {k: step.get(k) for k in ("key", "label", "title", "detail", "command")} if step else None,
            "needsYou": len(waiting), "lastActivity": last_activity, "flags": flags}


def categorize(project: dict) -> dict:
    """Pulse's findings, sorted into the groups (each "could be" entry carries a stable key)."""
    steps = [s for stage in project["stages"] for s in stage["steps"]]
    others = project["otherSteps"]
    issues_path = (project.get("sources") or {}).get("knownIssues")
    could: list[dict] = []
    for issue in project["issues"]:
        key = f"issue:{norm(issue['text'])}"
        if issue["state"] == "confirm":
            could.append({"key": key, "why": issue["note"] or "Fixed, waiting to be confirmed",
                          "text": issue["title"], "path": issues_path})
        elif SUSPECT.search(issue["text"]):
            could.append({"key": key, "why": "Suspected, not proven", "text": issue["title"], "path": issues_path})
    for kind in project.get("perf", []):
        before = {m["name"]: m for m in (kind.get("previous") or {}).get("metrics", [])}
        for m in kind["latest"]["metrics"]:
            b = before.get(m["name"])
            if b and m["median"] - b["median"] >= SLOWER_MS and m["median"] > b["median"] * (1 + SLOWER_SHARE):
                could.append({"key": f"speed:{norm(kind['label'])}:{norm(m['name'])}",
                              "why": f"Slower than the run before ({kind['label'].lower()})",
                              "text": f"{m['name']}: {b['median']} → {m['median']} ms", "path": kind["latest"]["path"]})
    for warning in project["warnings"]:
        could.append({"key": f"warning:{warning['key']}", "why": "Docs out of step", "text": warning["text"],
                      "path": warning.get("file")})
    return {
        "now": [s for s in steps + others if s["status"] == "in-progress"],
        "ready": [s for s in steps if s["readiness"] == "ready"],
        "waits": project["waitsOnYou"],
        # Prompt written, but its turn hasn't come: after another step, or later in the road.
        "later": [s for s in steps if s["status"] == "ready" and s["readiness"] in ("blocked", "later")
                  and not s.get("outside")],
        "could": could,
        "known": [i for i in project["issues"] if i["state"] != "confirm" and not SUSPECT.search(i["text"])],
        "missingPrompts": [s for s in steps if s["status"] in ("to-write", "outlined")],
        "errands": [e for e in project["errands"] if not e["done"]],
        "done": [s for s in steps if s["status"] == "done"] + [s for s in others if s["status"] == "done"],
    }


def step_detail(s: dict) -> str:
    """Where a step that isn't done stands: "Ready to start", "After RT-3c-C", "Waits on you: owner OK"."""
    if s.get("outside"):
        text = "Waits on you: " + ", ".join(s["outside"])
        if s.get("blockedBy"):
            text += f" · also after {', '.join(s['blockedBy'])}"
    elif s.get("readiness") == "blocked" and s.get("blockedBy"):
        text = f"After {', '.join(s['blockedBy'])}"
    elif s.get("readiness") == "later":
        text = "Later in the road"
    else:
        text = "Ready to start"
    return text


def roadmap_view(project: dict, verb: str) -> dict:
    """Every stage and step in the roadmap's order, like the first chart: tiles, coloured size bars, who each step
    waits on, the proofs and release gates, the owner's errands and what comes after."""
    root = project.get("path")
    steps = [s for stage in project["stages"] for s in stage["steps"]]
    left = [s for s in steps if s["status"] != "done"]
    mix = {size: sum(1 for s in left if s.get("size") == size) for size in "SML"}
    stages, seen = [], set()
    for stage in project["stages"]:
        rows = []
        for s in stage["steps"]:
            state = ROAD_STATE.get(s["status"], "todo")
            seen.add(state)
            if state == "done":
                detail = f"Done {day(s['date'])}" if s.get("date") else "Done"
            elif state == "doing":
                detail = "In progress" + (f" · {s['note']}" if s.get("note") else "")
            else:
                detail = step_detail(s) + (" · prompt written" if s.get("prompt") else
                                           " · outlined in the audit" if s["status"] == "outlined" else
                                           " · prompt not written yet")
            rows.append({"key": f"step:{s['id']}", "label": s["id"], "name": s["name"], "state": state,
                         "size": s.get("size"), "you": bool(s.get("outside")) and state != "done",
                         "cut": bool(s.get("cut")), "detail": detail, "path": s.get("link"),
                         "command": command_for(s.get("prompt"), root, verb) if state != "done" else None})
        all_done = bool(rows) and all(r["state"] == "done" for r in rows)
        stages.append({"stageID": stage["name"], "name": stage.get("title") or stage["name"],
                       "note": "all done" if all_done else stage.get("note", ""), "rows": rows})
    gates, before = [], None
    for gate in project.get("gates", []):
        arrow = before is not None and (gate.get("stage") != before.get("stage") or gate.get("arrow")
                                        or before.get("arrow"))
        gates.append({"name": gate["name"], "state": {"done": "done", "next": "next", "in-progress": "doing"}.get(
                      gate.get("status"), "todo"), "you": bool(OWNER_DOES.search(gate.get("text", ""))),
                      "detail": gate.get("note") or gate.get("text", "")[:200], "arrowBefore": bool(arrow),
                      "path": gate.get("link") or (project.get("sources") or {}).get("roadmap")})
        before = gate
    later = [{"group": idea["group"], "label": "", "text": idea["title"]} for idea in project.get("ideas", [])]
    return {
        "path": (project.get("sources") or {}).get("roadmap"),
        "unit": "steps",
        "sized": True,
        "tiles": [
            {"label": "Build steps done", "value": str(len(steps) - len(left)), "suffix": f"of {len(steps)}"},
            {"label": "Build steps left", "value": str(len(left)), "suffix": ""},
            {"label": "Mix left (S / M / L)", "value": f"{mix['S']} / {mix['M']} / {mix['L']}", "suffix": ""},
            {"label": "Work done, by size", "value": f"{project['summary']['workDonePct']}%", "suffix": ""},
        ],
        "legend": [{"state": state, "text": text} for state, text in LEGEND if state in seen],
        "stages": stages,
        "gatesTitle": "Proofs and release gates",
        "gatesNote": "not sized, run in order",
        "gates": gates,
        "errands": [{"text": e["text"], "done": e["done"]} for e in project.get("errands", [])],
        "laterTitle": "After v1" if later else None,
        "later": later,
    }


def app_view(project: dict, slug: str) -> dict:
    """What the Pulse app shows for one project. Each item is in exactly one group."""
    cats = categorize(project)
    sources = project.get("sources") or {}
    root = project.get("path")
    verb = project.get("promptVerb", "do")
    items: dict[str, list[dict]] = {key: [] for key, _, _ in GROUPS}

    def add(group: str, key: str, label: str, title: str, detail: str = "", path: str | None = None,
            time: str | None = None, command: str | None = None, you: bool = False) -> None:
        items[group].append({"key": key, "label": label, "title": title, "detail": detail, "path": path,
                             "time": time, "command": command, "you": you})

    for s in cats["now"]:
        add("now", f"step:{s['id']}", s["id"], s["name"],
            "In progress" + (f" · {s['note']}" if s.get("note") else ""), s.get("link"),
            command=command_for(s.get("prompt"), root, verb))
    git = project["git"]
    if git.get("ok") and git["uncommitted"]["files"]:
        u = git["uncommitted"]
        count = len(u["files"])
        add("now", "uncommitted", "git", f"{count} file{'' if count == 1 else 's'} not committed yet",
            f"+{u['added']} −{u['removed']} lines · last edit", None, u.get("newestEdit"))

    # Next steps, in the roadmap's order: ready, waiting on you, and prompts written ahead of their turn.
    wanted = {s["id"] for s in cats["ready"]} | {w["id"] for w in cats["waits"]} | {s["id"] for s in cats["later"]}
    in_next = set()
    for stage in project["stages"]:
        for s in stage["steps"]:
            if s["id"] not in wanted or s["status"] in ("done", "in-progress"):
                continue
            in_next.add(s["id"])
            prompt = "prompt written" if s.get("prompt") else "prompt not written yet"
            add("next", f"step:{s['id']}", s["id"], s["name"],
                f"{step_detail(s)} · {prompt}" + (" · on the cut line" if s.get("cut") else ""),
                s.get("prompt") or s.get("link"), command=command_for(s.get("prompt"), root, verb),
                you=bool(s.get("outside")))
    for w in cats["waits"]:  # waiting on you, but not a step in the road
        if w["id"] not in in_next:
            in_next.add(w["id"])
            add("next", f"step:{w['id']}", w["id"], w["name"], "Waits on you: " + ", ".join(w["outside"]),
                w.get("link"), you=True)

    for c in cats["could"]:
        add("could", c["key"], c["why"], c["text"], "", c.get("path"))
    for i in cats["known"]:
        add("known", f"issue:{norm(i['text'])}", i["area"], i["title"], "", sources.get("knownIssues"))

    for s in cats["missingPrompts"]:
        if s["id"] in in_next:
            continue
        add("missing", f"step:{s['id']}", s["id"], s["name"],
            ("Outlined; prompt not written yet" if s["status"] == "outlined" else "Prompt not written yet")
            + (f" · after {', '.join(s['blockedBy'])}" if s.get("blockedBy") else ""), s.get("link"))
    for e in cats["errands"]:
        add("missing", f"errand:{norm(e['text'])}", "errand", e["text"], "Your errand", sources.get("nextUp"),
            you=True)

    for s in sorted(cats["done"], key=lambda s: s.get("date") or "", reverse=True):
        add("done", f"step:{s['id']}", s["id"], s["name"], f"Done {day(s['date'])}" if s.get("date") else "Done",
            s.get("link"))

    for extra in project.get("extras", []):  # forgotten work: commits not pushed, stashes, other branches
        entry = {k: v for k, v in extra.items() if k != "group"}
        if not any(i["key"] == entry["key"] for i in items[extra["group"]]):
            items[extra["group"]].append(entry)

    map_parts = [f"{name}: {os.path.relpath(path, root) if root else path}" for name, path in (
        ("roadmap", sources.get("roadmap")), ("next up", sources.get("nextUp")),
        ("known issues", sources.get("knownIssues")), ("step write-ups", sources.get("steps")),
        ("prompts", sources.get("prompts"))) if path]
    setup = list(project.get("setup", []))
    at = next((n for n, item in enumerate(setup) if item.get("label") != "AI"), len(setup))
    if map_parts:
        setup.insert(at, {"key": "setup:map", "label": "plan", "title": "Plan: read through Pulse's map",
                          "detail": " · ".join(map_parts) + " (set in Pulse's projects.json)",
                          "path": sources.get("roadmap"), "time": None, "command": None})
    items["setup"] = setup

    head = git.get("head") if git.get("ok") else None
    edits = [d for d in ((head or {}).get("date"), (git.get("uncommitted") or {}).get("newestEdit")) if d]
    return {
        "name": project["name"],
        "slug": slug,
        "path": project.get("path"),
        "kind": "map",
        "home": home_summary(items, max(edits) if edits else None),
        "summary": {**{k: project["summary"][k] for k in ("stepsDone", "stepsTotal", "workDonePct")},
                    "unit": "steps", "weighted": True},
        "stages": [{"name": st["name"], "done": sum(1 for s in st["steps"] if s["status"] == "done"),
                    "total": len(st["steps"])} for st in project["stages"]],
        "since": {"comparedWith": project.get("comparedWith"), "changes": project.get("changes", [])},
        "lastCommit": {"short": head["short"], "subject": head["subject"], "date": head["date"]} if head else None,
        "layout": project.get("layout", []),
        "readers": [],
        "notes": [],
        "roadmap": roadmap_view(project, verb),
        "groups": [{"key": key, "title": title, "hint": hint, "items": items[key]} for key, title, hint in GROUPS],
    }
