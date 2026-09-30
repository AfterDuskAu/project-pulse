"""What Claude Code knows about a project: its conversations with you, read from Claude Code's own files on this Mac.

Claude Code saves every conversation in ~/.claude/projects/<the folder's path, every other character turned into
"-">/<session>.jsonl, and notes which sessions are open right now in ~/.claude/sessions/. Pulse reads those files
(never writes them) to show the prompts you gave Claude, what each session did, the files it changed, the tests and
builds it ran and what they said, and a session that stopped half-way (a usage limit, an error, an interruption).
Nothing leaves the Mac and no AI is used.

The files are big (a busy project has a gigabyte), so each is read once, then only from where Pulse stopped last
time: Claude Code only ever adds to the end. Pulse keeps a small digest per conversation in its own state folder,
which also remembers conversations after Claude Code has cleaned them up.

Pulse only ever opens the conversation files, the live-session list and, for a test run's verdict, the end of an
output Claude Code saved separately. Never ~/.claude.json, the .key files, shell snapshots or file backups.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path

CACHE_VERSION = 8
MAX_PROMPTS_KEPT = 80       # per session: the first one and the newest ones
MAX_PROMPT_CHARS = 600
MAX_LAST_WORDS = 1500
MAX_RUNS_KEPT = 40
PROMPT_LIST = 150           # prompts shown per project
SESSION_LIST = 40           # sessions shown per project
STOPS_SHOWN_DAYS = 7        # a session that stopped half-way is shown for this long

SECRET_HINT = re.compile(r"sk-|gh[pousr]_|github_pat_|AKIA|AIza|hf_|xox[abprs]-|_live_|PRIVATE KEY")


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def encode(path: str) -> str:
    """How Claude Code names a project's folder: every character that isn't a letter or digit becomes "-"."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def mask(text: str) -> str:
    """Keys pasted into a chat are never shown: each is replaced by what kind of key it was."""
    if not text or not SECRET_HINT.search(text):
        return text
    from pulse_any import SECRETS, looks_real
    for kind, pattern in SECRETS:
        text = pattern.sub(lambda m, k=kind: f"[{k} hidden]" if k == "a private key" or looks_real(m.group(0))
                           else m.group(0), text)
    return text


def clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


# ---------------------------------------------------------------- the owner's prompts

# What Claude Code adds to a conversation as if you'd typed it.
NOT_TYPED = re.compile(r"^\s*(<local-command-caveat>|<local-command-stdout>|<local-command-stderr>|<system-reminder>|"
                       r"<task-notification>|<cross-session-message|<bash-stdout>|<bash-stderr>|"
                       r"Caveat: The messages below|"
                       r"This session is being continued from a previous conversation|\[Request interrupted)")
COMMAND = re.compile(r"<command-name>\s*(/?[\w:.-]+)\s*</command-name>(?:.*?<command-args>(.*?)</command-args>)?",
                     re.S)
BASH_INPUT = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)
PASTED = re.compile(r"<pasted_content[^>]*>.*?</pasted_content>", re.S)
INTERRUPTED = "[Request interrupted"


def typed_text(entry: dict) -> str | None:
    """What the owner typed (a prompt, a slash command, a "!" command), or None when Claude Code wrote it: tool
    results, reminders, notifications, messages from other sessions, the summary after a compaction."""
    if entry.get("isMeta") or entry.get("isCompactSummary") or entry.get("isSidechain"):
        return None
    origin = (entry.get("origin") or {}).get("kind")
    if origin and origin != "human":
        return None
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        if not text.strip() and any(isinstance(b, dict) and b.get("type") == "image" for b in content):
            text = "[a picture]"
    elif isinstance(content, str):
        text = content
    else:
        return None
    return own_words(text)


def own_words(text: str) -> str | None:
    command = COMMAND.search(text)
    if command:
        name = command.group(1) if command.group(1).startswith("/") else "/" + command.group(1)
        return f"{name} {(command.group(2) or '').strip()}".strip()
    bash = BASH_INPUT.search(text)
    if bash:
        return "! " + bash.group(1).strip()
    if NOT_TYPED.match(text) or not text.strip():
        return None
    return text


def tidy_prompt(text: str) -> str:
    text = PASTED.sub("[pasted text]", text)
    text = re.sub(r"\[Image: [^\]]*\]", "[a picture]", text)
    return clip(mask(re.sub(r"[ \t]+", " ", text).strip()), MAX_PROMPT_CHARS)


