"""Checks how Pulse reads Claude Code's conversation files, on made-up conversations in a temporary folder
(never the real ~/.claude).

    python3 -m unittest -v test_pulse_claude
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path

import pulse_claude as pcl

NOW = dt.datetime.now().astimezone()


def fake_key() -> str:
    """A key-shaped jumble, built at run time so no key-like text sits in this file."""
    jumble = "q7Zp2Lk9Xw4Rt8Vn3Bm6Hc1Jd5Fg0Sy"
    return "sk-" + "ant-" + "".join(jumble[(i * 7) % len(jumble)] for i in range(40))


def stamp(minutes_ago: float) -> str:
    moment = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Conversation:
    """Writes a conversation file the way Claude Code does: one compact JSON object per line."""

    def __init__(self, home: Path, cwd: str, session: str = "s1"):
        self.cwd, self.session = cwd, session
        self.path = home / "projects" / pcl.encode(cwd) / f"{session}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.minute = 120.0
        self.tools = 0

    def add(self, entry: dict) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def tick(self) -> str:
        self.minute -= 1
        return stamp(self.minute)

    def user(self, content, **extra) -> None:
        self.add({"parentUuid": None, "isSidechain": False, "type": "user",
                  "message": {"role": "user", "content": content}, "timestamp": self.tick(), "cwd": self.cwd,
                  "sessionId": self.session, "entrypoint": "claude-desktop", **extra})

    def prompt(self, text: str) -> None:
        self.user(text, origin={"kind": "human"})

    def said(self, text: str, message_id: str = "m1") -> None:
        self.add({"parentUuid": None, "isSidechain": False,
                  "message": {"model": "claude-opus-5-5", "id": message_id, "type": "message", "role": "assistant",
                              "content": [{"type": "text", "text": text}]},
                  "type": "assistant", "timestamp": self.tick(), "cwd": self.cwd, "sessionId": self.session})

    def tool(self, name: str, given: dict) -> str:
        self.tools += 1
        tool_id = f"toolu_{self.session}_{self.tools}"
        self.add({"parentUuid": None, "isSidechain": False,
                  "message": {"model": "claude-opus-5-5", "id": f"m{self.tools}", "type": "message",
                              "role": "assistant", "content": [{"type": "tool_use", "id": tool_id, "name": name,
                                                                "input": given}]},
                  "type": "assistant", "timestamp": self.tick(), "cwd": self.cwd, "sessionId": self.session})
        return tool_id

    def result(self, tool_id: str, text: str, is_error: bool = False) -> None:
        self.user([{"tool_use_id": tool_id, "type": "tool_result", "content": text, "is_error": is_error}],
                  toolUseResult={"stdout": text, "stderr": "", "interrupted": False})

    def bash(self, command: str, output: str, is_error: bool = False, **given) -> None:
        self.result(self.tool("Bash", {"command": command, **given}), output, is_error)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.home = base / "claude"
        self.cache = base / "cache"
        self.project = base / "work" / "demo"
        self.project.mkdir(parents=True)
        self.old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.home)
        pcl.forget_this_run()

    def tearDown(self):
        if self.old is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old
        pcl.forget_this_run()
        self.tmp.cleanup()

    def read(self) -> dict:
        pcl.forget_this_run()
        return pcl.read_project(self.project, self.cache, NOW)


class Prompts(Base):
    def test_only_what_the_owner_typed(self):
        chat = Conversation(self.home, str(self.project))
        chat.add({"type": "custom-title", "customTitle": "Grid work", "sessionId": "s1"})
        chat.prompt("Read CLAUDE.md, then do step 3")
        chat.user("<command-name>/compact</command-name>\n<command-message>compact</command-message>\n"
                  "<command-args></command-args>", origin={"kind": "human"})
        chat.user("<task-notification><task-id>x</task-id></task-notification>", origin={"kind": "task-notification"})
        chat.user("This session is being continued from a previous conversation…", isCompactSummary=True)
        chat.user("<system-reminder>injected</system-reminder>", isMeta=True)
        chat.user("Another Claude session sent a message", origin={"kind": "peer"})
        chat.add({"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "prompt",
                                                       "prompt": "also fix the typo"},
                  "timestamp": chat.tick(), "cwd": str(self.project), "sessionId": "s1"})
        chat.prompt(f"here is my key {fake_key()} <pasted_content id=\"1\">a long log</pasted_content> thanks")
        chat.said("Done.")
        found = self.read()
        texts = [p["text"] for p in found["prompts"]]
        self.assertEqual(len(texts), 4)
        self.assertIn("Read CLAUDE.md, then do step 3", texts)
        self.assertIn("/compact", texts)
        self.assertIn("also fix the typo", texts)
        last = texts[0]
        self.assertNotIn(fake_key(), last)
        self.assertIn("[an Anthropic key hidden]", last)
        self.assertIn("[pasted text]", last)
        self.assertEqual(found["sessions"][0]["title"], "Grid work")
        self.assertEqual(found["sessions"][0]["lastWords"], "Done.")


class Runs(Base):
    def test_verdicts_scope_and_pipes(self):
        chat = Conversation(self.home, str(self.project))
        chat.prompt("run the tests")
        chat.bash(f"cd {self.project} && swift test 2>&1 | tail -5",
                  "Test run with 212 tests in 9 suites passed after 41.2 seconds.")
        chat.bash("pytest -k grid", "==== 1 failed, 3 passed in 0.8s ====\nE   AssertionError: tile size")
        chat.bash("swift build 2>&1 | grep error", "", is_error=True)  # grep found nothing: not a failure
        chat.bash("sed -n 1,20p scripts/perf-run.sh", "#!/bin/zsh")  # only reads the script
        chat.said("The grid test fails.")
        found = self.read()
        test = found["lastTest"]
        self.assertEqual((test["outcome"], test["scope"]), ("fail", "-k grid"))
        self.assertIn("AssertionError", test["detail"])
        whole = found["lastWholeTest"]
        self.assertEqual((whole["outcome"], whole["tests"]), ("pass", 212))
        build = found["lastBuild"]
        self.assertEqual(build["outcome"], "unknown")
        self.assertIsNone(build["before"])
        self.assertIsNone(found["lastBench"])

    def test_a_run_in_the_background_reports_later(self):
        output = Path(self.tmp.name) / "task.output"
        output.write_text("Compiling…\nerror: cannot find 'Grid' in scope\n** BUILD FAILED **\n", encoding="utf-8")
        chat = Conversation(self.home, str(self.project))
        chat.prompt("build it")
        tool_id = chat.tool("Bash", {"command": "xcodebuild -scheme Demo build", "run_in_background": True})
        chat.result(tool_id, "Command running in background with ID: b1. Output is being written to: x")
        chat.user(f"<task-notification>\n<task-id>b1</task-id>\n<tool-use-id>{tool_id}</tool-use-id>\n"
                  f"<output-file>{output}</output-file>\n<status>completed</status>\n"
                  "<summary>finished (exit code 65)</summary>\n</task-notification>",
                  origin={"kind": "task-notification"})
        chat.said("The build failed.")
        build = self.read()["lastBuild"]
        self.assertEqual(build["outcome"], "fail")
        self.assertIn("cannot find 'Grid'", build["detail"])

    def test_runs_in_another_folder_belong_there(self):
        other = Path(self.tmp.name) / "work" / "other"
        chat = Conversation(self.home, str(other))  # started in another folder, worked here
        chat.prompt("fix demo")
        chat.tool("Edit", {"file_path": str(self.project / "app.py"), "old_string": "a", "new_string": "b"})
        chat.bash(f"cd {self.project} && python3 -m unittest -q", "Ran 5 tests in 0.1s\n\nOK")
        chat.bash("npm test", "Tests: 1 failed, 4 total")  # in the other folder
        chat.said("Fixed.")
        found = self.read()
        self.assertEqual(found["sessionCount"], 1)
        session = found["sessions"][0]
        self.assertFalse(session["startedHere"])
        self.assertEqual(session["edited"], ["app.py"])
        self.assertEqual((found["lastTest"]["outcome"], found["lastTest"]["tests"]), ("pass", 5))


class Sessions(Base):
    def test_why_a_session_stopped(self):
        limit = Conversation(self.home, str(self.project), "limit")
        limit.prompt("go on")
        limit.add({"parentUuid": None, "isSidechain": False,
                   "message": {"model": "<synthetic>", "id": "x", "type": "message", "role": "assistant",
                               "content": [{"type": "text", "text": "You've hit your session limit · resets 5am"}]},
                   "type": "assistant", "timestamp": limit.tick(), "cwd": str(self.project), "sessionId": "limit",
                   "isApiErrorMessage": True})
        working = Conversation(self.home, str(self.project), "midwork")
        working.prompt("refactor")
        working.tool("Read", {"file_path": str(self.project / "a.py")})
        stopped = Conversation(self.home, str(self.project), "stopped")
        stopped.prompt("do it")
        stopped.user([{"type": "text", "text": "[Request interrupted by user]"}])
        done = Conversation(self.home, str(self.project), "done")
        done.prompt("hello")
        done.said("Hi.")
        states = {s["id"]: (s["state"], (s["stop"] or {}).get("why")) for s in self.read()["sessions"]}
        self.assertEqual(states["limit"], ("stopped", "limit"))
        self.assertEqual(states["midwork"], ("stopped", "midwork"))
        self.assertEqual(states["stopped"], ("stopped", "interrupted"))
        self.assertEqual(states["done"], ("finished", None))

    def test_a_live_session_is_working(self):
        chat = Conversation(self.home, str(self.project), "live")
        chat.prompt("build")
        chat.tool("Bash", {"command": "swift build"})
        (self.home / "sessions").mkdir(parents=True)
        (self.home / "sessions" / f"{os.getpid()}.json").write_text(json.dumps(
            {"pid": os.getpid(), "sessionId": "live", "status": "busy", "cwd": str(self.project)}))
        (self.home / "sessions" / "999999.json").write_text(json.dumps(
            {"pid": 999999, "sessionId": "gone", "status": "busy"}))  # its process ended: not live
        found = self.read()
        self.assertEqual(found["working"], ["live"])
        self.assertEqual(found["sessions"][0]["state"], "working")

    def test_reads_only_what_was_added_and_remembers_cleaned_up_sessions(self):
        chat = Conversation(self.home, str(self.project))
        chat.prompt("first")
        chat.said("One.")
        self.assertEqual(self.read()["promptCount"], 1)
        cached = json.loads(next(self.cache.glob("*.json")).read_text())
        offset = cached["offset"]
        chat.prompt("second")
        chat.said("Two.")
        with chat.path.open("a") as handle:
            handle.write('{"type":"user","message":{"role":"user","content":"half a li')  # still being written
        found = self.read()
        self.assertEqual(found["promptCount"], 2)
        self.assertGreater(json.loads(next(self.cache.glob("*.json")).read_text())["offset"], offset)
        chat.path.unlink()  # Claude Code cleaned it up
        found = self.read()
        self.assertEqual(found["promptCount"], 2)
        self.assertTrue(found["sessions"][0]["gone"])


class Pieces(unittest.TestCase):
    def test_what_a_command_runs(self):
        self.assertIsNone(pcl.run_kind('rg -n "foo|pytest.raises" tests/test_x.py'))
        self.assertIsNone(pcl.run_kind("python3 - <<'EOF'\nimport test_x\nEOF"))
        run = pcl.run_kind("ruff check . && pytest -q 2>&1 | tail -3")
        self.assertEqual((run["kind"], run["command"], run["piped"]), ("test", "pytest -q", True))
        run = pcl.run_kind("(cd App && swift build -c release)")
        self.assertEqual((run["kind"], run["command"], run["dir"]), ("build", "swift build -c release", "App"))
        self.assertEqual(pcl.run_kind("./scripts/check-warnings.sh")["kind"], "check")
        self.assertEqual(pcl.run_kind("scripts/perf-run.sh 150000 release")["kind"], "bench")
        self.assertEqual(pcl.run_kind("swift test --filter Grid")["scope"], "--filter Grid")

    def test_outcomes(self):
        self.assertEqual(pcl.outcome_of("** BUILD SUCCEEDED **", False)[0], "pass")
        self.assertEqual(pcl.outcome_of("Ran 3 tests in 0.1s\n\nFAILED (failures=1)", False)[0], "fail")
        self.assertEqual(pcl.outcome_of("test result: ok. 4 passed", False)[0], "pass")
        self.assertEqual(pcl.outcome_of("Exit code 1\nsomething", True)[0], "fail")
        self.assertEqual(pcl.outcome_of("", True, piped=True)[0], "unknown")
        self.assertEqual(pcl.outcome_of("Test run with 12 tests passed after 1 seconds.", False)[2], 12)

    def test_encode_matches_claude_code(self):
        self.assertEqual(pcl.encode("/Users/me/Developer/Trailmix"), "-Users-me-Developer-Trailmix")
        self.assertEqual(pcl.encode("/a b/c.d_e"), "-a-b-c-d-e")


if __name__ == "__main__":
    unittest.main()
