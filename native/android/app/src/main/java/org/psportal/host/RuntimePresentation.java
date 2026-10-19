// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

/** Native state and connection counts are distinct from a successfully opened listener. */
public final class RuntimePresentation {
    public enum State { STOPPED, PREPARING, LISTENING, WAKING, FORWARDING, READY, STOPPING, ERROR, UNKNOWN }
    private RuntimePresentation() {}
    public static State state(SessionController.Phase phase, boolean preparing, Boolean listening,
                              String coreState, Long connections, boolean error) {
        if (preparing) return State.PREPARING;
        switch (phase) {
            case STARTING: return State.PREPARING;
            case STOPPING: return State.STOPPING;
            case ERROR: case FAULTED: return State.ERROR;
            case STOPPED: return State.STOPPED;
            default: break;
        }
        if (error) return State.ERROR;
        if (listening == null) return State.UNKNOWN;
        if (!listening) return State.ERROR;
        if ("preparing".equals(coreState)) return State.PREPARING;
        if ("listening".equals(coreState)) return State.LISTENING;
        if ("forwarding".equals(coreState)) return State.FORWARDING;
        if ("starting".equals(coreState) || "waking".equals(coreState)) return State.WAKING;
        if ("failed".equals(coreState) || "error".equals(coreState)) return State.ERROR;
        if (connections != null && connections > 0) return State.FORWARDING;
        if ("stopped".equals(coreState)) return State.LISTENING;
        if ("running".equals(coreState)) return State.READY;
        return State.UNKNOWN;
    }
}