# ---------------------------------------------------------------- tests, builds, checks and benches

# Only what a part of a command STARTS with counts: "cd x && swift test 2>&1 | tail" is a test run,
# "sed -n 1,20p scripts/perf-run.sh" only reads the script.
RUN_STARTS = [
    ("test", re.compile(r"^(?:swift test\b|xcodebuild\b.*\btest(?:-without-building)?\b|py\.?test\b|"
                        r"python[0-9.]*\s+-m\s+(?:pytest|unittest)\b|python[0-9.]*\s+\S*test\S*\.py\b|"
                        r"(?:npm|pnpm|yarn|bun)(?:\s+run)?\s+test\b|npx\s+(?:jest|vitest|mocha|playwright test)\b|"
                        r"cargo test\b|go test\b|jest\b|vitest\b|mocha\b|(?:bundle exec )?rspec\b|phpunit\b|"
                        r"\S*gradlew?\s+\S*[tT]est|mvn\b.*\btest\b|dotnet test\b|make\s+test\b|ctest\b|"
                        r"\S*(?:run-)?tests?\.sh\b)")),
    ("bench", re.compile(r"^(?:\S*perf-run\.sh\b|\S*bench\S*\.sh\b|hyperfine\b)")),
    ("check", re.compile(r"^(?:\S*check-[\w-]+\.sh\b|swiftlint\b|(?:npx\s+)?eslint\b|ruff\b|flake8\b|mypy\b|"
                         r"pylint\b|(?:npx\s+)?tsc\s+--noEmit\b|(?:npm|pnpm|yarn)(?:\s+run)?\s+lint\b)")),
    ("build", re.compile(r"^(?:swift build\b|xcodebuild\b(?!.*\s-(?:version|list|showBuildSettings|showsdks|"
                         r"showdestinations|help|find|license|exportArchive|resolvePackageDependencies)\b)|"
                         r"(?:npm|pnpm|yarn|bun)(?:\s+run)?\s+build\b|cargo build\b|"
                         r"go build\b|\S*gradlew?\s+(?:assemble|build)\S*|mvn\b.*\b(?:package|compile)\b|"
                         r"npx\s+(?:next|vite)\s+build\b|\S*build-app\.sh\b|make\b)")),
]
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2[ \t]*(?=\n|$)", re.S)
LEADING = re.compile(r"^(?:\(\s*|(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)|time\s+|caffeinate(?:\s+-\w+)*\s+|nohup\s+|"
                     r"env\s+|sudo\s+|exec\s+|(?:bash|zsh|sh)\s+(?!-c\b)|\./)+")
CD = re.compile(r"^cd\s+(\"[^\"]+\"|'[^']+'|\S+)\s*$")
SCOPE = re.compile(r"(--filter[= ](?:\"[^\"]*\"|'[^']*'|\S+)|--skip[= ]\S+|-k[= ](?:\"[^\"]*\"|'[^']*'|\S+)|"
                   r"--only-testing[:= ]\S+|-run[= ]\S+|"
                   r"--testNamePattern[= ]\S+|(?<!\S)(?:\S+/)?test\S*\.(?:py|swift|js|ts)\b|::\w+)")

FAIL_LINE = re.compile(
    r"\*\* (?:BUILD|TEST|ARCHIVE) FAILED \*\*|Test run with \d+ tests?.* failed|Executed \d+ tests?, with [1-9]\d* "
    r"failures?|^FAILED \(|\b[1-9]\d* failed\b|test result: FAILED|^FAIL\b|✘ Test .* failed|error: fatalError|"
    r"BUILD FAILED|Build failed|^Tests: .*[1-9]\d* failed|Fatal error:|terminated by signal", re.M)
PASS_LINE = re.compile(
    r"\*\* (?:BUILD|TEST|ARCHIVE) SUCCEEDED \*\*|Test run with \d+ tests?(?: in \d+ suites?)? passed[^\n]*|"
    r"Executed \d+ tests?, with 0 failures[^\n]*|^OK(?: \(skipped=\d+\))?$|test result: ok\.[^\n]*|"
    r"Build complete![^\n]*|\b\d+ passed(?:, \d+ (?:skipped|warnings?|deselected))*(?: in [\d.]+s)?|"
    r"All tests passed|^Tests: +\d+ passed, \d+ total|Compiled successfully|^PASS\b[^\n]*", re.M)
