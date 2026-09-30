"""Checks the Obsidian note: what goes in which group, and that the person's writing always survives.

    python3 -m unittest -v
"""
from __future__ import annotations

import datetime as dt
import subprocess
import tempfile
import unittest
from pathlib import Path

import pulse_obsidian as po

NOW = dt.datetime(2026, 9, 30, 15, 0, tzinfo=dt.timezone(dt.timedelta(hours=10)))


def sample_project(root: Path) -> dict:
    def at(name: str) -> str:
        return str(root / name)

    return {
        "name": "Demo",
        "summary": {"stepsDone": 1, "stepsTotal": 3, "workDonePct": 25, "readyNow": ["B-1"]},
        "stages": [{"name": "Stage 1 — first", "steps": [
            {"id": "A-1", "name": "First thing", "what": "First thing", "size": "S", "status": "done",
             "date": "2026-09-29", "readiness": "done", "link": at("docs/history/steps/A-1.md"), "prompt": None,
             "blockedBy": [], "outside": [], "cut": False},
            {"id": "B-1", "name": "Second thing", "what": "Second thing", "size": "M", "status": "ready",
             "readiness": "ready", "link": at("docs/prompts/B-1-second.md"), "prompt": at("docs/prompts/B-1-second.md"),
             "blockedBy": [], "outside": [], "cut": True},
            {"id": "C-1", "name": "Third thing", "what": "Third thing", "size": "L", "status": "to-write",
             "readiness": "blocked", "link": at("docs/roadmap.md"), "prompt": None, "blockedBy": ["B-1"],
             "outside": ["owner OK"], "cut": False},
        ]}],
        "otherSteps": [
            {"id": "BIG-0", "name": "Early proof", "status": "in-progress", "date": None, "note": "run 2 to do",
             "link": at("docs/history/steps/BIG-0.md")},
            {"id": "SRC-1", "name": "Access", "status": "done", "date": "2026-09-30", "note": None,
             "link": at("docs/history/steps/SRC-1.md")},
        ],
        "waitsOnYou": [{"id": "C-1", "name": "Third thing", "outside": ["owner OK"], "blockedBy": ["B-1"],
                        "link": at("docs/roadmap.md")}],
        "errands": [{"text": "Get the icon made", "done": False}, {"text": "Old errand", "done": True}],
        "issues": [
            {"area": "Scans", "title": "NEF froze the scan", "text": "Fixed by RAW-1: a NEF froze the scan.",
             "state": "confirm", "note": "Fixed by RAW-1 — confirm in BIG-0 run 2"},
            {"area": "Tests", "title": "A test pauses", "text": "A test pauses for minutes. Cause not proven.",
             "state": "open", "note": None},
            {"area": "Scans", "title": "A decode holds its drive", "text": "A decode holds its drive for good.",
             "state": "open", "note": None},
        ],
        "perf": [{"label": "While browsing",
                  "latest": {"path": at("docs/testing/perf-b.md"), "metrics": [
                      {"name": "Back to Library", "median": 174, "worst": 185},
                      {"name": "Launch", "median": 831, "worst": None}]},
                  "previous": {"path": at("docs/testing/perf-a.md"), "metrics": [
                      {"name": "Back to Library", "median": 164, "worst": 184},
                      {"name": "Launch", "median": 829, "worst": None}]}}],
        "warnings": [],
        "git": {"ok": False},
        "memory": {"path": at("CLAUDE.md"), "next": "BIG-0 run 2"},
        "ideas": [{"group": "v1.1", "title": "Export everything", "text": "Export everything"}],
        "changes": [{"kind": "finished", "text": "A-1 finished: First thing"}],
        "comparedWith": "2026-09-30T13:58:00+10:00",
        "sources": {"knownIssues": at("docs/KNOWN-ISSUES.md")},
    }


class Groups(unittest.TestCase):
    def test_each_finding_lands_in_one_group(self):
        cats = po.categorize(sample_project(Path("/vault")))
        self.assertEqual([c["why"] for c in cats["could"]], [
            "Fixed by RAW-1 — confirm in BIG-0 run 2",          # waiting to be confirmed
            "Suspected, not proven",                             # its note says "cause not proven"
            "Slower than the run before (while browsing)"])      # 164 → 174 ms; Launch's 2 ms is noise
        self.assertEqual([i["title"] for i in cats["known"]], ["A decode holds its drive"])
        self.assertEqual([s["id"] for s in cats["now"]], ["BIG-0"])
        self.assertEqual([s["id"] for s in cats["ready"]], ["B-1"])
        self.assertEqual([s["id"] for s in cats["missingPrompts"]], ["C-1"])
        self.assertEqual([e["text"] for e in cats["errands"]], ["Get the icon made"])
        self.assertEqual([s["id"] for s in cats["done"]], ["A-1", "SRC-1"])


