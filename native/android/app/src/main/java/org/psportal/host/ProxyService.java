// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.pm.PackageManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/** Explicit user-started connected-device service. Never sticky and never boot-started. */
public final class ProxyService extends Service {
    static final String ACTION_START = "org.psportal.host.START";
    static final String ACTION_STOP = "org.psportal.host.STOP";
    static final String EXTRA_CONFIG = "config";
    static final String EXTRA_ADDRESS = "address";
    static final String EXTRA_PORT = "port";
    private static final String CHANNEL = "portal_proxy";
    private static final int NOTIFICATION = 10081;
    private final Handler main = new Handler(Looper.getMainLooper());
    private SessionController session;
    private boolean destroyed, foreground;
    private int latestStartId;
    private String listenAddress = "";
    private int listenPort;

    private final Runnable statusTick = new Runnable() {
        @Override public void run() {
            if (destroyed || !foreground) return;
            SessionController.Snapshot current = session.snapshot();
            if (!current.isActive()) { finishStop(latestStartId); return; }
            if (current.phase == SessionController.Phase.RUNNING) {
                session.refresh();
                if (!NetworkAddresses.isAssigned(listenAddress)) {
                    getSharedPreferences("ui", MODE_PRIVATE).edit().putBoolean("network_lost", true).apply();
                    requestStop(latestStartId);
                    return;
                }
            }
            // Revocation or channel disabling ends a run rather than leaving a hidden proxy.
            if (!notificationsAllowed() || !Permissions.localNetworkGranted(ProxyService.this)) {
                requestStop(latestStartId);
                return;
            }
            updateNotification();
            main.postDelayed(this, 2000);
        }
    };

    @Override public void onCreate() {
        super.onCreate();
        session = ((PortalApplication)getApplication()).session();
        NotificationChannel channel = new NotificationChannel(CHANNEL, getString(R.string.notification_channel), NotificationManager.IMPORTANCE_LOW);
        channel.setDescription(getString(R.string.notification_description));
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        if (intent == null || ACTION_STOP.equals(intent.getAction())) {
            requestStop(startId);
            return START_NOT_STICKY;
        }
        if (!ACTION_START.equals(intent.getAction())) { stopSelfResult(startId); return START_NOT_STICKY; }
        String config = intent.getStringExtra(EXTRA_CONFIG);
        intent.removeExtra(EXTRA_CONFIG); // Do not retain the subscription token in service intents.
        if (config == null || config.length() > 32768 || !Permissions.localNetworkGranted(this) || !notificationsAllowed()) {
            session.rejectedStart();
            requestStop(startId);
            return START_NOT_STICKY;
        }
        if (!session.snapshot().canStart()) {
            // Double taps cannot replace an active configuration or start another engine.
            // If this command arrived during teardown, attach its newer startId to the
            // same completion so an older stopSelfResult cannot leave a stranded service.
            if (session.snapshot().phase == SessionController.Phase.STOPPING)
                session.stop(() -> { if (!destroyed) finishStop(startId); });
            return START_NOT_STICKY;
        }
        listenAddress = intent.getStringExtra(EXTRA_ADDRESS);
        listenPort = intent.getIntExtra(EXTRA_PORT, 10081);
        try {
            if (Build.VERSION.SDK_INT >= 29)
                startForeground(NOTIFICATION, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
            else startForeground(NOTIFICATION, notification());
            foreground = true;
        } catch (RuntimeException denied) {
            session.rejectedStart();
            requestStop(startId);
            return START_NOT_STICKY;
        }
        session.start(config, () -> {
            if (destroyed || latestStartId != startId) return;
            if (!session.snapshot().isActive()) finishStop(startId);
        });
        main.removeCallbacks(statusTick);
        main.post(statusTick);
        return START_NOT_STICKY;
    }

    private boolean notificationsAllowed() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        NotificationChannel channel = manager.getNotificationChannel(CHANNEL);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return false;
        return manager.areNotificationsEnabled() && (channel == null || channel.getImportance() != NotificationManager.IMPORTANCE_NONE);
    }

    @SuppressLint("MissingPermission") // Explicit SDK/permission and channel checks immediately below.
    private void updateNotification() {
        if (notificationsAllowed()) getSystemService(NotificationManager.class).notify(NOTIFICATION, notification());
    }

    private Notification notification() {
        SessionController.Phase phase = session.snapshot().phase;
        int message = phase == SessionController.Phase.RUNNING ? R.string.notification_running :
                phase == SessionController.Phase.STOPPING ? R.string.notification_stopping : R.string.notification_starting;
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, ProxyService.class).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_portal)
                .setContentTitle(getString(R.string.notification_title))
                .setContentText(getString(message))
                .setSubText(listenAddress == null || listenAddress.isEmpty() ? null : listenAddress + ":" + listenPort)
                .setContentIntent(open)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_SERVICE)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .addAction(new Notification.Action.Builder(null, getString(R.string.stop), stop).build())
                .build();
    }

    private void requestStop(int startId) {
        main.removeCallbacks(statusTick);
        session.stop(() -> { if (!destroyed) finishStop(startId); });
        if (foreground) updateNotification();
    }

    private void finishStop(int startId) {
        // A completion from an older command cannot stop a newer run.
        if (startId != latestStartId) return;
        stopForeground(STOP_FOREGROUND_REMOVE);
        foreground = false;
        stopSelfResult(startId);
    }

    @Override public void onTaskRemoved(Intent rootIntent) { requestStop(latestStartId); }
    @Override public void onDestroy() {
        destroyed = true;
        main.removeCallbacksAndMessages(null);
        session.stop(() -> {});
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
