// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

public final class TrafficPresentationTests {
    public static void main(String[] args) {
        TrafficPresentation rates=new TrafficPresentation();
        if (!rates.sample(1,1000,new long[]{0,0,100,200})) throw new AssertionError();
        rates.sample(1,2000,new long[]{50,100,2100,4200});
        if (rates.bytesPerSecond(0)!=50 || rates.bytesPerSecond(2)!=2000) throw new AssertionError("scope rates");
        rates.sample(1,2100,new long[]{50,100,2100,4200});
        if (rates.bytesPerSecond(2)!=2000) throw new AssertionError("duplicate sample");
        rates.sample(1,3000,new long[]{50,100,2100,4200});
        if (rates.bytesPerSecond(2)!=0) throw new AssertionError("idle rate");
        rates.sample(2,4000,new long[]{0,0,0,0});
        if (rates.bytesPerSecond(0)!=0) throw new AssertionError("session reset");
        if (rates.sample(2,5000,new long[]{-1,0,0,0})) throw new AssertionError("invalid counter");
        System.out.println("PASS: scoped traffic rates, idle, session reset and validation");
    }
}
