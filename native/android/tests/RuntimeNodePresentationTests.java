// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

/** Pure presentation tests: no Android service, JNI, network, or VPN is started. */
public final class RuntimeNodePresentationTests {
    private static int assertions;
    private static void check(boolean value, String label) {
        assertions++;
        if (!value) throw new AssertionError(label);
    }
    public static void main(String[] arguments) {
        for (String name : new String[]{"香港 A", "SELECT", "DIRECT", "Group / two", "😀 test"})
            check(RuntimeNodePresentation.safeName(name).equals(name), "Keep an exact safe runtime label");
        for (String name : new String[]{null, "", " name", "name ", "x\nsecret", "x\u202esecret", "https://example.com/token", "node?token=secret", "a".repeat(257)})
            check(RuntimeNodePresentation.safeName(name).isEmpty(), "Reject unsafe or overlong labels");
        for (Long delay : new Long[]{null, -1L, 0L, 65535L, 65536L})
            check(RuntimeNodePresentation.latency(delay, true, true).equals("Unmeasured / unavailable"), "Missing and sentinel latency stay unknown");
        check(RuntimeNodePresentation.latency(25L, true, true).equals("25 ms"), "Show actual successful latency");
        check(RuntimeNodePresentation.latency(65534L, true, false).equals("65534 ms"), "Largest real measured value remains distinct from sentinel");
        check(RuntimeNodePresentation.latency(25L, false, true).equals("Unmeasured / unavailable"), "Failed node never looks measured");
        check(RuntimeNodePresentation.latency(25L, null, false).equals("未测得 / 不可用"), "Unknown health is not success");
        check(RuntimeNodePresentation.selectableGroup(true, 1L), "One explicit group choice is valid");
        check(RuntimeNodePresentation.selectableGroup(true, 1256L), "Bounded maximum choices is valid");
        for (Long count : new Long[]{null, -1L, 0L, 1257L})
            check(!RuntimeNodePresentation.selectableGroup(true, count), "Reject missing or excessive choices");
        check(!RuntimeNodePresentation.selectableGroup(false, 2L), "Automatic group remains read-only");
        check(!RuntimeNodePresentation.selectableGroup(null, 2L), "Unknown group remains read-only");
        check(RuntimeNodePresentation.canSelect(SessionController.Phase.RUNNING, false, 0L, false), "Quiescent session can select");
        for (SessionController.Phase phase : SessionController.Phase.values())
            if (phase != SessionController.Phase.RUNNING)
                check(!RuntimeNodePresentation.canSelect(phase, false, 0L, false), "Non-running session cannot select");
        check(!RuntimeNodePresentation.canSelect(SessionController.Phase.RUNNING, true, 0L, false), "Pending command cannot overlap");
        check(!RuntimeNodePresentation.canSelect(SessionController.Phase.RUNNING, false, null, false), "Unknown count cannot authorize selection");
        check(!RuntimeNodePresentation.canSelect(SessionController.Phase.RUNNING, false, 1L, false), "Active connections block selection");
        check(!RuntimeNodePresentation.canSelect(SessionController.Phase.RUNNING, false, 0L, true), "Active VPN blocks selection");
        SubscriptionAccounting dated = new SubscriptionAccounting("1", "2", "100", "2000000000", 1900000000L);
        check(dated.updatedAt == 1900000000L && dated.used == 3L, "Snapshot timestamp preserves valid accounting");
        check(new SubscriptionAccounting("", "", "", "", 1900000000L).updatedAt == null, "Unavailable response has no successful update time");
        check(new SubscriptionAccounting("1", "", "", "", 1900000000L).updatedAt == 1900000000L, "Partial server snapshot may have a time");
        for (Long timestamp : new Long[]{null, -1L, 0L, 253402300800L})
            check(new SubscriptionAccounting("1", "2", "100", "", timestamp).updatedAt == null, "Reject invalid update time");
        check(new SubscriptionAccounting("1", "2", "100", "").updatedAt == null, "Historical constructor never invents refresh time");
        check(ProductMode.values().length == 3, "Exactly three named product modes");
        check(ProductMode.GAME.lanEnabled && !ProductMode.GAME.phoneVpn, "Game is LAN only");
        check(ProductMode.MIXED.lanEnabled && ProductMode.MIXED.phoneVpn, "Mixed enables both input choices");
        check(!ProductMode.CLASH.lanEnabled && ProductMode.CLASH.phoneVpn, "Clash is phone only without a LAN listener");
        for (ProductMode mode : ProductMode.values()) {
            check(ProductMode.fromInputs(mode.lanEnabled, mode.phoneVpn) == mode, "Existing input switches map back to their exact preset");
            check(!mode.label(true).isEmpty() && !mode.label(false).isEmpty(), "Product label is bilingual");
            check(!mode.description(true).isEmpty() && !mode.description(false).isEmpty(), "Product boundaries are bilingual");
            check(!mode.shortDescription(true).isEmpty() && mode.shortDescription(true).length() <= 65, "English overview hint stays compact");
            check(!mode.shortDescription(false).isEmpty() && mode.shortDescription(false).length() <= 30, "Chinese overview hint stays compact");
            if (mode.phoneVpn) check(mode.shortDescription(true).contains("VPN consent") && mode.shortDescription(false).contains("VPN"), "Compact phone hint still explains consent");
        }
        for (ProductMode mode : ProductMode.values()) {
            for (ProductMode envelope : ProductMode.values())
                check(ProductMode.matchesSessionInputs(envelope.lanEnabled, envelope.phoneVpn, mode.lanEnabled, mode.phoneVpn)
                        == (mode == envelope), "Service flags must match native inputs exactly");
        }
        check(!ProductMode.matchesSessionInputs(false, false, false, false), "No-input service config is rejected");
        check(!ProductMode.matchesSessionInputs(true, false, "true", false), "String LAN flags cannot bypass admission");
        check(!ProductMode.matchesSessionInputs(true, false, true, "false"), "String phone flags cannot bypass admission");
        check(!ProductMode.matchesSessionInputs(true, false, null, false), "Missing native input flag is rejected");
        check(ProductMode.fromInputs(false, false) == null, "Both inputs off never silently enables a preset");
        check(ProductMode.GAME.description(true).contains("separate checks"), "Game setup separates service, connection and verified access");
        check(ProductMode.GAME.description(false).contains("分别确认"), "Chinese game setup preserves verification boundaries");
        check(ProductMode.GAME.description(true).contains("TCP only") && ProductMode.GAME.description(true).contains("not guaranteed"), "Game preset does not promise unsupported acceleration or UDP");
        for (ProductMode mode : new ProductMode[]{ProductMode.MIXED, ProductMode.CLASH})
            check(mode.description(true).contains("Android VPN consent"), "Phone presets require explicit Android consent");
        for (SessionController.Phase phase : SessionController.Phase.values()) {
            boolean allowed = phase == SessionController.Phase.STOPPED || phase == SessionController.Phase.ERROR;
            check(ProductMode.canChange(phase, false, false) == allowed, "Preset changes respect session phase");
            check(!ProductMode.canChange(phase, true, false), "Preparation and pending permissions block preset changes");
            check(!ProductMode.canChange(phase, false, true), "Live phone VPN blocks preset changes");
        }
        System.out.println("PASS: " + assertions + " Android runtime-node/accounting presentation assertions (JVM only)");
    }
}
