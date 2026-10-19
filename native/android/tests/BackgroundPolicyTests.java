// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

public final class BackgroundPolicyTests {
    private static int checks;

    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        check("background_sharing".equals(BackgroundPolicy.PREFERENCE_KEY), "One persisted policy key");
        check(BackgroundPolicy.DEFAULT_ALLOW_BACKGROUND, "User-requested background sharing defaults on");
        check(!BackgroundPolicy.stopWhenUiHidden(true, false), "On continues after Home, screen lock or Back");
        check(!BackgroundPolicy.stopWhenUiHidden(true, true), "On preserves configuration changes");
        check(BackgroundPolicy.stopWhenUiHidden(false, false), "Off stops when no longer visible");
        check(!BackgroundPolicy.stopWhenUiHidden(false, true), "Off preserves rotation");
        check(!BackgroundPolicy.stopWhenTaskRemoved(true), "On continues after removing Recents");
        check(BackgroundPolicy.stopWhenTaskRemoved(false), "Off stops when task is removed");
        System.out.println("PASS: " + checks + " Android background-policy assertions");
    }
}
