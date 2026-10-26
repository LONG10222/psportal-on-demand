// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

/** Destination-scoped, session-local rates from real monotonic byte counters. */
public final class TrafficPresentation {
    private long session = -1, sampledAt;
    private long[] baseline;
    private final double[] rates = new double[4];
    public boolean sample(long sessionId, long now, long[] counters) {
        if (counters == null || counters.length != 4) return false;
        for (long counter : counters) if (counter < 0) return false;
        boolean reset = sessionId != session || baseline == null || now < sampledAt;
        if (!reset) for (int i=0;i<4;i++) if (counters[i] < baseline[i]) reset = true;
        if (reset) {
            session=sessionId; sampledAt=now; baseline=counters.clone();
            java.util.Arrays.fill(rates, 0); return true;
        }
        if (now-sampledAt >= 1000) {
            double seconds=(now-sampledAt)/1000.0;
            for (int i=0;i<4;i++) rates[i]=(counters[i]-baseline[i])/seconds;
            baseline=counters.clone(); sampledAt=now;
        }
        return true;
    }
    public long bytesPerSecond(int index) { return (long)Math.max(0, rates[index]); }
}