COUNT_LINE = re.compile(r"Ran (\d+) tests?|Test run with (\d+) tests?|Executed (\d+) tests?|(\d+) passed")
ERROR_LINE = re.compile(r"^.*(?:\berror:|\w*Error\b:|\w+Exception\b:|Traceback \(most recent call last\)|✘|"
                        r"^E {2,}\S).*$", re.M)


def split_command(command: str) -> list[tuple[str, str]]:
    """The parts of a shell command, each with what follows it ("&&", "|", ";"…), ignoring separators in quotes."""
    parts, current, quote, i = [], "", None, 0
    while i < len(command):
        char = command[i]
        if quote:
            current += char
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
            current += char
        elif command.startswith(("&&", "||"), i):
            parts.append((current, command[i:i + 2]))
            current, i = "", i + 2
            continue
        elif char in "|;\n":
            parts.append((current, char))
            current = ""
        else:
            current += char
        i += 1
    parts.append((current, ""))
    return parts


def run_kind(command: str) -> dict | None:
    """What a Bash command runs: {kind: test / bench / check / build, command: the part that runs it, dir: the folder
    a "cd" moved to, piped: its output went through another command, scope: only some tests}. When a command runs
    several ("ruff check && pytest"), the last one counts: its output is the one that ends the command's output."""
    folder, found = None, None
    for part, after in split_command(HEREDOC.sub("", command)):
        segment = LEADING.sub("", part.strip()).strip()
        moved = CD.match(segment)
        if moved:
            folder = moved.group(1).strip("\"'")
            continue
        for kind, pattern in RUN_STARTS:
            if pattern.match(segment):
                shown = re.split(r"\s+2>&1|\s+>\s*\S+", segment)[0].rstrip(") ")
                scope = SCOPE.search(segment)
                found = {"kind": kind, "command": shown if len(shown) <= 90 else shown[:89] + "…", "dir": folder,
                         "piped": after == "|", "scope": clip(scope.group(0), 60) if scope else None}
                break
    return found


def where(folder: str | None, cwd: str | None) -> str | None:
    """The folder a command ran in: its "cd", taken from the session's folder when it's relative."""
    if not folder:
        return cwd
    folder = os.path.expanduser(folder)
    if not folder.startswith("/") and cwd:
        folder = os.path.normpath(os.path.join(cwd, folder))
    return folder.rstrip("/") or "/"


def outcome_of(text: str, is_error: bool, piped: bool = False) -> tuple[str, str, int | None]:
    """pass / fail / unknown, the line that says so (a failure's first error line when there is one) and how many
    tests ran. The last verdict in the output decides (a failure on the same line as a pass is a failure). An exit
    code only counts when the output wasn't piped into another command, which hides it."""
    failed = is_error and not piped
    fails = list(FAIL_LINE.finditer(text))
    passes = list(PASS_LINE.finditer(text))
    fail_line = text.count("\n", 0, fails[-1].start()) if fails else -1
    pass_line = text.count("\n", 0, passes[-1].start()) if passes else -1
    count = tests_counted(text)
    if fails and (fail_line >= pass_line or failed):
        first_error = ERROR_LINE.search(text)
        line = first_error.group(0) if first_error else fails[-1].group(0)
        return "fail", clip(line.strip(), 200), count
    if passes and not failed:
        return "pass", clip(passes[-1].group(0).strip(), 200), count
    if failed:
        first_error = ERROR_LINE.search(text)
        line = first_error.group(0) if first_error else (text.strip().splitlines() or ["It stopped with an error"])[0]
        return "fail", clip(line.strip(), 200), count
    return "unknown", "", count


def tests_counted(text: str) -> int | None:
    """How many tests ran, from the last summary that says ("1 failed, 3 passed" is 4)."""
    pytest = list(re.finditer(r"(?:(\d+) failed, )?(\d+) passed", text))
    others = list(COUNT_LINE.finditer(text))
    if pytest and (not others or pytest[-1].end() >= others[-1].end()):
        return int(pytest[-1].group(1) or 0) + int(pytest[-1].group(2))
    if others:
        return next((int(g) for g in others[-1].groups() if g), None)
    return None


