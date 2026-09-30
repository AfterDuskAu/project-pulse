"""Checklists: what every project needs, and a release checklist for what it's made for.

Pulse works out what a folder is made for (a Mac or iPhone app for the App Store, a Mac app shared outside the store,
a website, a Python or npm package, a browser extension, an Android app) and shows the matching checklist; any other
list can be added by hand ("checklists" in projects.json). It ticks by itself what the files prove (the App Sandbox is
on, the app icon has its pictures, a privacy manifest is there); the rest (screenshots, a privacy policy, the store
listing) the owner ticks in the app, and Pulse keeps those ticks in its own comments folder, never in the project.

Read-only, no network, no AI.
"""
from __future__ import annotations

import fnmatch
import json
import plistlib
import re
from pathlib import Path

PASS, FAIL, TODO, TICKED, WARN, SKIPPED = "pass", "fail", "todo", "ticked", "warn", "skipped"
APP_CODE_EXT = (".swift", ".m", ".mm", ".h", ".c", ".cc", ".cpp")
WEB_FRAMEWORKS = ("react", "next", "vue", "nuxt", "svelte", "@sveltejs/kit", "vite", "astro", "gatsby", "remix",
                  "@remix-run/react", "angular", "@angular/core", "solid-js", "express", "fastify", "hono", "koa")
CLAUDE_MD_WARN_CHARS = 40_000  # Claude Code itself warns about a CLAUDE.md bigger than this


# ---------------------------------------------------------------- reading an Xcode project

SETTING = re.compile(r'^\s*"?([A-Za-z0-9_]+(?:\[[^\]]*\])?)"?\s*=\s*(.*?)\s*;?\s*$')


def parse_settings(block: str) -> dict[str, str]:
    """One buildSettings block: KEY = value; and KEY = ( "a", "b", ); (a list becomes "a b")."""
    settings: dict[str, str] = {}
    lines = iter(block.splitlines())
    for line in lines:
        match = SETTING.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).rstrip(";").strip()
        if value == "(":
            parts = []
            for inner in lines:
                inner = inner.strip()
                if inner.startswith(")"):
                    break
                parts.append(inner.rstrip(",").strip().strip('"'))
            value = " ".join(p for p in parts if p)
        settings[key] = value.strip('"')
    return settings


class Xcode:
    """The app targets of one project.pbxproj, and their settings for each build configuration (Debug, Release)."""

    # One object: many lines ending with a line of two tabs and "};", or all on one line.
    OBJECT = re.compile(r"^\t\t(\w+) (?:/\* (.*?) \*/ )?= \{(?:\n\t\t\tisa = (\w+);(.*?)^\t\t\};"
                        r"|isa = (\w+);([^\n]*)\};$)", re.M | re.S)

    def __init__(self, rel: str, text: str):
        self.rel = rel
        self.folder = rel.rsplit("/", 2)[0] if rel.count("/") >= 2 else ""  # where the .xcodeproj sits
        objects = {m.group(1): (m.group(3) or m.group(5), m.group(4) or m.group(6) or "")
                   for m in self.OBJECT.finditer(text)}
        configs: dict[str, tuple[str, dict[str, str]]] = {}
        for oid, (isa, body) in objects.items():
            if isa == "XCBuildConfiguration":
                settings = re.search(r"buildSettings = \{(.*?)\n\t*\};", body, re.S)
                name = re.search(r"\bname = \"?([^\";]+)\"?;", body[settings.end():] if settings else body)
                configs[oid] = (name.group(1) if name else "?", parse_settings(settings.group(1)) if settings else {})

        def config_list(list_id: str) -> dict[str, dict[str, str]]:
            isa, body = objects.get(list_id, ("", ""))
            found = re.search(r"buildConfigurations = \((.*?)\);", body, re.S)
            ids = re.findall(r"(\w+)(?: /\*.*?\*/)?,", found.group(1)) if found else []
            return {configs[i][0]: configs[i][1] for i in ids if i in configs}

        self.project: dict[str, dict[str, str]] = {}
        for isa, body in objects.values():
            if isa == "PBXProject":
                found = re.search(r"buildConfigurationList = (\w+)", body)
                if found:
                    self.project = config_list(found.group(1))
        self.apps: list[dict] = []  # {"name", "configs": {"Release": {...merged...}}}
        for isa, body in objects.values():
            if isa != "PBXNativeTarget":
                continue
            kind = re.search(r'productType = "?([^";]+)"?;', body)
            if not kind or kind.group(1) != "com.apple.product-type.application":
                continue
            name = re.search(r"\bname = \"?([^\";]+)\"?;", body)
            found = re.search(r"buildConfigurationList = (\w+)", body)
            own = config_list(found.group(1)) if found else {}
            merged = {}
            for config in set(own) | set(self.project):
                merged[config] = {**self.project.get(config, {}), **own.get(config, {})}
            self.apps.append({"name": name.group(1) if name else "app", "configs": merged})

    def release(self, app: dict) -> dict[str, str]:
        configs = app["configs"]
        return configs.get("Release") or next((v for k, v in configs.items() if "release" in k.lower()), {}) \
            or next(iter(configs.values()), {})

    def platforms(self, app: dict) -> set[str]:
        settings = self.release(app)
        found = set()
        sdk = settings.get("SDKROOT", "") + " " + settings.get("SUPPORTED_PLATFORMS", "")
        if "macosx" in sdk or "MACOSX_DEPLOYMENT_TARGET" in settings and "iphoneos" not in sdk:
            found.add("mac")
        if "iphoneos" in sdk or "IPHONEOS_DEPLOYMENT_TARGET" in settings and "SDKROOT" not in settings:
            found.add("ios")
        if settings.get("SUPPORTS_MACCATALYST") == "YES":
            found.add("mac")
        return found or {"mac"}


# ---------------------------------------------------------------- code that ships

DIRECTIVE = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elseif|elif|else|endif)\b(.*)$")


def release_code(text: str) -> str:
    """The code without its debug-only parts (#if DEBUG … #endif): what a Release build is made of. Lines are kept
    as blank lines, so line numbers still match the file."""
    if "#if" not in text:
        return text
    out: list[str] = []
    stack: list[dict] = []  # per open #if: is this branch debug-only, and was the condition "not DEBUG"
    for line in text.splitlines(keepends=True):
        match = DIRECTIVE.match(line)
        if match:
            kind, condition = match.group(1), match.group(2)
            debug = bool(re.search(r"\bDEBUG\b", condition))
            negated = bool(re.search(r"!\s*DEBUG\b", condition))
            if kind in ("if", "ifdef"):
                stack.append({"skip": debug and not negated, "negated": negated})
            elif kind == "ifndef":
                stack.append({"skip": False, "negated": debug})
            elif kind in ("elseif", "elif") and stack:
                stack[-1]["skip"] = False
            elif kind == "else" and stack:
                stack[-1]["skip"] = stack[-1]["negated"]
            elif kind == "endif" and stack:
                stack.pop()
            out.append("\n")
            continue
        out.append("\n" if any(level["skip"] for level in stack) else line)
    return "".join(out)


