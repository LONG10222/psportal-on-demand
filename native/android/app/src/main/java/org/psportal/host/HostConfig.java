// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;
import java.util.List;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;

/** UI-side validation; the native engine independently validates every configuration. */
public final class HostConfig {
    public final String listenHost, portalHost, subscriptionUrl, selectionMode, preferredNode, routingMode;
    public final int listenPort, idleSeconds, switchThresholdMs;
    public final List<String> allowedClients;
    public final boolean lanEnabled, phoneVpn;

    public HostConfig(String listenHost, String portalHost, String listenPort,
                      String subscriptionUrl, String selectionMode, String preferredNode,
                      String idleSeconds) {
        this(listenHost, Collections.singletonList(portalHost.trim()), listenPort,
                subscriptionUrl, selectionMode, preferredNode, idleSeconds);
    }

    public HostConfig(String listenHost, List<String> allowedClients, String listenPort,
                      String subscriptionUrl, String selectionMode, String preferredNode,
                      String idleSeconds) {
        this(listenHost, allowedClients, listenPort, subscriptionUrl, selectionMode, preferredNode, idleSeconds, 50);
    }
    public HostConfig(String listenHost, List<String> allowedClients, String listenPort,
                      String subscriptionUrl, String selectionMode, String preferredNode,
                      String idleSeconds, int switchThresholdMs) {
        this(listenHost, allowedClients, listenPort, subscriptionUrl, selectionMode,
                preferredNode, idleSeconds, switchThresholdMs, "rule");
    }
    public HostConfig(String listenHost, List<String> allowedClients, String listenPort,
                      String subscriptionUrl, String selectionMode, String preferredNode,
                      String idleSeconds, int switchThresholdMs, String routingMode) {
        this(listenHost, allowedClients, listenPort, subscriptionUrl, selectionMode,
                preferredNode, idleSeconds, switchThresholdMs, routingMode, true);
    }
    public HostConfig(String listenHost, List<String> allowedClients, String listenPort,
                      String subscriptionUrl, String selectionMode, String preferredNode,
                      String idleSeconds, int switchThresholdMs, String routingMode, boolean lanEnabled) {
        this(listenHost, allowedClients, listenPort, subscriptionUrl, selectionMode,
                preferredNode, idleSeconds, switchThresholdMs, routingMode, lanEnabled, false);
    }
    public HostConfig(String listenHost, List<String> allowedClients, String listenPort,
                      String subscriptionUrl, String selectionMode, String preferredNode,
                      String idleSeconds, int switchThresholdMs, String routingMode, boolean lanEnabled, boolean phoneVpn) {
        if (!lanEnabled && !phoneVpn) throw new IllegalArgumentException("Select LAN sharing or phone-app VPN");
        this.lanEnabled = lanEnabled; this.phoneVpn = phoneVpn;
        if (!java.util.Arrays.asList("rule", "global", "direct").contains(routingMode))
            throw new IllegalArgumentException("Invalid routing mode");
        this.routingMode = routingMode;
        if (switchThresholdMs < 0 || switchThresholdMs > 60000) throw new IllegalArgumentException("Invalid switch threshold");
        this.switchThresholdMs = switchThresholdMs;
        this.listenHost = listenHost.trim();
        if (allowedClients == null || allowedClients.size() > 253 || lanEnabled && allowedClients.isEmpty())
            throw new IllegalArgumentException("Enter 1–253 explicit private client addresses");
        if (!lanEnabled && (!this.listenHost.isEmpty() || !allowedClients.isEmpty()))
            throw new IllegalArgumentException("VPN-only mode cannot include a LAN listener or clients");
        LinkedHashSet<String> unique = new LinkedHashSet<>();
        for (String client : allowedClients) {
            if (client == null || !isPrivateIpv4(client.trim()) || this.listenHost.equals(client.trim()))
                throw new IllegalArgumentException("Enter client private IPv4 addresses different from this phone");
            unique.add(client.trim());
        }
        this.allowedClients = Collections.unmodifiableList(new ArrayList<>(unique));
        this.portalHost = this.allowedClients.isEmpty() ? "" : this.allowedClients.get(0); // Existing single-client integration remains supported.
        this.subscriptionUrl = subscriptionUrl.trim();
        this.selectionMode = selectionMode;
        this.preferredNode = preferredNode.trim();
        this.listenPort = number(listenPort, 1024, 65535, "Proxy port must be 1024–65535");
        this.idleSeconds = number(idleSeconds, 1, 86400, "Idle seconds must be 1–86400");
        if (lanEnabled && !isPrivateIpv4(this.listenHost)) throw new IllegalArgumentException("Enter this phone's specific private IPv4 address");
        if (lanEnabled && !isPrivateIpv4(this.portalHost)) throw new IllegalArgumentException("Enter the Portal's specific private IPv4 address");
        if (lanEnabled && this.listenHost.equals(this.portalHost)) throw new IllegalArgumentException("Phone and Portal addresses must differ");
        if (this.listenPort == 10082 || this.listenPort == 10090) throw new IllegalArgumentException("Use a proxy port other than 10082 or 10090");
        validateSubscription(this.subscriptionUrl);
        if (!selectionMode.equals("auto") && !selectionMode.equals("prefer") && !selectionMode.equals("fixed") && !selectionMode.equals("fastest")) {
            throw new IllegalArgumentException("Invalid selection mode");
        }
        if ((selectionMode.equals("prefer") || selectionMode.equals("fixed")) && this.preferredNode.isEmpty()) throw new IllegalArgumentException("Enter an exact node name for this mode");
        String reserved = this.preferredNode.replaceAll("[\\s_-]", "").toLowerCase(Locale.ROOT);
        if (this.preferredNode.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 256 || hasControl(this.preferredNode) || this.preferredNode.contains("`") ||
                java.util.Arrays.asList("direct", "reject", "rejectdrop", "compatible", "pass", "dns", "global", "portal", "auto", "rematch", "passrule").contains(reserved)) {
            throw new IllegalArgumentException("Invalid or reserved node name");
        }
    }

