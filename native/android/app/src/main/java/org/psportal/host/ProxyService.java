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
    static final String EXTRA_LAN_ENABLED = "lan_enabled";
    static final String EXTRA_PHONE_APPS = "phone_apps";
    private static volatile ProxyService instance;
    private static final String CHANNEL = "portal_proxy";
    private static final int NOTIFICATION = 10081;
    private final Handler main = new Handler(Looper.getMainLooper());
    private SessionController session;
    private boolean destroyed, foreground, taskRemovedSinceCommand;
    private int latestStartId;
    private String listenAddress = "";
    private int listenPort;
    private boolean lanEnabled = true, phoneRequested;

    static void phoneRoutingStopped(android.content.Context context) {
        ProxyService service = instance;
        if (service != null && !service.lanEnabled && service.phoneRequested) service.requestStop(service.latestStartId);
    }

    private final Runnable statusTick = new Runnable() {
        @Override public void run() {
            if (destroyed || !foreground) return;
            SessionController.Snapshot current = session.snapshot();
            if (!current.isActive()) { finishStop(latestStartId); return; }
            if (current.phase == SessionController.Phase.RUNNING) {
                session.refresh();
                if (lanEnabled && !NetworkAddresses.isAssigned(listenAddress)) {
                    getSharedPreferences("ui", MODE_PRIVATE).edit().putBoolean("network_lost", true).apply();
                    requestStop(latestStartId);
                    return;
                }
            }
            // Revocation or channel disabling ends a run rather than leaving a hidden proxy.
            if (!notificationsAllowed() || (lanEnabled && !Permissions.localNetworkGranted(ProxyService.this))) {
                requestStop(latestStartId);
                return;
            }
            updateNotification();
            main.postDelayed(this, 2000);
        }
    };

    // The service follows the in-app language without restarting the listener.
    private android.content.Context localized() {
        android.content.res.Configuration config = new android.content.res.Configuration(getResources().getConfiguration());
        config.setLocale(getSharedPreferences("ui", MODE_PRIVATE).getBoolean("english", false)
                ? java.util.Locale.ENGLISH : java.util.Locale.SIMPLIFIED_CHINESE);
        return createConfigurationContext(config);
    }

    @Override public void onCreate() {
        super.onCreate();
        instance = this;
        session = ((PortalApplication)getApplication()).session();
        NotificationChannel channel = new NotificationChannel(CHANNEL, localized().getString(R.string.notification_channel), NotificationManager.IMPORTANCE_LOW);
        channel.setDescription(localized().getString(R.string.notification_description));
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    private static boolean inputsMatch(String config, boolean lan, boolean phone) {
        if (config == null || config.length() > 32768) return false;
        try {
            org.json.JSONObject json = new org.json.JSONObject(config);
            return ProductMode.matchesSessionInputs(lan, phone, json.opt("lan_enabled"), json.opt("phone_vpn"));
        } catch (org.json.JSONException invalid) { return false; }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        taskRemovedSinceCommand = false;
        if (intent == null || ACTION_STOP.equals(intent.getAction())) {
            requestStop(startId);
            return START_NOT_STICKY;
        }
        if (!ACTION_START.equals(intent.getAction())) { stopSelfResult(startId); return START_NOT_STICKY; }
        String config = intent.getStringExtra(EXTRA_CONFIG);
        intent.removeExtra(EXTRA_CONFIG); // Do not retain the subscription token in service intents.
        boolean requestedLan = intent.getBooleanExtra(EXTRA_LAN_ENABLED, true);
        boolean requestedPhone = intent.getBooleanExtra(EXTRA_PHONE_APPS, false);
        if (!inputsMatch(config, requestedLan, requestedPhone)
                || (requestedLan && !Permissions.localNetworkGranted(this)) || !notificationsAllowed()
                || (requestedPhone && (android.net.VpnService.prepare(this) != null || PhoneVpnService.hasVpnConflict(this)))) {
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
        if (PhoneVpnService.isActive()) { session.rejectedStart(); stopSelfResult(startId); return START_NOT_STICKY; }
        lanEnabled = requestedLan; phoneRequested = requestedPhone;
        if (phoneRequested) PhoneVpnService.prepareRequest();
        listenPort = intent.getIntExtra(EXTRA_PORT, 10081);
        try {
            if (Build.VERSION.SDK_INT >= 34 && !lanEnabled)
                startForeground(NOTIFICATION, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_SYSTEM_EXEMPTED);
            else if (Build.VERSION.SDK_INT >= 29 && lanEnabled)
                startForeground(NOTIFICATION, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
            else if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION, notification(), 0);
            else startForeground(NOTIFICATION, notification());
            foreground = true;
        } catch (RuntimeException denied) {
            session.rejectedStart();
            requestStop(startId);
            return START_NOT_STICKY;
        }
        session.start(config, () -> {
            // SessionController fences the run identity at dispatch. A newer
            // framework ID may belong to an ignored duplicate of this Start.
            if (destroyed) return;
            if (!session.snapshot().isActive()) { PhoneVpnService.rejectRequest("core_unavailable"); finishStop(latestStartId); }
            else if (phoneRequested && PhoneVpnService.requestPending() && session.snapshot().phase == SessionController.Phase.RUNNING) {
                try { startForegroundService(new Intent(this, PhoneVpnService.class).setAction(PhoneVpnService.ACTION_START)); }
                catch (RuntimeException denied) { PhoneVpnService.rejectRequest("permission_denied"); if (!lanEnabled) requestStop(latestStartId); }
            }
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
                .setContentTitle(localized().getString(R.string.notification_title))
                .setContentText(localized().getString(message))
                .setSubText(!lanEnabled || listenAddress == null || listenAddress.isEmpty() ? null : listenAddress + ":" + listenPort)
                .setContentIntent(open)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_SERVICE)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .addAction(new Notification.Action.Builder(null, localized().getString(R.string.stop), stop).build())
                .build();
    }

    private void requestStop(int startId) {
        requestStop(startId, false);
    }

    private void requestStop(int startId, boolean taskRemoved) {
        phoneRequested = false;
        PhoneVpnService.stop(this);
        main.removeCallbacks(statusTick);
        session.stop(() -> { if (!destroyed) finishStop(startId, taskRemoved); });
        if (foreground) updateNotification();
    }

    private void finishStop(int startId) {
        finishStop(startId, false);
    }

    private void finishStop(int startId, boolean taskRemoved) {
        // A completion from an older command cannot stop a newer run.
        if (startId != latestStartId) return;
        phoneRequested = false;
        PhoneVpnService.stop(this);
        stopForeground(STOP_FOREGROUND_REMOVE);
        foreground = false;
        // Android may assign its task-removal event a newer framework start ID
        // without delivering onStartCommand. stopSelfResult(oldId) then leaves
        // an idle service behind. The guard above still protects a newer run.
        // Background sharing may outlive task removal and stop later because of
        // network loss. Retain that event until a newer command supplies its ID.
        if (taskRemoved || taskRemovedSinceCommand) stopSelf();
        else stopSelfResult(startId);
    }

    @Override public void onTaskRemoved(Intent rootIntent) {
        taskRemovedSinceCommand = true;
        boolean allowBackground = getSharedPreferences("ui", MODE_PRIVATE).getBoolean(
                BackgroundPolicy.PREFERENCE_KEY, BackgroundPolicy.DEFAULT_ALLOW_BACKGROUND);
        if (BackgroundPolicy.stopWhenTaskRemoved(allowBackground)) requestStop(latestStartId, true);
        // The existing foreground run remains visible and stoppable. Never
        // schedule a relaunch: process death and system Stop end the session.
    }
    @Override public void onDestroy() {
        destroyed = true;
        phoneRequested = false;
        PhoneVpnService.stop(this);
        if (instance == this) instance = null;
        main.removeCallbacksAndMessages(null);
        session.stop(() -> {});
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