# ---------------------------------------------------------------- what the checks look at

class Context:
    """The folder, read once for every check: its files, its Xcode projects, its package files."""

    def __init__(self, folder, facts: dict):
        self.folder = folder
        self.root: Path = folder.root
        self.files: list[str] = folder.files
        self.lower = {f.lower(): f for f in self.files}
        self.facts = facts
        self._xcode: list[Xcode] | None = None
        self._code: list[tuple[str, str]] | None = None
        self._remote: dict | None = None

    def remote(self) -> dict:
        """Where the project is pushed to, and how many commits aren't there yet."""
        if self._remote is None:
            from pulse_base import git
            remotes = (git(self.root, "remote") or "").split()
            upstream = (git(self.root, "rev-parse", "--abbrev-ref", "@{upstream}") or "").strip()
            ahead = (git(self.root, "rev-list", "--count", "@{upstream}..HEAD") or "").strip() if upstream else ""
            self._remote = {"remotes": remotes, "upstream": upstream, "ahead": int(ahead) if ahead.isdigit() else 0}
        return self._remote

    # files ---------------------------------------------------------------
    def find(self, *patterns: str, top: bool = False) -> list[str]:
        """Files matching any pattern (case-insensitive, on the name or the whole path)."""
        found = []
        for rel in self.files:
            if top and "/" in rel:
                continue
            name = rel.rsplit("/", 1)[-1].lower()
            low = rel.lower()
            if any(fnmatch.fnmatch(name, p.lower()) or fnmatch.fnmatch(low, p.lower()) for p in patterns):
                found.append(rel)
        return found

    def text(self, rel: str) -> str:
        return self.folder.text(rel) or ""

    def json(self, rel: str) -> dict:
        try:
            value = json.loads(self.text(rel))
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def plist(self, rel: str) -> dict:
        try:
            with (self.root / rel).open("rb") as handle:
                value = plistlib.load(handle)
        except Exception:  # a broken plist is just "not there"
            return {}
        return value if isinstance(value, dict) else {}

    # Xcode ---------------------------------------------------------------
    @property
    def xcode(self) -> list[Xcode]:
        if self._xcode is None:
            self._xcode = []
            for rel in self.find("*.xcodeproj/project.pbxproj"):
                if "/checkouts/" in rel or "/SourcePackages/" in rel:
                    continue
                try:
                    project = Xcode(rel, self.text(rel))
                except Exception:  # an odd project file never stops the checklist
                    continue
                if project.apps:
                    self._xcode.append(project)
        return self._xcode

    def apps(self, platform: str) -> list[tuple[Xcode, dict]]:
        return [(x, app) for x in self.xcode for app in x.apps if platform in x.platforms(app)]

    def info(self, x: Xcode, app: dict, key: str) -> str | None:
        """An Info.plist key of the app's Release build: a build setting (INFOPLIST_KEY_…) or the Info.plist file."""
        settings = x.release(app)
        if f"INFOPLIST_KEY_{key}" in settings:
            return settings[f"INFOPLIST_KEY_{key}"]
        plist_path = settings.get("INFOPLIST_FILE")
        if plist_path:
            rel = self.resolve(x, plist_path)
            value = self.plist(rel).get(key) if rel else None
            if value is not None:
                return str(value)
        return None

    def entitlements(self, x: Xcode, app: dict, config: str = "Release") -> tuple[str | None, dict]:
        settings = app["configs"].get(config) or x.release(app)
        path = settings.get("CODE_SIGN_ENTITLEMENTS")
        rel = self.resolve(x, path) if path else None
        return rel, (self.plist(rel) if rel else {})

    def resolve(self, x: Xcode, path: str) -> str | None:
        path = path.replace("$(SRCROOT)/", "").replace("$(PROJECT_DIR)/", "").strip('"')
        rel = f"{x.folder}/{path}" if x.folder else path
        return self.lower.get(rel.lower()) or self.lower.get(path.lower())

    # code ------------------------------------------------------------------
    def code(self) -> list[tuple[str, str]]:
        """The app's own source files (not tests, examples or other people's code), read once."""
        if self._code is None:
            from pulse_any import in_fixtures, in_tests_or_examples
            self._code = []
            for rel in self.files:
                if rel.endswith(APP_CODE_EXT) and not in_tests_or_examples(rel) and not in_fixtures(rel) \
                        and "Tests/" not in rel and "/checkouts/" not in rel and len(self._code) < 4000:
                    self._code.append((rel, release_code(self.text(rel))))
        return self._code

    def uses(self, pattern: str) -> tuple[str, int] | None:
        """The first place the app's code matches, as (file, line)."""
        compiled = re.compile(pattern)
        for rel, text in self.code():
            match = compiled.search(text)
            if match:
                return rel, text.count("\n", 0, match.start()) + 1
        return None


# ---------------------------------------------------------------- the checks

def ok(evidence: str = "", path: str | None = None) -> dict:
    return {"state": PASS, "evidence": evidence, "path": path}


def bad(evidence: str = "", path: str | None = None) -> dict:
    return {"state": FAIL, "evidence": evidence, "path": path}


def warn(evidence: str = "", path: str | None = None) -> dict:
    return {"state": WARN, "evidence": evidence, "path": path}


def one_of(ctx: Context, patterns: tuple[str, ...], missing: str, top: bool = False) -> dict:
    found = ctx.find(*patterns, top=top)
    return ok(found[0], found[0]) if found else bad(missing)


def each_app(ctx: Context, platform: str, test) -> dict | None:
    """Runs a check on every app target for the platform; the first that fails decides."""
    apps = ctx.apps(platform)
    if not apps:
        return None
    results = [test(ctx, x, app) for x, app in apps]
    results = [r for r in results if r is not None]
    if not results:
        return None
    return next((r for r in results if r["state"] == FAIL), None) or next(
        (r for r in results if r["state"] == WARN), None) or results[0]


def setting_check(key: str, good, missing: str, shown: str | None = None):
    def test(ctx: Context, x: Xcode, app: dict) -> dict:
        value = x.release(app).get(key)
        if value is not None and good(value):
            return ok(f"{shown or key} = {value} ({app['name']}, Release)", x.rel)
        return bad(missing + (f" (it's {value})" if value else ""), x.rel)
    return test


