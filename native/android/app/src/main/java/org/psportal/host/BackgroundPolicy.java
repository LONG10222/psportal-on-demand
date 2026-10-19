// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

/** User-owned continuation policy. It never starts or restarts a session. */
final class BackgroundPolicy {
    static final String PREFERENCE_KEY = "background_sharing";
    static final boolean DEFAULT_ALLOW_BACKGROUND = true;

    private BackgroundPolicy() {}

    static boolean stopWhenUiHidden(boolean allowBackground, boolean changingConfigurations) {
        // Rotation replaces the Activity without ending the user's current run.
        return !allowBackground && !changingConfigurations;
    }

    static boolean stopWhenTaskRemoved(boolean allowBackground) {
        // Removing Recents is distinct from Android's Active-app Stop/force-stop.
        return !allowBackground;
    }
}
