// SPDX-License-Identifier: GPL-3.0-only
import org.psportal.host.HostConfig;
import org.psportal.host.LanSetup;
public final class ExportConfig {
    public static void main(String[] args) {
        String mode = args.length == 0 ? "fixed" : args[0];
        String routing = args.length < 2 ? "rule" : args[1];
        String topology = args.length < 3 ? "lan" : args[2];
        boolean lan = !topology.equals("vpn"), vpn = !topology.equals("lan");
        java.util.List<String> clients = !lan ? java.util.Collections.emptyList()
                : mode.equals("auto") ? LanSetup.clients("192.168.1.2", 24)
                : java.util.Arrays.asList("192.168.1.30");
        HostConfig config = new HostConfig(lan ? "192.168.1.2" : "", clients, "10081",
                "https://example.com/subscription", mode, (mode.equals("fixed") || mode.equals("prefer")) ? "香港 A" : "", "60",
                mode.equals("fastest") ? 75 : 50, routing, lan, vpn);
        System.out.println(config.toJson("/data/user/0/org.psportal.host/files/runtime"));
    }
}