def info_check(key: str, missing: str, good=lambda v: bool(v.strip())):
    def test(ctx: Context, x: Xcode, app: dict) -> dict:
        value = ctx.info(x, app, key)
        return ok(f"{key}: {value[:60]}", x.rel) if value is not None and good(value) else bad(missing, x.rel)
    return test


def sandbox(ctx: Context, x: Xcode, app: dict) -> dict:
    if x.release(app).get("ENABLE_APP_SANDBOX") == "YES":
        return ok(f"ENABLE_APP_SANDBOX = YES ({app['name']}, Release)", x.rel)
    rel, ents = ctx.entitlements(x, app)
    if ents.get("com.apple.security.app-sandbox") is True:
        return ok(f"{rel}: com.apple.security.app-sandbox", rel)
    return bad("The Release build doesn't turn on the App Sandbox", x.rel)


DEBUG_ONLY = ("com.apple.security.get-task-allow", "com.apple.security.cs.disable-library-validation",
              "com.apple.security.temporary-exception")


def debug_only_entitlements(ctx: Context, x: Xcode, app: dict) -> dict | None:
    """Debug settings that loosen the sandbox must not be in the Release entitlements."""
    rel, ents = ctx.entitlements(x, app)
    if not rel:
        return None
    loose = [k for k in ents if k.startswith(DEBUG_ONLY)]
    return bad(f"{rel} has {', '.join(loose)}", rel) if loose else ok(f"{rel} has none", rel)


def app_icon(ctx: Context) -> dict:
    sets = [f for f in ctx.find("*.appiconset/contents.json") if "/checkouts/" not in f]
    if not sets:
        return bad("No app icon set (AppIcon.appiconset) in the asset catalog")
    for rel in sets:
        images = ctx.json(rel).get("images") or []
        filled = [i for i in images if isinstance(i, dict) and i.get("filename")]
        if images and len(filled) == len(images):
            return ok(f"{rel.rsplit('/', 2)[-2]}: all {len(images)} pictures", rel)
        if filled and any(i.get("size") == "1024x1024" for i in filled):
            return ok(f"{rel.rsplit('/', 2)[-2]}: one 1024×1024 picture", rel)
    first = sets[0]
    images = ctx.json(first).get("images") or []
    filled = [i for i in images if isinstance(i, dict) and i.get("filename")]
    return bad(f"The app icon has {len(filled)} of its {len(images)} pictures", first)


# What code uses → the Info.plist sentence Apple needs before it's allowed (the app crashes or is rejected without).
USAGE = [
    (r"\bimport Photos\b|PHPhotoLibrary", "NSPhotoLibraryUsageDescription", "the photo library"),
    (r"AVCaptureDevice|\bimport AVKit\b.*camera|UIImagePickerController.*camera", "NSCameraUsageDescription",
     "the camera"),
    (r"AVAudioRecorder|AVAudioSession.*record|requestRecordPermission", "NSMicrophoneUsageDescription",
     "the microphone"),
    (r"CLLocationManager", "NSLocationWhenInUseUsageDescription", "the location"),
    (r"CNContactStore", "NSContactsUsageDescription", "contacts"),
    (r"EKEventStore", "NSCalendarsUsageDescription", "calendars"),
    (r"CBCentralManager|CBPeripheralManager", "NSBluetoothAlwaysUsageDescription", "Bluetooth"),
    (r"SFSpeechRecognizer", "NSSpeechRecognitionUsageDescription", "speech recognition"),
    (r"NSAppleScript|NSUserAppleScriptTask", "NSAppleEventsUsageDescription", "controlling other apps"),
    (r"HKHealthStore", "NSHealthShareUsageDescription", "Health data"),
    (r"MPMediaLibrary", "NSAppleMusicUsageDescription", "the music library"),
]


def usage_texts(ctx: Context, platform: str) -> dict | None:
    needed = []
    for pattern, key, what in USAGE:
        where = ctx.uses(pattern)
        if where:
            needed.append((key, what, where))
    if not needed:
        return None

    def test(ctx: Context, x: Xcode, app: dict) -> dict:
        missing = [(k, w, where) for k, w, where in needed if not (ctx.info(x, app, k) or "").strip()]
        if missing:
            key, what, where = missing[0]
            more = f" (and {len(missing) - 1} more)" if len(missing) > 1 else ""
            return bad(f"The code uses {what} ({where[0]}:{where[1]}) but there's no {key}{more}", x.rel)
        return ok(", ".join(k for k, _, _ in needed), x.rel)
    return each_app(ctx, platform, test)


# Apple's "required reason" APIs: using one without saying why in PrivacyInfo.xcprivacy gets an upload warning
# (ITMS-91053) and, since May 2024, a rejection.
REQUIRED_REASON = [
    (r"UserDefaults|@AppStorage|NSUserDefaults", "NSPrivacyAccessedAPICategoryUserDefaults", "UserDefaults"),
    (r"creationDate|modificationDate|contentModificationDate|attributesOfItem|\bstat\(|fileModificationDate",
     "NSPrivacyAccessedAPICategoryFileTimestamp", "file dates"),
    (r"volumeAvailableCapacity|systemFreeSize|statfs|volumeTotalCapacity", "NSPrivacyAccessedAPICategoryDiskSpace",
     "free disk space"),
    (r"systemUptime|mach_absolute_time", "NSPrivacyAccessedAPICategorySystemBootTime", "time since start-up"),
    (r"activeInputModes", "NSPrivacyAccessedAPICategoryActiveKeyboards", "active keyboards"),
]


def privacy_manifest(ctx: Context) -> dict:
    manifests = [f for f in ctx.find("PrivacyInfo.xcprivacy") if "/checkouts/" not in f]
    if not manifests:
        used = [what for pattern, _, what in REQUIRED_REASON if ctx.uses(pattern)]
        return bad("No PrivacyInfo.xcprivacy" + (f", and the code uses {', '.join(used)}" if used else ""))
    declared = set()
    for rel in manifests:
        for entry in ctx.plist(rel).get("NSPrivacyAccessedAPITypes") or []:
            if isinstance(entry, dict):
                declared.add(entry.get("NSPrivacyAccessedAPIType"))
    for pattern, category, what in REQUIRED_REASON:
        where = ctx.uses(pattern)
        if where and category not in declared:
            return bad(f"The code uses {what} ({where[0]}:{where[1]}) but the privacy manifest doesn't say why",
                       manifests[0])
    return ok(f"{manifests[0]} ({len(declared)} reason{'s' if len(declared) != 1 else ''} given)", manifests[0])


