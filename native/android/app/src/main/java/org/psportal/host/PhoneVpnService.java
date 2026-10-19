// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.net.VpnService;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.psportal.engine.androidmobile.Androidmobile;
import org.psportal.engine.androidmobile.SocketProtector;

/** Optional consented phone-app tunnel. No boot/always-on/sticky or host VPN. */
public final class PhoneVpnService extends VpnService {
    static final String ACTION_START = "org.psportal.host.PHONE_VPN_START";
    static final String ACTION_STOP = "org.psportal.host.PHONE_VPN_STOP";
    private static final String CHANNEL = "portal_phone_vpn";
    private static final int NOTIFICATION = 10082;
    private static final PhoneVpnState STATE = new PhoneVpnState();
    private static volatile boolean requested, established;
    private static volatile PhoneVpnService instance;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService work = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "portal-phone-vpn"); t.setDaemon(true); return t;
    });
    private SessionController session;
    private ConnectivityManager connectivity;
    private volatile Network underlying;
    private ConnectivityManager.NetworkCallback networkCallback;
    private ParcelFileDescriptor descriptor; // Only accessed on work lane.
    private volatile boolean cleanupQueued;
    private boolean destroyed, foreground, taskRemoved;
    private int latestStartId;

    public static String stateCode() { return STATE.code(); }
    public static boolean isRequested() { return requested || STATE.busy(); }
    public static boolean isActive() {
        PhoneVpnService service = instance;
        return STATE.busy() || (service != null && service.cleanupQueued);
    }
    public static boolean isRunning() { return STATE.code().equals("running"); }
    static void prepareRequest() { requested = true; }
    static boolean requestPending() { return requested; }
    static void rejectRequest(String reason) { requested = false; STATE.reject(reason); }

    /** Stop only phone routing. The session owner decides whether LAN remains. */
    public static void stop(Context context) {
        requested = false;
        PhoneVpnService service = instance;
        if (service != null) {
            if (STATE.busy()) STATE.stop("stopped"); // invalidate worker before posting cleanup
            service.main.post(() -> service.requestStop("stopped"));
        } else ProxyService.phoneRoutingStopped(context);
    }

    public static boolean hasVpnConflict(Context context) {
        try {
            ConnectivityManager cm = context.getSystemService(ConnectivityManager.class);
            if (cm == null) return true;
            for (Network n : cm.getAllNetworks()) {
                NetworkCapabilities c = cm.getNetworkCapabilities(n);
                if (c != null && c.hasTransport(NetworkCapabilities.TRANSPORT_VPN) && !established) return true;
            }
            return false;
        } catch (RuntimeException unavailable) { return true; }
    }

    private Context localized() {
        android.content.res.Configuration c = new android.content.res.Configuration(getResources().getConfiguration());
        c.setLocale(getSharedPreferences("ui", MODE_PRIVATE).getBoolean("english", false)
                ? java.util.Locale.ENGLISH : java.util.Locale.SIMPLIFIED_CHINESE);
        return createConfigurationContext(c);
    }

    @Override public void onCreate() {
        super.onCreate(); instance = this;
        session = ((PortalApplication)getApplication()).session();
        connectivity = getSystemService(ConnectivityManager.class);
        NotificationChannel channel = new NotificationChannel(CHANNEL, localized().getString(R.string.vpn_notification_channel), NotificationManager.IMPORTANCE_LOW);
        channel.setDescription(localized().getString(R.string.vpn_notification_description));
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId; taskRemoved = false;
        if (cleanupQueued) { requested = false; stopSelfResult(startId); return START_NOT_STICKY; }
        if (intent == null || ACTION_STOP.equals(intent.getAction())) { requestStop("stopped"); return START_NOT_STICKY; }
        if (!ACTION_START.equals(intent.getAction())) { requestStop("stopped"); return START_NOT_STICKY; }
        if (!requested) { requestStop("stopped"); return START_NOT_STICKY; }
        if (STATE.busy()) return START_NOT_STICKY;
        String rejection = null;
        if (session.snapshot().phase != SessionController.Phase.RUNNING) rejection = "core_unavailable";
        else if (VpnService.prepare(this) != null) rejection = "consent_required";
        else if (hasVpnConflict(this)) rejection = "vpn_conflict";
        else if (!notificationsAllowed()) rejection = "permission_denied";
        else if ((underlying = findUnderlyingNetwork()) == null) rejection = "no_network";
        if (rejection != null) { requestStop(rejection); return START_NOT_STICKY; }
        final long token = STATE.begin(); requested = true;
        try {
            if (Build.VERSION.SDK_INT >= 34) startForeground(NOTIFICATION, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_SYSTEM_EXEMPTED);
            else startForeground(NOTIFICATION, notification());
            foreground = true;
            registerNetworkMonitor();
        } catch (RuntimeException denied) { requestStop("permission_denied"); return START_NOT_STICKY; }
        work.execute(() -> startTunnel(token));
        main.post(statusTick);
        return START_NOT_STICKY;
    }

    private void startTunnel(long token) {
        try {
            // Prepare before routing packets; a failed subscription never leaves a
            // packet interface established while the core cannot handle traffic.
            Androidmobile.prepare();
            if (!STATE.current(token)) return;
            if (VpnService.prepare(this) != null) { main.post(() -> requestStop("consent_required")); return; }
            if (hasVpnConflict(this)) { main.post(() -> requestStop("vpn_conflict")); return; }
            if (findUnderlyingNetwork() == null) { main.post(() -> requestStop("no_network")); return; }
            Builder builder = new Builder().setSession("PSPortal").setMtu(1500)
                    .addAddress("198.18.0.1", 30).addAddress("fdfe:dcba:9876::1", 126)
                    .addRoute("0.0.0.0", 0).addRoute("::", 0)
                    .addDnsServer("198.18.0.2").addDnsServer("fdfe:dcba:9876::2")
                    .setUnderlyingNetworks(new Network[]{underlying})
                    // Only this host app is excluded. This also covers pre-existing
                    // bootstrap sockets; new Mihomo sockets are protected below.
                    .addDisallowedApplication(getPackageName());
            if (!STATE.current(token)) return;
            descriptor = builder.establish();
            if (descriptor == null) { main.post(() -> requestStop("consent_required")); return; }
            established = true;
            if (!STATE.current(token)) return;
            Androidmobile.startPhoneVPN(descriptor.getFd(), new SocketProtector() {
                @Override public boolean protect(long fd) {
                    if (fd < 0 || fd > Integer.MAX_VALUE) return false;
                    try { return PhoneVpnService.this.protect((int)fd); }
                    catch (RuntimeException denied) { return false; }
                }
            });
            if (!STATE.running(token)) return;
            main.post(this::updateNotification);
        } catch (Exception | LinkageError failure) {
            // Never display native exception text (it may contain subscription secrets).
            main.post(() -> requestStop("start_failed"));
        }
    }

    private Network findUnderlyingNetwork() {
        if (connectivity == null) return null;
        try {
            Network active = connectivity.getActiveNetwork();
            if (isUnderlying(active)) return active;
            for (Network n : connectivity.getAllNetworks()) if (isUnderlying(n)) return n;
        } catch (RuntimeException unavailable) { return null; }
        return null;
    }
    private boolean isUnderlying(Network n) {
        NetworkCapabilities c = n == null ? null : connectivity.getNetworkCapabilities(n);
        return c != null && c.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                && !c.hasTransport(NetworkCapabilities.TRANSPORT_VPN);
    }
    private void registerNetworkMonitor() {
        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override public void onLost(Network n) { if (n.equals(underlying)) main.post(() -> requestStop("no_network")); }
            @Override public void onCapabilitiesChanged(Network n, NetworkCapabilities c) {
                if (n.equals(underlying) && !c.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET))
                    main.post(() -> requestStop("no_network"));
            }
        };
        connectivity.registerNetworkCallback(new NetworkRequest.Builder()
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN).build(), networkCallback);
    }
    private final Runnable statusTick = new Runnable() {
        @Override public void run() {
            if (destroyed || cleanupQueued || !STATE.busy()) return;
            if (session.snapshot().phase != SessionController.Phase.RUNNING) { requestStop("core_unavailable"); return; }
            if (!notificationsAllowed()) { requestStop("permission_denied"); return; }
            if (!isUnderlying(underlying)) { requestStop("no_network"); return; }
            updateNotification(); main.postDelayed(this, 1000);
        }
    };

    private boolean notificationsAllowed() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        NotificationChannel channel = manager.getNotificationChannel(CHANNEL);
        return (Build.VERSION.SDK_INT < 33 || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)
                && manager.areNotificationsEnabled() && (channel == null || channel.getImportance() != NotificationManager.IMPORTANCE_NONE);
    }
    private Notification notification() {
        int text = STATE.code().equals("running") ? R.string.vpn_notification_running
                : STATE.code().equals("stopping") ? R.string.vpn_notification_stopping : R.string.notification_starting;
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        // Notification Stop is deliberately the shared session's complete Stop.
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, ProxyService.class).setAction(ProxyService.ACTION_STOP), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_portal)
                .setContentTitle(localized().getString(R.string.vpn_notification_title)).setContentText(localized().getString(text))
                .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_SERVICE).setVisibility(Notification.VISIBILITY_PRIVATE)
                .addAction(new Notification.Action.Builder(null, localized().getString(R.string.stop), stop).build()).build();
    }
    @android.annotation.SuppressLint("MissingPermission")
    private void updateNotification() {
        if (foreground && notificationsAllowed()) getSystemService(NotificationManager.class).notify(NOTIFICATION, notification());
    }
    private void requestStop(String reason) {
        requested = false; main.removeCallbacks(statusTick);
        if (cleanupQueued) return;
        cleanupQueued = true;
        long token = STATE.stop(reason);
        if (networkCallback != null) {
            try { connectivity.unregisterNetworkCallback(networkCallback); } catch (RuntimeException ignored) { }
            networkCallback = null;
        }
        updateNotification();
        work.execute(() -> {
            try { Androidmobile.stopPhoneVPN(); } catch (Exception | LinkageError ignored) { }
            try { if (descriptor != null) descriptor.close(); } catch (java.io.IOException ignored) { }
            descriptor = null; established = false;
            try { Androidmobile.releasePhoneVPNProtection(); } catch (Exception | LinkageError ignored) { }
            main.post(() -> {
                STATE.finish(token);
                stopForeground(STOP_FOREGROUND_REMOVE); foreground = false;
                // A VPN-only session has nothing left to serve after phone Stop.
                ProxyService.phoneRoutingStopped(this);
                if (taskRemoved) stopSelf(); else stopSelfResult(latestStartId);
                work.shutdown();
            });
        });
    }
    @Override public void onRevoke() { main.post(() -> requestStop("revoked")); }
    @Override public void onTaskRemoved(Intent rootIntent) {
        taskRemoved = true;
        boolean background = getSharedPreferences("ui", MODE_PRIVATE).getBoolean(BackgroundPolicy.PREFERENCE_KEY, BackgroundPolicy.DEFAULT_ALLOW_BACKGROUND);
        if (BackgroundPolicy.stopWhenTaskRemoved(background)) requestStop("stopped");
    }
    @Override public void onDestroy() {
        destroyed = true; main.removeCallbacks(statusTick);
        // Native cleanup completion must still run after framework destruction.
        // Removing all Handler messages here can strand STATE in stopping.
        requestStop("stopped");
        if (instance == this) instance = null;
        super.onDestroy();
    }
}
