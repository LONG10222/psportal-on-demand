// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;
import java.util.function.Consumer;

/** Process-owned lifecycle and probe lanes: old work cannot race a new Start. No Android dependencies. */
public final class SessionController {
    // Native permits up to 1000 bounded node names; match the desktop protocol cap.
    static final int MAX_STATUS_CHARACTERS = 1_048_576;
    public enum Phase { STOPPED, STARTING, RUNNING, STOPPING, ERROR, FAULTED }
    public interface Engine {
        void start(String configJson) throws Exception;
        void stop() throws Exception;
        String status() throws Exception;
        default void prepare() throws Exception { throw new UnsupportedOperationException(); }
        default void testNodes() throws Exception { throw new UnsupportedOperationException(); }
        default void selectNode(String mode, String name, int threshold) throws Exception { throw new UnsupportedOperationException(); }
        default String groupChoices(String group) throws Exception { throw new UnsupportedOperationException(); }
        default void selectGroup(String group, String choice) throws Exception { throw new UnsupportedOperationException(); }
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
    private final Executor serial, callbacks, commands;
    private final List<Runnable> stopCallbacks = new ArrayList<>();
    private volatile Snapshot snapshot = new Snapshot(Phase.STOPPED, "{}", "");
    private long generation, commandGeneration;
    private boolean refreshPending;
    private volatile boolean commandPending, commandFailed;
    private boolean teardownFinished, teardownSucceeded;

    public SessionController(Engine engine, Executor serial, Executor callbacks) {
        this(engine, serial, callbacks, serial);
    }
    public SessionController(Engine engine, Executor serial, Executor callbacks, Executor commands) {
        this.engine = engine; this.serial = serial; this.callbacks = callbacks; this.commands = commands;
    }
    public boolean commandPending() { return commandPending; }
    public boolean commandFailed() { return commandFailed; }

    public synchronized long sessionId() { return generation; }
    private interface Command { String run() throws Exception; }

    /** Dialogs retain this session ID, so old choices cannot act after restart. */
    public synchronized boolean control(long sessionId, String action, String mode, String name, int threshold) {
        if (!("prepare".equals(action) || "test".equals(action) || "select".equals(action))) return false;
        return enqueueCommand(sessionId, () -> {
            switch (action) {
                case "prepare": engine.prepare(); break;
                case "test": engine.testNodes(); break;
                default: engine.selectNode(mode, name, threshold);
            }
            return "{}";
        }, null);
    }
    public synchronized boolean control(String action, String mode, String name, int threshold) {
        return control(generation, action, mode, name, threshold);
    }
    public synchronized boolean groupChoices(long sessionId, String group, Consumer<String> completion) {
        if (completion == null) return false;
        return enqueueCommand(sessionId, () -> engine.groupChoices(group), completion);
    }
    public synchronized boolean selectGroup(long sessionId, String group, String choice) {
        return enqueueCommand(sessionId, () -> { engine.selectGroup(group, choice); return "{}"; }, null);
    }

    /** Probe work must not block native Stop. A new session waits for both lanes to retire. */
    private synchronized boolean enqueueCommand(long token, Command command, Consumer<String> completion) {
        if (token != generation || snapshot.phase != Phase.RUNNING || commandPending) return false;
        final long operation = ++commandGeneration;
        commandPending = true; commandFailed = false;
        commands.execute(() -> {
            boolean failed = false;
            String result = "{}";
            try {
                synchronized (this) {
                    if (generation != token || snapshot.phase != Phase.RUNNING) return;
                }
                String received = command.run();
                if (received == null || received.length() > MAX_STATUS_CHARACTERS)
                    throw new IllegalStateException("Invalid command result");
                result = received;
            } catch (Exception | LinkageError failure) { failed = true; }
            finally {
                synchronized (this) {
                    commandPending = false;
                    if (generation == token && snapshot.phase == Phase.RUNNING) commandFailed = failed;
                    finishTeardownIfReady();
                }
            }
            if (completion != null) {
                final String delivered = result;
                callbacks.execute(() -> {
                    synchronized (this) {
                        if (generation == token && commandGeneration == operation && snapshot.phase == Phase.RUNNING)
                            completion.accept(delivered);
                    }
                });
            }
        });
        return true;
    }
    public Snapshot snapshot() { return snapshot; }
    public synchronized void rejectedStart() {
        if (snapshot.canStart()) snapshot = new Snapshot(Phase.ERROR, "{}",
                "Android could not start the service. Check notification and local-network permissions, then try again.");
    }

    public synchronized boolean start(String configJson, Runnable completion) {
        if (!snapshot.canStart()) return false;
        long token = ++generation;
        commandFailed = false;
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
            callbacks.execute(() -> {
                // A Stop/restart can happen after native startup completes but
                // before this callback is dispatched. Duplicate Start commands
                // leave the generation unchanged and must retain this callback.
                synchronized (this) {
                    if (token == generation) completion.run();
                }
            });
        });
        return true;
    }

    public synchronized void stop(Runnable completion) {
        if (!snapshot.isActive()) { callbacks.execute(completion); return; }
        stopCallbacks.add(completion);
        if (snapshot.phase == Phase.STOPPING) return;
        ++generation;
        commandFailed = false; teardownFinished = false;
        snapshot = new Snapshot(Phase.STOPPING, "{}", "");
        serial.execute(() -> {
            boolean stopped = true;
            try { engine.stop(); } catch (Exception | LinkageError ignored) { stopped = false; }
            synchronized (this) {
                teardownSucceeded = stopped; teardownFinished = true;
                finishTeardownIfReady();
            }
        });
    }

    private void finishTeardownIfReady() {
        if (snapshot.phase != Phase.STOPPING || !teardownFinished || commandPending) return;
        snapshot = new Snapshot(teardownSucceeded ? Phase.STOPPED : Phase.FAULTED, "{}",
                teardownSucceeded ? "" : "Native cleanup failed. Force stop this app before trying again.");
        List<Runnable> completions = new ArrayList<>(stopCallbacks); stopCallbacks.clear();
        for (Runnable callback : completions) callbacks.execute(callback);
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
                if (token == generation && snapshot.phase == Phase.RUNNING) {
                    boolean oversized = status != null && status.length() > MAX_STATUS_CHARACTERS;
                    snapshot = new Snapshot(Phase.RUNNING, status == null || oversized ? "{}" : status,
                            oversized ? "Native status exceeds the supported size limit." : "");
                }
            }
        });
    }
}
