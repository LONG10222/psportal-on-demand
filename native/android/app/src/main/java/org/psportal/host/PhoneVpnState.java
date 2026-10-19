// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

/** Thread-safe generation gate. Old starts can never revive a stopped VPN. */
final class PhoneVpnState {
    private long generation;
    private String state = "stopped", terminal = "stopped";
    synchronized long begin() {
        if (busy()) return -1;
        state = "starting"; terminal = "stopped"; return ++generation;
    }
    synchronized boolean current(long token) { return generation == token && state.equals("starting"); }
    synchronized boolean running(long token) {
        if (!current(token)) return false;
        state = "running"; return true;
    }
    synchronized long stop(String reason) {
        if (state.equals("stopping")) return generation;
        terminal = reason; state = "stopping"; return ++generation;
    }
    synchronized void finish(long token) { if (generation == token && state.equals("stopping")) state = terminal; }
    synchronized void reject(String reason) { if (!busy()) state = reason; }
    synchronized String code() { return state; }
    synchronized boolean busy() { return state.equals("starting") || state.equals("running") || state.equals("stopping"); }
}