def no_process(ctx: Context) -> dict:
    where = ctx.uses(r"\bProcess\(\)|\bNSTask\b|\bposix_spawn\(|\bdlopen\(")
    if where:
        return warn(f"{where[0]}:{where[1]} starts another program or loads code; the App Sandbox blocks most of it",
                    str(ctx.root / where[0]))
    return ok("None found in the app's code")


NETWORK = r"URLSession|NWConnection|NWPathMonitor|WKWebView|URLRequest\("


def network_entitlement(ctx: Context, x: Xcode, app: dict) -> dict | None:
    where = ctx.uses(NETWORK)
    if not where:
        return None
    rel, ents = ctx.entitlements(x, app)
    if ents.get("com.apple.security.network.client") is True or x.release(app).get(
            "ENABLE_OUTGOING_NETWORK_CONNECTIONS") == "YES":
        return ok("Outgoing connections are allowed", rel or x.rel)
    return bad(f"The code goes online ({where[0]}:{where[1]}) but the sandbox doesn't allow outgoing connections",
               rel or x.rel)


def licences(ctx: Context) -> dict | None:
    resolved = ctx.find("Package.resolved", "Podfile.lock", "Cartfile.resolved")
    if not resolved:
        return None
    notice = ctx.find("*acknowledg*", "*third*party*", "NOTICE*", "*licenses*", "*credits*")
    notice = [f for f in notice if "/checkouts/" not in f and not f.endswith((".swift", ".py"))]
    if notice:
        return ok(notice[0], notice[0])
    return bad(f"It uses other people's code ({resolved[0].rsplit('/', 1)[-1]}) but no acknowledgements file was found")


def git_check(ctx: Context, what: str) -> dict:
    if not ctx.folder.git.get("ok"):
        return bad("Not in git yet")
    remote = ctx.remote()
    if what == "remote":
        return ok(", ".join(remote["remotes"])) if remote["remotes"] else bad("No copy on GitHub or another "
                                                                               "server yet")
    if not remote["remotes"]:
        return bad("Nowhere to push to yet")
    if not remote["upstream"]:
        return bad(f"The branch “{ctx.folder.git.get('branch')}” was never pushed")
    ahead = remote["ahead"]
    return ok(f"Everything is on {remote['upstream']}") if not ahead else bad(
        f"{ahead} commit{'s' if ahead != 1 else ''} not pushed yet")


def fact_check(ctx: Context, key: str, good_text: str, bad_text) -> dict | None:
    value = ctx.facts.get(key)
    if value is None:
        return None
    if value:
        return bad(bad_text(value) if callable(bad_text) else bad_text)
    return ok(good_text)


def tests_passing(ctx: Context) -> dict | None:
    run = ctx.facts.get("lastTestRun")
    if not run:
        return None
    when = run.get("time", "")[:16].replace("T", " ")
    if run.get("outcome") == "fail":
        return bad(f"The last test run failed ({run.get('command', '')}, {when})")
    if run.get("outcome") == "pass":
        return ok(f"The last test run passed ({run.get('command', '')}, {when})")
    return None


def claude_md_size(ctx: Context) -> dict | None:
    files = ctx.find("CLAUDE.md", top=True)
    if not files:
        return None
    size = len(ctx.text(files[0]))
    if size > CLAUDE_MD_WARN_CHARS:
        return warn(f"{files[0]} is {size:,} characters; Claude Code warns past {CLAUDE_MD_WARN_CHARS:,}", files[0])
    return ok(f"{files[0]}: {size:,} characters", files[0])


def pkg(ctx: Context) -> dict:
    return ctx.json("package.json") if "package.json" in ctx.files else {}


def pkg_field(field: str, missing: str):
    def check(ctx: Context) -> dict:
        value = pkg(ctx)
        for part in field.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return ok(f"package.json: {field}") if value else bad(missing, "package.json")
    return check


def pyproject_field(field: str, missing: str):
    def check(ctx: Context) -> dict:
        text = ctx.text("pyproject.toml")
        if re.search(rf"^\s*{re.escape(field)}\s*=", text, re.M):
            return ok(f"pyproject.toml: {field}", "pyproject.toml")
        if field in ("version",) and re.search(r"dynamic\s*=\s*\[[^\]]*\"version\"", text):
            return ok("pyproject.toml: version comes from the code", "pyproject.toml")
        return bad(missing, "pyproject.toml")
    return check


def manifest(ctx: Context) -> dict:
    for rel in ctx.find("manifest.json"):
        data = ctx.json(rel)
        if data.get("manifest_version"):
            return data
    return {}


def ext_icons(ctx: Context) -> dict:
    icons = manifest(ctx).get("icons") or {}
    if not icons:
        return bad("manifest.json names no icons")
    missing = [size for size, path in icons.items() if not ctx.lower.get(str(path).lower().lstrip("./"))
               and not any(f.lower().endswith(str(path).lower().lstrip("./")) for f in ctx.files)]
    return bad(f"Icon file missing for size {', '.join(missing)}") if missing else ok(f"{len(icons)} icons")


def ext_permissions(ctx: Context) -> dict:
    data = manifest(ctx)
    wide = [p for p in (data.get("host_permissions") or []) + (data.get("permissions") or [])
            if isinstance(p, str) and (p in ("<all_urls>", "*://*/*", "http://*/*", "https://*/*"))]
    return warn(f"Asks for every website ({wide[0]}): the store reviews this closely") if wide \
        else ok("Asks only for what it names")


def gradle_text(ctx: Context) -> str:
    return "\n".join(ctx.text(f) for f in ctx.find("build.gradle", "build.gradle.kts") if f.count("/") <= 1)


def gradle_has(pattern: str, good: str, missing: str):
    def check(ctx: Context) -> dict:
        return ok(good) if re.search(pattern, gradle_text(ctx)) else bad(missing)
    return check


# ---------------------------------------------------------------- the lists

def item(id_: str, text: str, why: str, check=None) -> dict:
    return {"id": id_, "text": text, "why": why, "check": check}