    private static int number(String text, int minimum, int maximum, String error) {
        try {
            String value = text.trim();
            if (!value.matches("[0-9]{1,5}")) throw new NumberFormatException();
            int result = Integer.parseInt(value);
            if (result < minimum || result > maximum) throw new NumberFormatException();
            return result;
        } catch (NumberFormatException e) { throw new IllegalArgumentException(error); }
    }

    public static boolean isPrivateIpv4(String text) {
        String[] octets = text.split("\\.", -1);
        if (octets.length != 4) return false;
        int[] n = new int[4];
        for (int i = 0; i < 4; i++) {
            if (!octets[i].matches("0|[1-9][0-9]{0,2}")) return false;
            n[i] = Integer.parseInt(octets[i]);
            if (n[i] > 255) return false;
        }
        return n[0] == 10 || n[0] == 172 && n[1] >= 16 && n[1] <= 31 || n[0] == 192 && n[1] == 168;
    }

    private static boolean hasControl(String value) {
        for (int i = 0; i < value.length(); i++) if ((Character.isISOControl(value.charAt(i)) || Character.getType(value.charAt(i)) == Character.FORMAT)) return true;
        return false;
    }

    private static void validateSubscription(String value) {
        try {
            URI uri = new URI(value);
            if (value.length() > 8192 || hasControl(value) || !"https".equalsIgnoreCase(uri.getScheme()) ||
                    uri.getHost() == null || uri.getRawUserInfo() != null || uri.getRawFragment() != null ||
                    (uri.getPort() != -1 && uri.getPort() != 443)) throw new URISyntaxException("", "Invalid");
        } catch (URISyntaxException e) { throw new IllegalArgumentException("Subscription must be a public HTTPS URL on port 443, without user info or a fragment"); }
    }

    static String quote(String value) {
        StringBuilder result = new StringBuilder("\"");
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c == '"' || c == '\\') result.append('\\').append(c);
            else if (c < 0x20 || Character.isSurrogate(c)) result.append(String.format(Locale.ROOT, "\\u%04x", (int)c));
            else result.append(c);
        }
        return result.append('"').toString();
    }

    public String toJson(String appPrivateDataDirectory) {
        StringBuilder clients = new StringBuilder();
        for (String client : allowedClients) {
            if (clients.length() > 0) clients.append(',');
            clients.append(quote(client));
        }
        return "{\"lan_enabled\":" + lanEnabled + ",\"phone_vpn\":" + phoneVpn + ",\"listen_host\":" + quote(listenHost) + ",\"listen_port\":" + listenPort +
                ",\"allowed_clients\":[" + clients + "],\"subscription_url\":" + quote(subscriptionUrl) +
                ",\"routing_mode\":" + quote(routingMode) + ",\"selection_mode\":" + quote(selectionMode) + ",\"preferred_node\":" + quote(preferredNode) +
                ",\"switch_threshold_ms\":" + switchThresholdMs +
                ",\"idle_seconds\":" + idleSeconds + ",\"backend_port\":10082,\"api_port\":10090,\"data_dir\":" +
                quote(appPrivateDataDirectory) + "}";
    }
}
