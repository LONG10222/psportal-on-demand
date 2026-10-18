// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.View;
import android.view.WindowManager;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public final class MainActivity extends Activity {
    private static final int REQUEST_NOTIFICATIONS = 101, REQUEST_LAN = 102;
    private static final String[] MODES = { "auto", "prefer", "fixed" };
    private final Handler main = new Handler(Looper.getMainLooper());
    private final List<View> configurationViews = new ArrayList<>();
    private SessionController session;
    private EditText phone, portal, port, subscription, preferred, idle;
    private Spinner selection;
    private TextView status;
    private Button start, stop;
    private HostConfig pendingConfig;
    private boolean visible;
    private final Runnable renderTick = new Runnable() {
        @Override public void run() { if (visible) { render(); main.postDelayed(this, 500); } }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        session = ((PortalApplication)getApplication()).session();
        ScrollView scroll = new ScrollView(this);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = dp(24);
        layout.setPadding(padding, padding, padding, padding);
        scroll.addView(layout);
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        setContentView(scroll);
        text(layout, R.string.title, 27, true);
        text(layout, R.string.subtitle, 16, true);
        text(layout, R.string.explanation, 14, false);
        status = text(layout, R.string.stopped, 18, true);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        SharedPreferences prefs = getSharedPreferences("ui", MODE_PRIVATE);
        phone = input(layout, R.string.phone_ip, prefs.getString("phone", ""), InputType.TYPE_CLASS_PHONE);
        Button choose = button(layout, R.string.choose_address, v -> chooseAddress());
        configurationViews.add(choose);
        portal = input(layout, R.string.portal_ip, prefs.getString("portal", ""), InputType.TYPE_CLASS_PHONE);
        port = input(layout, R.string.port, prefs.getString("port", "10081"), InputType.TYPE_CLASS_NUMBER);
        subscription = input(layout, R.string.subscription, "", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        subscription.setSaveEnabled(false);
        subscription.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        text(layout, R.string.subscription_help, 12, false);
        text(layout, R.string.selection, 14, true);
        selection = new Spinner(this);
        ArrayAdapter<CharSequence> modes = ArrayAdapter.createFromResource(this, R.array.selection_labels, android.R.layout.simple_spinner_item);
        modes.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        selection.setAdapter(modes);
        selection.setSelection(Math.min(2, Math.max(0, prefs.getInt("mode", 0))));
        layout.addView(selection);
        configurationViews.add(selection);
        preferred = input(layout, R.string.preferred, prefs.getString("preferred", ""), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        idle = input(layout, R.string.idle, prefs.getString("idle", "60"), InputType.TYPE_CLASS_NUMBER);
        start = button(layout, R.string.start, v -> beginStart());
        stop = button(layout, R.string.stop, v -> {
            pendingConfig = null;
            startService(new Intent(this, ProxyService.class).setAction(ProxyService.ACTION_STOP));
            render();
        });
        text(layout, R.string.limitations, 13, false);
        button(layout, R.string.licenses, v -> showLicenses());
        if (phone.getText().length() == 0) {
            List<String> addresses = NetworkAddresses.localPrivateIpv4();
            if (addresses.size() == 1) phone.setText(addresses.get(0));
        }
        render();
    }

    private TextView text(LinearLayout parent, int resource, int size, boolean bold) {
        TextView text = new TextView(this);
        text.setText(resource); text.setTextSize(size); text.setTextColor(Color.rgb(22, 32, 55));
        if (bold) text.setTypeface(null, android.graphics.Typeface.BOLD);
        text.setPadding(0, dp(8), 0, dp(8));
        parent.addView(text, new LinearLayout.LayoutParams(-1, -2));
        return text;
    }
    private EditText input(LinearLayout parent, int label, String value, int inputType) {
        TextView caption = text(parent, label, 14, true);
        EditText input = new EditText(this);
        input.setId(View.generateViewId()); caption.setLabelFor(input.getId());
        input.setInputType(inputType); input.setSingleLine(true); input.setText(value);
        input.setSaveEnabled(false);
        parent.addView(input, new LinearLayout.LayoutParams(-1, -2));
        configurationViews.add(input);
        return input;
    }
    private Button button(LinearLayout parent, int resource, View.OnClickListener listener) {
        Button button = new Button(this); button.setText(resource); button.setAllCaps(false); button.setOnClickListener(listener);
        parent.addView(button, new LinearLayout.LayoutParams(-1, -2)); return button;
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private String value(EditText input) { return input.getText().toString(); }

    private void chooseAddress() {
        List<String> addresses = NetworkAddresses.localPrivateIpv4();
        if (addresses.isEmpty()) { message(getString(R.string.no_address)); return; }
        new AlertDialog.Builder(this).setTitle(R.string.choose_address)
                .setItems(addresses.toArray(new String[0]), (dialog, item) -> phone.setText(addresses.get(item))).show();
    }

    private void beginStart() {
        if (pendingConfig != null || !session.snapshot().canStart()) return;
        try {
            pendingConfig = new HostConfig(value(phone), value(portal), value(port), value(subscription),
                    MODES[selection.getSelectedItemPosition()], value(preferred), value(idle));
            if (!NetworkAddresses.isAssigned(pendingConfig.listenHost)) throw new IllegalArgumentException(getString(R.string.no_address));
        } catch (IllegalArgumentException invalid) {
            pendingConfig = null;
            new AlertDialog.Builder(this).setTitle(R.string.invalid_config).setMessage(invalid.getMessage()).setPositiveButton(R.string.ok, null).show();
            return;
        }
        saveNonSecretFields();
        continueStart();
    }

    private void continueStart() {
        if (!visible || pendingConfig == null) { pendingConfig = null; return; }
        if (Permissions.requiresLocalNetwork(this) && !Permissions.localNetworkGranted(this)) {
            new AlertDialog.Builder(this).setMessage(R.string.local_network_required)
                    .setPositiveButton(R.string.ok, (dialog, which) -> requestPermissions(new String[] {Permissions.LOCAL_NETWORK}, REQUEST_LAN))
                    .setNegativeButton(android.R.string.cancel, (dialog, which) -> pendingConfig = null)
                    .setOnCancelListener(dialog -> pendingConfig = null).show();
            return;
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            new AlertDialog.Builder(this).setMessage(R.string.notification_required)
                    .setPositiveButton(R.string.ok, (dialog, which) -> requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, REQUEST_NOTIFICATIONS))
                    .setNegativeButton(android.R.string.cancel, (dialog, which) -> pendingConfig = null)
                    .setOnCancelListener(dialog -> pendingConfig = null).show();
            return;
        }
        NotificationManager notifications = getSystemService(NotificationManager.class);
        android.app.NotificationChannel channel = notifications.getNotificationChannel("portal_proxy");
        if (!notifications.areNotificationsEnabled() || channel != null && channel.getImportance() == NotificationManager.IMPORTANCE_NONE) {
            pendingConfig = null; message(getString(R.string.notifications_disabled)); return;
        }
        HostConfig config = pendingConfig; pendingConfig = null;
        getSharedPreferences("ui", MODE_PRIVATE).edit().putBoolean("network_lost", false).apply();
        Intent intent = new Intent(this, ProxyService.class).setAction(ProxyService.ACTION_START)
                .putExtra(ProxyService.EXTRA_CONFIG, config.toJson(new java.io.File(getFilesDir(), "runtime").getAbsolutePath()))
                .putExtra(ProxyService.EXTRA_ADDRESS, config.listenHost).putExtra(ProxyService.EXTRA_PORT, config.listenPort);
        try { startForegroundService(intent); }
        catch (RuntimeException denied) { message(getString(R.string.start_rejected)); }
        // Keep no extra saved copy of this token in the UI once transferred to the engine.
        subscription.setText("");
        render();
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode != REQUEST_NOTIFICATIONS && requestCode != REQUEST_LAN) return;
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED && pendingConfig != null && visible) continueStart();
        else { pendingConfig = null; if (visible) message(getString(R.string.permission_denied)); }
    }

    private void saveNonSecretFields() {
        getSharedPreferences("ui", MODE_PRIVATE).edit().putString("phone", value(phone)).putString("portal", value(portal))
                .putString("port", value(port)).putInt("mode", selection.getSelectedItemPosition())
                .putString("preferred", value(preferred)).putString("idle", value(idle)).apply();
    }
    private void render() {
        SessionController.Snapshot snapshot = session.snapshot();
        boolean editable = snapshot.canStart() && pendingConfig == null;
        for (View view : configurationViews) view.setEnabled(editable);
        start.setEnabled(editable);
        stop.setEnabled(snapshot.isActive() && snapshot.phase != SessionController.Phase.STOPPING);
        String display;
        switch (snapshot.phase) {
            case STARTING: display = getString(R.string.starting); break;
            case STOPPING: display = getString(R.string.stopping); break;
            case RUNNING:
                display = getString(R.string.listener_ready);
                try {
                    JSONObject nativeState = new JSONObject(snapshot.nativeStatus);
                    display += "\n" + getString(R.string.native_state, nativeState.optString("state", "unknown"), nativeState.optLong("active", 0));
                    String error = nativeState.optString("error", "");
                    if (!error.isEmpty()) display += "\n" + error.substring(0, Math.min(300, error.length()));
                } catch (org.json.JSONException invalid) { display += "\n" + getString(R.string.status_unavailable); }
                break;
            case ERROR: case FAULTED: display = snapshot.error; break;
            default: display = getString(R.string.stopped);
        }
        if (!display.contentEquals(status.getText())) status.setText(display);
    }
    private void message(String text) { new AlertDialog.Builder(this).setMessage(text).setPositiveButton(R.string.ok, null).show(); }

    private void showLicenses() {
        try {
            String[] files = getAssets().list("licenses");
            if (files == null || files.length == 0) throw new java.io.IOException();
            StringBuilder contents = new StringBuilder();
            for (String file : files) {
                try (InputStream input = getAssets().open("licenses/" + file); ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                    byte[] buffer = new byte[8192]; int read;
                    while ((read = input.read(buffer)) != -1) { bytes.write(buffer, 0, read); if (bytes.size() > 4_000_000) throw new java.io.IOException(); }
                    contents.append(file).append("\n\n").append(new String(bytes.toByteArray(), StandardCharsets.UTF_8)).append("\n\n");
                }
            }
            ScrollView scroll = new ScrollView(this); TextView text = new TextView(this);
            text.setText(contents.toString()); text.setTextIsSelectable(true); text.setPadding(dp(20), dp(12), dp(20), dp(12)); scroll.addView(text);
            new AlertDialog.Builder(this).setTitle(R.string.licenses).setView(scroll).setPositiveButton(R.string.ok, null).show();
        } catch (java.io.IOException missing) { message(getString(R.string.license_unavailable)); }
    }

    @Override public void onStart() {
        super.onStart(); visible = true; main.post(renderTick);
        SharedPreferences prefs = getSharedPreferences("ui", MODE_PRIVATE);
        if (prefs.getBoolean("network_lost", false)) {
            prefs.edit().putBoolean("network_lost", false).apply(); message(getString(R.string.network_lost));
        }
    }
    @Override public void onStop() {
        visible = false; pendingConfig = null; main.removeCallbacks(renderTick); saveNonSecretFields(); super.onStop();
    }
    @Override public void onDestroy() { main.removeCallbacksAndMessages(null); super.onDestroy(); }
}