def result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def file_tail(path: str, limit: int = 24_000) -> str:
    """The end of an output Claude Code saved to its own file, where tests and builds say how they went."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - limit))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------- why a session stopped

LIMIT = re.compile(r"hit your (?:session |usage |weekly )?limit|usage limit|limit reached|resets? (?:at )?\d", re.I)


def stop_reason(text: str) -> str:
    if LIMIT.search(text):
        return "limit"
    if "Prompt is too long" in text:
        return "full"
    return "api"


# ---------------------------------------------------------------- one conversation file

def new_summary(path: Path) -> dict:
    return {"id": path.stem, "file": str(path), "title": None, "firstPrompt": None, "cwd": None, "branch": None,
            "started": None, "ended": None, "entry": None, "model": None, "version": None, "prompts": [],
            "promptCount": 0, "lastWords": None, "lastPromptAt": None, "edited": {}, "runs": [], "pending": {},
            "background": {}, "toolUses": 0, "toolResults": 0, "lastRole": None, "problem": None, "cost": None,
            "compactions": 0}


def add_prompt(summary: dict, text: str, stamp: str | None) -> None:
    prompt = tidy_prompt(text)
    seen = summary.setdefault("seen", [])
    key = f"{stamp}|{prompt[:120]}"
    if key in seen or any(p["text"] == prompt for p in summary["prompts"][-4:]):
        return  # written twice: queued while Claude was busy and then sent, or the conversation replayed
    seen.append(key)
    del seen[:-400]
    summary["promptCount"] += 1
    summary["firstPrompt"] = summary["firstPrompt"] or clip(prompt, 160)
    summary["prompts"].append({"at": stamp, "text": prompt})
    if len(summary["prompts"]) > MAX_PROMPTS_KEPT:
        del summary["prompts"][1:len(summary["prompts"]) - MAX_PROMPTS_KEPT + 1]
    summary["lastPromptAt"] = stamp
    summary["lastRole"] = "prompt"
    summary["problem"] = None


def note_edit(summary: dict, path: str | None, stamp: str | None) -> None:
    if not path:
        return
    if not path.startswith("/") and summary["cwd"]:
        path = os.path.normpath(os.path.join(summary["cwd"], path))
    summary["edited"][path] = stamp


def finish_run(summary: dict, run: dict, text: str, is_error: bool, stopped: bool = False) -> None:
    saved = re.search(r"Full output saved to: (\S+)", text)
    if saved:
        text += "\n" + file_tail(saved.group(1))
    outcome, line, count = ("unknown", "Stopped before it finished", None) if stopped else \
        outcome_of(text, is_error, run.get("piped", False))
    summary["runs"].append({**run, "outcome": outcome, "detail": mask(line), "tests": count})
    del summary["runs"][:-MAX_RUNS_KEPT]


def absorb(summary: dict, entry: dict) -> None:
    """Adds one line of a conversation file to the session's digest."""
    kind = entry.get("type")
    stamp = entry.get("timestamp")
    if stamp and kind != "file-history-snapshot":
        summary["started"] = summary["started"] or stamp
        summary["ended"] = max(summary["ended"] or stamp, stamp)
    if entry.get("cwd") and not summary["cwd"]:
        summary["cwd"] = entry["cwd"]
    if entry.get("gitBranch") and entry["gitBranch"] != "HEAD":
        summary["branch"] = entry["gitBranch"]
    for field, key in (("entrypoint", "entry"), ("version", "version")):
        if entry.get(field):
            summary[key] = entry[field]
    if kind in ("custom-title", "agent-name", "summary"):
        title = entry.get("customTitle") or entry.get("agentName") or entry.get("summary")
        if title and (kind != "summary" or not summary["title"]):
            summary["title"] = clip(mask(str(title)), 120)
    elif kind == "cost-state":
        usage = entry.get("modelUsage") or {}
        summary["cost"] = {
            "usd": round(float(entry.get("totalCostUSD") or 0), 2),
            "added": entry.get("totalLinesAdded") or 0, "removed": entry.get("totalLinesRemoved") or 0,
            "tokens": sum(int(m.get("inputTokens", 0)) + int(m.get("outputTokens", 0))
                          + int(m.get("cacheCreationInputTokens", 0)) for m in usage.values() if isinstance(m, dict)),
        }
    elif kind == "file-history-delta":
        note_edit(summary, entry.get("trackingPath"), stamp)
    elif kind == "system":
        if entry.get("subtype") == "compact_boundary":
            summary["compactions"] += 1
    elif kind == "attachment":
        attached = entry.get("attachment") or {}
        if attached.get("type") == "queued_command" and attached.get("commandMode") == "prompt" \
                and isinstance(attached.get("prompt"), str):
            words = own_words(attached["prompt"])  # typed while Claude was busy
            if words:
                add_prompt(summary, words, stamp or attached.get("timestamp"))
    elif kind == "assistant" and not entry.get("isSidechain"):
        absorb_assistant(summary, entry, stamp)
    elif kind == "user":
        absorb_user(summary, entry, stamp)


