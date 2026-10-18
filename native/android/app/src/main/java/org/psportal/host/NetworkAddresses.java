// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.SocketException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

final class NetworkAddresses {
    private NetworkAddresses() {}
    static List<String> localPrivateIpv4() {
        List<String> addresses = new ArrayList<>();
        try {
            java.util.Enumeration<NetworkInterface> all = NetworkInterface.getNetworkInterfaces();
            if (all == null) return addresses;
            for (NetworkInterface network : Collections.list(all)) {
                if (!network.isUp() || network.isLoopback()) continue;
                for (InetAddress address : Collections.list(network.getInetAddresses())) {
                    if (address instanceof Inet4Address && HostConfig.isPrivateIpv4(address.getHostAddress()))
                        addresses.add(address.getHostAddress());
                }
            }
        } catch (SocketException | SecurityException ignored) { }
        Collections.sort(addresses);
        return addresses;
    }
    static boolean isAssigned(String address) { return address != null && localPrivateIpv4().contains(address); }
}