class NoteText(unittest.TestCase):
    def test_sections_links_and_bars(self):
        vault = Path("/vault")
        text = po.render(sample_project(vault), vault, NOW)
        self.assertTrue(text.startswith(po.MARKER))
        self.assertTrue(text.endswith("---\n\n"))
        self.assertIn("`" + "█" * 8 + "░" * 22 + "`", text)  # 25% of a 30-wide bar
        self.assertIn("> [!warning] Could be problems (3)", text)
        self.assertIn("> [!bug]- Known problems (1)", text)       # folded
        self.assertIn("> [!question]- Missing (2)", text)         # C-1's prompt + one errand
        self.assertIn("> [!success]- Done (2)", text)
        self.assertIn("[[docs/prompts/B-1-second|B-1]] Second thing · cut line", text)
        self.assertIn("[[docs/history/steps/A-1|A-1]] First thing · 29 Sep", text)

    def test_links_outside_the_vault_open_by_path(self):
        self.assertEqual(po.link("/elsewhere/Notes.md", "Notes", Path("/vault")),
                         "[Notes](obsidian://open?path=/elsewhere/Notes.md)")

    def test_text_from_docs_cannot_turn_into_markup(self):
        self.assertEqual(po.esc("a <b> %% c * d [[e]]"), "a &lt;b> %\\% c \\* d [\\[e]]")


class KeepingYourWriting(unittest.TestCase):
    GEN1 = f"{po.MARKER} v1 %%\n# Demo: where you are\nold numbers\n---\n\n"
    GEN2 = f"{po.MARKER} v2 %%\n# Demo: where you are\nnew numbers\n---\n\n"

    def test_a_new_note_gets_an_empty_my_notes(self):
        text, moved = po.merge(None, self.GEN1, None, NOW)
        self.assertEqual(text, self.GEN1 + po.NOTES_HEADING + "\n" + po.NOTES_HINT + "\n")
        self.assertEqual(moved, [])

    def test_my_notes_survive_a_refresh_unchanged(self):
        existing = self.GEN1 + "## My notes\nMy idea\n\n- [ ] ask about RT-3c-C\n"
        text, moved = po.merge(existing, self.GEN2, self.GEN1, NOW)
        self.assertEqual(text, self.GEN2 + "## My notes\nMy idea\n\n- [ ] ask about RT-3c-C\n")
        self.assertEqual(moved, [])

    def test_lines_typed_above_are_moved_not_lost(self):
        existing = (self.GEN1.replace("old numbers", "old numbers\nremember to check X")
                    + "## My notes\nMy idea\n")
        text, moved = po.merge(existing, self.GEN2, self.GEN1, NOW)
        self.assertEqual(moved, ["remember to check X"])
        self.assertTrue(text.startswith(self.GEN2))
        mine = text[len(self.GEN2):]
        self.assertIn("My idea", mine)
        self.assertIn("remember to check X", mine)

    def test_a_deleted_heading_comes_back_with_the_writing_under_it(self):
        text, moved = po.merge(self.GEN1 + "a thought with no heading\n", self.GEN2, self.GEN1, NOW)
        self.assertEqual(moved, ["a thought with no heading"])
        self.assertIn("## My notes", text)
        self.assertIn("a thought with no heading", text.split("## My notes", 1)[1])


class WritingTheFile(unittest.TestCase):
    def test_git_never_sees_it_and_nothing_is_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, state = Path(tmp) / "vault", Path(tmp) / "state"
            vault.mkdir()
            subprocess.run(["git", "-C", str(vault), "init", "-q"], capture_output=True, check=True)
            project, settings = sample_project(vault), {"vault": str(vault), "note": "Pulse/Demo.md"}
            note = vault / "Pulse" / "Demo.md"

            first = po.update_note(settings, project, NOW, state)
            self.assertEqual(first["status"], "skipped")          # git would see Pulse/
            self.assertIn(".git/info/exclude", first["message"])
            self.assertFalse(note.exists())

            (vault / ".git" / "info" / "exclude").write_text("Pulse/\n", encoding="utf-8")
            self.assertEqual(po.update_note(settings, project, NOW, state)["status"], "written")
            self.assertTrue(note.read_text(encoding="utf-8").startswith(po.MARKER))
            status = subprocess.run(["git", "-C", str(vault), "status", "--porcelain"], capture_output=True,
                                    text=True, check=True)
            self.assertEqual(status.stdout, "")                     # hidden from git

            note.write_text(note.read_text(encoding="utf-8") + "My idea\n", encoding="utf-8")
            stamp = note.stat().st_mtime_ns
            self.assertEqual(po.update_note(settings, project, NOW, state)["status"], "unchanged")
            self.assertEqual(note.stat().st_mtime_ns, stamp)        # nothing to do, nothing touched

            later = NOW + dt.timedelta(minutes=5)
            self.assertEqual(po.update_note(settings, project, later, state)["status"], "written")
            self.assertTrue(note.read_text(encoding="utf-8").endswith("My idea\n"))

            other = vault / "Pulse" / "Mine.md"
            other.write_text("hello\n", encoding="utf-8")
            result = po.update_note({"vault": str(vault), "note": "Pulse/Mine.md"}, project, later, state)
            self.assertEqual(result["status"], "skipped")           # not Pulse's note
            self.assertEqual(other.read_text(encoding="utf-8"), "hello\n")


if __name__ == "__main__":
    unittest.main()