BASICS = [
    item("readme", "A README says what it is and how to start it",
         "It's the first thing anyone (and any AI) reads, including you in six months.",
         lambda c: one_of(c, ("README*",), "No README yet", top=True)),
    item("git", "The project is in git", "Every change can be seen and undone.",
         lambda c: ok("Yes") if c.folder.git.get("ok") else bad("Not in git yet")),
    item("gitignore", "A .gitignore keeps build files and secrets out of git",
         "Without one, keys and gigabytes of build output end up in the history.",
         lambda c: one_of(c, (".gitignore",), "No .gitignore", top=True) if c.folder.git.get("ok") else None),
    item("remote", "A copy lives on GitHub (or another server)", "A disk that dies takes an unpushed project with it.",
         lambda c: git_check(c, "remote")),
    item("pushed", "Everything is pushed", "Work that's only on this Mac isn't backed up.",
         lambda c: git_check(c, "pushed")),
    item("nokeys", "No keys or passwords written into the files",
         "A key in a file ends up in git, on GitHub and in every copy.",
         lambda c: fact_check(c, "secrets", "None found", lambda n: f"{n} found: see Could be problems")),
    item("nocopies", "No stray copies like “app (1).py” or “main_final2.py”",
         "Copies make it unclear which file is the real one, for you and for Claude.",
         lambda c: fact_check(c, "copies", "None found", lambda n: f"{n} found: see Could be problems")),
    item("tests", "It has tests", "Tests let Claude check its own work before you do.",
         lambda c: ok(f"{c.facts['testFiles']} test files") if c.facts.get("testFiles") else bad("No tests found")),
    item("testsPass", "The last test run passed", "A failing test is a bug somebody already found.", tests_passing),
    item("aiGuide", "A CLAUDE.md (or AGENTS.md) tells AI assistants the rules",
         "Claude reads it at the start of every session; without it every session starts from zero.",
         lambda c: one_of(c, ("CLAUDE.md", "AGENTS.md", ".cursorrules", "GEMINI.md"), "No AI guide file yet",
                          top=True)),
    item("aiGuideSize", "The CLAUDE.md is a sensible size", "Past about 40,000 characters it costs every session.",
         claude_md_size),
    item("plan", "A plan says what's next (a step list, a roadmap or a TODO list)",
         "Pulse builds the roadmap from it; without one there's no “next step”.",
         lambda c: ok("Found") if c.facts.get("plan") else bad("No plan found")),
    item("issues", "Known problems are written down in one place", "Nobody fixes a bug that only lives in a chat.",
         lambda c: ok("Found") if c.facts.get("knownIssues") else bad("No known-issues list found")),
    item("licence", "A LICENSE says what others may do with it (if it's shared)",
         "Without one, nobody may legally use code you publish.",
         lambda c: one_of(c, ("LICENSE*", "LICENCE*", "COPYING*"), "No licence file", top=True)),
]

MAC_APP_STORE = [
    item("devProgram", "You're in the Apple Developer Program",
         "Needed to sign and upload anything to the App Store ($99 a year)."),
    item("sandbox", "The App Sandbox is on in the Release build", "The Mac App Store rejects an app without it.",
         lambda c: each_app(c, "mac", sandbox)),
    item("debugEnts", "No debug-only permissions in the Release build",
         "get-task-allow or turned-off library validation get an upload rejected.",
         lambda c: each_app(c, "mac", debug_only_entitlements)),
    item("bundleId", "It has its own bundle ID", "The App Store knows the app by it; it can't change after release.",
         lambda c: each_app(c, "mac", setting_check("PRODUCT_BUNDLE_IDENTIFIER",
                                                     lambda v: "example" not in v.lower() and "$(" not in v[:2],
                                                     "No bundle ID set"))),
    item("team", "A signing team is set", "Xcode can't sign an upload without it.",
         lambda c: each_app(c, "mac", setting_check("DEVELOPMENT_TEAM", bool, "No signing team set yet"))),
    item("version", "It has a version and a build number", "Every upload needs a higher build number.",
         lambda c: each_app(c, "mac", lambda _, x, a: ok(
             f"{x.release(a).get('MARKETING_VERSION')} ({x.release(a).get('CURRENT_PROJECT_VERSION')})", x.rel)
             if x.release(a).get("MARKETING_VERSION") and x.release(a).get("CURRENT_PROJECT_VERSION")
             else bad("MARKETING_VERSION or CURRENT_PROJECT_VERSION is missing", x.rel))),
    item("category", "An App Store category is chosen", "Uploads without LSApplicationCategoryType are refused.",
         lambda c: each_app(c, "mac", info_check("LSApplicationCategoryType", "No category (LSApplicationCategoryType)"))),
    item("icon", "The app icon has all its pictures", "An upload without a full icon is refused.", app_icon),
    item("usage", "Every permission it asks for says why", "Apple needs a sentence for each (photos, camera…).",
         lambda c: usage_texts(c, "mac")),
    item("privacy", "A privacy manifest gives the reasons for the APIs it uses",
         "Apple rejects uploads that use file dates, UserDefaults or disk space without saying why.",
         privacy_manifest),
    item("network", "The sandbox allows the connections the app makes", "Without it, going online quietly fails.",
         lambda c: each_app(c, "mac", network_entitlement)),
    item("noProcess", "It doesn't start other programs", "The App Sandbox blocks most of them; reviewers look for it.",
         no_process),
    item("encryption", "The export-compliance answer is in the app",
         "Setting ITSAppUsesNonExemptEncryption saves answering the question on every upload.",
         lambda c: each_app(c, "mac", info_check("ITSAppUsesNonExemptEncryption", "Not set: you'll be asked at every "
                                                                                  "upload", good=lambda v: True))),
    item("hardened", "The hardened runtime is on for Release", "Recommended; required for anything shared outside "
                                                               "the store.",
         lambda c: each_app(c, "mac", setting_check("ENABLE_HARDENED_RUNTIME", lambda v: v == "YES",
                                                     "Not turned on yet"))),
    item("licences", "Other people's code is acknowledged", "Most open-source licences require it.", licences),
    item("copyright", "A copyright line is set", "Shown in the About window and in the store.",
         lambda c: each_app(c, "mac", info_check("NSHumanReadableCopyright", "No copyright line"))),
    item("record", "The app has a record in App Store Connect (name reserved)",
         "The name is first come, first served."),
    item("privacyPolicy", "A privacy policy page is online", "Every app needs its web address in App Store Connect."),
    item("privacyLabel", "The App Privacy questions are answered", "The “nutrition label” on the store page."),
    item("screenshots", "Screenshots are made (at least one, 1280×800 or larger)", "The store page needs them."),
    item("listing", "Description, keywords, support page and age rating are filled in",
         "App Store Connect won't submit without them."),
    item("testflight", "A build was tested through TestFlight", "The first real test of the signed, sandboxed app."),
    item("reviewNotes", "Review notes explain anything a reviewer can't find alone",
         "Saves a rejection round when setup is needed."),
]

