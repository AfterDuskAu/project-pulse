"""The briefing: where a project stands, said in a few plain sentences, the way a good assistant would tell you.

"Good evening. Trailmix is 40% done. We're on the beta test, which waits on you. Next up: step 11; its prompt is
written. The last build passed today at 19:07. Trailmix crashed today at 13:42 (an uncaught exception in
MapCache.load). First move is yours: the beta test."

It also adds to each project what Claude Code, crash reports and checklists say (enrich), and the four gauges the
briefing shows: build, tests, crashes, safety.

How it words things (so a briefing never says more than the files prove):
- A status (done, next) comes only from the project's own plan and write-ups; what Claude said is quoted as Claude's.
- A test or build result is past tense, with when and how much ran ("the tests Claude picked"), and says when it
  was before the latest commit. No result on record is said as such, never as "no errors".
- A crash is an event with its time, never "it keeps crashing".
- Every line says where it comes from, so a click can show the proof.
Read-only, no network, no AI (the greeting and the name are added by the app when it shows the briefing).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pulse_any
import pulse_checks
import pulse_claude
import pulse_errors
import pulse_prompts
from pulse_base import git

WEEK = dt.timedelta(days=7)
DESK_PROJECTS = 6  # the homepage's briefing names the most recently active ones


# ---------------------------------------------------------------- small wording helpers

def parse(stamp: str | None) -> dt.datetime | None:
    if not stamp:
        return None
    try:
        moment = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.astimezone()


def moment(stamp: str | None, now: dt.datetime) -> str:
    """"today at 17:03", "yesterday at 09:12", "on Monday at 14:00", "on 22 Sep"."""
    when = parse(stamp)
    if not when:
        return ""
    when = when.astimezone(now.tzinfo)
    days = (now.date() - when.date()).days
    clock = when.strftime("%H:%M")
    if days <= 0:
        return f"today at {clock}"
    if days == 1:
        return f"yesterday at {clock}"
    if days < 7:
        return f"on {when.strftime('%A')} at {clock}"
    return f"on {when.day} {when.strftime('%b')}"


def plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def spoken(text: str) -> str:
    """The same sentence for the voice: an aside with a path left out, a path said as its file's name, a file's name
    without its extension, and no symbols it would spell out."""
    text = re.sub(r"\s*\([^)]*[/\\][^)]*\)", "", text)                     # "(docs/NEXT-UP.md)"
    text = re.sub(r"(?:[\w.-]+/)+([\w.-]+)", r"\1", text)                     # "App/Sources/Grid.swift" → "Grid.swift"
    text = re.sub(r"\b([\w-]+)\.(?:md|swift|py|json|txt|sh|log|ips|js|ts|tsx|jsx|html|css)\b", r"\1", text)
    text = text.replace("—", ",").replace("·", ",").replace("“", "").replace("”", "").replace("`", "")
    text = re.sub(r"\s{2,}", " ", text)
    return re.sub(r"\s+([,.])", r"\1", text).strip()


def line(kind: str, text: str, tone: str = "info", source: str | None = None, path: str | None = None,
         group: str | None = None, key: str | None = None) -> dict:
    return {"kind": kind, "text": text, "say": spoken(text), "tone": tone,
            "source": {"label": source, "path": path} if source else None,
            "target": {"group": group, "key": key} if group else None}


# ---------------------------------------------------------------- gathering: Claude Code, crashes, checklists

def load_ticks(home: Path, slug: str) -> dict:
    try:
        ticks = json.loads((home / "comments" / f"{slug}.ticks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return ticks if isinstance(ticks, dict) else {}


def items_of(view: dict) -> dict[str, list[dict]]:
    return {group["key"]: group["items"] for group in view.get("groups") or []}


def env_in_git(folder) -> bool:
    return ".env" in folder.file_set and folder.in_git and bool((git(folder.root, "ls-files", ".env") or "").strip())


def enrich(view: dict, cfg: dict, now: dt.datetime, home: Path) -> None:
    """Adds to a project's view: its Claude Code conversations, crashes, checklists, prompts, the four gauges, and the
    briefing. Each part is fenced off: one that fails is noted and the others carry on."""
    root = Path(cfg["path"]).expanduser()
    off = set(cfg.get("off") or [])
    folder = pulse_any.folder_for(root, now)
    notes = view.setdefault("notes", [])
    claude = None
    if "claude" not in off:
        try:
            claude = pulse_claude.read_project(root, home / "state" / "claude", now)
        except Exception as error:  # Claude Code changed its files: say so, carry on
            notes.append(f"Pulse couldn't read Claude Code's conversations: {type(error).__name__}: {error}")
    if claude and claude.get("unreadable"):
        version = claude["unreadable"].get("version") or "this version"
        notes.append(f"Pulse couldn't fully read {plural(claude['unreadable']['count'], 'conversation')} "
                     f"(Claude Code {version}): what they say about tests and builds may be missing.")
    view["claude"] = claude
    items = items_of(view)
    every = [i for group in items.values() for i in group]
    test_run = (claude or {}).get("lastWholeTest") or (claude or {}).get("lastTest")
    if any(i["key"].startswith("tests:") for i in every):
        test_run = {"outcome": "fail", "command": "pytest", "time": ""}
    facts = {
        "secrets": sum(1 for i in every if i["key"].startswith("secret:")),
        "copies": sum(1 for i in every if i["key"].startswith("copies:")),
        "testFiles": sum(1 for f in folder.files if pulse_any.TEST_FILE.search(f)),
        "plan": bool((view.get("summary") or {}).get("stepsTotal")),
        "knownIssues": bool(items.get("known")) or bool(folder.named("KNOWN-ISSUES.md", "known-issues.md",
                                                                     "KNOWN_ISSUES.md", "ISSUES.md")),
        "lastTestRun": {**test_run, "time": test_run.get("at") or test_run.get("time", "")} if test_run else None,
        "envInGit": env_in_git(folder),
    }
    ctx = pulse_checks.Context(folder, facts)
    crashes, xcode = [], None
    if "crashes" not in off:
        try:
            crashes = pulse_errors.crashes(pulse_errors.names_for(ctx), now)
            xcode = pulse_errors.xcode_build(root)
        except Exception as error:
            notes.append(f"Pulse couldn't read the crash reports: {type(error).__name__}: {error}")
    view["crashes"], view["xcodeBuild"] = crashes, xcode
    if "checklists" not in off:
        try:
            view["checklists"] = pulse_checks.checklists(folder, facts, load_ticks(home, view["slug"]),
                                                         cfg.get("checklists"), cfg.get("hiddenChecklists"))
        except Exception as error:
            view["checklists"] = []
            notes.append(f"Pulse couldn't work out the checklists: {type(error).__name__}: {error}")
    else:
        view["checklists"] = []
    view["checklistCatalog"] = pulse_checks.catalog()
    try:
        verb = next((r["command"].split(" ", 1)[0] for s in (view.get("roadmap") or {}).get("stages") or []
                     for r in s["rows"] if r.get("command")), "do")
        view["prompts"] = pulse_prompts.library(folder, view, claude, verb)
    except Exception as error:
        view["prompts"] = None
        notes.append(f"Pulse couldn't list the prompts: {type(error).__name__}: {error}")
    add_items(view, claude, crashes, now)
    view["gauges"] = gauges(view, folder, ctx, claude, crashes, xcode, now)
    reading = home / "state" / view["slug"] / "claude-reading.json"
    try:
        view["claudeReading"] = json.loads(reading.read_text(encoding="utf-8")) if reading.exists() else None
    except (OSError, ValueError):
        view["claudeReading"] = None
    view["brief"] = compose(view, now)


def add_items(view: dict, claude: dict | None, crashes: list[dict], now: dt.datetime) -> None:
    """What Claude Code and the crash reports found, as items on the lists (with keys that stay put for notes)."""
    groups = {group["key"]: group for group in view.get("groups") or []}
    home = view.setdefault("home", {"next": None, "needsYou": 0, "lastActivity": None, "flags": []})
    flags = home.setdefault("flags", [])

    def add(group: str, item: dict) -> None:
        if group in groups:
            groups[group]["items"].insert(0, {"path": None, "time": None, "command": None, "you": False, **item})

    working = [s for s in (claude or {}).get("sessions", []) if s["state"] == "working"]
    for session in working[:3]:
        add("now", {"key": f"claude:working:{session['id']}", "label": "Claude",
                    "title": f"Claude is working on “{session['title']}”",
                    "detail": f"Started {moment(session['started'], now)} · {plural(session['prompts'], 'prompt')}",
                    "time": session["ended"]})
    if working:
        flags.insert(0, {"text": "Claude is working now", "tone": "now"})
    busy = bool(working)
    for name, verdict in (("test", (claude or {}).get("lastTest")), ("build", (claude or {}).get("lastBuild"))):
        if verdict and verdict["outcome"] == "fail" and (parse(verdict["at"]) or now) > now - WEEK:
            scope = f" (only {verdict['scope']})" if verdict.get("scope") else ""
            add("could", {"key": f"claude:{name}", "label": "tests" if name == "test" else "build",
                          "title": f"The last {'test run' if name == 'test' else 'build'} failed{scope}",
                          "detail": f"{verdict['detail']} · {verdict['command']} · in “{verdict['sessionTitle']}”"
                                    + (" · Claude is working on it now" if busy else ""),
                          "time": verdict["at"]})
            if not busy:
                flags.append({"text": "Tests failed" if name == "test" else "Build failed", "tone": "could"})
    for crash in crashes[:3]:
        if (parse(crash["at"]) or now) < now - WEEK:
            continue
        where = f" in {crash['where']}" if crash.get("where") else ""
        add("could", {"key": f"crash:{crash['app']}:{crash['at']}", "label": "test crash" if crash.get("tests")
                      else "crash",
                      "title": f"{crash['app']} crashed {moment(crash['at'], now)}",
                      "detail": f"{crash['exception']}{where} · the crash report opens in Console",
                      "path": crash["path"], "time": crash["at"]})
    if crashes and (parse(crashes[0]["at"]) or now) > now - WEEK:
        flags.append({"text": f"Crashed {moment(crashes[0]['at'], now)}", "tone": "could"})
    for session in (claude or {}).get("stops", [])[:3]:
        stop = session["stop"]
        if stop["why"] == "noreply":
            continue
        why = {"limit": "hit the usage limit", "api": "stopped on an error", "interrupted": "was stopped by you",
               "midwork": "stopped in the middle of its work", "full": "ran out of room"}.get(stop["why"], "stopped")
        add("could", {"key": f"claude:stop:{session['id']}", "label": "Claude",
                      "title": f"A Claude session {why}",
                      "detail": f"“{session['title']}” · {stop['text']} · the last prompt can be sent again",
                      "command": session.get("lastPrompt"), "time": stop.get("at")})


# ---------------------------------------------------------------- the four gauges

def stale(stamp: str | None, view: dict, folder) -> str:
    """Why a result may no longer be true: " · before the latest commit", " · files changed since", or ""."""
    when = parse(stamp)
    if not when:
        return ""
    commit = parse((view.get("lastCommit") or {}).get("date"))
    if commit and commit > when:
        return " · before the latest commit"
    edited = parse(((folder.git or {}).get("uncommitted") or {}).get("newestEdit"))
    return " · files changed since" if edited and edited > when else ""


def gauges(view: dict, folder, ctx, claude: dict | None, crashes: list[dict], xcode: dict | None,
           now: dt.datetime) -> list[dict]:
    busy = bool((claude or {}).get("working"))
    shown = []

    # Build: Claude's newest build, or Xcode's own record when that's newer.
    build = (claude or {}).get("lastBuild")
    source = f"Claude Code: {build['command']}" if build else None
    if xcode and (not build or (xcode["at"] or "") > (build["at"] or "")):
        build = {**xcode, "detail": f"{plural(xcode['errors'], 'error')}, {plural(xcode['warnings'], 'warning')}"}
        source = "Xcode's own record of its last build"
    if build and build["outcome"] == "unknown" and build.get("before"):
        build = {**build["before"], "note": "the newest one didn't say"}
    if not build:
        shown.append({"key": "build", "label": "Build", "state": "none", "value": "No build on record",
                      "detail": "", "at": None, "source": None})
    else:
        state = {"pass": "good", "fail": "bad"}.get(build["outcome"], "none")
        value = {"pass": "Passed", "fail": "Failed"}.get(build["outcome"], "Result not captured")
        detail = moment(build["at"], now) + stale(build["at"], view, folder)
        if state == "bad" and busy:
            state, detail = "busy", detail + " · Claude is working now"
        shown.append({"key": "build", "label": "Build", "state": state, "value": value,
                      "detail": detail, "at": build["at"], "source": source, "why": build.get("detail")})

    # Tests: the newest run, with how much of the suite it was.
    tests = (claude or {}).get("lastTest")
    whole = (claude or {}).get("lastWholeTest")
    items = items_of(view)
    pytest_failed = [i for i in items.get("could", []) if i["key"].startswith("tests:")]
    if pytest_failed and not tests:
        shown.append({"key": "tests", "label": "Tests", "state": "bad", "value": "Failed",
                      "detail": pytest_failed[0]["title"], "at": pytest_failed[0].get("time"),
                      "source": "pytest's own record", "why": pytest_failed[0]["detail"]})
    elif not tests:
        shown.append({"key": "tests", "label": "Tests", "state": "none",
                      "value": "No test run on record" if ctx.facts.get("testFiles", 1) else "No tests",
                      "detail": "", "at": None, "source": None})
    else:
        if tests["outcome"] == "unknown" and tests.get("before"):
            tests = {**tests["before"], "note": "the newest one didn't say"}
        state = {"pass": "good", "fail": "bad"}.get(tests["outcome"], "none")
        count = f"{tests['tests']:,} tests" if tests.get("tests") else ""
        value = {"pass": "Passed", "fail": "Failed"}.get(tests["outcome"], "Result not captured")
        if tests.get("scope"):
            picked = f"{count or 'Some tests'} picked by {tests['scope']}"
        else:
            picked = f"All {count}" if count else "All tests"
        detail = " · ".join(p for p in (picked, moment(tests["at"], now)) if p)
        if tests.get("scope") and whole and whole["outcome"] in ("pass", "fail"):
            detail += f" · all tests {'passed' if whole['outcome'] == 'pass' else 'failed'} {moment(whole['at'], now)}"
        detail += stale(tests["at"], view, folder)
        if state == "bad" and busy:
            state, detail = "busy", detail + " · Claude is working now"
        shown.append({"key": "tests", "label": "Tests", "state": state, "value": value, "detail": detail,
                      "at": tests["at"], "source": f"Claude Code: {tests['command']}", "why": tests.get("detail")})

    # Crashes: this week's, the app's own apart from its test runs'.
    week = [c for c in crashes if (parse(c["at"]) or now) > now - WEEK]
    app_crashes = [c for c in week if not c.get("tests")]
    test_crashes = [c for c in week if c.get("tests")]
    if week:
        latest = (app_crashes or test_crashes)[0]
        where = f" in {latest['where']}" if latest.get("where") else ""
        parts = [plural(len(app_crashes), "app crash", "app crashes")] if app_crashes else []
        parts += [plural(len(test_crashes), "test-run crash", "test-run crashes")] if test_crashes else []
        shown.append({"key": "crashes", "label": "Crashes", "state": "bad" if app_crashes else "warn",
                      "value": " · ".join(parts) + " this week",
                      "detail": f"Last {moment(latest['at'], now)}: {latest['exception']}{where}",
                      "at": latest["at"], "source": "macOS crash reports", "path": latest["path"]})
    else:
        shown.append({"key": "crashes", "label": "Crashes", "state": "good" if ctx.xcode or crashes else "none",
                      "value": "None this week" if ctx.xcode or crashes else "No app to crash",
                      "detail": "From macOS's crash reports" if ctx.xcode else "", "at": None,
                      "source": "macOS crash reports"})

    # Safety: keys in files, work that isn't committed or pushed.
    every = [i for group in items.values() for i in group]
    keys = [i for i in every if i["key"].startswith("secret:")]
    unpushed = next((i for i in every if i["key"] == "git:unpushed"), None)
    uncommitted = next((i for i in every if i["key"] == "uncommitted"), None)
    if keys:
        shown.append({"key": "safety", "label": "Safety", "state": "bad", "value": "A key is written in a file",
                      "detail": keys[0]["title"], "at": None, "source": "Pulse's key check"})
    elif not folder.in_git:
        shown.append({"key": "safety", "label": "Safety", "state": "warn", "value": "No git: no undo",
                      "detail": "Nothing records the changes, so a bad edit can't be undone", "at": None,
                      "source": None})
    elif unpushed or uncommitted:
        parts = [p["title"] for p in (uncommitted, unpushed) if p]
        shown.append({"key": "safety", "label": "Safety", "state": "warn", "value": "Not backed up yet",
                      "detail": " · ".join(parts), "at": None, "source": "git"})
    else:
        remote = ctx.remote()
        shown.append({"key": "safety", "label": "Safety", "state": "good" if remote["remotes"] else "warn",
                      "value": "Committed and pushed" if remote["remotes"] else "Only on this Mac",
                      "detail": "No keys found in the files" if remote["remotes"]
                      else "No copy on GitHub or another server", "at": None, "source": "git"})
    return shown


# ---------------------------------------------------------------- the briefing

def compose(view: dict, now: dt.datetime) -> dict:
    """A project's briefing: a handful of lines, most important first, each with where it comes from."""
    name = view["name"]
    items = items_of(view)
    summary = view.get("summary") or {}
    roadmap = view.get("roadmap") or {}
    claude = view.get("claude") or {}
    lines: list[dict] = []
    source_plan = (roadmap.get("path") or "").rsplit("/", 1)[-1] or None

    # Where it stands.
    if summary.get("stepsTotal"):
        unit = summary.get("unit") or "steps"
        text = f"{name} is {summary['workDonePct']}% done: {summary['stepsDone']} of {summary['stepsTotal']} {unit}."
        stage = next((s for s in view.get("stages") or [] if s["done"] < s["total"]), None)
        if stage and re.match(r"(stage|phase|milestone|part|sprint|week)\b", stage["name"], re.I):
            text = text[:-1] + f", in {stage['name'].split(' —')[0].split(' -')[0].strip()}."
        lines.append(line("status", text, source=source_plan, path=roadmap.get("path"), group="roadmap"))
    else:
        recent = next((i for i in items.get("now", []) if i["key"].startswith("edit:")), None)
        text = f"{name} has no plan Pulse can read yet."
        if recent:
            text += f" You last worked on {recent['title'].replace('edited ', '')}."
        lines.append(line("status", text, group="missing"))

    # Claude at work right now.
    working = [s for s in claude.get("sessions", []) if s["state"] == "working"]
    if working:
        more = f", and {plural(len(working) - 1, 'other session')}" if len(working) > 1 else ""
        lines.append(line("working", f"Claude is working on “{working[0]['title']}” right now{more}.", "busy",
                          source="Claude Code", group="claude", key=working[0]["id"]))

    # What we're on, what's next, what waits on the owner.
    now_item = next((i for i in items.get("now", []) if not i["key"].startswith(
        ("claude:", "uncommitted", "edit:", "more:", "changelog")) and i.get("label") not in ("edited", "more")), None)
    if now_item:
        waiting_names = {g["name"] for g in roadmap.get("gates") or [] if g.get("you")}
        waiting_names |= {r["label"] for s in roadmap.get("stages") or [] for r in s["rows"] if r.get("you")}
        waits = " It waits on you." if now_item.get("you") or now_item.get("label") in waiting_names else ""
        if waits:
            now_item = {**now_item, "you": True}
        label = f"{now_item['label']}: " if now_item.get("label") and now_item["label"] not in now_item["title"] else ""
        lines.append(line("now", f"We're on {label}{now_item['title']}.{waits}", "you" if waits else "info",
                          source=short_source(now_item), path=now_item.get("path"), group="now", key=now_item["key"]))
    nxt = (view.get("home") or {}).get("next")
    if nxt and (not now_item or nxt["key"] != now_item["key"]):
        written = "prompt written" in (nxt.get("detail") or "")
        tail = " Its prompt is written." if written else (" It waits on you." if "Waits on you" in (nxt.get("detail")
                                                                                                  or "") else "")
        lines.append(line("next", f"Next up: {nxt['label']}, {nxt['title']}.{tail}", source=source_plan,
                          path=roadmap.get("path"), group="roadmap", key=nxt["key"]))
    yours = [i for group in ("now", "next", "could", "known", "missing") for i in items.get(group, [])
             if i.get("you") and i["key"] not in {(now_item or {}).get("key"), (nxt or {}).get("key")}]
    if yours:
        first = yours[0]
        lines.append(line("you", f"{plural(len(yours), 'other thing waits', 'other things wait')} on you, starting "
                                 f"with {first['title'].rstrip('.')}.", "you", group="next", key=first["key"]))

    # Errors, honestly.
    errors = error_lines(view, now)
    lines.extend(errors)

    # Since last time.
    changes = (view.get("since") or {}).get("changes") or []
    finished = [c for c in changes if c["kind"] == "finished"]
    commits = [c for c in changes if c["kind"] == "commit"]
    if finished or commits:
        parts = [plural(len(finished), "step") + " finished" if finished else "",
                 plural(len(commits), "commit") if commits else ""]
        when = moment((view.get("since") or {}).get("comparedWith"), now)
        lines.append(line("since", f"Since {when.replace('today ', '').replace('at ', '') or 'the last look'}: "
                                   f"{' and '.join(p for p in parts if p)}.", group="done"))

    # The release checklist.
    release = next((c for c in view.get("checklists") or [] if c["id"] != "basics"), None)
    if release and release["total"]:
        blocker = next((r for r in release["items"] if r["state"] == "fail"), None)
        text = f"{release['title']} checklist: {release['done']} of {release['total']} done"
        text += f"; first blocker: {blocker['text'].rstrip('.')}." if blocker else "."
        tone = "bad" if blocker else ("good" if release["done"] == release["total"] else "info")
        lines.append(line("release", text, tone, source="Pulse's checklist", group="checklists"))

    return {"lines": lines, "close": first_move(view, now_item, nxt, errors, items), "at": now.isoformat(
        timespec="seconds")}


