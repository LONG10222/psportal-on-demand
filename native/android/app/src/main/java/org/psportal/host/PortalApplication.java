// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import android.app.Application;
import android.os.Handler;
import android.os.Looper;
import java.util.concurrent.Executors;

public final class PortalApplication extends Application {
    private SessionController session;
    @Override public void onCreate() {
        super.onCreate();
        Handler main = new Handler(Looper.getMainLooper());
        session = new SessionController(new NativeEngine(), Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "portal-native-owner"); t.setDaemon(true); return t;
        }), main::post, Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "portal-node-probes"); t.setDaemon(true); return t;
        }));
    }
    public SessionController session() { return session; }
}
