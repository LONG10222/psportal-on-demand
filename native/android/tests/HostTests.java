// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;

/** Host-side unit tests. Fake engine tests ownership only; they do not prove Android or native runtime. */
public final class HostTests {
    private static int assertions;
    private static void check(boolean value, String message) { assertions++; if (!value) throw new AssertionError(message); }
    private static void rejects(Runnable action) {
        try { action.run(); } catch (IllegalArgumentException expected) { assertions++; return; }
        throw new AssertionError("Invalid configuration accepted");
    }
    private static HostConfig config(String phone, String portal, String port, String url, String mode, String node, String idle) {
        return new HostConfig(phone, portal, port, url, mode, node, idle);
    }
    private static void configTests() {
        for (String ip : new String[] {"10.0.0.1", "172.16.0.1", "172.31.255.254", "192.168.1.2"}) check(HostConfig.isPrivateIpv4(ip), ip);
        for (String ip : new String[] {"127.0.0.1", "0.0.0.0", "172.15.0.1", "172.32.0.1", "192.169.1.2", "169.254.1.1", "8.8.8.8", "192.168.01.1", "10.0.0.256", "10.0.0.1\n", "10.0.1", "::1", "10.0.0.-1", ""}) check(!HostConfig.isPrivateIpv4(ip), ip);
        HostConfig valid = config("192.168.1.2", "192.168.1.30", "10081", "https://example.com/token?auth=secret", "auto", "", "60");
        String json = valid.toJson("/data/user/0/org.psportal.host/files/runtime");
        check(json.contains("\"allowed_clients\":[\"192.168.1.30\"]"), "Client allowlist is explicit");
        check(!json.contains("core_path"), "No executable path");
        check(valid.lanEnabled && !valid.phoneVpn && json.contains("\"lan_enabled\":true") && json.contains("\"phone_vpn\":false"), "Default shares LAN only without phone VPN");
        HostConfig vpnOnly = new HostConfig("", java.util.Collections.emptyList(), "10081", "https://example.com/", "auto", "", "60", 50, "rule", false, true);
        check(!vpnOnly.lanEnabled && vpnOnly.phoneVpn && vpnOnly.allowedClients.isEmpty() && vpnOnly.listenHost.isEmpty(), "VPN-only needs no LAN address or client allowlist");
        check(vpnOnly.toJson("/private/runtime").contains("\"lan_enabled\":false,\"phone_vpn\":true"), "VPN-only explicitly disables LAN listener");
        HostConfig combined = new HostConfig("10.0.0.1", java.util.Arrays.asList("10.0.0.2"), "10081", "https://example.com/", "auto", "", "60", 50, "global", true, true);
        check(combined.lanEnabled && combined.phoneVpn, "LAN and phone VPN can both be selected");
        rejects(() -> new HostConfig("", java.util.Collections.emptyList(), "10081", "https://example.com/", "auto", "", "60", 50, "rule", false, false));
        rejects(() -> new HostConfig("10.0.0.1", java.util.Collections.emptyList(), "10081", "https://example.com/", "auto", "", "60", 50, "rule", false, true));
        rejects(() -> new HostConfig("", java.util.Arrays.asList("10.0.0.2"), "10081", "https://example.com/", "auto", "", "60", 50, "rule", false, true));
        check(valid.routingMode.equals("rule") && json.contains("\"routing_mode\":\"rule\""), "Existing constructors default to explicit rule routing");
        for (String routing : new String[]{"rule", "global", "direct"}) {
            HostConfig routed = new HostConfig("10.0.0.1", java.util.Arrays.asList("10.0.0.2"), "10081", "https://example.com/", "fixed", "香港 A", "60", 75, routing);
            check(routed.routingMode.equals(routing) && routed.toJson("/private/runtime").contains("\"routing_mode\":" + HostConfig.quote(routing)), "Serialize exact routing mode " + routing);
            check(routed.selectionMode.equals("fixed") && routed.preferredNode.equals("香港 A") && routed.switchThresholdMs == 75, "Routing remains independent from node policy " + routing);
            check(!routed.toJson("/private/runtime").contains("background_sharing"), "Background sharing is an Android service policy");
        }
        for (String routing : new String[]{"", "RULE", "rules", "global ", "auto", "direct\n"})
            rejects(() -> new HostConfig("10.0.0.1", java.util.Arrays.asList("10.0.0.2"), "10081", "https://example.com/", "auto", "", "60", 50, routing));
        rejects(() -> new HostConfig("10.0.0.1", java.util.Arrays.asList("10.0.0.2"), "10081", "https://example.com/", "auto", "", "60", 50, null));
        rejects(() -> new HostConfig("10.0.0.1", java.util.Arrays.asList("10.0.0.2"), "10081", "", "auto", "", "60", 50, "direct"));
        check(json.contains("\"idle_seconds\":60"), "Correct idle");
        check(HostConfig.quote("x\"y\\z\n😀").equals("\"x\\\"y\\\\z\\u000a\\ud83d\\ude00\""), "JSON escaping");
        for (String ip : new String[] {"0.0.0.0", "127.0.0.1", "8.8.8.8", "192.168.1.30"}) rejects(() -> config(ip, "192.168.1.30", "10081", "https://example.com/", "auto", "", "60"));
        for (String port : new String[] {"0", "80", "65536", "10082", "10090", "999999999999", "1.5", "-1", ""}) rejects(() -> config("10.0.0.1", "10.0.0.2", port, "https://example.com/", "auto", "", "60"));
        for (String url : new String[] {"http://example.com/", "https://user:pass@example.com/", "https://example.com/#token", "https://", "https://example.com/\nsecret", "https://example.com:65536/", "https://example.com:8443/", "file:///tmp/token"}) rejects(() -> config("10.0.0.1", "10.0.0.2", "10081", url, "auto", "", "60"));
        for (String mode : new String[] {"prefer", "fixed", "unknown"}) rejects(() -> config("10.0.0.1", "10.0.0.2", "10081", "https://example.com/", mode, "", "60"));
        for (String node : new String[] {"DIRECT", "re-ject", "REJECT_DROP", "pass", "auto", "my`node", "my\nnode", "REMatch", "PassRule", "my\u200bnode"}) rejects(() -> config("10.0.0.1", "10.0.0.2", "10081", "https://example.com/", "fixed", node, "60"));
        check(config("10.0.0.1", "10.0.0.2", "65535", "https://example.com/", "fixed", "香港 A", "86400").selectionMode.equals("fixed"), "Fixed exact name");
        rejects(() -> config("10.0.0.1", "10.0.0.2", "10081", "https://example.com/", "auto", "", "0"));
        rejects(() -> config("10.0.0.1", "10.0.0.2", "10081", "https://example.com/", "auto", "", "86401"));
    }
    private static final class Queue implements Executor {
        final ArrayDeque<Runnable> tasks = new ArrayDeque<>();
        @Override public void execute(Runnable task) { tasks.add(task); }
        void one() { tasks.remove().run(); }
        void drain() { while (!tasks.isEmpty()) one(); }
    }
    private static void simpleHomeTests() {
        List<String> clients = LanSetup.clients("192.168.1.2", 24);
        check(clients.size() == 253, "Bound /24 allowlist to 253 distinct clients");
        check(!clients.contains("192.168.1.2") && !clients.contains("192.168.1.0") && !clients.contains("192.168.1.255"), "Exclude self, network and broadcast");
        check(LanSetup.clients("10.0.0.1", 30).equals(java.util.Arrays.asList("10.0.0.2")), "Use actual /30 mask");
        for (int prefix : new int[]{0, 16, 23, 31, 32}) rejects(() -> LanSetup.clients("10.0.0.1", prefix));
        for (String ip : new String[]{"8.8.8.8", "127.0.0.1", "192.168.1.0", "192.168.1.255"}) rejects(() -> LanSetup.clients(ip, 24));
        for (String name : new String[]{"wlan0", "wifi0", "eth1", "en0"}) check(LanSetup.safeInterface(name), "Physical interface " + name);
        for (String name : new String[]{"tun0", "utun4", "wg0", "rmnet0", "dummy0", "docker0", "bridge0", "lo"}) check(!LanSetup.safeInterface(name), "Exclude virtual/cellular " + name);
        try {
            check(LanSetup.choosePort("192.168.1.2", 10081, (host, port) -> true) == 10081, "Keep default when free");
            check(LanSetup.choosePort("192.168.1.2", 10081, (host, port) -> port != 10081) == 10083, "Skip reserved backend port on conflict");
            check(LanSetup.choosePort("192.168.1.2", 23456, (host, port) -> true) == 23456, "Keep explicit available preference");
            try { LanSetup.choosePort("192.168.1.2", 10081, (host, port) -> false); throw new AssertionError("No free port accepted"); }
            catch (java.io.IOException expected) { assertions++; }
        } catch (java.io.IOException failure) { throw new AssertionError(failure); }
        HostConfig auto = new HostConfig("192.168.1.2", clients, "10081", "https://example.com/", "auto", "", "60");
        check(auto.allowedClients.size() == 253 && auto.toJson("/private/runtime").contains("\"192.168.1.254\""), "Explicit subnet serialized to native config");
        check(new HostConfig("10.0.0.1", java.util.Arrays.asList("10.0.0.2", "10.0.0.2"), "10081", "https://example.com/", "auto", "", "60").allowedClients.size() == 1, "Deduplicate explicit clients");
        rejects(() -> new HostConfig("10.0.0.1", new ArrayList<>(), "10081", "https://example.com/", "auto", "", "60"));
        rejects(() -> new HostConfig("10.0.0.1", java.util.Arrays.asList("10.0.0.1"), "10081", "https://example.com/", "auto", "", "60"));
        SubscriptionAccounting unknown = new SubscriptionAccounting("", "", "", "");
        check(unknown.used == null && unknown.total == null && unknown.remaining == null && unknown.expires == null && unknown.percent() == -1, "Missing accounting stays unknown");
        SubscriptionAccounting known = new SubscriptionAccounting("1024", "3072", "8192", "2000000000");
        check(known.used == 4096 && known.remaining == 4096 && known.percent() == 50, "Real header arithmetic");
        check(SubscriptionAccounting.bytes(known.used, "missing", java.util.Locale.ENGLISH).equals("4.00 KiB"), "Binary accounting units");
        check(new SubscriptionAccounting("100", "200", "150", "0").remaining == 0, "Overage clamps only remaining");
        check(new SubscriptionAccounting("100", "200", "150", "0").percent() == 100, "Overage progress capped");
        check(new SubscriptionAccounting("100", "", "150", "253402300800").used == null, "Partial use stays unknown");
        check(new SubscriptionAccounting("100", "200", "0", "253402300800").total == null, "Zero total is not unlimited");
        check(new SubscriptionAccounting("9223372036854775807", "1", "-1", "999999999999999999999999").used == null, "Overflow accounting unknown");
        check(new SubscriptionAccounting("NaN", "1", "100", "253402300800").expires == null, "Reject out-of-range expiry");
        check(RuntimePresentation.settingLabel("dns", false).equals("DNS"), "Known overridden DNS key uses a local label");
        check(RuntimePresentation.settingLabel("hosts", true).equals("Hosts mappings"), "Known hosts override is explicit");
        for (String unsafe : new String[]{"https://secret.example/token", "secret-value", "dns\nsecret", "\u202esecret"})
            check(RuntimePresentation.settingLabel(unsafe, true).equals("Other settings"), "Unknown keys never echo upstream strings");
        check(RuntimePresentation.settingLabel(null, false).equals("其他设置"), "Missing setting labels stay safe");
        for (String code : new String[]{"profile_unsupported", "profile_selection_required", "profile_invalid", "download_failed"})
            check(!RuntimePresentation.profileError(code, false).isEmpty() && !RuntimePresentation.profileError(code, true).isEmpty(), "Known safe profile error is localized " + code);
        check(RuntimePresentation.profileError("https://secret.example/token", true).isEmpty(), "Unknown error never exposes raw native text");
        check(RuntimePresentation.profileError(null, false).isEmpty(), "Missing error code stays absent");
        SessionController.Phase run = SessionController.Phase.RUNNING;
        check(RuntimePresentation.state(run, false, true, "stopped", 0L, false) == RuntimePresentation.State.LISTENING, "Idle core does not imply stopped listener");
        check(RuntimePresentation.state(run, false, true, "starting", 0L, false) == RuntimePresentation.State.WAKING, "Real waking state");
        check(RuntimePresentation.state(run, false, true, "running", 2L, false) == RuntimePresentation.State.FORWARDING, "Real forwarding count");
        check(RuntimePresentation.state(run, false, true, "listening", 0L, false) == RuntimePresentation.State.LISTENING, "Additive service state");
        check(RuntimePresentation.state(run, false, true, "running", 0L, false) == RuntimePresentation.State.READY, "Warm idle core");
        check(RuntimePresentation.state(run, false, null, "", null, false) == RuntimePresentation.State.UNKNOWN, "Unavailable is not zero or ready");
        check(RuntimePresentation.state(run, false, true, "running", 1L, true) == RuntimePresentation.State.ERROR, "Native failure stays visible");
        check(RuntimePresentation.state(SessionController.Phase.STOPPED, true, null, "", null, false) == RuntimePresentation.State.PREPARING, "Preparation precedes listening");
        check(RuntimePresentation.state(SessionController.Phase.STOPPED, false, null, "", null, false) == RuntimePresentation.State.STOPPED, "Canceled preparation stays stopped");
    }
    private static final class Engine implements SessionController.Engine {
        final List<String> calls = new ArrayList<>();
        boolean failStart, failStop, failStatus, failCommand;
        String nativeStatus = "{\"running\":true,\"state\":\"stopped\"}";
        Runnable duringStart, duringCommand;
        @Override public void start(String config) throws Exception {
            calls.add("start"); if (duringStart != null) duringStart.run();
            if (failStart) throw new Exception("https://secret.example/private-token");
        }
        @Override public void stop() throws Exception { calls.add("stop"); if (failStop) throw new Exception("secret"); }
        @Override public String status() throws Exception { calls.add("status"); if (failStatus) throw new Exception("secret"); return nativeStatus; }
        @Override public void prepare() throws Exception {
            calls.add("prepare"); if (duringCommand != null) duringCommand.run();
            if (failCommand) throw new Exception("https://secret.example/token");
        }
        @Override public void testNodes() throws Exception { calls.add("test"); if (failCommand) throw new Exception("secret"); }
        @Override public void selectNode(String mode, String name, int threshold) throws Exception { calls.add("select:" + mode + ":" + threshold); if (failCommand) throw new Exception("secret"); }
    }
    private static final class Fixture {
        final Engine engine = new Engine();
        final Queue work = new Queue(), callbacks = new Queue();
        final SessionController session = new SessionController(engine, work, callbacks);
        int completed;
        final Runnable done = () -> completed++;
    }
    private static void lifecycleTests() {
        Fixture f = new Fixture();
        check(f.session.start("{}", f.done), "First start accepted");
        check(!f.session.start("{}", f.done), "Double start rejected");
        check(f.engine.calls.isEmpty(), "Native work off calling thread");
        check(f.session.snapshot().phase == SessionController.Phase.STARTING, "Starting transition");
        f.work.drain(); f.callbacks.drain();
        check(f.session.snapshot().phase == SessionController.Phase.RUNNING && f.completed == 1, "Started once");
        f.session.refresh(); f.session.refresh(); check(f.work.tasks.size() == 1, "Refresh coalesced");
        f.work.drain(); check(f.session.snapshot().nativeStatus.contains("running"), "Status refreshed");
        f.session.stop(f.done); f.session.stop(f.done);
        check(!f.session.start("{}", f.done), "No start during stop");
        check(f.session.snapshot().phase == SessionController.Phase.STOPPING, "Stopping transition");
        f.work.drain(); f.callbacks.drain();
        check(f.session.snapshot().phase == SessionController.Phase.STOPPED, "Stopped");
        check(f.engine.calls.equals(java.util.Arrays.asList("start", "status", "stop")), "Single native owner");
        check(f.completed == 3, "Both stop waiters complete");
        check(f.session.start("{}", f.done), "Restart after full stop"); f.work.drain();
        check(f.engine.calls.get(3).equals("start"), "Restart ordered after stop");

        Fixture canceled = new Fixture();
        canceled.session.start("{}", canceled.done); canceled.session.stop(canceled.done); canceled.work.drain(); canceled.callbacks.drain();
        check(canceled.engine.calls.equals(java.util.Arrays.asList("stop")), "Canceled queued start never opens listener");
        check(canceled.session.snapshot().phase == SessionController.Phase.STOPPED, "Cancel finishes stopped");

        Fixture during = new Fixture();
        during.engine.duringStart = () -> during.session.stop(during.done);
        during.session.start("{}", during.done); during.work.one();
        check(during.session.snapshot().phase == SessionController.Phase.STOPPING, "Stop during native start preserved");
        during.work.drain(); check(during.engine.calls.equals(java.util.Arrays.asList("start", "stop")), "Stop follows in-progress start");

        Fixture stale = new Fixture(); stale.session.start("{}", stale.done); stale.work.drain();
        stale.session.refresh(); stale.session.stop(stale.done); stale.work.one();
        check(stale.session.snapshot().phase == SessionController.Phase.STOPPING, "Stale status cannot resurrect running");
        stale.work.drain(); check(stale.session.snapshot().nativeStatus.equals("{}"), "Status cleared after stop");

        Fixture failed = new Fixture(); failed.engine.failStart = true;
        failed.session.start("secret", failed.done); failed.work.drain();
        check(failed.session.snapshot().phase == SessionController.Phase.ERROR, "Start error visible");
        check(!failed.session.snapshot().error.contains("secret"), "Exception secrets redacted");
        check(failed.engine.calls.equals(java.util.Arrays.asList("start", "stop")), "Failed start cleaned up");
        failed.engine.failStart = false; check(failed.session.start("{}", failed.done), "Retry after cleanup permitted"); failed.work.drain();
        failed.engine.failStop = true; failed.session.stop(failed.done); failed.work.drain();
        check(failed.session.snapshot().phase == SessionController.Phase.FAULTED, "Failed stop is terminal");
        check(!failed.session.start("{}", failed.done), "Never reuse failed native cleanup");

        Fixture status = new Fixture(); status.engine.failStatus = true; status.session.start("{}", status.done); status.work.drain();
        status.session.refresh(); status.work.drain(); check(status.session.snapshot().nativeStatus.equals("{}"), "Status exception redacted");
        Fixture rejected = new Fixture(); rejected.session.rejectedStart();
        check(rejected.session.snapshot().phase == SessionController.Phase.ERROR, "Platform denial visible");
        check(rejected.session.start("{}", rejected.done), "Platform denial is retryable"); rejected.work.drain();
        rejected.session.rejectedStart(); check(rejected.session.snapshot().phase == SessionController.Phase.RUNNING, "Late rejection cannot overwrite running state");
        Fixture stopped = new Fixture(); stopped.session.stop(stopped.done); stopped.callbacks.drain();
        check(stopped.completed == 1 && stopped.engine.calls.isEmpty(), "Stop without start is idempotent");
    }
    private static void nodeControlTests() {
        Engine engine = new Engine(); Queue owner = new Queue(), probes = new Queue(), callbacks = new Queue();
        SessionController session = new SessionController(engine, owner, callbacks, probes);
        check(!session.control("prepare", "", "", 50), "No node work before listener");
        session.start("{}", () -> {}); owner.drain(); callbacks.drain();
        check(session.control("prepare", "", "", 50), "Accept node preparation");
        check(session.commandPending() && !session.control("test", "", "", 50), "Coalesce repeated node actions");
        check(owner.tasks.isEmpty() && probes.tasks.size() == 1, "Probe lane does not block native owner");
        probes.drain(); check(!session.commandPending() && !session.commandFailed(), "Probe completion");
        check(session.control("select", "fastest", "", 80), "Live selection accepted"); probes.drain();
        check(engine.calls.contains("select:fastest:80"), "Pass exact live threshold");
        engine.failCommand = true; session.control("test", "", "", 50); probes.drain();
        check(session.commandFailed() && session.snapshot().phase == SessionController.Phase.RUNNING, "Failed node action does not discard listener ownership");
        check(session.snapshot().error.isEmpty(), "Node exception text never exposed"); engine.failCommand = false;
        session.control("prepare", "", "", 50); session.stop(() -> {}); owner.drain();
        check(session.snapshot().phase == SessionController.Phase.STOPPING, "Stop waits for queued probe retirement");
        check(!session.start("{}", () -> {}), "No stale probe can touch a new session");
        int calls = engine.calls.size(); probes.drain();
        check(engine.calls.size() == calls, "Canceled queued probe never reaches native");
        check(session.snapshot().phase == SessionController.Phase.STOPPED && !session.commandFailed(), "Both lanes finish before restart");
        session.start("{}", () -> {}); owner.drain();
        engine.duringCommand = () -> {
            session.stop(() -> {}); owner.drain();
            check(engine.calls.get(engine.calls.size()-1).equals("stop"), "Native Stop runs during probe");
            check(session.snapshot().phase == SessionController.Phase.STOPPING, "In-flight old probe still protects restart");
        };
        session.control("prepare", "", "", 50); probes.drain();
        check(session.snapshot().phase == SessionController.Phase.STOPPED, "Stop during probe retires safely");
        check(session.start("{}", () -> {}), "Restart allowed after full command teardown"); owner.drain();
        check(!session.control("unknown", "", "", 50), "Reject unknown commands");
        check(new HostConfig("10.0.0.1", java.util.Arrays.asList("10.0.0.2"), "10081", "https://example.com/", "fastest", "", "60", 75).toJson("/private/runtime").contains("\"switch_threshold_ms\":75"), "Fastest config carries threshold");
        rejects(() -> new HostConfig("10.0.0.1", java.util.Arrays.asList("10.0.0.2"), "10081", "https://example.com/", "fastest", "", "60", -1));
    }
    private static void startCompletionIdentityTests() {
        // Android assigns a new startId even when the active session rejects a
        // duplicate Start. The original completion must still run exactly once.
        Fixture duplicate = new Fixture();
        int[] latestStartId = {11}, launched = {0}, launchStartId = {0};
        check(duplicate.session.start("first", () -> {
            if (duplicate.session.snapshot().phase == SessionController.Phase.RUNNING) {
                launched[0]++; launchStartId[0] = latestStartId[0];
            }
        }), "Accept initial phone startup");
        latestStartId[0] = 12;
        check(!duplicate.session.start("duplicate", () -> { throw new AssertionError("Duplicate startup completed"); }), "Reject duplicate during native startup");
        duplicate.work.drain();
        latestStartId[0] = 13;
        check(!duplicate.session.start("duplicate", () -> { throw new AssertionError("Duplicate startup completed"); }), "Reject duplicate while original callback is queued");
        duplicate.callbacks.drain();
        check(launched[0] == 1 && launchStartId[0] == 13, "Same-session completion survives duplicate framework start IDs");
        check(duplicate.engine.calls.equals(java.util.Arrays.asList("start")), "Duplicate start never replaces native configuration");

        Fixture failed = new Fixture(); failed.engine.failStart = true;
        int[] failedStartId = {21}, cleanedStartId = {0}, cleanups = {0};
        failed.session.start("first", () -> {
            if (!failed.session.snapshot().isActive()) {
                cleanups[0]++; cleanedStartId[0] = failedStartId[0];
            }
        });
        failedStartId[0] = 22;
        check(!failed.session.start("duplicate", () -> {}), "Failed startup still rejects an in-flight duplicate");
        failed.work.drain(); failed.callbacks.drain();
        check(cleanups[0] == 1 && cleanedStartId[0] == 22, "Failed same-session startup cleans newest framework start ID");

        Fixture stopped = new Fixture();
        int[] staleStarts = {0}, stops = {0};
        stopped.session.start("first", () -> staleStarts[0]++); stopped.work.drain();
        check(stopped.callbacks.tasks.size() == 1, "Start completion is already queued before Stop");
        stopped.session.stop(() -> stops[0]++); stopped.work.drain(); stopped.callbacks.drain();
        check(staleStarts[0] == 0 && stops[0] == 1, "Stop suppresses queued startup completion at dispatch time");

        Fixture restarted = new Fixture();
        int[] oldStarts = {0}, newStarts = {0}, completedStops = {0};
        restarted.session.start("old", () -> oldStarts[0]++); restarted.work.drain();
        restarted.session.stop(() -> completedStops[0]++); restarted.work.drain();
        check(restarted.session.start("new", () -> newStarts[0]++), "Restart accepted after native teardown before callback drain");
        restarted.work.drain(); restarted.callbacks.drain();
        check(oldStarts[0] == 0 && newStarts[0] == 1 && completedStops[0] == 1, "Old queued startup cannot launch or stop replacement session");

        Fixture retried = new Fixture(); retried.engine.failStart = true;
        int[] staleFailures = {0}, retryStarts = {0};
        retried.session.start("failed", () -> staleFailures[0]++); retried.work.drain();
        retried.engine.failStart = false;
        check(retried.session.start("retry", () -> retryStarts[0]++), "Retry accepted before old failure callback is delivered");
        retried.work.drain(); retried.callbacks.drain();
        check(staleFailures[0] == 0 && retryStarts[0] == 1, "Old failure callback cannot clean up a successful retry");

        Fixture during = new Fixture();
        int[] interruptedStart = {0}, interruptedStop = {0};
        during.engine.duringStart = () -> during.session.stop(() -> interruptedStop[0]++);
        during.session.start("first", () -> interruptedStart[0]++);
        during.work.drain(); during.callbacks.drain();
        check(interruptedStart[0] == 0 && interruptedStop[0] == 1, "Stop during native startup retires its completion");
    }
    private static void statusSizeTests() {
        Fixture fixture = new Fixture(); fixture.session.start("{}", fixture.done); fixture.work.drain();
        StringBuilder json = new StringBuilder("{\"running\":true,\"state\":\"listening\",\"connected_clients\":2,\"active_connections\":4,\"node_management\":true,\"nodes\":[");
        String name = "x".repeat(250);
        for (int i = 0; i < 1000; i++) {
            if (i > 0) json.append(',');
            json.append("{\"name\":\"").append(name).append(i).append("\",\"healthy\":true,\"delay_ms\":123}");
        }
        json.append("]}"); fixture.engine.nativeStatus = json.toString();
        check(json.length() > 262144 && json.length() < SessionController.MAX_STATUS_CHARACTERS, "Maximum native pool exceeds old status cap but stays bounded");
        fixture.session.refresh(); fixture.work.drain();
        check(fixture.session.snapshot().nativeStatus.equals(json.toString()), "1000 long node names preserve all top-level state and metrics");
        check(fixture.session.snapshot().nativeStatus.contains("\"node_management\":true"), "Maximum pool keeps live controls available");
        StringBuilder escaped = new StringBuilder("{\"running\":true,\"state\":\"listening\",\"node_management\":true,\"nodes\":[");
        for (int i = 0; i < 1000; i++) {
            if (i > 0) escaped.append(',');
            escaped.append("{\"name\":").append(HostConfig.quote("\\\"".repeat(125) + i)).append(",\"healthy\":true,\"delay_ms\":123}");
        }
        escaped.append("]}");
        check(escaped.length() > json.length() && escaped.length() < SessionController.MAX_STATUS_CHARACTERS, "JSON-escaped maximum names remain below aligned cap");
        fixture.engine.nativeStatus = escaped.toString(); fixture.session.refresh(); fixture.work.drain();
        check(fixture.session.snapshot().nativeStatus.equals(escaped.toString()), "Escape-heavy maximum pool preserves status");
        fixture.engine.nativeStatus = "x".repeat(SessionController.MAX_STATUS_CHARACTERS + 1);
        fixture.session.refresh(); fixture.work.drain();
        check(fixture.session.snapshot().nativeStatus.equals("{}"), "Oversize status remains bounded");
        check(!fixture.session.snapshot().error.isEmpty(), "Oversize status has an explicit safe diagnostic");
        fixture.engine.nativeStatus = null; fixture.session.refresh(); fixture.work.drain();
        check(fixture.session.snapshot().nativeStatus.equals("{}"), "Null status stays unavailable");
    }
    public static void main(String[] args) {
        configTests(); lifecycleTests(); startCompletionIdentityTests(); simpleHomeTests(); nodeControlTests(); statusSizeTests(); System.out.println("PASS: " + assertions + " Android host config/lifecycle/presentation assertions (JVM only)");
    }
}
