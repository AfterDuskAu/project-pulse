"""Checks Pulse's checklists on small made-up projects: what it detects, what it ticks by itself, and the owner's ticks.

    python3 -m unittest -v test_pulse_checks
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import pulse_any as pa
import pulse_checks as pc
from test_pulse_any import QUIET, commit, write

NOW = dt.datetime.now().astimezone()
FACTS = {"secrets": 0, "copies": 0, "testFiles": 0, "plan": False, "knownIssues": False}


def pbxproj(release: str, debug: str = "", app_name: str = "Demo") -> str:
    """A small project.pbxproj in Xcode's own layout: one app target with Debug and Release settings."""
    return f"""// !$*UTF8*$!
{{
	archiveVersion = 1;
	objects = {{

/* Begin PBXBuildFile section */
		AA0000000000000000000001 /* DemoApp.swift in Sources */ = {{isa = PBXBuildFile; fileRef = AA0000000000000000000002; }};
/* End PBXBuildFile section */

/* Begin PBXNativeTarget section */
		AA0000000000000000000010 /* {app_name} */ = {{
			isa = PBXNativeTarget;
			buildConfigurationList = AA0000000000000000000020 /* Build configuration list for PBXNativeTarget "{app_name}" */;
			name = {app_name};
			productType = "com.apple.product-type.application";
		}};
		AA0000000000000000000011 /* DemoTests */ = {{
			isa = PBXNativeTarget;
			buildConfigurationList = AA0000000000000000000021;
			name = DemoTests;
			productType = "com.apple.product-type.bundle.unit-test";
		}};
/* End PBXNativeTarget section */

/* Begin PBXProject section */
		AA0000000000000000000030 /* Project object */ = {{
			isa = PBXProject;
			buildConfigurationList = AA0000000000000000000022 /* Build configuration list for PBXProject "Demo" */;
		}};
/* End PBXProject section */

/* Begin XCBuildConfiguration section */
		AA0000000000000000000040 /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				SDKROOT = macosx;
				MACOSX_DEPLOYMENT_TARGET = 14.0;
			}};
			name = Debug;
		}};
		AA0000000000000000000041 /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				SDKROOT = macosx;
				MACOSX_DEPLOYMENT_TARGET = 14.0;
			}};
			name = Release;
		}};
		AA0000000000000000000042 /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				PRODUCT_BUNDLE_IDENTIFIER = com.demo.app;
{debug}
			}};
			name = Debug;
		}};
		AA0000000000000000000043 /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				PRODUCT_BUNDLE_IDENTIFIER = com.demo.app;
				OTHER_LDFLAGS = (
					"-ObjC",
					"-lz",
				);
{release}
			}};
			name = Release;
		}};
/* End XCBuildConfiguration section */

/* Begin XCConfigurationList section */
		AA0000000000000000000020 /* Build configuration list for PBXNativeTarget "{app_name}" */ = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				AA0000000000000000000042 /* Debug */,
				AA0000000000000000000043 /* Release */,
			);
			defaultConfigurationName = Release;
		}};
		AA0000000000000000000022 /* Build configuration list for PBXProject "Demo" */ = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				AA0000000000000000000040 /* Debug */,
				AA0000000000000000000041 /* Release */,
			);
			defaultConfigurationName = Release;
		}};
/* End XCConfigurationList section */
	}};
	rootObject = AA0000000000000000000030 /* Project object */;
}}
"""


def plist(entries: dict) -> str:
    import plistlib
    return plistlib.dumps(entries).decode()


def lists(root: Path, ticks: dict | None = None, extra: list | None = None, **facts) -> dict:
    folder = pa.Folder(root, NOW)
    found = pc.checklists(folder, {**FACTS, **facts}, ticks or {}, extra)
    return {c["id"]: c for c in found}


def row(checklist: dict, item_id: str) -> dict:
    return next(r for r in checklist["items"] if r["key"].endswith(f":{item_id}"))


class ReleaseCode(unittest.TestCase):
    def test_debug_only_parts_are_blanked_and_lines_still_match(self):
        text = "a\n#if DEBUG\nb\n#else\nc\n#endif\n#if !DEBUG\nd\n#else\ne\n#endif\n#if os(macOS)\nf\n#endif\n"
        kept = pc.release_code(text)
        self.assertEqual(kept.count("\n"), text.count("\n"))
        self.assertEqual([line for line in kept.splitlines() if line], ["a", "c", "d", "f"])

    def test_nested_blocks(self):
        text = "#if DEBUG || PERF\n#if os(macOS)\nx\n#endif\n#endif\ny\n"
        self.assertEqual([line for line in pc.release_code(text).splitlines() if line], ["y"])


class MacAppStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, {
            "Demo.xcodeproj/project.pbxproj": pbxproj(
                release="\t\t\t\tENABLE_APP_SANDBOX = YES;\n\t\t\t\tCODE_SIGN_ENTITLEMENTS = Demo/Demo.entitlements;\n"
                        "\t\t\t\tMARKETING_VERSION = 1.0;\n\t\t\t\tCURRENT_PROJECT_VERSION = 3;\n"
                        "\t\t\t\tINFOPLIST_KEY_NSHumanReadableCopyright = \"\";",
                debug="\t\t\t\tENABLE_APP_SANDBOX = NO;"),
            "Demo/Demo.entitlements": plist({"com.apple.security.app-sandbox": True,
                                             "com.apple.security.files.user-selected.read-only": True}),
            "Demo/PrivacyInfo.xcprivacy": plist({"NSPrivacyAccessedAPITypes": [
                {"NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategoryUserDefaults",
                 "NSPrivacyAccessedAPITypeReasons": ["CA92.1"]}]}),
            "Demo/Assets.xcassets/AppIcon.appiconset/Contents.json": json.dumps({"images": [
                {"size": "16x16", "scale": "1x", "filename": "icon16.png"}, {"size": "16x16", "scale": "2x"}]}),
            "Demo/DemoApp.swift": "import SwiftUI\nlet saved = UserDefaults.standard\n"
                                  "let clock = ProcessInfo.processInfo.systemUptime\n",
            "Demo/Debugging.swift": "#if DEBUG\nlet spawn = Process()\n#endif\n",
            "README.md": "# Demo\nA Mac app for the App Store.\n",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_detected_with_the_reason(self):
        found = lists(self.root)
        self.assertIn("mac-app-store", found)
        self.assertIn("App Sandbox on", found["mac-app-store"]["why"])
        self.assertNotIn("mac-direct", found)

    def test_what_the_files_prove(self):
        store = lists(self.root)["mac-app-store"]
        self.assertEqual(row(store, "sandbox")["state"], "pass")
        self.assertEqual(row(store, "debugEnts")["state"], "pass")
        self.assertEqual(row(store, "version")["state"], "pass")
        self.assertIn("1.0 (3)", row(store, "version")["evidence"])
        self.assertEqual(row(store, "team")["state"], "fail")
        self.assertEqual(row(store, "category")["state"], "fail")
        self.assertEqual(row(store, "copyright")["state"], "fail")  # set, but empty
        icon = row(store, "icon")
        self.assertEqual(icon["state"], "fail")
        self.assertIn("1 of its 2 pictures", icon["evidence"])

    def test_privacy_manifest_must_give_every_reason_the_code_needs(self):
        privacy = row(lists(self.root)["mac-app-store"], "privacy")
        self.assertEqual(privacy["state"], "fail")
        self.assertIn("time since start-up", privacy["evidence"])
        self.assertIn("DemoApp.swift:3", privacy["evidence"])

    def test_debug_only_code_isnt_counted(self):
        self.assertEqual(row(lists(self.root)["mac-app-store"], "noProcess")["state"], "pass")
        write(self.root, {"Demo/Helper.swift": "let task = Process()\n"})
        self.assertEqual(row(lists(self.root)["mac-app-store"], "noProcess")["state"], "warn")

    def test_manual_items_wait_for_the_owner_and_ticks_count(self):
        store = lists(self.root)["mac-app-store"]
        self.assertEqual(row(store, "screenshots")["state"], "todo")
        ticks = {"check:mac-app-store:screenshots": {"state": "ticked", "at": "2026-09-30T19:00:00+10:00"},
                 "check:mac-app-store:reviewNotes": {"state": "skipped", "at": "2026-09-30T19:00:00+10:00"},
                 "check:mac-app-store:team": {"state": "ticked", "at": "2026-09-30T19:00:00+10:00"}}
        ticked = lists(self.root, ticks)["mac-app-store"]
        self.assertEqual(row(ticked, "screenshots")["state"], "ticked")
        self.assertEqual(row(ticked, "reviewNotes")["state"], "skipped")
        team = row(ticked, "team")
        self.assertEqual((team["state"], team["found"]), ("ticked", "fail"))  # the owner overrules; Pulse's view kept
        self.assertEqual(ticked["total"], store["total"] - 1)
        self.assertEqual(ticked["done"], store["done"] + 2)

    def test_a_usage_text_is_needed_for_what_the_code_uses(self):
        write(self.root, {"Demo/Library.swift": "import Photos\nlet library = PHPhotoLibrary.shared()\n"})
        usage = row(lists(self.root)["mac-app-store"], "usage")
        self.assertEqual(usage["state"], "fail")
        self.assertIn("NSPhotoLibraryUsageDescription", usage["evidence"])

