// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

public final class PhoneVpnStateTests {
    private static int assertions;
    private static void check(boolean value) { assertions++; if (!value) throw new AssertionError(); }
    public static void main(String[] args) {
        PhoneVpnState s = new PhoneVpnState();
        check(s.code().equals("stopped") && !s.busy());
        long first = s.begin();
        check(first > 0 && s.code().equals("starting"));
        check(s.begin() == -1);
        long stopped = s.stop("revoked");
        check(stopped > first && s.busy());
        check(!s.current(first) && !s.running(first));
        check(s.stop("stopped") == stopped); // preserve first meaningful reason
        check(s.begin() == -1); // no restart until descriptor/native cleanup
        s.finish(first); check(s.code().equals("stopping"));
        s.finish(stopped); check(s.code().equals("revoked") && !s.busy());
        long second = s.begin(); check(second > stopped);
        check(s.running(second) && s.code().equals("running"));
        check(!s.running(first));
        s.reject("start_failed"); check(s.code().equals("running"));
        long end = s.stop("no_network"); s.finish(end);
        check(s.code().equals("no_network"));
        s.reject("vpn_conflict"); check(s.code().equals("vpn_conflict"));
        System.out.println("PASS: " + assertions + " VPN consent/start/stop generation assertions (no VPN activated)");
    }
}
