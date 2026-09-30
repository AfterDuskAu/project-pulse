"""Checks Pulse's reader for any folder on small made-up projects, one per common layout.

    python3 -m unittest -v
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import pulse
import pulse_any as pa

NOW = dt.datetime.now().astimezone()
QUIET = {"capture_output": True, "check": True}


def write(root: Path, files: dict) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def commit(root: Path, message: str, *paths: str) -> None:
    subprocess.run(["git", "-C", str(root), "add", *(paths or ["."])], **QUIET)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "-q", "-m", message], **QUIET)


def read(root: Path, **cfg) -> dict:
    return pa.read_folder({"name": "Demo", "path": str(root), **cfg}, NOW, "demo")


def groups(project: dict) -> dict:
    return {g["key"]: g["items"] for g in project["view"]["groups"]}


def keys(project: dict, group: str) -> list:
    return [item["key"] for item in groups(project)[group]]


def item(project: dict, key: str) -> dict:
    return next(i for g in project["view"]["groups"] for i in g["items"] if i["key"] == key)


PROMPTS_README = """# The brief
Open Claude Code in the project and say e.g. "do prompts/01-setup.md".

| Step | File | What you get |
|---|---|---|
| 01 | `prompts/01-setup.md` | Repo and folders |
| 02 | `prompts/02-engine.md` | The engine |
| 03 | `prompts/03-matcher.md` | The matcher |

## Roadmap after v0.1
| Version | What |
|---|---|
| **0.1** | The engine (this brief) |
| 0.2 | Mac app. Plan: `docs/roadmap/0.2-app.md` |
"""
CHANGELOG = """# Changelog

## 0.1.0 — in progress

### Step 01: Project setup
- Made the repo.

### Step 02: Engine
- The engine.

### Step 02b: A page the owner asked for (2026-09-29)
- A page.

