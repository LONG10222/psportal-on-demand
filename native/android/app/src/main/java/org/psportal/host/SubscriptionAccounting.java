// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import java.util.Locale;

/** Server-provided snapshot only. Unknown is never rendered as zero or unlimited. */
public final class SubscriptionAccounting {
    public final Long used, total, remaining, expires, updatedAt;
    public SubscriptionAccounting(String upload, String download, String total, String expires) {
        this(upload, download, total, expires, null);
    }
    public SubscriptionAccounting(String upload, String download, String total, String expires, Long updatedAt) {
        Long up = number(upload), down = number(download), allowance = number(total), expiry = number(expires);
        used = up != null && down != null && Long.MAX_VALUE - up >= down ? up + down : null;
        this.total = allowance != null && allowance > 0 ? allowance : null;
        remaining = this.total == null || used == null ? null : Math.max(0, this.total - used);
        this.expires = expiry != null && expiry > 0 && expiry <= 253402300799L ? expiry : null;
        boolean hasServerData = up != null || down != null || allowance != null || this.expires != null;
        this.updatedAt = hasServerData && updatedAt != null && updatedAt > 0 && updatedAt <= 253402300799L ? updatedAt : null;
    }
    private static Long number(String text) {
        if (text == null || !text.matches("[0-9]{1,19}")) return null;
        try { return Long.parseLong(text); } catch (NumberFormatException invalid) { return null; }
    }
    public static String bytes(Long value, String missing, Locale locale) {
        if (value == null) return missing;
        String[] units = {"B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"};
        double amount = value; int unit = 0;
        while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit++; }
        return String.format(locale, "%.2f %s", amount, units[unit]);
    }
    public int percent() {
        if (used == null || total == null) return -1;
        return (int)Math.round(Math.min(1.0, used.doubleValue() / total.doubleValue()) * 100);
    }
}