    def test_without_the_sandbox_it_is_a_mac_app_outside_the_store(self):
        write(self.root, {
            "Demo.xcodeproj/project.pbxproj": pbxproj(release="\t\t\t\tENABLE_HARDENED_RUNTIME = YES;"),
            "Demo/Demo.entitlements": plist({}), "README.md": "# Demo\nDownload it from my site.\n"})
        found = lists(self.root)
        self.assertIn("mac-direct", found)
        self.assertNotIn("mac-app-store", found)
        self.assertEqual(row(found["mac-direct"], "hardened")["state"], "pass")


class OtherKinds(unittest.TestCase):
    def detect(self, files: dict) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp), files)
            return [c for c in lists(Path(tmp)) if c != "basics"]

    def test_each_kind_of_project_gets_its_list(self):
        self.assertEqual(self.detect({"package.json": json.dumps({"dependencies": {"react": "18"}})}), ["web"])
        self.assertEqual(self.detect({"package.json": json.dumps({"name": "x", "version": "1.0.0",
                                                                  "main": "index.js"})}), ["npm-package"])
        self.assertEqual(self.detect({"pyproject.toml": "[project]\nname = 'x'\n"}), ["python-package"])
        self.assertEqual(self.detect({"manifest.json": json.dumps({"manifest_version": 3, "name": "x"}),
                                      "package.json": json.dumps({"private": True})}), ["browser-extension"])
        self.assertEqual(self.detect({"app/src/main/AndroidManifest.xml": "<manifest/>",
                                      "app/build.gradle": "plugins { id 'com.android.application' }"}), ["android"])
        self.assertEqual(self.detect({"requirements.txt": "flask==3.0\n"}), ["web"])
        self.assertEqual(self.detect({"App/Package.swift": "platforms: [.macOS(.v14)]\n.executableTarget(name: \"A\")",
                                      "App/Sources/A/Main.swift": "import SwiftUI\n"}), ["mac-direct"])
        self.assertEqual(self.detect({"notes.txt": "ideas"}), [])

    def test_a_list_can_be_added_by_hand(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp), {"notes.txt": "ideas"})
            found = lists(Path(tmp), extra=["ios-app-store", "nonsense"])
            self.assertIn("ios-app-store", found)
            self.assertTrue(found["ios-app-store"]["added"])
            self.assertNotIn("nonsense", found)

    def test_web_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {"package.json": json.dumps({"dependencies": {"next": "14"}, "scripts": {"build": "next build"}}),
                         "README.md": "Run `npm run dev`.", "public/favicon.ico": "x", ".env.example": "KEY=\n"})
            web = lists(root)["web"]
            self.assertEqual(row(web, "run")["state"], "pass")
            self.assertEqual(row(web, "build")["state"], "pass")
            self.assertEqual(row(web, "favicon")["state"], "pass")
            self.assertEqual(row(web, "lockfile")["state"], "fail")
            self.assertEqual(row(web, "https")["state"], "todo")


class Basics(unittest.TestCase):
    def test_git_remote_and_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, remote = Path(tmp) / "p", Path(tmp) / "remote.git"
            root.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], **QUIET)
            write(root, {"README.md": "# P\n", "CLAUDE.md": "rules"})
            commit(root, "first")
            basics = lists(root)["basics"]
            self.assertEqual(row(basics, "remote")["state"], "fail")
            subprocess.run(["git", "init", "-q", "--bare", str(remote)], **QUIET)
            subprocess.run(["git", "-C", str(root), "remote", "add", "origin", str(remote)], **QUIET)
            subprocess.run(["git", "-C", str(root), "push", "-q", "-u", "origin", "main"], **QUIET)
            basics = lists(root)["basics"]
            self.assertEqual(row(basics, "remote")["state"], "pass")
            self.assertEqual(row(basics, "pushed")["state"], "pass")
            write(root, {"a.txt": "more"})
            commit(root, "second")
            pushed = row(lists(root)["basics"], "pushed")
            self.assertEqual(pushed["state"], "fail")
            self.assertIn("1 commit not pushed", pushed["evidence"])

    def test_facts_from_the_other_readers(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp), {"README.md": "x"})
            basics = lists(Path(tmp), secrets=2, copies=0,
                           lastTestRun={"outcome": "fail", "command": "pytest", "time": "2026-09-30T18:00"})["basics"]
            self.assertEqual(row(basics, "nokeys")["state"], "fail")
            self.assertEqual(row(basics, "nocopies")["state"], "pass")
            self.assertEqual(row(basics, "testsPass")["state"], "fail")
            self.assertEqual(row(basics, "git")["state"], "fail")


if __name__ == "__main__":
    unittest.main()