def short_source(item: dict) -> str | None:
    path = item.get("path") or ""
    return path.rsplit("/", 1)[-1] or None


def error_lines(view: dict, now: dt.datetime) -> list[dict]:
    """Builds, tests, crashes and stopped sessions: what the records say, when, and how sure."""
    found = []
    gauges_by = {g["key"]: g for g in view.get("gauges") or []}
    claude = view.get("claude") or {}
    build, tests, crashes = gauges_by.get("build"), gauges_by.get("tests"), gauges_by.get("crashes")
    if build and build["state"] in ("bad", "busy"):
        found.append(line("error", f"The last build failed {build['detail']}: {build.get('why') or ''}".rstrip(": ")
                          + ".", "busy" if build["state"] == "busy" else "bad", source=build["source"],
                          group="could", key="claude:build"))
    if tests and tests["state"] in ("bad", "busy"):
        found.append(line("error", f"The last test run failed ({tests['detail']}): {tests.get('why') or ''}".rstrip(": ")
                          + ".", "busy" if tests["state"] == "busy" else "bad", source=tests["source"],
                          group="could", key="claude:test"))
    week = [c for c in view.get("crashes") or [] if (parse(c["at"]) or now) > now - WEEK]
    app_crashes = [c for c in week if not c.get("tests")]
    test_crashes = [c for c in week if c.get("tests")]
    if app_crashes:
        latest = app_crashes[0]
        where = f" in {latest['where']}" if latest.get("where") else ""
        more = f" ({len(app_crashes)} app crashes this week)" if len(app_crashes) > 1 else ""
        found.append(line("error", f"{latest['app']} crashed {moment(latest['at'], now)}: {latest['exception']}"
                                   f"{where}{more}.", "bad", source="crash report", path=latest["path"],
                          group="could", key=f"crash:{latest['app']}:{latest['at']}"))
    if test_crashes:
        latest = test_crashes[0]
        where = f" in {latest['where']}" if latest.get("where") else ""
        found.append(line("error", f"A test run crashed {moment(latest['at'], now)}: {latest['exception']}{where}"
                                   + (f" ({plural(len(test_crashes), 'test-run crash', 'test-run crashes')} this "
                                      f"week)." if len(test_crashes) > 1 else "."),
                          "bad", source="crash report", path=latest["path"], group="could",
                          key=f"crash:{latest['app']}:{latest['at']}"))
    for session in claude.get("stops", [])[:2]:
        stop = session["stop"]
        if stop["why"] in ("noreply", "interrupted"):
            continue
        why = {"limit": "hit the usage limit", "api": "stopped on an error",
               "midwork": "stopped in the middle of its work", "full": "ran out of room"}.get(stop["why"], "stopped")
        detail = f" ({stop['text']})" if stop["why"] in ("limit", "api") else ""
        found.append(line("error", f"The Claude session “{session['title']}” {why} {moment(stop.get('at'), now)}"
                                   f"{detail}.", "bad", source="Claude Code", group="claude", key=session["id"]))
    keys = [i for g in view.get("groups") or [] for i in g["items"] if i["key"].startswith("secret:")]
    if keys:
        found.append(line("error", f"{keys[0]['title'].rstrip('.')}. Pulse won't read it out.", "bad",
                          source="Pulse's key check", group="could", key=keys[0]["key"]))
    if not found:
        good = [g for g in (build, tests) if g and g["state"] == "good"]
        if good:
            said = " and ".join(f"the last {'build' if g['key'] == 'build' else 'test run'} passed "
                                f"({g['detail']})" for g in good)
            found.append(line("clear", f"No errors on record: {said}.", "good"))
        elif (build or {}).get("state") == "none" and (tests or {}).get("state") == "none":
            found.append(line("clear", "No test or build results on record yet.", "info"))
    return found


