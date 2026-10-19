// SPDX-License-Identifier: GPL-3.0-only
import org.psportal.host.HostConfig;
import org.psportal.host.LanSetup;
public final class ExportConfig {
    public static void main(String[] args) {
        String mode = args.length == 0 ? "fixed" : args[0];
        HostConfig config = mode.equals("auto")
                ? new HostConfig("192.168.1.2", LanSetup.clients("192.168.1.2", 24), "10081", "https://example.com/subscription", "auto", "", "60")
                : mode.equals("fastest")
                ? new HostConfig("192.168.1.2", java.util.Arrays.asList("192.168.1.30"), "10081", "https://example.com/subscription", "fastest", "", "60", 75)
                : new HostConfig("192.168.1.2", "192.168.1.30", "10081", "https://example.com/subscription", "fixed", "香港 A", "60");
        System.out.println(config.toJson("/data/user/0/org.psportal.host/files/runtime"));
    }
}