### Ideas from another project (2026-09-30)
- Two ideas.
"""


class AStepList(unittest.TestCase):
    """Numbered step prompts, a step table, finished steps in the CHANGELOG, and "Step NN:" commits."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = cls.root = Path(cls.tmp.name)
        write(root, {
            "README.md": "# Demo\n", ".gitignore": "*.pyc\n",
            "prompts/README.md": PROMPTS_README,
            "prompts/01-setup.md": "# Step 01: Project setup\n",
            "prompts/02-engine.md": "# Step 02: Engine skeleton\n",
            "prompts/03-matcher.md": "# Step 03: The matcher\n",
            "docs/CHANGELOG.md": "# Changelog\n", "docs/roadmap/0.2-app.md": "# The app\n",
            "engine/core.py": "x = 1\n",
        })
        subprocess.run(["git", "-C", str(root), "init", "-q"], **QUIET)
        commit(root, "Project setup")
        (root / "engine/core.py").write_text("x = 2\n", encoding="utf-8")
        (root / "docs/CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
        commit(root, "Step 02: the engine")
        (root / "prompts/03-matcher.md").write_text("# Step 03: The matcher\nMore detail.\n", encoding="utf-8")
        commit(root, "Step 03 brief: more detail")  # only its prompt changed: step 03 hasn't started
        cls.index_before = (root / ".git" / "index").stat().st_mtime_ns
        cls.project = read(root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_never_touches_the_repo(self):
        self.assertEqual((self.root / ".git" / "index").stat().st_mtime_ns, self.index_before)

    def test_which_steps_are_done(self):
        rows = self.project["view"]["roadmap"]["stages"][0]["rows"]
        self.assertEqual([(r["label"], r["state"]) for r in rows], [("01", "done"), ("02", "done"), ("03", "ready")])
        self.assertEqual(self.project["view"]["summary"]["stepsDone"], 2)
        self.assertEqual(self.project["view"]["summary"]["stepsTotal"], 3)

    def test_the_next_step_comes_with_its_command(self):
        nxt = item(self.project, "step:03")
        self.assertEqual(nxt["detail"], "Up next · prompt written")
        self.assertEqual(nxt["command"], "do prompts/03-matcher.md")
        self.assertEqual(nxt["title"], "The matcher")

    def test_a_step_only_the_changelog_knows(self):
        extra = item(self.project, "step:02b")
        self.assertEqual((extra["title"], extra["detail"]), ("A page the owner asked for", "Done · not in the step list"))
        self.assertIn("changelog:ideasfromanotherproject", keys(self.project, "done"))
        self.assertNotIn("changelog:step01projectsetup", keys(self.project, "done"))  # counted as step 01

    def test_the_version_in_progress(self):
        now = item(self.project, "changelog:010")
        self.assertEqual((now["title"], now["detail"]), ("Version 0.1.0 is in progress", "4 entries in the CHANGELOG so far"))

    def test_later_versions_and_their_plans(self):
        later = self.project["view"]["roadmap"]["later"]
        self.assertEqual([(r["label"], r["group"]) for r in later], [("0.1", "Roadmap after v0.1"),
                                                                     ("0.2", "Roadmap after v0.1")])
        self.assertTrue(later[1]["path"].endswith("docs/roadmap/0.2-app.md"))

    def test_the_roadmap_colours_mean_prompts(self):
        self.assertEqual(self.project["view"]["roadmap"]["legend"],
                         [{"state": "done", "text": "Done"}, {"state": "ready", "text": "Prompt written"}])

    def test_every_key_once_and_the_groups_in_order(self):
        view = self.project["view"]
        self.assertEqual([g["key"] for g in view["groups"]],
                         ["now", "next", "could", "known", "missing", "done", "setup"])
        every = [i["key"] for g in view["groups"] for i in g["items"]]
        self.assertEqual(len(every), len(set(every)))
        self.assertEqual(view["groups"][1]["title"], "Next steps")

    def test_how_it_is_set_up(self):
        setup = {i["key"]: i for i in groups(self.project)["setup"]}
        self.assertIn("setup:steps", setup)
        self.assertIn("started with “do <prompt>”", setup["setup:steps"]["detail"])
        self.assertIn("Step list", self.project["view"]["layout"])


class SpecKit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, {
            ".specify/memory/constitution.md": "# Principles\n",
            "specs/001-albums/spec.md": "# Feature Specification: Photo Albums\n[NEEDS CLARIFICATION: largest album?]\n",
            "specs/001-albums/plan.md": "# Plan\n",
            "specs/001-albums/tasks.md": "## Phase 1: Setup\n- [X] T001 Create the project\n"
                                         "## Phase 3: User Story 1\n- [ ] T002 [P] [US1] Add the model in src/model.py\n",
            "specs/002-search/spec.md": "# Feature Specification: Search\n",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_features_tasks_questions_and_commands(self):
        project = read(self.root)
        self.assertEqual(item(project, "speckit:001-albums:T002")["title"], "Add the model in src/model.py")
        self.assertIn("speckit:001-albums:T001", keys(project, "done"))
        self.assertEqual(item(project, "speckit:001-albums:q:largestalbum")["title"], "Largest album?")
        self.assertEqual(item(project, "speckit:002-search:plan")["command"], "/speckit.plan")
        self.assertEqual(item(project, "speckit:001-albums")["command"], "/speckit.implement")
        rows = project["view"]["roadmap"]["stages"][0]["rows"]
        self.assertEqual([(r["label"], r["state"], r["done"], r["total"]) for r in rows],
                         [("001-albums", "doing", 1, 2), ("002-search", "todo", None, None)])
        self.assertFalse(any(k.startswith("task:") for k in keys(project, "next")))  # tasks.md isn't a checklist


class Kiro(unittest.TestCase):
    def test_sub_tasks_count_and_a_dash_means_in_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {
                ".kiro/steering/product.md": "# Product\n",
                ".kiro/specs/login/requirements.md": "# R\n", ".kiro/specs/login/design.md": "# D\n",
                ".kiro/specs/login/tasks.md": "- [x] 1. Set up\n  - [x] 1.1 Create models\n  - [ ] 1.2 Write tests\n"
                                              "- [-] 2. Build the screen\n",
            })
            project = read(root)
            self.assertEqual(project["view"]["stages"], [{"name": "login", "done": 1, "total": 3}])
            self.assertEqual([k for k in keys(project, "now") if k.startswith("kiro:")], ["kiro:login:2"])
            self.assertEqual(keys(project, "next"), ["kiro:login:1.2"])


class TaskMaster(unittest.TestCase):
    def test_statuses_dependencies_and_commands(self):
        tasks = {"master": {"tasks": [
            {"id": 1, "title": "Setup", "status": "done"},
            {"id": 2, "title": "API", "status": "pending", "dependencies": [1], "priority": "high"},
            {"id": 3, "title": "UI", "status": "pending", "dependencies": [2]},
            {"id": 4, "title": "Docs", "status": "in-progress", "subtasks": [{"id": 1, "status": "done"},
                                                                            {"id": 2, "status": "pending"}]},
            {"id": 5, "title": "Old idea", "status": "cancelled"},
            {"id": 6, "title": "Payments", "status": "blocked"}]}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {".taskmaster/tasks/tasks.json": json.dumps(tasks)})
            project = read(root)
            self.assertEqual(keys(project, "next"), ["tm:master:2", "tm:master:3"])
            self.assertEqual(item(project, "tm:master:2")["detail"], "Ready to start · high priority")
            self.assertEqual(item(project, "tm:master:2")["command"], "task-master show 2")
            self.assertEqual(item(project, "tm:master:3")["detail"], "Waits on #2")
            self.assertEqual(item(project, "tm:master:4")["detail"], "In progress · 1 of 2 subtasks done")
            self.assertIn("tm:master:6", keys(project, "could"))
            self.assertEqual(project["view"]["stages"], [{"name": "Task Master", "done": 1, "total": 5}])


class BacklogMd(unittest.TestCase):
    def test_one_file_per_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {
                "backlog/config.yml": 'statuses: ["To Do", "In Progress", "Done"]\n',
                "backlog/tasks/task-1 - Login.md": "---\nid: task-1\ntitle: Login\nstatus: In Progress\n---\n"
                                                   "## Acceptance Criteria\n- [x] #1 Works\n- [ ] #2 Is fast\n",
                "backlog/tasks/task-2 - Signup.md": "---\nid: task-2\ntitle: Signup\nstatus: To Do\n"
                                                    "dependencies: [task-1]\n---\n",
                "backlog/completed/task-3 - Setup.md": "---\nid: task-3\ntitle: Setup\nstatus: Done\n---\n",
                "backlog/drafts/task-4 - Idea.md": "---\nid: task-4\ntitle: An idea\nstatus: To Do\n---\n",
            })
            project = read(root)
            self.assertEqual(item(project, "backlog:task-1")["detail"], "In progress · 1 of 2 criteria met")
            self.assertEqual(item(project, "backlog:task-2")["detail"], "Waits on task-1")
            self.assertIn("backlog:task-3", keys(project, "done"))
            self.assertEqual(keys(project, "missing"), ["backlog:task-4", "basic:readme", "basic:git"])
            self.assertEqual(project["view"]["stages"], [{"name": "Backlog", "done": 1, "total": 3}])


class Bmad(unittest.TestCase):
    def test_stories_by_epic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {
                "docs/prd.md": "# PRD\n",
                "docs/stories/1.1.setup.md": "# Story 1.1: Set up\n\n## Status\n\nDone\n",
                "docs/stories/1.2.login.md": "# Story 1.2: Log in\n\n## Status\n\nInProgress\n\n## Tasks / Subtasks\n"
                                             "- [x] Task 1\n- [ ] Task 2\n",
                "docs/stories/2.1.search.md": "# Story 2.1: Search\n\n## Status\n\nDraft\n",
            })
            project = read(root)
            self.assertEqual(project["view"]["stages"], [{"name": "Epic 1", "done": 1, "total": 2},
                                                        {"name": "Epic 2", "done": 0, "total": 1}])
            self.assertEqual(item(project, "story:1.2")["detail"], "In progress · 1 of 2 tasks done")
            self.assertEqual(item(project, "story:2.1")["detail"], "Draft: waiting for approval")
            self.assertIn("bmad:architecture", keys(project, "missing"))


