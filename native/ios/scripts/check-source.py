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
    def test_valid_plist_without_background_modes_or_file_sharing(self):
        with (APP / "Info.plist").open("rb") as source:
            info = plistlib.load(source)
        self.assertTrue(info["NSLocalNetworkUsageDescription"])
        self.assertNotIn("UIBackgroundModes", info)
        self.assertNotIn("BGTaskSchedulerPermittedIdentifiers", info)
        self.assertFalse(info["UIFileSharingEnabled"])
        self.assertFalse(info["LSSupportsOpeningDocumentsInPlace"])
        self.assertFalse(info["UIApplicationSceneManifest"]["UIApplicationSupportsMultipleScenes"])

    def test_real_engine_abi_and_no_fallback_transport(self):
        bridge = (APP / "Bridge/PSPortalEngineBridge.m").read_text()
        self.assertIn("<PSPortalEngine/PSPortalEngine.h>", bridge)
        for expression in ["MobileStart(configJSON, &error)", "MobileStop()", "MobileStatus()"]:
            self.assertIn(expression, bridge)
        mobile = (NATIVE / "mobile/mobile.go").read_text()
        for expression in ["func Start(configJSON string) error", "func Stop()", "func Status() string"]:
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
