// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.InterfaceAddress;
import java.net.SocketException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

final class NetworkAddresses {
    static final class LocalAddress {
        final String address, interfaceName;
        final int prefix;
        LocalAddress(String address, String interfaceName, int prefix) {
            this.address = address; this.interfaceName = interfaceName; this.prefix = prefix;
        }
    }
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

    static List<LocalAddress> automaticAddresses() {
        List<LocalAddress> addresses = new ArrayList<>();
        try {
            java.util.Enumeration<NetworkInterface> all = NetworkInterface.getNetworkInterfaces();
            if (all == null) return addresses;
            for (NetworkInterface network : Collections.list(all)) {
                if (!network.isUp() || network.isLoopback() || network.isVirtual() || !LanSetup.safeInterface(network.getName())) continue;
                for (InterfaceAddress entry : network.getInterfaceAddresses()) {
                    InetAddress address = entry.getAddress();
                    if (!(address instanceof Inet4Address) || !HostConfig.isPrivateIpv4(address.getHostAddress())) continue;
                    try {
                        LanSetup.clients(address.getHostAddress(), entry.getNetworkPrefixLength());
                        addresses.add(new LocalAddress(address.getHostAddress(), network.getName(), entry.getNetworkPrefixLength()));
                    } catch (IllegalArgumentException unsupported) { /* Explicit manual configuration remains available. */ }
                }
            }
        } catch (SocketException | SecurityException ignored) { }
        addresses.sort((a, b) -> a.address.compareTo(b.address));
        return addresses;
    }
}
