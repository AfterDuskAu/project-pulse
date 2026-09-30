"""Checks the data the Pulse app shows: every item in exactly one group, with a key that never changes, and the
roadmap with every stage and step.

    python3 -m unittest -v
"""
from __future__ import annotations

import unittest
from pathlib import Path

import pulse_groups as pg
from test_pulse_obsidian import sample_project


def demo_project() -> dict:
    project = sample_project(Path("/vault"))
    project["path"] = "/vault"
    project["sources"]["roadmap"] = "/vault/docs/roadmap.md"
    # A step whose prompt is written ahead of its turn: it comes after B-1.
    project["stages"][0]["steps"].append(
        {"id": "D-1", "name": "Fourth thing", "what": "Fourth thing", "size": "M", "status": "ready",
         "readiness": "blocked", "link": "/vault/docs/prompts/D-1-fourth.md", "prompt": "/vault/docs/prompts/D-1-fourth.md",
         "blockedBy": ["B-1"], "outside": [], "cut": False})
    project["gates"] = [
        {"stage": None, "name": "BIG-0", "status": "next", "arrow": False, "text": "A run. The owner runs it."},
        {"stage": "Stage 5", "name": "Pricing decision", "status": "pending", "arrow": False, "text": "Pricing."},
        {"stage": "Stage 5", "name": "External TestFlight", "status": "pending", "arrow": True, "text": "→ Beta."},
        {"stage": "Stage 6", "name": "SUB", "status": "pending", "arrow": False, "text": "SUB: screenshots."},
    ]
    return project


class AppView(unittest.TestCase):
    def setUp(self):
        self.view = pg.app_view(demo_project(), "demo")
        self.groups = {g["key"]: g for g in self.view["groups"]}

    def keys(self, group: str) -> list[str]:
        return [item["key"] for item in self.groups[group]["items"]]

    def test_the_groups_in_order(self):
        self.assertEqual([g["key"] for g in self.view["groups"]],
                         ["now", "next", "could", "known", "missing", "done", "setup"])
        self.assertEqual(self.groups["next"]["title"], "Next steps")

    def test_every_item_is_in_one_group_only(self):
        every = [item["key"] for g in self.view["groups"] for item in g["items"]]
        self.assertEqual(len(every), len(set(every)))

    def test_where_each_thing_goes(self):
        self.assertEqual(self.keys("now"), ["step:BIG-0"])
        self.assertEqual(self.keys("next"), ["step:B-1", "step:C-1", "step:D-1"])  # the roadmap's order
        self.assertEqual(self.keys("missing"), ["errand:gettheiconmade"])     # C-1 is already in Next
        self.assertEqual(self.keys("done"), ["step:SRC-1", "step:A-1"])         # newest first
        self.assertEqual(self.keys("could"), [f"issue:{pg.norm('Fixed by RAW-1: a NEF froze the scan.')}",
                                              "issue:atestpausesforminutescausenotproven",
                                              "speed:whilebrowsing:backtolibrary"])
        self.assertEqual(self.keys("known"), ["issue:adecodeholdsitsdriveforgood"])

    def test_details_a_person_reads(self):
        next_items = {i["key"]: i for i in self.groups["next"]["items"]}
        self.assertEqual(next_items["step:B-1"]["detail"], "Ready to start · prompt written · on the cut line")
        self.assertEqual(next_items["step:C-1"]["detail"],
                         "Waits on you: owner OK · also after B-1 · prompt not written yet")
        self.assertEqual(next_items["step:D-1"]["detail"], "After B-1 · prompt written")
        self.assertEqual(self.groups["done"]["items"][1]["detail"], "Done 29 Sep")

    def test_a_written_prompt_comes_with_its_command(self):
        next_items = {i["key"]: i for i in self.groups["next"]["items"]}
        self.assertEqual(next_items["step:B-1"]["command"], "do docs/prompts/B-1-second.md")
        self.assertEqual(next_items["step:D-1"]["command"], "do docs/prompts/D-1-fourth.md")
        self.assertIsNone(next_items["step:C-1"]["command"])  # no prompt yet

    def test_summary_and_stages(self):
        self.assertEqual(self.view["summary"], {"stepsDone": 1, "stepsTotal": 3, "workDonePct": 25,
                                                "unit": "steps", "weighted": True})
        self.assertEqual(self.view["stages"], [{"name": "Stage 1 — first", "done": 1, "total": 4}])
        self.assertEqual(self.view["since"]["changes"][0]["kind"], "finished")


class Roadmap(unittest.TestCase):
    def setUp(self):
        self.road = pg.app_view(demo_project(), "demo")["roadmap"]

    def test_tiles_like_the_first_chart(self):
        self.assertEqual([(t["label"], t["value"], t["suffix"]) for t in self.road["tiles"]], [
            ("Build steps done", "1", "of 4"), ("Build steps left", "3", ""), ("Mix left (S / M / L)", "0 / 2 / 1", ""),
            ("Work done, by size", "25%", "")])

    def test_every_step_with_its_colour_size_and_marks(self):
        rows = self.road["stages"][0]["rows"]
        self.assertEqual([(r["label"], r["state"], r["size"]) for r in rows],
                         [("A-1", "done", "S"), ("B-1", "ready", "M"), ("C-1", "todo", "L"), ("D-1", "ready", "M")])
        self.assertEqual([r["label"] for r in rows if r["you"]], ["C-1"])   # waits on the owner
        self.assertEqual([r["label"] for r in rows if r["cut"]], ["B-1"])   # on the cut line
        self.assertEqual([r["command"] for r in rows],
                         [None, "do docs/prompts/B-1-second.md", None, "do docs/prompts/D-1-fourth.md"])
        self.assertEqual([e["state"] for e in self.road["legend"]], ["done", "ready", "todo"])

    def test_gates_run_in_order_with_arrows_between_stages(self):
        gates = self.road["gates"]
        self.assertEqual([(g["name"], g["state"], g["you"], g["arrowBefore"]) for g in gates], [
            ("BIG-0", "next", True, False), ("Pricing decision", "todo", False, True),
            ("External TestFlight", "todo", False, True), ("SUB", "todo", False, True)])

    def test_errands_and_what_comes_after(self):
        self.assertEqual(self.road["errands"], [{"text": "Get the icon made", "done": False},
                                                {"text": "Old errand", "done": True}])
        self.assertEqual(self.road["later"], [{"group": "v1.1", "label": "", "text": "Export everything"}])

    def test_a_stage_that_is_finished_says_so(self):
        project = demo_project()
        for step in project["stages"][0]["steps"]:
            step["status"] = "done"
        self.assertEqual(pg.roadmap_view(project, "do")["stages"][0]["note"], "all done")


class PromptCommands(unittest.TestCase):
    def test_the_verb_comes_from_the_projects_own_docs(self):
        self.assertEqual(pg.prompt_verb(['Open Claude Code and say e.g. "do prompts/03a-library-core.md".']), "do")
        self.assertEqual(pg.prompt_verb(["Tell Claude “run docs/prompts/X-1-a.md” to start."]), "run")
        self.assertEqual(pg.prompt_verb(["Run `prompts/01-project-setup.md` first."]), "do")  # no verb inside
        self.assertEqual(pg.prompt_verb([]), "do")

    def test_a_command_uses_the_path_inside_the_project(self):
        self.assertEqual(pg.command_for("/p/docs/prompts/A-1-x.md", "/p", "do"), "do docs/prompts/A-1-x.md")
        self.assertIsNone(pg.command_for(None, "/p", "do"))


if __name__ == "__main__":
    unittest.main()