def absorb_assistant(summary: dict, entry: dict, stamp: str | None) -> None:
    message = entry.get("message") or {}
    model = str(message.get("model") or "")
    blocks = [b for b in message.get("content") or [] if isinstance(b, dict)]
    if model == "<synthetic>" or entry.get("isApiErrorMessage"):
        said = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        if said:
            summary["problem"] = {"why": stop_reason(said), "text": clip(mask(said), 200), "at": stamp}
        return
    if model and not model.startswith("<"):
        summary["model"] = model
    for block in blocks:
        if block.get("type") == "text" and block.get("text", "").strip():
            text = block["text"].strip()
            words = summary["lastWords"]
            if words and words.get("id") == message.get("id") and summary["lastRole"] == "said":
                text = words["text"] + "\n\n" + text  # one message's text can arrive in several lines
            summary["lastWords"] = {"id": message.get("id"), "text": clip(mask(text), MAX_LAST_WORDS), "at": stamp}
            summary["lastRole"] = "said"
            summary["problem"] = None
        elif block.get("type") == "tool_use":
            summary["toolUses"] += 1
            summary["lastRole"] = "working"
            name, given = block.get("name"), block.get("input") or {}
            if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                note_edit(summary, given.get("file_path") or given.get("notebook_path"), stamp)
            elif name == "Bash":
                run = run_kind(str(given.get("command") or ""))
                if run and block.get("id"):
                    run = {"at": stamp, "kind": run["kind"], "command": clip(mask(run["command"]), 120),
                           "dir": where(run["dir"], entry.get("cwd") or summary["cwd"]), "piped": run["piped"],
                           "scope": run["scope"], "background": bool(given.get("run_in_background"))}
                    summary["background" if run["background"] else "pending"][block["id"]] = run


def absorb_user(summary: dict, entry: dict, stamp: str | None) -> None:
    message = entry.get("message") or {}
    content = message.get("content")
    extra = entry.get("toolUseResult")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            summary["toolResults"] += 1
            summary["lastRole"] = "working"
            run = summary["pending"].pop(block.get("tool_use_id"), None)
            if run:
                text = result_text(block)
                if isinstance(extra, dict) and not text.strip():
                    text = f"{extra.get('stdout', '')}\n{extra.get('stderr', '')}"
                if "Command running in background" in text:
                    summary["background"][block.get("tool_use_id")] = run
                    continue
                finish_run(summary, run, text, bool(block.get("is_error")),
                           stopped=isinstance(extra, dict) and bool(extra.get("interrupted")))
        if isinstance(extra, dict) and isinstance(extra.get("bashEditDiff"), dict):
            for changed in extra["bashEditDiff"].get("files") or []:
                if isinstance(changed, dict):
                    note_edit(summary, changed.get("filePath"), stamp)
    text = content if isinstance(content, str) else " ".join(
        str(b.get("text", "")) for b in content or [] if isinstance(b, dict))
    if "<task-notification>" in text and "<tool-use-id>" in text:
        tool = re.search(r"<tool-use-id>\s*(\S+?)\s*</tool-use-id>", text)
        run = summary["background"].pop(tool.group(1), None) if tool else None
        if run:
            output = re.search(r"<output-file>\s*(\S+?)\s*</output-file>", text)
            exit_code = re.search(r"exit code (\d+)", text)
            tail = file_tail(output.group(1)) if output else ""
            finish_run(summary, {**run, "piped": run["piped"] or not exit_code}, tail or text,
                       bool(exit_code and exit_code.group(1) != "0"),
                       stopped=bool(re.search(r"<status>\s*(killed|stopped)", text)))
        return
    if INTERRUPTED in text:
        summary["problem"] = {"why": "interrupted", "text": "You stopped it", "at": stamp}
        return
    typed = typed_text(entry)
    if typed is not None:
        add_prompt(summary, typed, stamp)


