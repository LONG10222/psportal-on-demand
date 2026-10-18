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
    private static final class Engine implements SessionController.Engine {
        final List<String> calls = new ArrayList<>();
        boolean failStart, failStop, failStatus;
        Runnable duringStart;
        @Override public void start(String config) throws Exception {
            calls.add("start"); if (duringStart != null) duringStart.run();
            if (failStart) throw new Exception("https://secret.example/private-token");
        }
        @Override public void stop() throws Exception { calls.add("stop"); if (failStop) throw new Exception("secret"); }
        @Override public String status() throws Exception { calls.add("status"); if (failStatus) throw new Exception("secret"); return "{\"running\":true,\"state\":\"stopped\"}"; }
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
    public static void main(String[] args) {
        configTests(); lifecycleTests(); System.out.println("PASS: " + assertions + " Android host config/lifecycle assertions (JVM only)");
    }
}
