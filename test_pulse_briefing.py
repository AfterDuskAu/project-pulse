"""Checks the briefing (what it says and how), crash reports, the prompt list and "Ask Claude", on made-up projects,
conversations and crash reports in temporary folders (never the real ones on this Mac).

    python3 -m unittest -v test_pulse_briefing
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import pulse_any as pa
import pulse_ask
import pulse_briefing as pb
import pulse_errors as pe
import pulse_prompts as pp
from test_pulse_any import QUIET, commit, elsewhere, write
from test_pulse_claude import Conversation

NOW = dt.datetime.now().astimezone()


def view(**extra) -> dict:
    """A project's view, as pulse.py makes it, with only what a test needs."""
    base = {
        "name": "Demo", "slug": "demo", "path": "/x", "kind": "auto",
        "summary": {"stepsDone": 10, "stepsTotal": 25, "workDonePct": 40, "unit": "steps"},
        "stages": [{"name": "Stage 1 — safety", "done": 5, "total": 5}, {"name": "Stage 2 — grid", "done": 5, "total": 20}],
        "roadmap": {"path": "/x/ROADMAP.md", "stages": [], "gates": [{"name": "BETA", "you": True}]},
        "home": {"next": {"key": "step:S-11", "label": "S-11", "title": "App Store readiness",
                          "detail": "Up next · prompt written", "command": "do prompts/S-11.md"},
                 "needsYou": 2, "lastActivity": NOW.isoformat(), "flags": []},
        "groups": [
            {"key": "now", "title": "Now", "hint": "", "items": [
                {"key": "gate:BETA", "label": "BETA", "title": "The beta test on your own phone", "detail": "",
                 "you": False}]},
            {"key": "next", "title": "Next steps", "hint": "", "items": [
                {"key": "step:S-11", "label": "S-11", "title": "App Store readiness", "detail": "", "you": False},
                {"key": "errand:icon", "label": "you", "title": "Get the app icon made", "detail": "", "you": True}]},
            {"key": "could", "title": "Could be problems", "hint": "", "items": []},
            {"key": "known", "title": "Known problems", "hint": "", "items": []},
            {"key": "missing", "title": "Missing", "hint": "", "items": []},
            {"key": "done", "title": "Done", "hint": "", "items": []},
            {"key": "setup", "title": "How it's set up", "hint": "", "items": []}],
        "since": {"comparedWith": (NOW - dt.timedelta(hours=3)).isoformat(),
                  "changes": [{"kind": "finished", "text": "S-10 finished"}, {"kind": "commit", "text": "abc S-10"}]},
        "gauges": [], "checklists": [], "crashes": [], "claude": None,
    }
    base.update(extra)
    return base