def first_move(view: dict, now_item: dict | None, nxt: dict | None, errors: list[dict],
               items: dict[str, list[dict]]) -> dict | None:
    """The one thing to do first, with what a click should do."""
    if now_item and now_item.get("you"):
        return {"text": f"First move is yours: {now_item['title'].rstrip('.')}.", "group": "now",
                "key": now_item["key"], "copy": now_item.get("command")}
    bad = next((e for e in errors if e["tone"] == "bad" and e["target"]), None)
    if bad and bad["target"].get("key", "").startswith(("claude:test", "claude:build")):
        what = "tests" if "test" in bad["target"]["key"] else "build"
        return {"text": f"First move: ask Claude to fix the failing {what}.", "group": "could",
                "key": bad["target"]["key"], "copy": f"The last {what} failed. Please find out why and fix it."}
    if nxt and nxt.get("command"):
        return {"text": f"First move: start {nxt['label']}. Its command is one click away.", "group": "roadmap",
                "key": nxt["key"], "copy": nxt["command"]}
    unpushed = next((i for i in items.get("next", []) if i["key"] == "git:unpushed"), None)
    if unpushed:
        return {"text": "First move: push your commits, so there's a copy off this Mac.", "group": "next",
                "key": unpushed["key"], "copy": None}
    if nxt:
        return {"text": f"First move: {nxt['label']}, {nxt['title'].rstrip('.')}.", "group": "roadmap",
                "key": nxt["key"], "copy": None}
    summary = view.get("summary") or {}
    if summary.get("stepsTotal") and summary.get("stepsDone") == summary.get("stepsTotal"):
        return {"text": "Every step is done. First move: plan what comes next.", "group": "roadmap", "key": None,
                "copy": "Every step in the plan is done. Help me plan what comes next: read the plan, the known "
                        "issues and the ideas, and suggest the next few steps, smallest first."}
    if not summary.get("stepsTotal"):
        return {"text": "First move: give it a plan. A TODO.md with one “- [ ] …” line per task is enough; Pulse "
                        "turns it into the roadmap.", "group": "missing", "key": None,
                "copy": "Write a TODO.md for this project: one “- [ ] …” line per task that's left, in the order "
                        "you'd do them."}
    return None