def interesting(line: bytes) -> bool:
    """A quick look before the (slow) JSON reading: most of a conversation file is file contents and tool output
    Pulse doesn't need. An assistant line names its type at its very end, but its role near the start."""
    head = line[:360]
    return any(kind in head for kind in (
        b'"type":"user"', b'"role":"assistant"', b'"type":"custom-title"', b'"type":"agent-name"',
        b'"type":"cost-state"', b'"type":"file-history-delta"', b'"type":"system"', b'"type":"summary"'))


def read_file(path: Path, cached: dict | None) -> dict:
    """Reads a conversation file from where Pulse stopped last time (or from the start)."""
    stat = path.stat()
    fresh = bool(cached) and cached.get("version") == CACHE_VERSION and cached.get("inode") == stat.st_ino
    if fresh and cached.get("size") == stat.st_size and cached.get("mtime") == stat.st_mtime:
        return cached
    if fresh and cached.get("offset", 0) <= stat.st_size:
        summary, offset = cached["summary"], cached["offset"]
    else:
        summary, offset = new_summary(path), 0  # new, or rewritten: from the start
    with path.open("rb") as handle:
        handle.seek(offset)
        for line in handle:
            if not line.endswith(b"\n"):
                break  # still being written: next time
            offset += len(line)
            if not interesting(line) and b'"queued_command"' not in line[:600]:
                continue
            if b'"tool_use_id"' in line and b'"type":"user"' in line[:360]:
                waiting = summary["pending"]
                if (not waiting or not any(key.encode() in line for key in waiting)) and b"bashEditDiff" not in line:
                    summary["toolResults"] += line.count(b'"type":"tool_result"') or 1
                    summary["lastRole"] = "working"
                    continue  # a result nobody waits for: only counted
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                absorb(summary, entry)
    return {"version": CACHE_VERSION, "inode": stat.st_ino, "size": stat.st_size, "mtime": stat.st_mtime,
            "offset": offset, "summary": summary}


# ---------------------------------------------------------------- every conversation on this Mac

def cache_name(path: Path) -> str:
    return hashlib.sha1(str(path).encode()).hexdigest()[:20] + ".json"


_SEEN: dict[str, list[dict]] = {}