class Wording(unittest.TestCase):
    def test_a_briefing_in_order_with_its_sources(self):
        brief = pb.compose(view(), NOW)
        kinds = [line["kind"] for line in brief["lines"]]
        self.assertEqual(kinds[:4], ["status", "now", "next", "you"])
        texts = [line["text"] for line in brief["lines"]]
        self.assertEqual(texts[0], "Demo is 40% done: 10 of 25 steps, in Stage 2.")
        self.assertEqual(texts[1], "We're on BETA: The beta test on your own phone. It waits on you.")
        self.assertEqual(texts[2], "Next up: S-11, App Store readiness. Its prompt is written.")
        self.assertEqual(texts[3], "1 other thing waits on you, starting with Get the app icon made.")
        self.assertIn("Since", texts[-2] if brief["lines"][-1]["kind"] == "clear" else texts[-1])
        self.assertEqual(brief["lines"][0]["source"]["label"], "ROADMAP.md")
        self.assertEqual(brief["close"]["text"], "First move is yours: The beta test on your own phone.")

    def test_errors_are_said_with_when_and_how_much(self):
        gauges = [{"key": "build", "label": "Build", "state": "good", "value": "Passed", "detail": "today at 19:07",
                   "source": "Claude Code: swift build"},
                  {"key": "tests", "label": "Tests", "state": "bad", "value": "Failed",
                   "detail": "3 tests picked by -k grid · today at 17:03", "source": "Claude Code: pytest -k grid",
                   "why": "AssertionError: tile size"}]
        crashes = [{"at": NOW.isoformat(), "app": "Demo", "tests": False, "exception": "an uncaught exception",
                    "where": "Grid.reload", "path": "/r/a.ips"},
                   {"at": NOW.isoformat(), "app": "DemoPackageTests (tests)", "tests": True,
                    "exception": "a stack overflow (code that calls itself too deeply)", "where": "Store.volume",
                    "path": "/r/b.ips"}]
        brief = pb.compose(view(gauges=gauges, crashes=crashes), NOW)
        errors = [line["text"] for line in brief["lines"] if line["kind"] == "error"]
        self.assertEqual(errors[0], "The last test run failed (3 tests picked by -k grid · today at 17:03): "
                                    "AssertionError: tile size.")
        self.assertTrue(errors[1].startswith("Demo crashed today at "))
        self.assertIn("an uncaught exception in Grid.reload", errors[1])
        self.assertTrue(errors[2].startswith("A test run crashed today at "))

    def test_nothing_on_record_is_said_as_such(self):
        gauges = [{"key": "build", "label": "Build", "state": "none", "value": "No build on record", "detail": ""},
                  {"key": "tests", "label": "Tests", "state": "none", "value": "No test run on record", "detail": ""}]
        brief = pb.compose(view(gauges=gauges), NOW)
        self.assertIn("No test or build results on record yet.", [line["text"] for line in brief["lines"]])

    def test_a_folder_with_no_plan(self):
        empty = view(summary={"stepsDone": 0, "stepsTotal": 0, "workDonePct": 0}, stages=[], roadmap=None,
                     home={"next": None, "needsYou": 0, "flags": []}, since={"changes": []},
                     groups=[{"key": "now", "title": "Now", "hint": "", "items": [
                         {"key": "edit:budget.py", "label": "edited", "title": "budget.py", "detail": "Edited"}]}])
        brief = pb.compose(empty, NOW)
        self.assertEqual(brief["lines"][0]["text"], "Demo has no plan Pulse can read yet. You last worked on budget.py.")
        self.assertTrue(brief["close"]["text"].startswith("First move: give it a plan."))

    def test_times_and_the_voice(self):
        self.assertTrue(pb.moment(NOW.isoformat(), NOW).startswith("today at "))
        self.assertTrue(pb.moment((NOW - dt.timedelta(days=1)).isoformat(), NOW).startswith("yesterday at "))
        self.assertRegex(pb.moment((NOW - dt.timedelta(days=30)).isoformat(), NOW), r"^on \d+ \w{3}$")
        self.assertEqual(pb.spoken("Next up: S-11 (docs/prompts/S-11.md) · its prompt is written."),
                         "Next up: S-11, its prompt is written.")
        self.assertEqual(pb.spoken("You last worked on App/Sources/Pulse/BriefingView.swift."),
                         "You last worked on BriefingView.")

    def test_the_homepage_names_who_is_busy_and_the_most_urgent_move(self):
        busy = view(name="Busy", slug="busy", claude={"sessions": [{"id": "s", "state": "working", "title": "Grid"}]})
        busy["brief"] = pb.compose(busy, NOW)
        quiet = view(name="Quiet", slug="quiet", groups=[], home={"next": None, "needsYou": 0,
                                                                 "lastActivity": "2026-01-01T00:00:00+10:00"})
        quiet["brief"] = pb.compose(quiet, NOW)
        desk = pb.desk([quiet, busy], NOW)
        self.assertEqual(desk["lines"][0]["text"], "Claude is working in Busy right now (1 session).")
        self.assertTrue(desk["lines"][1]["text"].startswith("Busy: we're on BETA"))
        self.assertTrue(any(line["text"].startswith("Quiet is 40% done") for line in desk["lines"]))
        self.assertEqual(desk["close"]["project"], "busy")


class Enrich(unittest.TestCase):
    """Everything together on a real folder, with a made-up Claude Code history."""

    def test_a_failed_test_run_reaches_the_gauges_the_lists_and_the_briefing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, root = Path(tmp) / "home", Path(tmp) / "demo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], **QUIET)
            write(root, {"README.md": "# Demo\n", "TODO.md": "- [x] One\n- [ ] Two\n", "tests/test_app.py": "x"})
            commit(root, "first")
            with elsewhere(home):
                claude_home = Path(os.environ["CLAUDE_CONFIG_DIR"])
                chat = Conversation(claude_home, str(root))
                chat.prompt("run the tests")
                chat.bash("pytest -q", "==== 2 failed, 5 passed in 0.4s ====\nE   AssertionError: totals")
                chat.said("Two tests fail.")
                project = pa.read_folder({"name": "Demo", "path": str(root)}, dt.datetime.now().astimezone(), "demo")
                v = project["view"]
                pb.enrich(v, {"name": "Demo", "path": str(root)}, dt.datetime.now().astimezone(), home)
            gauges = {g["key"]: g for g in v["gauges"]}
            self.assertEqual((gauges["tests"]["state"], gauges["tests"]["value"]), ("bad", "Failed"))
            self.assertIn("All 7 tests", gauges["tests"]["detail"])
            self.assertEqual(gauges["safety"]["value"], "Only on this Mac")
            could = next(g for g in v["groups"] if g["key"] == "could")["items"]
            self.assertEqual(could[0]["key"], "claude:test")
            texts = [line["text"] for line in v["brief"]["lines"]]
            self.assertTrue(any(t.startswith("The last test run failed (All 7 tests") for t in texts))
            self.assertEqual(v["brief"]["close"]["text"], "First move: ask Claude to fix the failing tests.")
            self.assertEqual(v["claude"]["sessionCount"], 1)
            self.assertEqual(v["checklists"][0]["id"], "basics")