IOS_APP_STORE = [
    item("devProgram", "You're in the Apple Developer Program", "Needed to sign and upload ($99 a year)."),
    item("bundleId", "It has its own bundle ID", "It can't change after release.",
         lambda c: each_app(c, "ios", setting_check("PRODUCT_BUNDLE_IDENTIFIER",
                                                     lambda v: "example" not in v.lower(), "No bundle ID set"))),
    item("team", "A signing team is set", "Xcode can't sign an upload without it.",
         lambda c: each_app(c, "ios", setting_check("DEVELOPMENT_TEAM", bool, "No signing team set yet"))),
    item("version", "It has a version and a build number", "Every upload needs a higher build number.",
         lambda c: each_app(c, "ios", lambda _, x, a: ok(f"{x.release(a).get('MARKETING_VERSION')}", x.rel)
                            if x.release(a).get("MARKETING_VERSION") and x.release(a).get("CURRENT_PROJECT_VERSION")
                            else bad("MARKETING_VERSION or CURRENT_PROJECT_VERSION is missing", x.rel))),
    item("icon", "The app icon has its 1024×1024 picture", "An upload without it is refused.", app_icon),
    item("launch", "It has a launch screen", "Required for every iPhone app.",
         lambda c: each_app(c, "ios", lambda _, x, a: ok("Set", x.rel) if (
             x.release(a).get("INFOPLIST_KEY_UILaunchScreen_Generation") == "YES"
             or x.release(a).get("INFOPLIST_KEY_UILaunchStoryboardName")
             or c.find("LaunchScreen.storyboard") or c.info(x, a, "UILaunchScreen"))
             else bad("No launch screen", x.rel))),
    item("usage", "Every permission it asks for says why", "The app crashes when it asks without one.",
         lambda c: usage_texts(c, "ios")),
    item("privacy", "A privacy manifest gives the reasons for the APIs it uses", "Apple rejects uploads without it.",
         privacy_manifest),
    item("encryption", "The export-compliance answer is in the app", "Saves answering at every upload.",
         lambda c: each_app(c, "ios", info_check("ITSAppUsesNonExemptEncryption", "Not set: you'll be asked at every "
                                                                                  "upload", good=lambda v: True))),
    item("licences", "Other people's code is acknowledged", "Most open-source licences require it.", licences),
    item("record", "The app has a record in App Store Connect", "The name is first come, first served."),
    item("privacyPolicy", "A privacy policy page is online", "Required for every app."),
    item("privacyLabel", "The App Privacy questions are answered", "The store page's privacy label."),
    item("screenshots", "iPhone (and iPad) screenshots are made", "6.9″ iPhone screenshots are required."),
    item("listing", "Description, keywords, support page and age rating are filled in", "Needed to submit."),
    item("testflight", "A build was tested through TestFlight on a real iPhone", "Simulators hide real problems."),
]

MAC_DIRECT = [
    item("devId", "You have a Developer ID certificate", "Without it macOS warns people your app can't be checked."),
    item("hardened", "The hardened runtime is on for Release", "Notarization refuses an app without it.",
         lambda c: each_app(c, "mac", setting_check("ENABLE_HARDENED_RUNTIME", lambda v: v == "YES",
                                                     "Not turned on yet"))
         if c.xcode else None),
    item("bundleId", "It has its own bundle ID", "macOS keeps its settings and permissions under it.",
         lambda c: each_app(c, "mac", setting_check("PRODUCT_BUNDLE_IDENTIFIER",
                                                     lambda v: "example" not in v.lower(), "No bundle ID set"))
         if c.xcode else None),
    item("version", "It has a version number", "People (and updaters) need to know which one they have.",
         lambda c: each_app(c, "mac", setting_check("MARKETING_VERSION", bool, "No version set"))
         if c.xcode else None),
    item("icon", "The app icon has all its pictures", "Without one it shows a blank icon.",
         lambda c: app_icon(c) if c.xcode else None),
    item("notarize", "Builds are notarized and stapled",
         "Gatekeeper blocks un-notarized downloads on other people's Macs.",
         lambda c: ok(f"{hits[0]} mentions notarytool", hits[0]) if (hits := [
             f for f in c.find("*.sh", "Makefile", "*.yml", "*.yaml") if "notarytool" in c.text(f)]) else None),
    item("package", "A .dmg or .zip is made the same way every time", "A script avoids a broken download.",
         lambda c: ok(hits[0], hits[0]) if (hits := [
             f for f in c.find("*.sh", "Makefile") if re.search(r"hdiutil|create-dmg|ditto -c", c.text(f))]) else None),
    item("updates", "It can update itself (Sparkle) or says where updates are",
         "People keep old versions forever otherwise.",
         lambda c: ok("Sparkle") if any("sparkle" in c.text(f).lower() for f in c.find("Package.resolved"))
         else None),
    item("licences", "Other people's code is acknowledged", "Most open-source licences require it.", licences),
    item("page", "A download page says what it does and what Mac it needs", "Where people find it."),
]

WEB = [
    item("run", "The README says how to run it on your own computer", "You'll forget; so will Claude.",
         lambda c: ok("README mentions npm/yarn/pnpm") if re.search(r"\b(npm|yarn|pnpm|bun) (run|install|dev|start)\b",
                                                                   " ".join(c.text(f) for f in c.find("README*",
                                                                                                       top=True)))
         else bad("The README doesn't say how to start it")),
    item("lockfile", "A lockfile is committed", "Without it, the site builds differently next month.",
         lambda c: one_of(c, ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock"),
                          "No lockfile", top=True) if "package.json" in c.files else None),
    item("envIgnored", "Secrets live in .env, and .env is ignored by git", "A committed .env publishes your keys.",
         lambda c: bad(".env is in git", ".env") if ".env" in c.files and c.folder.git.get("ok") and
         c.facts.get("envInGit") else ok("OK")),
    item("envExample", "A .env.example lists the settings it needs (without values)",
         "The next person (or deploy) knows what to fill in.",
         lambda c: one_of(c, (".env.example", ".env.sample", ".env.template"), "No .env.example", top=True)
         if c.find(".env*", top=True) else None),
    item("build", "It has a build script", "Hosting services run it.",
         lambda c: ok("package.json: scripts.build") if (pkg(c).get("scripts") or {}).get("build")
         else (bad("No build script in package.json") if "package.json" in c.files else None)),
    item("deploy", "Deploying is written down or automated", "So it isn't a ritual only one person remembers.",
         lambda c: one_of(c, ("vercel.json", "netlify.toml", "fly.toml", "render.yaml", "Dockerfile",
                              "wrangler.toml", "app.yaml", "Procfile", "firebase.json", ".github/workflows/*deploy*"),
                          "No deploy config found")),
    item("favicon", "It has a favicon and a page title", "The tab shows a blank page without them.",
         lambda c: one_of(c, ("favicon.*", "icon.png", "icon.svg", "apple-touch-icon*"), "No favicon")),
    item("meta", "Pages have a description for search and link previews", "What Google and chat apps show.",
         lambda c: ok("Found") if any(re.search(r"name=[\"']description[\"']|og:description|description:",
                                                c.text(f)) for f in c.find("*.html", "layout.*", "_document.*",
                                                                           "_app.*", "head.*", "+layout.svelte",
                                                                           "nuxt.config.*", "app.vue"))
         else bad("No description found")),
    item("404", "A friendly “not found” page", "Broken links happen.",
         lambda c: one_of(c, ("404.*", "not-found.*", "*/404/*", "+error.svelte", "error.vue"), "No 404 page")),
    item("https", "It's served over HTTPS", "Browsers mark plain HTTP as not secure."),
    item("privacyPolicy", "A privacy policy, if it collects anything about visitors",
         "Required by law in many places (and by analytics tools)."),
    item("backups", "The database (if any) is backed up", "Hosting companies lose data too."),
    item("errors", "Errors in production reach you (logs or an error tracker)", "Otherwise users find them first."),
]

