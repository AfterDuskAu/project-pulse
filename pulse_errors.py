"""Errors a project leaves outside its folder: crash reports and Xcode's own record of its last build.

macOS writes a report each time an app (or a test run) crashes, in ~/Library/Logs/DiagnosticReports. Pulse finds
the ones of the project's own app, by its name or bundle ID, and of its tests (a Swift package's test runner loads
"<Package>PackageTests"), and shows when, how (the exception) and where (the first place in the project's own code).
Xcode keeps a record of each build made in the Xcode app, with its errors and warnings.

Read-only, no network, no AI.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import plistlib
import re
from pathlib import Path

CRASH_DAYS = 14
MAX_CRASHES = 12
CRASH = {"309", "109"}  # crash reports (the JSON format, and the older one)
TEST_RUNNERS = {"swiftpm-testing-helper", "xctest", "XCTRunner", "xctest-x86_64", "xctest-arm64"}
SKIP_SYMBOLS = re.compile(r"\$main|^main$|_crashOnException|reportException|NSApplicationMain|UIApplicationMain|"
                          r"_assertionFailure|swift_unexpectedError|__exceptionPreprocess|objc_exception_throw|"
                          r"__chkstk_darwin")


def reports_folder() -> Path:
    return Path(os.environ.get("PULSE_CRASH_REPORTS") or Path.home() / "Library/Logs/DiagnosticReports")


def names_for(ctx) -> dict[str, set[str]]:
    """What the project's crashes are called: its apps' names and bundle IDs (from the Xcode project), its Swift
    packages' test bundles, and the executables its packages build. `ctx` is a pulse_checks.Context."""
    apps, bundles, images = set(), set(), set()
    for x in ctx.xcode:
        for app in x.apps:
            settings = x.release(app)
            product = settings.get("PRODUCT_NAME", "")
            apps.add(app["name"] if not product or "$(" in product else product)
            if settings.get("PRODUCT_BUNDLE_IDENTIFIER") and "$(" not in settings["PRODUCT_BUNDLE_IDENTIFIER"]:
                bundles.add(settings["PRODUCT_BUNDLE_IDENTIFIER"])
    for rel in ctx.find("Package.swift"):
        text = ctx.text(rel)
        package = re.search(r"Package\s*\(\s*name:\s*\"([^\"]+)\"", text)
        if package:
            images.add(package.group(1) + "PackageTests")
        for executable in re.findall(r"\.executable(?:Target)?\s*\(\s*name:\s*\"([^\"]+)\"", text):
            apps.add(executable)
    images |= {f"{name}Tests" for name in apps}
    return {"apps": apps, "bundles": bundles, "images": images}


def crashes(names: dict[str, set[str]], now: dt.datetime) -> list[dict]:
    """The project's crashes in the last two weeks, newest first."""
    folder = reports_folder()
    if not folder.is_dir() or not (names["apps"] or names["bundles"] or names["images"]):
        return []
    found = []
    cutoff = (now - dt.timedelta(days=CRASH_DAYS)).timestamp()
    for path in folder.glob("*.ips"):
        try:
            if path.stat().st_mtime < cutoff:
                continue
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                header = json.loads(handle.readline() or "{}")
                if str(header.get("bug_type")) not in CRASH:
                    continue
                app = header.get("app_name") or header.get("name") or ""
                ours = app in names["apps"] or header.get("bundleID") in names["bundles"]
                if not ours and app not in TEST_RUNNERS:
                    continue
                body = json.loads(handle.read() or "{}")
        except (OSError, ValueError):
            continue
        images = [i.get("name") or "" for i in body.get("usedImages") or [] if isinstance(i, dict)]
        test_image = next((i for i in images if i in names["images"]), None)
        if not ours and not test_image:
            continue  # another project's tests
        own = (names["apps"] | names["images"]) & set(images) or names["apps"] | names["images"]
        found.append({
            "at": report_time(header.get("timestamp"), path),
            "app": app if ours else f"{test_image} (tests)", "tests": not ours,
            "version": header.get("app_version") or None,
            "exception": exception_of(body),
            "where": first_own_frame(body, images, own),
            "path": str(path),
        })
    found.sort(key=lambda c: c["at"] or "", reverse=True)
    return found[:MAX_CRASHES]


