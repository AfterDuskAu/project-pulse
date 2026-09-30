"""Checks Pulse's readers on small samples, and one full run on a throwaway git repo.

    python3 -m unittest -v
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import pulse

ROADMAP = """# Plan
## 1. Scope
- things
## 2. The road, in order
**Stage 0 — decide.** The owner's errands:
- Enrol in the Apple Developer Program as an individual.
- Get an 8 GB Apple Silicon Mac (a used M1 is fine). It covers both proofs.

**Stage 1 — safety first.**
| # | Step | What | Status | Size | After |
|---|---|---|---|---|---|
| 1 | SF-1 | Safety one-liners | written (`SF-1-safety-fixes.md`) | S | — |
| 2 | RT-3c-B | Selection and keys (#2) | to write | M | SF-1 |
| 3 | RT-3c-C | Right-click | to write | M | B, SF-3 |
| 4 | AS-1 | Store settings | outlined | S | owner OK |
| 5 | HM-1 | One home | to write | L | D, BN-1; ships with SE-1 |
| 6 | PL-1 | Play button | to write | S | — (cut line 2) |

**BIG-0 — early proof (#44).** Right after stage 1.
- A scan-only run of the full real library.

**Stage 5 — prove it.**
- **Pricing decision (#47).** If it's free, add a StoreKit step (M) here.
- **A11Y-1.** VoiceOver, keyboard only, reduced motion (M).
- **→ External TestFlight.**

**Stage 6 — before charging money.**
- CAL round 3 (a second library). If it's below 96%, filing is off.
- SUB: screenshots, privacy label.

## 3. v1.1 — first in line (in this order)
1. "Export everything organised" (#46): one subfolder per folder, a
   report left in the destination.
2. Apple Photos: download originals that are only in iCloud, on demand.

**Later still:**
- The 185 → 100 ms tab switch.

## 4. Dropped
- PDF tools.
"""

NEXT_UP = """# Next up
## The road, in order
- **Stage 0.** DOC-1 is done (29 Sep). Owner errands:
  - Enrol in the Apple Developer Program as an individual.
  - DONE Reserve the app name and bundle ID.
- **Stage 1, safety first.** SF-1 DONE.

## v1 — grid
2. RT-3c-B (to write) — selection, ⌘/⇧-click, Esc.
29. DONE (SF-1, 29 Sep — hidden). SAFETY: hide the bulk button.
53. CB-2 (BIG-0, proposed): catalog backups without the rebuildable fingerprint cache (~0.8–1 GB a copy).
14. Library very slow while Deep Scan runs → covered by RT-3c-A…E.
"""

ISSUES = """# Known issues
Intro text.

## Undo and decisions
- Removing a source never says how many of its photos are in folders (planned in step 19; the durable ledgers make
  remove + re-add safe, so this is only a warning, not data loss). (L20–21)
- After a relaunch, Swipe's Cmd+Z undoes ONE Undo-log row at a time: a Multi-folder sort made before the relaunch takes
  one Cmd+Z per folder.

## Scans
- **Fixed by RAW-1 (30 Sep) — delete this line once BIG-0 run 2 confirms it:** a Nikon NEF froze the whole scan
  twice in BIG-0 run 1 (ImageIO's thumbnail call deadlocks) — `docs/history/steps/RAW-1.md`.
"""

PERF = """# Perf bench — 150,000 items · Release

30 Sep 2026 at 1:57 am · iMac19,1 (6 cores, 40 GB) · macOS 15.8

| Phase | Time | Stalls ≥100 / ≥250 / ≥1000 ms | Longest | Memory start / peak / end | Tiles served |
|---|---|---|---|---|---|
| launch → first grid | 2.9 s | 2 / 0 / 0 | 227 ms | 100 MB / 195 MB / 195 MB | 99 |
| tab switches | 74.0 s | 28 / 1 / 0 | 262 ms | 344 MB / 427 MB / 427 MB | 15 |

- Launch → first grid frame: 831 ms
- Back to Library from Swipe (×20) → grid's first frame: median 164 ms, worst 184 ms
- Library updates applied in launch → first grid: 1 · off-main median 128 ms worst 128 ms

Notes: grid: AppKit engine · window visible for the whole run
"""


class Headlines(unittest.TestCase):
    def test_drops_asides_and_keeps_the_first_clause(self):
        text = ("Removing a source never says how many of its photos are in folders (planned in step 19; the "
                "durable ledgers make remove + re-add safe). (L20–21)")
        self.assertEqual(pulse.headline(text), "Removing a source never says how many of its photos are in folders")

    def test_a_path_keeps_the_space_before_it(self):
        self.assertEqual(pulse.strip_parens("the core + .claude/rules/ files (29 Sep) ."), "the core + .claude/rules/ files.")

    def test_colon_cut_can_be_turned_off(self):
        text = "Apple Photos: download originals that are only in iCloud, on demand."
        self.assertEqual(pulse.headline(text, cut_at_colon=False),
                         "Apple Photos: download originals that are only in iCloud, on demand")

    def test_a_short_label_before_a_colon_keeps_the_problem(self):
        self.assertEqual(pulse.headline("Convert › Move converted originals: when the Empty Bin stops, the original "
                                        "is put back. The next launch records it."),
                         "Convert › Move converted originals: when the Empty Bin stops, the original is put back")

    def test_code_names_keep_their_case(self):
        self.assertEqual(pulse.headline("`asset.protected` / `favorite` are dead columns (curationState is real)."),
                         "asset.protected / favorite are dead columns")

    def test_step_names_lose_their_reference_numbers(self):
        self.assertEqual(pulse.step_name("#19 + #20: a ▶ on Review's video tiles and Swipe's centre video; P = play"),
                         "A ▶ on Review's video tiles and Swipe's centre video")
        self.assertEqual(pulse.step_name("Step 26-1 (#43): PhotoKit adapter plus the round-trip test (the fetched "
                                         "original must be byte-identical); does PhotoKit need a network entitlement?"),
                         "PhotoKit adapter plus the round-trip test")


class StepTitles(unittest.TestCase):
    def test_done_with_a_date(self):
        info = pulse.parse_title_line("# SF-1 — Safety fixes: the four one-liners (2026-09-29)", "SF-1")
        self.assertEqual((info["id"], info["name"], info["status"], info["date"]),
                         ("SF-1", "Safety fixes: the four one-liners", "done", "2026-09-29"))

    def test_in_progress(self):
        info = pulse.parse_title_line(
            "# BIG-0 — Early proof: the whole library in the sandboxed Release build (IN PROGRESS — run 2 to do)",
            "BIG-0")
        self.assertEqual((info["status"], info["note"], info["name"]),
                         ("in-progress", "run 2 to do", "Early proof: the whole library in the sandboxed Release build"))


class Roadmap(unittest.TestCase):
    def setUp(self):
        self.road = pulse.parse_roadmap(ROADMAP, "The road", "v1.1")

    def test_stages_and_steps(self):
        self.assertEqual([s["name"] for s in self.road["stages"]], ["Stage 1 — safety first", "Stage 5 — prove it"])
        first = self.road["stages"][0]["steps"]
        self.assertEqual([s["id"] for s in first], ["SF-1", "RT-3c-B", "RT-3c-C", "AS-1", "HM-1", "PL-1"])
        self.assertEqual([s["size"] for s in first], ["S", "M", "M", "S", "L", "S"])
        a11y = self.road["stages"][1]["steps"][0]
        self.assertEqual((a11y["id"], a11y["size"], a11y.get("fromBullet")), ("A11Y-1", "M", True))

    def test_errands_gates_and_ideas(self):
        self.assertEqual(self.road["errands"], ["Enrol in the Apple Developer Program as an individual",
                                                "Get an 8 GB Apple Silicon Mac"])
        self.assertEqual([g["name"] for g in self.road["gates"]],
                         ["BIG-0", "Pricing decision", "External TestFlight", "CAL round 3", "SUB"])
        self.assertEqual([(i["group"], i["title"]) for i in self.road["ideas"]], [
            ("v1.1 — first in line",
             '"Export everything organised": one subfolder per folder, a report left in the destination'),
            ("v1.1 — first in line", "Apple Photos: download originals that are only in iCloud, on demand"),
            ("Later still", "The 185 → 100 ms tab switch")])


class After(unittest.TestCase):
    IDS = ["SF-1", "SF-2", "SF-3", "RT-3c-B", "RT-3c-C", "RT-3c-D", "RT-3c-0b", "BN-1", "SE-1", "AS-1", "DS-1"]

    def test_short_names_and_notes(self):
        self.assertEqual(pulse.parse_after("B, SF-3", self.IDS), (["RT-3c-B", "SF-3"], [], False))
        self.assertEqual(pulse.parse_after("SF-2, before RT-3c-C", self.IDS), (["SF-2"], [], False))
        self.assertEqual(pulse.parse_after("D, BN-1; ships with SE-1", self.IDS), (["RT-3c-D", "BN-1"], [], False))
        self.assertEqual(pulse.parse_after("0b", self.IDS), (["RT-3c-0b"], [], False))
        self.assertEqual(pulse.parse_after("DS-1 (#15's track check)", self.IDS), (["DS-1"], [], False))

    def test_waits_on_you_and_the_cut_line(self):
        self.assertEqual(pulse.parse_after("AS-1, enrolment", self.IDS), (["AS-1"], ["enrolment"], False))
        self.assertEqual(pulse.parse_after("owner OK", self.IDS), ([], ["owner OK"], False))
        self.assertEqual(pulse.parse_after("— (cut line 2)", self.IDS), ([], [], True))

    def test_status_cell(self):
        self.assertTrue(pulse.says_prompt_written("written (SF-1-safety-fixes.md)", "SF-1"))
        self.assertTrue(pulse.says_prompt_written("written", "RT-3c-0b"))
        self.assertFalse(pulse.says_prompt_written("NU-21 / NU-22 written — merge", "SB-1"))
        self.assertFalse(pulse.says_prompt_written("to write", "RT-3c-B"))
        self.assertFalse(pulse.says_prompt_written("outlined", "AS-1"))


class NextUpAndIssues(unittest.TestCase):
    def test_errands_and_items(self):
        parsed = pulse.parse_next_up(NEXT_UP)
        self.assertEqual(parsed["errands"], [
            {"done": False, "text": "Enrol in the Apple Developer Program as an individual"},
            {"done": True, "text": "Reserve the app name and bundle ID"}])
        items = {i["num"]: i for i in parsed["items"]}
        self.assertEqual((items[2]["id"], items[2]["toWrite"], items[2]["done"]), ("RT-3c-B", True, False))
        self.assertEqual((items[29]["id"], items[29]["done"]), ("SF-1", True))
        self.assertEqual((items[53]["id"], items[53]["what"]),
                         ("CB-2", "Catalog backups without the rebuildable fingerprint cache"))
        self.assertIsNone(items[14]["id"])

    def test_known_issues(self):
        issues = pulse.parse_known_issues(ISSUES)
        self.assertEqual([(i["area"], i["title"], i["state"]) for i in issues], [
            ("Undo and decisions", "Removing a source never says how many of its photos are in folders", "open"),
            ("Undo and decisions", "After a relaunch, Swipe's Cmd+Z undoes ONE Undo-log row at a time", "open"),
            ("Scans", "A Nikon NEF froze the whole scan twice in BIG-0 run 1", "confirm")])
        self.assertEqual(issues[2]["note"], "Fixed by RAW-1 — confirm in BIG-0 run 2")


class NextLine(unittest.TestCase):
    STATUS = {"BIG-0": "in-progress", "SRC-1": "done", "RAW-1": "done", "RT-3c-B": "done"}

    def test_only_the_first_step_named_counts(self):
        self.assertIsNone(pulse.next_starts_with_done(
            "BIG-0 run 2 (owner); the owed 150k Release benches (SRC-1 + RAW-1, RT-3c-B); then RT-3c-C", self.STATUS))
        self.assertEqual(pulse.next_starts_with_done("SRC-1 → RAW-1 (BIG-0 run 1 found them), then BIG-0 run 2",
                                                     self.STATUS), "SRC-1")


class Speed(unittest.TestCase):
    def test_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "perf-2026-09-30-150000-release-newgrid-rv1.md"
            path.write_text(PERF, encoding="utf-8")
            report = pulse.parse_perf_report(path)
        self.assertEqual(report["when"], "2026-09-30T01:57")
        self.assertTrue(report["valid"])
        self.assertEqual((report["stalls100"], report["longestStall"]), (30, 262))
        self.assertEqual(report["metrics"], [
            {"name": "Launch → first grid frame", "median": 831, "worst": None},
            {"name": "Back to Library from Swipe → grid's first frame", "median": 164, "worst": 184}])


class SinceLastLook(unittest.TestCase):
    def test_changes_between_two_snapshots(self):
        old = {"head": None,
               "steps": {"SF-1": {"status": "ready", "name": "Safety"}, "RT-3c-B": {"status": "to-write", "name": "Keys"}},
               "proposed": {},
               "issues": {"a": {"title": "Old problem", "state": "open"}, "b": {"title": "NEF freeze", "state": "open"}},
               "warnings": {"w1": "Old warning"}, "gates": {"BIG-0": "pending"}, "errands": {"Icon": False}}
        new = {"head": None,
               "steps": {"SF-1": {"status": "done", "name": "Safety"}, "RT-3c-B": {"status": "ready", "name": "Keys"},
                         "SRC-1": {"status": "done", "name": "Access"}},
               "proposed": {"CB-2": "Smaller backups"},
               "issues": {"b": {"title": "NEF freeze", "state": "confirm"}, "c": {"title": "New problem", "state": "open"}},
               "warnings": {"w2": "New warning"}, "gates": {"BIG-0": "in-progress"}, "errands": {"Icon": True}}
        self.assertEqual([(c["kind"], c["text"]) for c in pulse.compare(old, new, None)], [
            ("finished", "SF-1 finished: Safety"),
            ("finished", "SRC-1 finished (a new step): Access"),
            ("finished", "Errand done: Icon"),
            ("ready", "Prompt written for RT-3c-B: Keys"),
            ("proposed", "Proposed in NEXT-UP: CB-2: Smaller backups"),
            ("progress", "Fixed, waiting to be confirmed: NEF freeze"),
            ("progress", "BIG-0: pending → in-progress"),
            ("parked", "New problem"),
            ("warning", "New warning"),
            ("cleared", "Off the problem list: Old problem"),
            ("cleared", "Warning cleared: Old warning"),
        ])

    def test_baseline_is_at_least_an_hour_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for moment, marker in ((dt.datetime(2026, 9, 30, 9, 0), "morning"),
                                   (dt.datetime(2026, 9, 30, 14, 30), "just now")):
                (folder / f"{pulse.stamp_name(moment)}.json").write_text(
                    json.dumps({"generatedAt": marker, "snapshot": {"m": marker}}), encoding="utf-8")
            snap, when = pulse.pick_baseline(folder, dt.datetime(2026, 9, 30, 15, 0))
        self.assertEqual((snap, when), ({"m": "morning"}, "morning"))


class WholeProject(unittest.TestCase):
    """A throwaway repo laid out like a mapped project: the facts come out right, and Pulse changes nothing in it."""

    def test_reads_a_repo_without_touching_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            files = {
                "docs/design/roadmap-v1.md": ROADMAP,
                "docs/NEXT-UP.md": NEXT_UP,
                "docs/KNOWN-ISSUES.md": ISSUES,
                "docs/history/steps/SF-1.md": "# SF-1 — Safety fixes (2026-09-29)\n",
                "docs/prompts/RT-3c-B-selection-keys.md": "# RT-3c-B — The new grid: selection and keys\n",
                "CLAUDE.md": "# Notes\n- Next: SF-1, then RT-3c-B.\n",  # starts with a finished step
                "scripts/check-memory.sh": "LIMIT_BYTES=30\nLIMIT_LINES=3\n",  # CLAUDE.md below is 37 bytes: over
                "app.swift": "let a = 1\n",
            }
            for name, text in files.items():
                (repo / name).parent.mkdir(parents=True, exist_ok=True)
                (repo / name).write_text(text, encoding="utf-8")
            quiet = {"capture_output": True, "check": True}
            subprocess.run(["git", "-C", tmp, "init", "-q"], **quiet)
            subprocess.run(["git", "-C", tmp, "add", "."], **quiet)
            subprocess.run(["git", "-C", tmp, "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "commit", "-q", "-m", "First"], **quiet)
            (repo / "app.swift").write_text("let a = 2\nlet b = 3\n", encoding="utf-8")
            index = repo / ".git" / "index"
            before = index.stat().st_mtime_ns

            project = pulse.build_project({"name": "Test", "path": tmp,
                                           "map": {"memoryCheck": "scripts/check-memory.sh"}},
                                          dt.datetime.now().astimezone())

            self.assertEqual(index.stat().st_mtime_ns, before, "Pulse must never rewrite the repo's index")
            steps = {s["id"]: s for stage in project["stages"] for s in stage["steps"]}
            self.assertEqual((steps["SF-1"]["status"], steps["SF-1"]["date"]), ("done", "2026-09-29"))
            self.assertEqual((steps["RT-3c-B"]["status"], steps["RT-3c-B"]["readiness"], steps["RT-3c-B"]["name"]),
                             ("ready", "ready", "The new grid: selection and keys"))
            self.assertEqual(steps["RT-3c-C"]["readiness"], "blocked")
            self.assertEqual(steps["AS-1"]["readiness"], "waits-on-you")
            self.assertEqual(project["summary"]["readyNow"], ["RT-3c-B", "PL-1"])
            self.assertEqual([p["id"] for p in project["proposed"]], ["CB-2"])
            self.assertEqual({w["key"] for w in project["warnings"]},
                             {"roadmap-status", "next-up-to-write", "memory-size", "memory-next"})
            uncommitted = project["git"]["uncommitted"]
            self.assertEqual([(f["path"], f["added"], f["removed"]) for f in uncommitted["files"]],
                             [("app.swift", 2, 1)])


if __name__ == "__main__":
    unittest.main()
