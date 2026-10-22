#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Structural guardrails only: this does not compile or run the iOS app."""
import pathlib
import plistlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
NATIVE = ROOT.parent
APP = ROOT / "PSPortalHost"


class SourceGuardrails(unittest.TestCase):
    def test_updates_are_explicit_read_only_guidance_not_fake_installation(self):
        view = (APP / "ContentView.swift").read_text()
        section = view.split('Text(t("当前版本：", "Installed version: ")', 1)
        self.assertEqual(len(section), 2)
        section = section[1].split('Text(t("关于星渡", "About StarPass"))', 1)[0]
        for expected in ["no version check performed", "not an installable IPA", "Do not uninstall",
                         "Subscription URLs are session-only", "automatic rollback is not provided",
                         "No update or latest-version determination was made", "openURL(ApplicationUpdateInfo.releasesURL)", '}.disabled(!model.canEdit).accessibilityIdentifier("applicationUpdateReleases")']:
            self.assertIn(expected, section)
        for forbidden in ["URLSession", "model.stop()", "model.start()", "model.forgetSettings()", ".onAppear", "Timer"]:
            self.assertNotIn(forbidden, section)
        helper = (APP / "ApplicationUpdateInfo.swift").read_text()
        self.assertIn("https://github.com/LONG10222/psportal-on-demand/releases", helper)
        self.assertIn('"CFBundleShortVersionString"', helper)
        self.assertIn('"CFBundleVersion"', helper)
        self.assertNotIn("URLSession", helper)

    def test_game_setup_explains_evidence_and_scope_on_home(self):
        view = (APP / "ContentView.swift").read_text()
        home = view.split("private var sharingPage", 1)[1].split("private var", 1)[0]
        self.assertIn("Game mode · Device sharing", home)
        self.assertIn('accessibilityIdentifier("gameSetupGuide")', home)
        self.assertIn("does not prove Internet access", home)
        self.assertIn("HTTP/TCP only, not game UDP; foreground by default", home)
        self.assertIn("Turn the device's HTTP proxy off when finished", view)

    def test_beginner_visual_hierarchy_preserves_controls_and_privacy(self):
        view = (APP / "ContentView.swift").read_text()
        home = view.split("private var sharingPage", 1)[1].split("private var", 1)[0]
        self.assertLess(home.index('"Subscription & start"'), home.index('"Service status"'))
        self.assertLess(home.index('"quickStartProxy"'), home.index('"sharingStatusTitle"'))
        self.assertIn('accessibilityIdentifier("setupNextStep")', home)
        self.assertIn('SecureField(', home)
        self.assertIn('.privacySensitive()', home)
        self.assertIn('if model.canStop { model.stop() } else { model.quickStart() }', home)
        self.assertIn('dynamicTypeSize.isAccessibilitySize', home)
        self.assertIn('ViewThatFits(in: .horizontal)', view)
        self.assertIn('.tint(model.canStop ? Color.red : primaryAccent)', home)
        self.assertIn('Image("StarPassMark")', view)
        self.assertIn('if !model.isActive', view)

    def test_anime_hero_is_static_decorative_and_accessible(self):
        view = (APP / "ContentView.swift").read_text()
        hero = view.split("private var navigatorHero", 1)[1].split("private var sharingPage", 1)[0]
        home = view.split("private var sharingPage", 1)[1].split("private var", 1)[0]
        self.assertIn("navigatorHero", home)
        self.assertIn('Image("StarPassMark")', hero)
        self.assertIn("dynamicTypeSize.isAccessibilitySize", hero)
        self.assertIn(".fixedSize(horizontal: false, vertical: true)", hero)
        self.assertIn(".allowsHitTesting(false).accessibilityHidden(true)", hero)
        self.assertIn('accessibilityIdentifier("animeNavigatorHero")', hero)
        self.assertNotIn("Button", hero)
        self.assertNotIn(".onAppear", hero)
        self.assertNotIn(".animation", hero)
        self.assertNotIn("Timer", hero)
        decoration = view.split("private struct NavigatorStarfield", 1)[1].split("private struct LicensesView", 1)[0]
        self.assertIn("Canvas", decoration)
        for expression in ["TimelineView", "Timer", "URLSession", "AsyncImage"]:
            self.assertNotIn(expression, decoration)

    def test_required_reason_manifest_matches_reviewed_uses(self):
        manifest = plistlib.loads((APP / "PrivacyInfo.xcprivacy").read_bytes())
        entries = manifest["NSPrivacyAccessedAPITypes"]
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry["NSPrivacyAccessedAPIType"]: entry["NSPrivacyAccessedAPITypeReasons"] for entry in entries}, {
            "NSPrivacyAccessedAPICategoryFileTimestamp": ["C617.1"],
            "NSPrivacyAccessedAPICategorySystemBootTime": ["35F9.1"],
        })

    def test_valid_plist_with_only_timed_processing_and_no_file_sharing(self):
        with (APP / "Info.plist").open("rb") as source:
            info = plistlib.load(source)
        self.assertTrue(info["NSLocalNetworkUsageDescription"])
        self.assertEqual(info["UIBackgroundModes"], ["processing"])
        self.assertEqual(info["BGTaskSchedulerPermittedIdentifiers"], ["org.psportal.host.foreground.sharing.*"])
        self.assertFalse(info["UIFileSharingEnabled"])
        self.assertFalse(info["LSSupportsOpeningDocumentsInPlace"])
        self.assertFalse(info["UIApplicationSceneManifest"]["UIApplicationSupportsMultipleScenes"])

    def test_real_engine_abi_and_no_fallback_transport(self):
        bridge = (APP / "Bridge/PSPortalEngineBridge.m").read_text()
        self.assertIn("<PSPortalEngine/PSPortalEngine.h>", bridge)
        for expression in ["MobileStart(configJSON, &error)", "MobileStop()", "MobileStatus()", "MobileNodeCommand(command)"]:
            self.assertIn(expression, bridge)
        mobile = (NATIVE / "mobile/mobile.go").read_text()
        for expression in ["func Start(configJSON string) error", "func Stop()", "func Status() string", "func NodeCommand(command string) string"]:
            self.assertIn(expression, mobile)
        self.assertNotIn("#if", bridge)
        self.assertIn('NS_SWIFT_NAME(start(configJSON:))', (APP / "Bridge/PSPortalEngineBridge.h").read_text())

    def test_only_nonsecret_settings_are_serialized(self):
        settings = (APP / "ProxySettings.swift").read_text()
        keys = re.search(r"private enum CodingKeys[^\{]*\{([^}]+)\}", settings).group(1)
        self.assertNotIn("subscriptionURL", keys)
        self.assertIn("keepAwake", keys)
        store = (APP / "PrivateSettingsStore.swift").read_text()
        self.assertIn(".completeFileProtection", store)
        self.assertIn("FileProtectionType.complete", store)
        self.assertIn("isExcludedFromBackup = true", store)
        self.assertIn("0o700", store)
        self.assertIn("0o600", store)
        self.assertIn(".applicationSupportDirectory", store)
        code = "\n".join(path.read_text() for path in APP.rglob("*.swift"))
        for forbidden in ["UserDefaults.standard", "@AppStorage", "@SceneStorage", "UIPasteboard", "NSLog(", "print(", "Logger("]:
            self.assertNotIn(forbidden, code)

    def test_lifecycle_stop_and_idle_restoration_guardrails(self):
        app = (APP / "PSPortalHostApp.swift").read_text()
        model = (APP / "ProxyModel.swift").read_text()
        self.assertIn("didEnterBackgroundNotification", app)
        self.assertIn("protectedDataWillBecomeUnavailableNotification", app)
        self.assertIn("phase == .background", model)
        self.assertIn("self.generation == token", model)
        self.assertIn("UIApplication.shared.isIdleTimerDisabled = previous", model)
        self.assertIn("UIApplication.shared.endBackgroundTask(task)", model)
        self.assertIn("guard canStart else", model)
        init_body = model.split("    func start()", 1)[0]
        self.assertNotIn("engine.start(", init_body)
        controller = (APP / "EngineController.swift").read_text()
        self.assertIn("DispatchQueue(label:", controller)
        self.assertIn("self.driver.stop()", controller)
        self.assertNotIn(".concurrent", controller)

    def test_no_network_extension_or_downloaded_executable_host(self):
        for path in APP.rglob("*"):
            if path.suffix not in {".swift", ".m", ".h", ".plist"}:
                continue
            code = path.read_text()
            for forbidden in ["import NetworkExtension", "NEPacketTunnelProvider", "NEVPNManager", "Process()", "dlopen(", "posix_spawn("]:
                self.assertNotIn(forbidden, code, str(path))
        project = (ROOT / "project.yml").read_text()
        self.assertNotIn("app-extension", project)
        self.assertIn("CODE_SIGNING_ALLOWED: NO", project)
        self.assertIn("framework: Frameworks/PSPortalEngine.xcframework", project)
        self.assertIn("embed: false", project)
        self.assertNotIn("DEVELOPMENT_TEAM", project)

    def test_license_files_match_project_sources(self):
        self.assertEqual((APP / "Resources/GPL-3.0.txt").read_bytes(), (NATIVE / "LICENSE").read_bytes())
        self.assertEqual((APP / "Resources/PROJECT-MIT.txt").read_bytes(), (NATIVE.parent / "LICENSE").read_bytes())
        self.assertIn("GPL-3.0-only", (APP / "Resources/THIRD-PARTY-NOTICES.txt").read_text())
        self.assertIn("ENGINE-NOTICES.txt", (ROOT / "scripts/verify-build-inputs.sh").read_text())

    def test_generated_header_when_available(self):
        header = NATIVE / "dist/bindings/objc/src/gobind/Mobile.objc.h"
        if not header.exists():
            self.skipTest("Run native/scripts/mobile.sh headers to inspect generated Objective-C ABI")
        code = header.read_text()
        self.assertRegex(code, r"BOOL MobileStart\(NSString\*.*NSError\*")
        self.assertRegex(code, r"NSString\*.*MobileStatus\(void\)")
        self.assertIn("void MobileStop(void)", code)
        self.assertIn("MobileNodeCommand", code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
