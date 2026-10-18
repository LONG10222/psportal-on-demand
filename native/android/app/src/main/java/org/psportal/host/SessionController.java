// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;

/** One process-owned queue: old shutdown cannot race a new native Start. No Android dependencies. */
public final class SessionController {
    public enum Phase { STOPPED, STARTING, RUNNING, STOPPING, ERROR, FAULTED }
    public interface Engine {
        void start(String configJson) throws Exception;
        void stop() throws Exception;
        String status() throws Exception;
    }
    public static final class Snapshot {
        public final Phase phase;
        public final String nativeStatus, error;
        Snapshot(Phase phase, String nativeStatus, String error) {
            this.phase = phase; this.nativeStatus = nativeStatus; this.error = error;
        }
        public boolean canStart() { return phase == Phase.STOPPED || phase == Phase.ERROR; }
        public boolean isActive() { return phase == Phase.STARTING || phase == Phase.RUNNING || phase == Phase.STOPPING; }
    }
    private final Engine engine;
    private final Executor serial, callbacks;
    private final List<Runnable> stopCallbacks = new ArrayList<>();
    private volatile Snapshot snapshot = new Snapshot(Phase.STOPPED, "{}", "");
    private long generation;
    private boolean refreshPending;

    public SessionController(Engine engine, Executor serial, Executor callbacks) {
        this.engine = engine; this.serial = serial; this.callbacks = callbacks;
    }
    public Snapshot snapshot() { return snapshot; }
    public synchronized void rejectedStart() {
        if (snapshot.canStart()) snapshot = new Snapshot(Phase.ERROR, "{}",
                "Android could not start the service. Check notification and local-network permissions, then try again.");
    }

    public synchronized boolean start(String configJson, Runnable completion) {
        if (!snapshot.canStart()) return false;
        long token = ++generation;
        snapshot = new Snapshot(Phase.STARTING, "{}", "");
        serial.execute(() -> {
            synchronized (this) {
                // A stop before the queued start must never briefly open a listener.
                if (token != generation || snapshot.phase != Phase.STARTING) return;
            }
            try {
                engine.start(configJson);
                synchronized (this) {
                    if (token == generation && snapshot.phase == Phase.STARTING)
                        snapshot = new Snapshot(Phase.RUNNING, "{}", "");
                }
            } catch (Exception | LinkageError failure) {
                boolean cleaned = true;
                try { engine.stop(); } catch (Exception | LinkageError ignored) { cleaned = false; }
                synchronized (this) {
                    if (token == generation) snapshot = new Snapshot(cleaned ? Phase.ERROR : Phase.FAULTED, "{}",
                            cleaned ? "Start failed. Check the LAN address, available proxy port, public HTTPS subscription (port 443), and bundled engine." :
                            "Native cleanup failed. Force stop this app before trying again.");
                }
            }
            callbacks.execute(completion);
        });
        return true;
    }

    public synchronized void stop(Runnable completion) {
        if (!snapshot.isActive()) { callbacks.execute(completion); return; }
        stopCallbacks.add(completion);
        if (snapshot.phase == Phase.STOPPING) return;
        ++generation;
        snapshot = new Snapshot(Phase.STOPPING, "{}", "");
        serial.execute(() -> {
            boolean stopped = true;
            try { engine.stop(); } catch (Exception | LinkageError ignored) { stopped = false; }
            List<Runnable> completions;
            synchronized (this) {
                snapshot = new Snapshot(stopped ? Phase.STOPPED : Phase.FAULTED, "{}",
                        stopped ? "" : "Native cleanup failed. Force stop this app before trying again.");
                completions = new ArrayList<>(stopCallbacks);
                stopCallbacks.clear();
            }
            for (Runnable callback : completions) callbacks.execute(callback);
        });
    }

    public synchronized void refresh() {
        if (snapshot.phase != Phase.RUNNING || refreshPending) return;
        refreshPending = true;
        long token = generation;
        serial.execute(() -> {
            String status;
            try { status = engine.status(); }
            catch (Exception | LinkageError ignored) { status = "{}"; }
            synchronized (this) {
                refreshPending = false;
                if (token == generation && snapshot.phase == Phase.RUNNING)
                    snapshot = new Snapshot(Phase.RUNNING, status == null || status.length() > 32768 ? "{}" : status, "");
            }
        });
    }
}