PYTHON_PACKAGE = [
    item("name", "pyproject.toml names the package", "pip installs it by this name.",
         pyproject_field("name", "No name in pyproject.toml")),
    item("version", "It has a version", "Every upload to PyPI needs a new one.",
         pyproject_field("version", "No version in pyproject.toml")),
    item("description", "It has a one-line description", "Shown on PyPI and in search.",
         pyproject_field("description", "No description")),
    item("readme", "The PyPI page shows the README", "Otherwise the page is empty.",
         pyproject_field("readme", "pyproject.toml doesn't point at the README")),
    item("license", "The licence is declared", "People (and companies) check before using it.",
         lambda c: pyproject_field("license", "No licence in pyproject.toml")(c)),
    item("python", "It says which Python versions it needs", "pip then refuses versions that would break.",
         pyproject_field("requires-python", "No requires-python")),
    item("tests", "It has tests", "A package others depend on needs them.",
         lambda c: ok(f"{c.facts['testFiles']} test files") if c.facts.get("testFiles") else bad("No tests found")),
    item("changelog", "A CHANGELOG says what changed in each version", "Users decide whether to upgrade from it.",
         lambda c: one_of(c, ("CHANGELOG*", "CHANGES*", "HISTORY*", "NEWS*"), "No changelog", top=True)),
    item("testpypi", "It was uploaded to TestPyPI and installed from there once", "Catches packaging mistakes safely."),
    item("ci", "Tests run by themselves on every push", "Catches the Python version you don't have.",
         lambda c: one_of(c, (".github/workflows/*",), "No CI workflow")),
]

NPM_PACKAGE = [
    item("name", "package.json has a name and a version", "npm publishes by them.",
         lambda c: ok(f"{pkg(c).get('name')}@{pkg(c).get('version')}") if pkg(c).get("name") and pkg(c).get("version")
         else bad("Name or version missing", "package.json")),
    item("description", "It has a description", "Shown in npm search.", pkg_field("description", "No description")),
    item("license", "The licence is declared", "People check before using it.", pkg_field("license", "No licence")),
    item("repository", "It links to its repository", "People report bugs there.",
         pkg_field("repository", "No repository link")),
    item("entry", "It says what to import (main / exports / bin)", "Otherwise importing it fails.",
         lambda c: ok("Set") if any(pkg(c).get(k) for k in ("main", "exports", "bin", "module")) else bad(
             "No main, exports or bin", "package.json")),
    item("files", "Only the right files are published (files list or .npmignore)",
         "Otherwise tests, notes and maybe secrets get published.",
         lambda c: ok("Set") if pkg(c).get("files") or ".npmignore" in c.files else bad("Everything would be "
                                                                                        "published")),
    item("types", "It ships TypeScript types", "Editors then show how to use it.",
         lambda c: (ok("Set") if pkg(c).get("types") or pkg(c).get("typings") else bad("No types entry"))
         if "tsconfig.json" in c.files else None),
    item("tests", "It has tests", "A package others depend on needs them.",
         lambda c: ok("Set") if (pkg(c).get("scripts") or {}).get("test") else bad("No test script")),
    item("dryrun", "“npm publish --dry-run” lists only what you expect", "The last look before it's public."),
]

BROWSER_EXTENSION = [
    item("mv3", "It uses Manifest V3", "Chrome no longer accepts Manifest V2.",
         lambda c: ok("manifest_version 3") if manifest(c).get("manifest_version") == 3
         else bad(f"manifest_version {manifest(c).get('manifest_version')}")),
    item("basics", "manifest.json has a name, version and description", "The store shows them.",
         lambda c: ok("Set") if all(manifest(c).get(k) for k in ("name", "version", "description"))
         else bad("Name, version or description missing")),
    item("icons", "Its icons are there (16, 48 and 128 px)", "The store and toolbar need them.", ext_icons),
    item("permissions", "It asks only for the permissions it needs", "Wide permissions slow review and scare users.",
         ext_permissions),
    item("remoteCode", "No code is loaded from the internet", "Manifest V3 forbids it.",
         lambda c: bad(f"{hits[0]} loads a script from the web", hits[0]) if (hits := [
             f for f in c.find("*.html") if re.search(r"<script[^>]+src=[\"']https?://", c.text(f))]) else ok("None")),
    item("privacyPolicy", "A privacy policy, if it handles any user data", "Required by the Chrome Web Store."),
    item("listing", "Store listing: screenshots (1280×800), description, category", "Needed to submit."),
    item("zip", "The upload .zip is made by a script", "So it never includes junk or secrets."),
]

ANDROID = [
    item("appId", "It has its own application ID", "Google Play knows the app by it forever.",
         gradle_has(r"applicationId\s*[= ]", "applicationId set", "No applicationId")),
    item("version", "It has a versionCode and versionName", "Every upload needs a higher versionCode.",
         gradle_has(r"versionCode\s*[= ]\s*\d", "versionCode set", "No versionCode")),
    item("targetSdk", "It targets a recent Android version", "Google Play requires a recent targetSdk.",
         lambda c: (ok(f"targetSdk {m.group(1)}") if int(m.group(1)) >= 34 else bad(f"targetSdk {m.group(1)} is too "
                                                                                   "old for new uploads"))
         if (m := re.search(r"targetSdk(?:Version)?\s*[= ]\s*(\d+)", gradle_text(c))) else None),
    item("keystore", "The upload key is kept out of git", "Anyone with it can publish as you.",
         lambda c: bad(f"{hits[0]} is in the project", hits[0]) if (hits := c.find("*.jks", "*.keystore"))
         else ok("No key files in the project")),
    item("icon", "It has an app icon", "The store and home screen need it.",
         lambda c: one_of(c, ("*/mipmap-*/ic_launcher*",), "No launcher icon")),
    item("privacyPolicy", "A privacy policy page is online", "Required by Google Play."),
    item("dataSafety", "The Data safety form is filled in", "Google Play won't publish without it."),
    item("testing", "It went through a closed test first", "New personal accounts must test with 12 people for "
                                                         "14 days."),
    item("listing", "Store listing: screenshots, description, feature graphic", "Needed to submit."),
]