def all_sessions(cache_dir: Path) -> list[dict]:
    """Every conversation's digest: the ones Claude Code still has, read up to date, and the ones it cleaned up,
    from Pulse's own memory. Read once per refresh, however many projects ask."""
    remembered = _SEEN.get(str(cache_dir))
    if remembered is not None:
        return remembered
    base = claude_home() / "projects"
    cache_dir.mkdir(parents=True, exist_ok=True)
    kept = {p.name: p for p in cache_dir.glob("*.json")}
    sessions = []
    files = [p for folder in (base.iterdir() if base.is_dir() else []) if folder.is_dir()
             for p in folder.glob("*.jsonl") if p.is_file()]
    for path in files:
        name = cache_name(path)
        cached = None
        if name in kept:
            try:
                cached = json.loads(kept.pop(name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = None
        try:
            fresh = read_file(path, cached)
        except OSError:
            continue
        if fresh is not cached:
            target = cache_dir / name
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, target)
        if fresh["summary"]["started"]:
            sessions.append(fresh["summary"])
    for leftover in kept.values():  # Claude Code cleaned these up; Pulse still remembers them
        try:
            summary = json.loads(leftover.read_text(encoding="utf-8"))["summary"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if summary.get("started"):
            sessions.append({**summary, "gone": True})
    _SEEN[str(cache_dir)] = sessions
    return sessions


def forget_this_run() -> None:
    _SEEN.clear()


def live_sessions() -> dict[str, dict]:
    """Claude Code sessions open right now, by session id: working (busy) or waiting for you (idle)."""
    live = {}
    for path in (claude_home() / "sessions").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            os.kill(int(data.get("pid") or path.stem), 0)
        except PermissionError:
            pass  # a process of another user with that number: still alive
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if isinstance(data, dict) and data.get("sessionId"):
            live[data["sessionId"]] = {"status": data.get("status"), "cwd": data.get("cwd"), "name": data.get("name")}
    return live


# ---------------------------------------------------------------- one project's view

def inside(path: str | None, root: str) -> bool:
    """Is the path the folder or in it? `root` may hold two spellings of one folder, joined by "\n" (as added, and
    with its links resolved: /tmp and /private/tmp)."""
    if not path:
        return False
    return any(path == r or path.startswith(r + "/") for r in root.split("\n"))


def strip_root(path: str, root: str) -> str:
    for r in root.split("\n"):
        if path.startswith(r + "/"):
            return path[len(r) + 1:]
    return path


def local(stamp: str | None) -> str | None:
    """Claude Code writes UTC ("…Z"); Pulse shows local time with its offset."""
    if not stamp:
        return None
    try:
        return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().isoformat(timespec="seconds")
    except ValueError:
        return stamp


def when(stamp: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(local(stamp)) if stamp else None
    except (TypeError, ValueError):
        return None


def session_state(s: dict, live: dict) -> tuple[str, dict | None]:
    """working / open (waiting for you) / finished / stopped (with why)."""
    state = (live.get(s["id"]) or {}).get("status")
    if state == "busy":
        return "working", None
    if state:
        return "open", None
    if s.get("problem"):
        return "stopped", s["problem"]
    if s.get("lastRole") == "working":
        return "stopped", {"why": "midwork", "text": "It stopped in the middle of its work", "at": s["ended"]}
    if s.get("lastRole") == "prompt":
        return "stopped", {"why": "noreply", "text": "Your last prompt got no answer", "at": s["lastPromptAt"]}
    return "finished", None


def readable(s: dict) -> bool:
    """A format check: in a conversation Pulse reads fully, nearly every tool call has its result."""
    uses = s.get("toolUses", 0)
    return uses < 20 or s.get("toolResults", 0) >= 0.9 * uses


def session_view(s: dict, root: str, live: dict) -> dict:
    state, problem = session_state(s, live)
    changed = sorted(s["edited"].items(), key=lambda kv: kv[1] or "", reverse=True)
    here = [strip_root(p, root) for p, _ in changed if inside(p, root)]
    words = s.get("lastWords") or {}
    return {
        "id": s["id"], "title": s["title"] or s["firstPrompt"] or "A conversation", "started": local(s["started"]),
        "ended": local(s["ended"]), "state": state,
        "stop": {**problem, "at": local(problem.get("at"))} if problem else None,
        "prompts": s["promptCount"], "model": s["model"], "branch": s["branch"],
        "app": {"claude-desktop": "Claude app", "cli": "Terminal"}.get(s["entry"] or "", "Other"),
        "lastWords": words.get("text"), "lastWordsAt": local(words.get("at")),
        "lastPrompt": s["prompts"][-1]["text"] if s["prompts"] else None,
        "edited": here[:40], "editedCount": len(here), "editedElsewhere": len(changed) - len(here),
        "startedHere": inside(s["cwd"], root), "startedIn": s["cwd"],
        "runs": [{**r, "at": local(r["at"])} for r in s["runs"] if inside(r.get("dir") or s["cwd"], root)][-8:],
        "cost": s["cost"], "compactions": s["compactions"], "gone": bool(s.get("gone")), "readable": readable(s),
    }


def verdict(runs: list[tuple[dict, dict]], kinds: tuple[str, ...], whole: bool = False) -> dict | None:
    """The newest run of these kinds (optionally only runs of every test). When it didn't say how it went, the newest
    one that did comes with it as "before"."""
    found = sorted(((r, s) for r, s in runs if r["kind"] in kinds and (not whole or not r.get("scope"))),
                   key=lambda pair: pair[0]["at"] or "", reverse=True)
    if not found:
        return None

    def shown(pair: tuple[dict, dict]) -> dict:
        run, session = pair
        return {"at": local(run["at"]), "kind": run["kind"], "command": run["command"], "outcome": run["outcome"],
                "detail": run["detail"], "scope": run.get("scope"), "tests": run.get("tests"),
                "session": session["id"], "sessionTitle": session["title"] or session["firstPrompt"]}

    newest = shown(found[0])
    if newest["outcome"] == "unknown":
        said = next((pair for pair in found if pair[0]["outcome"] != "unknown"), None)
        newest["before"] = shown(said) if said else None
    return newest


def read_project(root: Path, cache_dir: Path, now: dt.datetime) -> dict | None:
    """Everything Pulse shows about a project's Claude Code conversations, or None when it has none.

    A conversation belongs to the project when it ran in the folder, changed files in it, or ran commands in it
    (a session started in another folder that worked here counts too)."""
    given, real = str(root).rstrip("/"), os.path.realpath(str(root)).rstrip("/")
    here = given if given == real else f"{given}\n{real}"  # a folder added through a link: sessions name the real path
    live = live_sessions()
    sessions = [s for s in all_sessions(cache_dir) if inside(s["cwd"], here) or any(inside(p, here) for p in s["edited"])
                or any(inside(r.get("dir"), here) for r in s["runs"])]
    if not sessions:
        return None
    sessions.sort(key=lambda s: s["ended"] or "", reverse=True)
    views = [session_view(s, here, live) for s in sessions[:SESSION_LIST]]
    runs = [(r, s) for s in sessions for r in s["runs"] if inside(r.get("dir") or s["cwd"], here)]
    prompts = [{"at": local(p["at"]), "text": p["text"], "session": s["id"],
                "sessionTitle": s["title"] or s["firstPrompt"], "startedHere": inside(s["cwd"], here)}
               for s in sessions for p in s["prompts"]]
    prompts.sort(key=lambda p: p["at"] or "", reverse=True)
    week_ago = now - dt.timedelta(days=7)
    week = [s for s in sessions if (when(s["ended"]) or week_ago) > week_ago]
    stops = [v for v in views if v["state"] == "stopped" and v["stop"]
             and (when(v["stop"].get("at")) or week_ago) > now - dt.timedelta(days=STOPS_SHOWN_DAYS)]
    unreadable = [s for s in sessions[:SESSION_LIST] if not readable(s)]
    return {
        "sessions": views, "sessionCount": len(sessions), "prompts": prompts[:PROMPT_LIST],
        "promptCount": sum(s["promptCount"] for s in sessions),
        "working": [v["id"] for v in views if v["state"] == "working"],
        "open": [v["id"] for v in views if v["state"] == "open"],
        "lastTest": verdict(runs, ("test",)), "lastWholeTest": verdict(runs, ("test",), whole=True),
        "lastBuild": verdict(runs, ("build",)), "lastCheck": verdict(runs, ("check",)),
        "lastBench": verdict(runs, ("bench",)),
        "stops": stops[:6],
        "week": {"sessions": len(week), "prompts": sum(s["promptCount"] for s in week),
                 "added": sum((s["cost"] or {}).get("added", 0) for s in week),
                 "removed": sum((s["cost"] or {}).get("removed", 0) for s in week),
                 "usd": round(sum((s["cost"] or {}).get("usd", 0) for s in week), 2)},
        "memory": memories(root),
        "unreadable": {"count": len(unreadable), "version": unreadable[0].get("version")} if unreadable else None,
        "since": local(min(s["started"] for s in sessions)),
    }


def memories(root: Path) -> list[dict]:
    """Claude's own notes about this project (its auto-memory), by name and one-line summary."""
    folder = claude_home() / "projects" / encode(str(root)) / "memory"
    found = []
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        if path.name == "MEMORY.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")[:4000]
        name = re.search(r"^name:\s*(.+)$", text, re.M)
        about = re.search(r"^description:\s*[\"']?(.+?)[\"']?\s*$", text, re.M)
        found.append({"name": (name.group(1) if name else path.stem).strip(),
                      "about": clip(mask(about.group(1)), 200) if about else "", "path": str(path)})
    return found


def folders_used() -> list[dict]:
    """The folders Claude Code has worked in on this Mac, newest first: Pulse offers them on its first run."""
    seen: dict[str, str] = {}
    base = claude_home() / "projects"
    for folder in base.iterdir() if base.is_dir() else []:
        if not folder.is_dir():
            continue
        for path in folder.glob("*.jsonl"):
            cwd = None
            try:
                with path.open("rb") as handle:
                    for _, line in zip(range(80), handle):
                        found = re.search(rb'"cwd":"([^"]+)"', line)
                        if found:
                            cwd = found.group(1).decode("utf-8", errors="replace")
                            break
                stamp = dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
            except OSError:
                continue
            if cwd and Path(cwd).is_dir():
                seen[cwd] = max(seen.get(cwd, ""), stamp)
    return [{"path": p, "last": t} for p, t in sorted(seen.items(), key=lambda kv: kv[1], reverse=True)]