class Crashes(unittest.TestCase):
    def report(self, folder: Path, name: str, header: dict, body: dict, age_days: float = 0) -> None:
        path = folder / f"{name}.ips"
        path.write_text(json.dumps(header) + "\n" + json.dumps(body), encoding="utf-8")
        if age_days:
            old = time.time() - age_days * 86400
            os.utime(path, (old, old))

    def test_the_projects_own_crashes_and_its_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp)
            header = {"app_name": "Demo", "bundleID": "com.demo.app", "bug_type": "309",
                      "timestamp": NOW.strftime("%Y-%m-%d %H:%M:%S.00 %z")}
            self.report(reports, "Demo-1", header, {
                "exception": {"type": "EXC_BAD_INSTRUCTION", "signal": "SIGILL"},
                "asiBacktraces": ["0   CoreFoundation   0x1 __exceptionPreprocess + 242\n"
                                  "1   Demo   0x2 $s4Demo4GridC6reloadyyF + 10\n"],
                "usedImages": [{"name": "Demo"}], "threads": [], "faultingThread": 0})
            runner = {"app_name": "swiftpm-testing-helper", "bug_type": "309",
                      "timestamp": NOW.strftime("%Y-%m-%d %H:%M:%S.00 %z")}
            self.report(reports, "helper-1", runner, {
                "exception": {"type": "EXC_BAD_ACCESS", "signal": "SIGSEGV"}, "faultingThread": 0,
                "usedImages": [{"name": "libswiftCore.dylib"}, {"name": "DemoPackageTests"}],
                "threads": [{"frames": [{"imageIndex": 1, "symbol": "Store.volume.getter"}]}]})
            self.report(reports, "helper-2", runner, {  # another project's tests
                "usedImages": [{"name": "OtherPackageTests"}], "threads": [], "faultingThread": 0})
            self.report(reports, "Demo-old", header, {"usedImages": [{"name": "Demo"}]}, age_days=30)
            self.report(reports, "Other-1", {**header, "app_name": "Other", "bundleID": "com.other"}, {})
            old = os.environ.get("PULSE_CRASH_REPORTS")
            os.environ["PULSE_CRASH_REPORTS"] = tmp
            try:
                found = pe.crashes({"apps": {"Demo"}, "bundles": {"com.demo.app"}, "images": {"DemoPackageTests"}},
                                   NOW)
            finally:
                if old is None:
                    os.environ.pop("PULSE_CRASH_REPORTS")
                else:
                    os.environ["PULSE_CRASH_REPORTS"] = old
            self.assertEqual(len(found), 2)
            app = next(c for c in found if not c["tests"])
            self.assertEqual((app["exception"], app["where"]), ("an uncaught exception", "Grid.reload"))
            tests = next(c for c in found if c["tests"])
            self.assertEqual((tests["app"], tests["where"]), ("DemoPackageTests (tests)", "Store.volume.getter"))

    def test_swift_names_made_readable(self):
        self.assertEqual(pe.readable_symbol("$s10TrailmixUI8MapCacheC4load33_51A4LLF"),
                         "MapCache.load")
        self.assertEqual(pe.readable_symbol("closure #1 in f()"), "closure #1 in f()")