CATALOG = {
    "basics": ("Project basics", BASICS),
    "mac-app-store": ("Mac App Store", MAC_APP_STORE),
    "ios-app-store": ("iPhone & iPad App Store", IOS_APP_STORE),
    "mac-direct": ("Mac app outside the store", MAC_DIRECT),
    "web": ("Website or web app", WEB),
    "python-package": ("Python package (PyPI)", PYTHON_PACKAGE),
    "npm-package": ("npm package", NPM_PACKAGE),
    "browser-extension": ("Browser extension", BROWSER_EXTENSION),
    "android": ("Android app (Google Play)", ANDROID),
}


# ---------------------------------------------------------------- which lists a folder gets

def detect(ctx: Context) -> list[tuple[str, str]]:
    """The release checklists that fit the folder, each with the reason."""
    found: list[tuple[str, str]] = []
    mac, ios = ctx.apps("mac"), ctx.apps("ios")
    docs = " ".join(ctx.text(f)[:200_000] for f in ctx.find("README*", "CLAUDE.md", "AGENTS.md", top=True))
    store_words = re.search(r"\bApp Store\b", docs)
    if mac:
        sandboxed = any(sandbox(ctx, x, app)["state"] == PASS for x, app in mac)
        if sandboxed or store_words:
            found.append(("mac-app-store", "an Xcode project for a Mac app" + (" with the App Sandbox on" if sandboxed
                                                                                else " that talks of the App Store")))
        else:
            found.append(("mac-direct", "an Xcode project for a Mac app without the App Sandbox"))
    if ios:
        found.append(("ios-app-store", "an Xcode project for an iPhone or iPad app"))
    if not mac and not ios:
        for rel in ctx.find("Package.swift"):
            package = ctx.text(rel)
            if rel.count("/") <= 1 and ".macOS" in package and "executableTarget" in package \
                    and ctx.uses(r"\bimport (SwiftUI|AppKit)\b"):
                found.append(("mac-direct", "a Swift package that builds a Mac app"))
                break
    data = pkg(ctx)
    if manifest(ctx):
        found.append(("browser-extension", "a manifest.json for a browser extension"))
    elif data:
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        web = [d for d in WEB_FRAMEWORKS if d in deps]
        if web:
            found.append(("web", f"package.json uses {web[0]}"))
        if not data.get("private") and any(data.get(k) for k in ("main", "exports", "bin", "module")) and not web:
            found.append(("npm-package", "package.json describes a package others can install"))
    elif ctx.find("index.html", top=True):
        found.append(("web", "an index.html at the top"))
    python_deps = ctx.text("requirements.txt") + ctx.text("pyproject.toml")
    web_python = re.search(r"^\s*[\"']?(flask|django|fastapi|streamlit|gradio)\b", python_deps, re.M | re.I)
    if web_python and all(t != "web" for t, _ in found):
        found.append(("web", f"it uses {web_python.group(1).lower()}"))
    if re.search(r"^\[project\]", ctx.text("pyproject.toml"), re.M) or "setup.py" in ctx.files:
        found.append(("python-package", "pyproject.toml describes a package"))
    if ctx.find("AndroidManifest.xml") and re.search(r"com\.android\.application", gradle_text(ctx)):
        found.append(("android", "an Android app module"))
    return found


def checklists(folder, facts: dict, ticks: dict[str, dict], extra: list[str] | None = None,
               hidden: list[str] | None = None) -> list[dict]:
    """Every checklist for the folder: the basics, the release lists that fit, and any added by hand.

    `ticks` are the owner's own marks, kept by the app: {"check:web:https": {"state": "ticked" | "skipped", "at": …}}.
    A tick also overrules what Pulse worked out (the owner knows better); "skipped" means it doesn't apply here."""
    ctx = Context(folder, facts)
    chosen = [("basics", "every project")] + detect(ctx)
    for list_id in extra or []:
        if list_id in CATALOG and all(list_id != c for c, _ in chosen):
            chosen.append((list_id, "added by you"))
    result = []
    for list_id, reason in chosen:
        if list_id in (hidden or []):
            continue
        title, items = CATALOG[list_id]
        rows = []
        for entry in items:
            key = f"check:{list_id}:{entry['id']}"
            outcome = None
            if entry["check"]:
                try:
                    outcome = entry["check"](ctx)
                except Exception as error:  # one odd file never stops the list
                    outcome = {"state": WARN, "evidence": f"Couldn't check: {type(error).__name__}", "path": None}
                if outcome is None:
                    continue  # doesn't apply to this folder
            outcome = dict(outcome or {"state": TODO, "evidence": "", "path": None})
            mark = ticks.get(key) or {}
            if mark.get("state") in (TICKED, SKIPPED):
                outcome["found"] = outcome["state"] if entry["check"] else None  # what Pulse saw, kept for the app
                outcome["state"] = mark["state"]
                outcome["evidence"] = ("Ticked" if mark["state"] == TICKED else "Doesn't apply, you said") \
                    + (f" {str(mark.get('at', ''))[:10]}" if mark.get("at") else "")
            path = outcome.get("path")
            rows.append({"key": key, "text": entry["text"], "why": entry["why"], "state": outcome["state"],
                         "auto": entry["check"] is not None, "evidence": outcome.get("evidence") or "",
                         "found": outcome.get("found"),
                         "path": str(ctx.root / path) if path and not path.startswith("/") else path})
        counted = [r for r in rows if r["state"] != SKIPPED]
        done = sum(1 for r in counted if r["state"] in (PASS, TICKED))
        result.append({"id": list_id, "title": title, "why": f"Pulse found {reason}." if list_id != "basics"
                       else "What every project needs.", "items": rows, "done": done, "total": len(counted),
                       "added": reason == "added by you"})
    return result


def catalog() -> list[dict]:
    """Every list Pulse knows, for the app's “Add a checklist” menu."""
    return [{"id": k, "title": v[0]} for k, v in CATALOG.items() if k != "basics"]