TODO_MD = """# Plan
## Now
- [/] Write the importer
- [ ] Ship it
  - [x] Build it
  - [ ] Sign it
- [-] A dropped idea

```
- [ ] an example in a code block, not a task
```
- [x] Pick a name ✅ 2026-09-28
"""
README = """# Demo

## Known issues
- **Imports over 2 GB fail.** Split the file first.

## Next steps
1. Add a settings screen
2. Write the docs
"""
ISSUES = """# Known issues
Open gaps, not fixed yet.

## Needs the owner's decision
- **Moving the folder loses the notes.**
  - The id comes from the path.
  - Decide: fix it now or later?

## Tests
- A test hangs once in a while. Cause not proven.
- **Step 11 (RPC):** treat a stop like Ctrl-C.

## Fixed
- The crash on launch.
"""


class NotesCodeLogsAndTests(unittest.TestCase):
    """A folder that isn't in git: its checklists, notes, code notes, logs and a failed test run."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = cls.root = Path(cls.tmp.name)
        write(root, {
            "TODO.md": TODO_MD, "README.md": README, "docs/KNOWN-ISSUES.md": ISSUES,
            "app.py": "def run():\n    # TODO: add retries\n    print('TODO is only a word here')\n"
                      "    return 1  # FIXME: crashes on an empty list\n",
            "tools.py": "x = 1\n", "more.py": "y = 2\n",
            "NOTES.md": "# TODO\nA heading in a note is not a code note.\n",
            "worker.log": "INFO start\nERROR: the server said 403\nINFO done\n",
            "chat.log": "Traceback (most recent call last):\n  File \"main.py\", line 6\nopenai.AuthenticationError: "
                        "Incorrect API key provided\n",
            ".pytest_cache/v/cache/lastfailed": json.dumps({"tests/test_a.py::test_one": True}),
        })
        cls.project = read(root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_checklists_count_leaves_and_skip_code_blocks(self):
        todo = [s for s in self.project["view"]["stages"] if s["name"] == "TODO.md"]
        self.assertEqual(todo, [{"name": "TODO.md", "done": 2, "total": 4}])  # importer, build, sign, name
        self.assertIn("task:TODO.md:writetheimporter", keys(self.project, "now"))
        self.assertIn("task:TODO.md:signit", keys(self.project, "next"))
        self.assertNotIn("task:TODO.md:shipit", keys(self.project, "next"))  # it has sub-tasks
        self.assertNotIn("task:TODO.md:anexampleinacodeblocknotatask", keys(self.project, "next"))
        self.assertEqual(item(self.project, "task:TODO.md:pickaname")["time"], "2026-09-28")

    def test_sections_in_notes(self):
        self.assertIn("note:README.md:addasettingsscreen", keys(self.project, "next"))
        self.assertIn("note:README.md:importsover2gbfailsplitthefilefirst", keys(self.project, "known"))

    def test_a_known_issues_note(self):
        moving = item(self.project, "issue:movingthefolderlosesthenotes")
        self.assertEqual((moving["title"], moving["detail"]), ("Moving the folder loses the notes",
                                                               "Decide: fix it now or later?"))
        self.assertIn("issue:atesthangsonceinawhilecausenotproven", keys(self.project, "could"))  # suspected
        rpc = item(self.project, "issue:step11rpctreatastoplikectrlc")
        self.assertEqual((rpc["title"], rpc["detail"]), ("Treat a stop like Ctrl-C", "Step 11"))
        self.assertIn("issue:thecrashonlaunch", keys(self.project, "done"))

    def test_code_notes_only_in_comments(self):
        todo = item(self.project, "code:app.py:addretries")
        self.assertEqual((todo["label"], todo["detail"]), ("TODO", "app.py, line 2"))
        self.assertIn("code:app.py:crashesonanemptylist", keys(self.project, "could"))
        self.assertEqual(len([k for k in keys(self.project, "missing") if k.startswith("code:")]), 1)

    def test_errors_in_a_recent_log(self):
        log = item(self.project, "log:worker.log")
        self.assertEqual(log["title"], "worker.log: 1 error line")
        self.assertIn("403", log["detail"])
        chat = item(self.project, "log:chat.log")
        self.assertEqual(chat["title"], "chat.log: 2 error lines")  # the traceback and the error it ends with
        self.assertEqual(chat["detail"], "Newest: openai.AuthenticationError: Incorrect API key provided")

    def test_a_failed_test_run(self):
        self.assertEqual(item(self.project, "tests:pytest:.")["title"], "1 test failed the last time pytest ran")

    def test_the_basics_that_are_missing(self):
        self.assertIn("basic:git", keys(self.project, "missing"))
        self.assertIn("basic:tests", keys(self.project, "missing"))
        self.assertNotIn("basic:readme", keys(self.project, "missing"))

    def test_without_a_plan_every_checklist_task_is_listed(self):
        self.assertIn("Checklists", self.project["view"]["layout"])
        self.assertEqual(self.project["view"]["roadmap"]["stages"][0]["name"], "Checklists")


class ToDoListsWithoutBoxes(unittest.TestCase):
    def test_a_todo_txt_and_a_todo_md_written_as_plain_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {"todo.txt": "(A) Fix the login\nx 2026-09-29 Pick a name\nAdd a dark mode\n",
                         "docs/TODO.md": "# Plan\n- Write the docs\n- DONE: set up the repo\n  - a detail\n",
                         "notes.md": "- Not a to-do list, just notes\n"})
            project = read(root)
            stages = {s["name"]: (s["done"], s["total"]) for s in project["view"]["stages"]}
            self.assertEqual(stages, {"todo.txt": (1, 3), "docs/TODO.md": (1, 2)})
            self.assertIn("task:todo.txt:fixthelogin", keys(project, "next"))
            self.assertIn("task:docs/TODO.md:setuptherepo", keys(project, "done"))
            self.assertNotIn("task:notes.md:notatodolistjustnotes", keys(project, "next"))


class ChoosingWhatToRead(unittest.TestCase):
    def test_a_reader_switched_off_still_claims_its_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {"specs/001-a/spec.md": "# A\n", "specs/001-a/plan.md": "# P\n",
                         "specs/001-a/tasks.md": "- [ ] T001 Do it\n", "app.py": "# TODO: later\n"})
            project = read(root, off=["speckit", "codenotes"])
            every = [i["key"] for g in project["view"]["groups"] for i in g["items"]]
            self.assertFalse([k for k in every if k.startswith(("speckit:", "task:", "code:"))])
            readers = {r["id"]: r for r in project["view"]["readers"]}
            self.assertEqual((readers["speckit"]["on"], readers["speckit"]["found"]), (False, "turned off"))
            self.assertEqual(readers["kiro"]["found"], "nothing found")

    def test_a_big_folder_is_read_in_part(self):
        saved = pa.MAX_FILES
        pa.MAX_FILES = 3
        try:
            with tempfile.TemporaryDirectory() as tmp:
                write(Path(tmp), {f"f{n}.txt": "x" for n in range(6)})
                project = read(Path(tmp))
                self.assertTrue(project["view"]["notes"])
                self.assertIn("setup:size", [i["key"] for i in groups(project)["setup"]])
        finally:
            pa.MAX_FILES = saved

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    def test_a_folder_macos_wont_let_pulse_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            locked = Path(tmp) / "locked"
            locked.mkdir()
            locked.chmod(0)
            try:
                with self.assertRaises(PermissionError) as caught:
                    read(locked)
                self.assertIn("Privacy & Security", str(caught.exception))
            finally:
                locked.chmod(0o755)


class HowItsSetUp(unittest.TestCase):
    def test_ai_files_code_tests_and_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {
                "CLAUDE.md": "# Rules\nOne.\n", ".claude/rules/library.md": "x", ".claude/commands/ship.md": "x",
                "AGENTS.md": "# Agents\n", ".cursor/rules/style.mdc": "x",
                ".mcp.json": json.dumps({"mcpServers": {"github": {}, "files": {}}}),
                ".github/workflows/ci.yml": "on: push\n", "pyproject.toml": "[tool.pytest.ini_options]\n",
                "src/a.py": "a = 1\n", "src/b.py": "b = 1\n", "tests/test_a.py": "def test(): pass\n",
                "ruff.toml": "",
            })
            setup = {i["key"]: i for i in groups(read(root))["setup"]}
            self.assertEqual(setup["setup:claude"]["detail"], "CLAUDE.md (2 lines) · 1 rule file · 1 command")
            self.assertIn("setup:agents", setup)
            self.assertIn("setup:cursor", setup)
            self.assertEqual(setup["setup:mcp"]["title"], "MCP servers: files, github")
            self.assertEqual(setup["setup:tests"]["detail"], "pytest")
            self.assertIn("GitHub Actions (ci.yml)", setup["setup:checks"]["detail"])
            self.assertIn("linters: ruff", setup["setup:checks"]["detail"])

    def test_a_remote_never_shows_a_password(self):
        self.assertEqual(pa.safe_remote("https://me:ghp_secret123@github.com/me/repo.git"), "GitHub: me/repo")
        self.assertEqual(pa.safe_remote("git@github.com:me/repo.git"), "GitHub: me/repo")
        self.assertEqual(pa.safe_remote("https://git.example.org/team/app"), "git.example.org")


def fake_key(prefix: str = "sk-") -> str:
    """A made-up key that looks real, built here so this file never holds one."""
    return prefix + "".join(chr(ord("A") + (n * 7) % 26) + str(n % 10) + chr(ord("a") + (n * 3) % 26) for n in range(12))


class ForgottenWorkKeysAndCopies(unittest.TestCase):
    def test_a_stash_and_a_branch_with_work_of_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "-C", tmp, "init", "-q", "-b", "main"], **QUIET)
            write(root, {"README.md": "# R\n", ".gitignore": "x\n", "a.py": "a = 1\n"})
            commit(root, "First")
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "-b", "idea"], **QUIET)
            write(root, {"b.py": "b = 1\n"})
            commit(root, "An idea")
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "main"], **QUIET)
            write(root, {"a.py": "a = 2\n"})
            subprocess.run(["git", "-C", tmp, "-c", "user.name=T", "-c", "user.email=t@example.com", "stash", "-q"],
                           **QUIET)
            project = read(root)
            self.assertEqual(item(project, "git:branch:idea")["title"], "Branch “idea” has 1 commit that isn’t in main")
            self.assertIn("never pushed", item(project, "git:branch:idea")["detail"])
            self.assertEqual(item(project, "git:stash")["title"], "1 stash: work set aside, not committed")
            flags = [f["text"] for f in project["view"]["home"]["flags"]]
            self.assertIn("1 stash of unsaved work", flags)
            self.assertIn("1 branch with work of its own", flags)

    def test_keys_written_into_files_are_found_but_never_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = fake_key()
            write(root, {"app.py": f'API_KEY = "{key}"\n', "notes.md": "sk-" + "x" * 40 + "\n",
                         "config.json": '{"token": "' + fake_key("ghp_") + '"}\n'})
            project = read(root)
            found = {i["key"]: i for i in groups(project)["could"] if i["label"] == "secret"}
            self.assertEqual(set(found), {"secret:app.py:anopenaikey", "secret:config.json:agithubtoken"})
            self.assertEqual(found["secret:app.py:anopenaikey"]["title"], "An OpenAI key seems to be written in app.py")
            self.assertTrue(found["secret:app.py:anopenaikey"]["you"])
            self.assertNotIn(key, json.dumps(project["view"]))  # the key itself never leaves the file

    def test_a_env_file_in_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "-C", tmp, "init", "-q"], **QUIET)
            write(root, {".env": "DEBUG=1\n", ".env.example": "DEBUG=\n", "README.md": "# R\n"})
            commit(root, "First")
            could = keys(read(root), "could")
            self.assertIn("secret:env:.env", could)
            self.assertNotIn("secret:env:.env.example", could)

    def test_copies_of_a_file_next_to_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {"app.py": "1", "app (1).py": "2", "app_final.py": "3", "schema.json": "{}",
                         "schema_v2.json": "{}", "src/view.swift": "x", "src/view copy.swift": "y",
                         "lonely copy.txt": "z"})
            project = read(root)
            copies = {i["key"]: i for i in groups(project)["could"] if i["label"] == "copies"}
            self.assertEqual(set(copies), {"copies:/app (1)", "copies:src/view copy"})
            self.assertEqual(copies["copies:/app (1)"]["title"], "3 versions of the same file")
            self.assertTrue(copies["copies:/app (1)"]["detail"].startswith("app (1).py, app.py, app_final.py."))


class Homepage(unittest.TestCase):
    def test_the_next_step_what_needs_you_and_warning_signs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {"TODO.md": "- [ ] Write the importer\n- [x] Pick a name\n",
                         "docs/KNOWN-ISSUES.md": ISSUES, "worker.log": "ERROR: boom\n"})
            home = read(root)["view"]["home"]
            self.assertEqual(home["next"]["title"], "Write the importer")
            self.assertEqual(home["needsYou"], 1)  # the decision about moving the folder
            self.assertEqual([f["text"] for f in home["flags"]], ["1 log with errors"])
            self.assertIsNotNone(home["lastActivity"])


class SinceLastTime(unittest.TestCase):
    def test_what_changed_between_two_readings(self):
        old = {"kind": "auto", "head": None, "items": {
            "task:TODO.md:docs": ["next", "Write the docs", "TODO.md"],
            "speckit:001:T012": ["next", "Add the model", "T012"],
            "issue:crash": ["known", "The crash", "Scans"]}}
        new = {"kind": "auto", "head": None, "items": {
            "task:TODO.md:docs": ["done", "Write the docs", "TODO.md"],
            "speckit:001:T012": ["done", "Add the model", "T012"],
            "note:README.md:q": ["could", "Which format?", "README.md"]}}
        changes = pa.compare(old, new, None)
        self.assertEqual([(c["kind"], c["text"], c.get("name")) for c in changes], [
            ("finished", "Finished: Write the docs", None),
            ("finished", "T012 finished: Add the model", "T012"),
            ("warning", "Could be a problem: Which format?", None),
            ("cleared", "Off the problem list: The crash", None)])


class TheWholeRun(unittest.TestCase):
    """pulse.py end to end, with a folder that has no map: the app's data, the page and "Since …"."""

    def test_two_refreshes(self):
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as project_dir:
            home, project_root = Path(home_dir), Path(project_dir)
            (home / "page_template.html").write_text((pulse.HERE / "page_template.html").read_text(encoding="utf-8"),
                                                     encoding="utf-8")
            (home / "projects.json").write_text(json.dumps({"projects": [{"name": "Any", "path": project_dir}]}),
                                                encoding="utf-8")
            write(project_root, {"TODO.md": "- [ ] First\n- [ ] Second\n"})
            saved = pulse.HERE
            pulse.HERE = home
            try:
                with elsewhere(home):
                    pulse.main(["--no-open"])
                    (project_root / "TODO.md").write_text("- [x] First\n- [ ] Second\n", encoding="utf-8")
                    time.sleep(1.1)  # snapshots are named by the second
                    pulse.main(["--no-open"])
            finally:
                pulse.HERE = saved
            data = json.loads((home / "out" / "data.json").read_text(encoding="utf-8"))
            view = data["projects"][0]
            self.assertEqual((view["kind"], view["summary"]["stepsDone"], view["summary"]["stepsTotal"]), ("auto", 1, 2))
            self.assertEqual([c["text"] for c in view["since"]["changes"]], ["Finished: First"])
            self.assertIn('"kind": "auto"', (home / "out" / "index.html").read_text(encoding="utf-8"))
            # The briefing and what goes with it.
            self.assertEqual(view["brief"]["lines"][0]["text"], "Any is 50% done: 1 of 2 tasks.")
            self.assertEqual([g["key"] for g in view["gauges"]], ["build", "tests", "crashes", "safety"])
            self.assertEqual(view["checklists"][0]["id"], "basics")
            self.assertIsNone(view["claude"])
            self.assertIn("lines", data["desk"])
            self.assertEqual(data["claudeFolders"], [])


@contextlib.contextmanager
def elsewhere(home: Path):
    """Claude Code's files, the crash reports and Xcode's records, pointed at empty folders: a test never reads the
    real ones on this Mac."""
    names = ("CLAUDE_CONFIG_DIR", "PULSE_CRASH_REPORTS", "PULSE_DERIVED_DATA")
    saved = {name: os.environ.get(name) for name in names}
    for name in names:
        folder = home / "empty" / name.lower()
        folder.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(folder)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
