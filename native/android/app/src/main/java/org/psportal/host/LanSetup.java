// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Bounded, explicit LAN allowlists. Never changes addresses, routing, DNS or Wi-Fi. */
public final class LanSetup {
    private LanSetup() {}

    static boolean safeInterface(String name) {
        String value = name.toLowerCase(Locale.ROOT);
        // Physical Wi-Fi/Ethernet only. Cellular alone never proves hotspot sharing.
        return value.matches("(?:wlan|wifi|eth|en)[0-9]+(?:\\.[0-9]+)?");
    }

    public static List<String> clients(String address, int prefix) {
        if (!HostConfig.isPrivateIpv4(address) || prefix < 24 || prefix > 30)
            throw new IllegalArgumentException("Automatic setup requires a private /24–/30 LAN");
        long host = numeric(address), mask = (0xffffffffL << (32 - prefix)) & 0xffffffffL;
        long network = host & mask, broadcast = network | (~mask & 0xffffffffL);
        if (host == network || host == broadcast) throw new IllegalArgumentException("Invalid LAN host address");
        List<String> result = new ArrayList<>();
        for (long client = network + 1; client < broadcast; client++) {
            if (client != host) result.add(dotted(client));
        }
        return result;
    }

    private static long numeric(String address) {
        long result = 0;
        for (String octet : address.split("\\.")) result = (result << 8) | Integer.parseInt(octet);
        return result;
    }
    private static String dotted(long value) {
        return ((value >> 24) & 255) + "." + ((value >> 16) & 255) + "." + ((value >> 8) & 255) + "." + (value & 255);
    }

    interface PortCheck { boolean available(String address, int port); }
    static int choosePort(String address, int preferred, PortCheck check) throws IOException {
        if (preferred < 1024 || preferred > 65535 || preferred == 10082 || preferred == 10090)
            throw new IllegalArgumentException("Invalid proxy port");
        if (check.available(address, preferred)) return preferred;
        for (int port = 10081; port <= 10181; port++) {
            if (port != 10082 && port != 10090 && port != preferred && check.available(address, port)) return port;
        }
        throw new IOException("No available LAN proxy port");
    }
    static int choosePort(String address, int preferred) throws IOException {
        return choosePort(address, preferred, (host, port) -> {
            try (ServerSocket socket = new ServerSocket()) {
                socket.setReuseAddress(false);
                socket.bind(new InetSocketAddress(host, port));
                return true;
            } catch (IOException | SecurityException unavailable) { return false; }
        });
    }
}