# ---------------------------------------------------------------- every project at once

def desk(views: list[dict], now: dt.datetime) -> dict:
    """The homepage's briefing across every project: who's busy, each project in a sentence, what waits on you, and
    the one first move."""
    readable = [v for v in views if not v.get("error")]
    lines: list[dict] = []
    working = [(v, s) for v in readable for s in (v.get("claude") or {}).get("sessions", []) if s["state"] == "working"]
    if working:
        names = sorted({v["name"] for v, _ in working})
        lines.append(line("working", f"Claude is working in {', '.join(names)} right now "
                                     f"({plural(len(working), 'session')}).", "busy"))
    ordered = sorted(readable, key=lambda v: (v.get("home") or {}).get("lastActivity") or "", reverse=True)
    for view in ordered[:DESK_PROJECTS]:
        brief = view.get("brief") or {}
        parts = [bl for bl in brief.get("lines", []) if bl["kind"] in ("now", "next")][:1]
        bad = [bl for bl in brief.get("lines", []) if bl["kind"] == "error" and bl["tone"] == "bad"][:1]
        if not parts:
            status = next((bl for bl in brief.get("lines", []) if bl["kind"] == "status"), None)
            parts = [status] if status else []
        text = " ".join(bl["text"] for bl in parts + bad)
        if text:
            if not text.startswith(view["name"]):  # "Trailmix: we're on…", but not "Pulse: Pulse is…"
                text = f"{view['name']}: " + (text[0].lower() + text[1:] if text.startswith(("We're", "Next")) else text)
            lines.append({**line("project", text, "bad" if bad else "info"), "project": view["slug"]})
    if len(ordered) > DESK_PROJECTS:
        lines.append(line("project", f"…and {plural(len(ordered) - DESK_PROJECTS, 'quieter project')}.", "info"))
    waiting = sum((v.get("home") or {}).get("needsYou", 0) for v in readable)
    if waiting:
        lines.append(line("you", f"{plural(waiting, 'thing waits', 'things wait')} on you across your projects.",
                          "you"))
    moves = []
    for rank, view in enumerate(ordered):
        move = (view.get("brief") or {}).get("close")
        if move:
            urgency = 0 if "yours" in move["text"] else 1 if "fix" in move["text"] else 2
            moves.append((urgency, rank, {**move, "project": view["slug"],
                                          "text": f"{view['name']}: {move['text']}"}))
    close = min(moves, key=lambda m: (m[0], m[1]))[2] if moves else None
    return {"lines": lines, "close": close, "at": now.isoformat(timespec="seconds")}
