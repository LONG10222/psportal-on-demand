// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;

final class Permissions {
    static final String LOCAL_NETWORK = "android.permission.ACCESS_LOCAL_NETWORK";
    private Permissions() {}
    static boolean requiresLocalNetwork(Context context) {
        return Build.VERSION.SDK_INT >= 37 && context.getApplicationInfo().targetSdkVersion >= 37;
    }
    static boolean localNetworkGranted(Context context) {
        return !requiresLocalNetwork(context) || context.checkSelfPermission(LOCAL_NETWORK) == PackageManager.PERMISSION_GRANTED;
    }
}