class Prompts(unittest.TestCase):
    def test_written_prompts_and_when_they_were_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {"prompts/01-setup.md": "# Set up the project\n", "prompts/02-engine.md": "# The engine\n",
                         "prompts/README.md": "| Step |", ".claude/commands/review.md":
                         "---\ndescription: Review the last change\n---\nReview it.",
                         ".claude/skills/deploy/SKILL.md": "---\nname: deploy\ndescription: Ship it\n---\n",
                         ".claude/agents/tester.md": "---\nname: tester\n---\nRuns tests."})
            folder = pa.Folder(root, NOW)
            claude = {"prompts": [{"at": NOW.isoformat(), "text": "do prompts/01-setup.md please"},
                                  {"at": NOW.isoformat(), "text": "/review the grid"}],
                      "promptCount": 2, "since": (NOW - dt.timedelta(days=30)).isoformat(), "stops": []}
            library = pp.library(folder, {"roadmap": None}, claude, "do")
            written = {p["rel"]: p for p in library["written"]}
            self.assertEqual(set(written), {"prompts/01-setup.md", "prompts/02-engine.md", ".claude/commands/review.md",
                                            ".claude/skills/deploy/SKILL.md", ".claude/agents/tester.md"})
            self.assertEqual(written["prompts/01-setup.md"]["title"], "Set up the project")
            self.assertEqual(written["prompts/01-setup.md"]["sent"], 1)
            self.assertTrue(written["prompts/02-engine.md"]["neverSent"])
            self.assertEqual((written[".claude/commands/review.md"]["use"], written[".claude/commands/review.md"]["sent"]),
                             ("/review", 1))
            self.assertEqual(written[".claude/commands/review.md"]["title"], "Review the last change")
            self.assertEqual(written[".claude/skills/deploy/SKILL.md"]["use"], "/deploy")

    def test_long_prompts_typed_twice(self):
        long = "Read CLAUDE.md, then look at the grid code and tell me " + "why it is slow " * 12
        sent = [{"at": "2026-09-30T10:00:00+10:00", "text": long}, {"at": "2026-09-29T10:00:00+10:00", "text": long},
                {"at": "2026-09-28T10:00:00+10:00", "text": "short"}]
        self.assertEqual([(r["times"], r["last"]) for r in pp.repeated(sent)], [(2, "2026-09-30T10:00:00+10:00")])


class AskClaude(unittest.TestCase):
    def test_the_facts_are_numbered(self):
        text = pulse_ask.facts(view(brief={"lines": [{"text": "Demo is 40% done."}]}))
        self.assertTrue(text.startswith("F1 Demo is 40% done.\nF2 [Now] BETA: The beta test on your own phone"))

    def test_without_claude_code_it_says_so(self):
        old = os.environ.get("PULSE_CLAUDE")
        os.environ["PULSE_CLAUDE"] = "/nowhere/claude"
        try:
            reading = pulse_ask.ask(view(), Path("/tmp"), NOW)
        finally:
            if old is None:
                os.environ.pop("PULSE_CLAUDE")
            else:
                os.environ["PULSE_CLAUDE"] = old
        self.assertIn("isn't installed", reading["problem"])
        self.assertEqual(reading["items"], [])

    def test_the_answer_is_read_and_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "claude"
            answer = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.41,
                      "modelUsage": {"claude-sonnet-5": {}},
                      "structured_output": {"headline": "Two fixes are only done on paper.", "items": [
                          {"kind": "contradiction", "text": "RAW-1 is marked fixed but unconfirmed.",
                           "evidence": "KNOWN-ISSUES.md:51", "sure": "proven"},
                          {"kind": "made-up", "text": "An odd kind (F1).", "evidence": "F1; F2-F3", "sure": "guess"}]}}
            fake.write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps(answer) + "\nEOF\n", encoding="utf-8")
            fake.chmod(0o755)
            old = os.environ.get("PULSE_CLAUDE")
            os.environ["PULSE_CLAUDE"] = str(fake)
            try:
                demo = view()
                demo["brief"] = pb.compose(demo, NOW)
                reading = pulse_ask.ask(demo, Path(tmp), NOW)
            finally:
                if old is None:
                    os.environ.pop("PULSE_CLAUDE")
                else:
                    os.environ["PULSE_CLAUDE"] = old
            self.assertIsNone(reading["problem"])
            self.assertEqual(reading["headline"], "Two fixes are only done on paper.")
            self.assertEqual([i["kind"] for i in reading["items"]], ["contradiction", "idea"])
            self.assertEqual(reading["items"][1]["text"], "An odd kind.")
            self.assertEqual(reading["items"][1]["evidence"],
                             "Pulse: “Demo is 40% done: 10 of 25 steps, in Stage 2.”; Pulse's facts 2–3")
            self.assertEqual((reading["costUSD"], reading["model"]), (0.41, "claude-sonnet-5"))


if __name__ == "__main__":
    unittest.main()