def report_time(stamp: str | None, path: Path) -> str:
    """"2026-09-30 13:42:03.00 +1000" → ISO 8601 with the offset; failing that, the file's time."""
    if stamp:
        found = re.match(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.\d+)? ([+-]\d{2})(\d{2})", stamp)
        if found:
            return f"{found.group(1)}T{found.group(2)}{found.group(3)}:{found.group(4)}"
    return dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def exception_of(body: dict) -> str:
    exception = body.get("exception") or {}
    kind = exception.get("type") or ""
    signal = exception.get("signal") or ""
    indicator = (body.get("termination") or {}).get("indicator") or ""
    if body.get("asiBacktraces") and kind == "EXC_BAD_INSTRUCTION":
        return "an uncaught exception"
    threads = body.get("threads") or [{}]
    faulting = json.dumps(threads[body.get("faultingThread") or 0] if (body.get("faultingThread") or 0) < len(threads)
                          else {})[:20000]
    if "_assertionFailure" in faulting:
        return "a Swift runtime error (a failed check, a force-unwrap or try!)"
    if "__chkstk_darwin" in faulting[:3000]:
        return "a stack overflow (code that calls itself too deeply)"
    return " · ".join(p for p in (kind, signal) if p) or indicator or "a crash"


def readable_symbol(symbol: str) -> str:
    """A mangled Swift name ("$s10TrailmixUI8MapCacheC4load…") as "MapCache.load":
    the names spelt out as <length><name>, without the module's."""
    found = re.match(r"_?\$[sS]", symbol)
    if not found:
        return symbol
    body, names, i = symbol[found.end():], [], 0
    while i < len(body):
        digits = re.match(r"\d+", body[i:])
        if not digits:
            if body[i].isalpha() and i + 1 < len(body) and body[i + 1].isdigit() and len(names) < 4:
                i += 1  # a one-letter kind between names (C class, V struct, O enum)
                continue
            break
        length, start = int(digits.group(0)), i + len(digits.group(0))
        name = body[start:start + length]
        if len(name) < length or name.startswith("_"):
            break  # a private name's hash: the readable part is over
        names.append(name)
        i = start + length
    return ".".join(names[1:] if len(names) > 1 else names) or symbol


def first_own_frame(body: dict, images: list[str], own: set[str]) -> str | None:
    """The first line of the project's own code on the crashing thread (or in the exception's backtrace)."""
    threads = body.get("threads") or []
    faulting = body.get("faultingThread")
    frames = threads[faulting].get("frames") or [] if isinstance(faulting, int) and faulting < len(threads) else []
    for text in body.get("asiBacktraces") or []:  # an Objective-C exception: where it was thrown
        for line in str(text).splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4 and parts[1] in own:
                symbol = re.sub(r"\s+\+\s+\d+$", "", parts[3]).strip()
                if symbol and not SKIP_SYMBOLS.search(symbol):
                    return readable_symbol(symbol)[:160]
    for frame in frames:
        index = frame.get("imageIndex")
        image = images[index] if isinstance(index, int) and index < len(images) else ""
        symbol = frame.get("symbol") or ""
        if image in own and symbol and not SKIP_SYMBOLS.search(symbol):
            return readable_symbol(symbol)[:160]
    return None


def xcode_build(root: Path) -> dict | None:
    """Xcode's own record of the last build made in the Xcode app for this folder's project (builds from the
    command line aren't always in it). None when Xcode never built it."""
    derived = Path(os.environ.get("PULSE_DERIVED_DATA") or Path.home() / "Library/Developer/Xcode/DerivedData")
    if not derived.is_dir():
        return None
    here = str(root).rstrip("/") + "/"
    newest = None
    for info in derived.glob("*/info.plist"):
        try:
            with info.open("rb") as handle:
                workspace = plistlib.load(handle).get("WorkspacePath") or ""
        except Exception:  # a broken plist is just "not this project"
            continue
        if not workspace.startswith(here) or not Path(workspace).exists():
            continue
        manifest = info.parent / "Logs" / "Build" / "LogStoreManifest.plist"
        try:
            with manifest.open("rb") as handle:
                logs = (plistlib.load(handle).get("logs") or {}).values()
        except Exception:
            continue
        for entry in logs:
            if isinstance(entry, dict) and (not newest or entry.get("timeStoppedRecording", 0) >
                                            newest.get("timeStoppedRecording", 0)):
                newest = entry
    if not newest:
        return None
    seen = newest.get("primaryObservable") or {}
    moment = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(
        seconds=float(newest.get("timeStoppedRecording") or 0))
    status = {"S": "pass", "W": "pass", "E": "fail"}.get(seen.get("highLevelStatus"), "unknown")
    return {"at": moment.astimezone().isoformat(timespec="seconds"), "outcome": status,
            "title": newest.get("title") or "Build", "errors": seen.get("totalNumberOfErrors") or 0,
            "warnings": seen.get("totalNumberOfWarnings") or 0}
