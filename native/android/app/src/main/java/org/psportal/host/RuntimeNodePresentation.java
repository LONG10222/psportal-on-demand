// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

/** Bounded labels from the runtime; never expose credentials or fabricated latency. */
public final class RuntimeNodePresentation {
    private RuntimeNodePresentation() {}

    public static String safeName(String name) {
        if (name == null || name.isEmpty() || name.length() > 256 || !name.equals(name.trim()) ||
                name.contains("://") || name.contains("?")) return "";
        for (int i = 0; i < name.length(); i++)
            if (Character.isISOControl(name.charAt(i)) || Character.getType(name.charAt(i)) == Character.FORMAT) return "";
        return name;
    }

    public static String latency(Long delay, Boolean healthy, boolean english) {
        // Mihomo reports UINT16_MAX when no successful measurement is available.
        if (delay == null || delay <= 0 || delay >= 65535 || !Boolean.TRUE.equals(healthy))
            return english ? "Unmeasured / unavailable" : "未测得 / 不可用";
        return delay + " ms";
    }

    public static boolean selectableGroup(Boolean selectable, Long choices) {
        return Boolean.TRUE.equals(selectable) && choices != null && choices > 0 && choices <= 1256;
    }

    public static boolean canSelect(SessionController.Phase phase, boolean commandPending,
                                    Long connections, boolean phoneVpnActive) {
        return phase == SessionController.Phase.RUNNING && !commandPending && connections != null &&
                connections == 0 && !phoneVpnActive;
    }
}
