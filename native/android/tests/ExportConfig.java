// SPDX-License-Identifier: GPL-3.0-only
import org.psportal.host.HostConfig;
public final class ExportConfig {
    public static void main(String[] args) {
        System.out.println(new HostConfig("192.168.1.2", "192.168.1.30", "10081", "https://example.com/subscription", "fixed", "香港 A", "60").toJson("/data/user/0/org.psportal.host/files/runtime"));
    }
}
