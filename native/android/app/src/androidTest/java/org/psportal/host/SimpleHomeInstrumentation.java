// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;
import android.text.InputType;
import android.text.method.PasswordTransformationMethod;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Switch;
import android.widget.Spinner;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import java.util.ArrayList;
import java.util.List;

/** On-device, dummy-only UI regression. Does not start service, read clipboard or use a subscription. */
public final class SimpleHomeInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    private static void require(boolean condition, String label) { if (!condition) throw new AssertionError(label); }
    private static void walk(View view, List<View> result) {
        result.add(view);
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) walk(((ViewGroup)view).getChildAt(i), result);
    }
    private static View tagged(List<View> views, String name) {
        for (View view : views) if (name.equals(view.getTag())) return view;
        throw new AssertionError("Missing navigation target " + name);
    }
    @Override public void onStart() {
        Bundle result = new Bundle(); Activity activity = null;
        android.content.SharedPreferences prefs = getTargetContext().getSharedPreferences("ui", 0);
        boolean hadLanguage = prefs.contains("english"), language = prefs.getBoolean("english", false);
        boolean hadTheme = prefs.contains("dark"), dark = prefs.getBoolean("dark", true);
        boolean hadRouting = prefs.contains("routing_mode"); String routingMode = prefs.getString("routing_mode", "rule");
        boolean hadBackground = prefs.contains(BackgroundPolicy.PREFERENCE_KEY);
        boolean allowBackground = prefs.getBoolean(BackgroundPolicy.PREFERENCE_KEY, BackgroundPolicy.DEFAULT_ALLOW_BACKGROUND);
        boolean hadLan = prefs.contains("lan_enabled"), lanEnabled = prefs.getBoolean("lan_enabled", true);
        int resultCode = Activity.RESULT_OK;
        try {
            activity = startActivitySync(new Intent(getTargetContext(), MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            final Activity current = activity;
            final Throwable[] failure = new Throwable[1];
            runOnMainSync(() -> {
                try {
                    SessionController session = ((PortalApplication)current.getApplication()).session();
                    SessionController.Snapshot before = session.snapshot();
                    require(before.phase == SessionController.Phase.STOPPED, "Dummy-only test requires a stopped session");
                    List<View> views = new ArrayList<>(); walk(current.getWindow().getDecorView(), views);
                    EditText secret = null; Switch appearance = null, background = null, lan = null, phoneApps = null; Spinner routing = null; Button languageButton = null;
                    RadioGroup productModes = null; RadioButton game = null, mixed = null, clash = null;
                    for (View view : views) {
                        if (view instanceof EditText && (((EditText)view).getInputType() & InputType.TYPE_MASK_VARIATION) == InputType.TYPE_TEXT_VARIATION_PASSWORD) secret = (EditText)view;
                        if (view instanceof Switch && "appearance".equals(view.getTag())) appearance = (Switch)view;
                        if (view instanceof Switch && "background_sharing".equals(view.getTag())) background = (Switch)view;
                        if (view instanceof Switch && "lan_enabled".equals(view.getTag())) lan = (Switch)view;
                        if (view instanceof Switch && "phone_apps".equals(view.getTag())) phoneApps = (Switch)view;
                        if (view instanceof Spinner && "routing_mode".equals(view.getTag())) routing = (Spinner)view;
                        if (view instanceof RadioGroup && "product_modes".equals(view.getTag())) productModes = (RadioGroup)view;
                        if (view instanceof RadioButton && "product_mode_game".equals(view.getTag())) game = (RadioButton)view;
                        if (view instanceof RadioButton && "product_mode_mixed".equals(view.getTag())) mixed = (RadioButton)view;
                        if (view instanceof RadioButton && "product_mode_clash".equals(view.getTag())) clash = (RadioButton)view;
                        if (view instanceof Button && (((Button)view).getText().toString().equals("English") || ((Button)view).getText().toString().equals("中文"))) languageButton = (Button)view;
                    }
                    require(secret != null && appearance != null && background != null && lan != null && phoneApps != null && routing != null && languageButton != null, "Simple-home controls present");
                    require(productModes != null && productModes.getChildCount() == 3 && game != null && mixed != null && clash != null, "Three product modes present");
                    require(!phoneApps.isChecked(), "Phone-app VPN defaults off on a fresh stopped session");
                    require(lan.isChecked() == lanEnabled, "Independent LAN preference restored");
                    Button startButton = null;
                    for (View view : views) if (view instanceof Button && (((Button)view).getText().toString().equals("连接") || ((Button)view).getText().toString().equals("Connect"))) startButton = (Button)view;
                    require(startButton != null, "Start control present");
                    int visibleText = 0;
                    for (View view : views) if (view instanceof android.widget.TextView && view.isShown()
                            && !((android.widget.TextView)view).getText().toString().isEmpty()) visibleText++;
                    require(visibleText <= 22, "Overview stays compact without tutorial paragraphs");
                    require(!tagged(views, "page_settings").isShown() && !tagged(views, "page_nodes").isShown(), "Secondary controls are hidden on Overview");
                    lan.setChecked(false); phoneApps.setChecked(false);
                    require(!startButton.isEnabled(), "Both traffic options off disables Start");
                    phoneApps.setChecked(true);
                    require(startButton.isEnabled() && !lan.isChecked(), "VPN-only is independently selectable without opening consent");
                    lan.setChecked(true);
                    require(phoneApps.isChecked() && startButton.isEnabled(), "LAN and phone-app options can be selected together");
                    phoneApps.setChecked(false); lan.setChecked(lanEnabled);
                    require(routing.getCount() == 3 && routing.isEnabled(), "Three routing modes are available while stopped");
                    require(background.isChecked() == allowBackground && background.isEnabled(), "Background policy preference restored");
                    routing.setSelection(1); background.performClick();
                    require(prefs.getBoolean(BackgroundPolicy.PREFERENCE_KEY, allowBackground) != allowBackground, "Background option saved independently");
                    require((current.getWindow().getAttributes().flags & WindowManager.LayoutParams.FLAG_SECURE) != 0, "Secure window retained");
                    require(!secret.isSaveEnabled(), "Secret view-state saving disabled");
                    require(secret.getImportantForAutofill() == View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS, "Autofill disabled");
                    require(secret.getTransformationMethod() instanceof PasswordTransformationMethod, "Password transformation retained after singleLine");
                    String dummy = "https://example.invalid/DUMMY-NOT-A-SECRET";
                    secret.setText(dummy);
                    String[] pageTags = {"page_overview", "page_nodes", "page_sharing", "page_settings"};
                    for (int page : new int[]{1, 2, 3, 0}) {
                        ((Button)tagged(views, "tab_" + page)).performClick();
                        require(tagged(views, pageTags[page]).isShown(), "Selected page is visible");
                        int shown = 0; for (String tag : pageTags) if (tagged(views, tag).isShown()) shown++;
                        require(shown == 1, "Only one page appears at a time");
                        require(secret.getText().toString().equals(dummy), "Navigation preserves in-memory subscription");
                        require(session.snapshot() == before, "Navigation never starts or stops the session");
                    }
                    game.performClick();
                    require(lan.isChecked() && !phoneApps.isChecked() && game.isChecked(), "Game selects only LAN sharing");
                    mixed.performClick();
                    require(lan.isChecked() && phoneApps.isChecked() && mixed.isChecked(), "Mixed selects both inputs without starting them");
                    clash.performClick();
                    require(!lan.isChecked() && phoneApps.isChecked() && clash.isChecked(), "Clash selects phone only");
                    require(secret.getText().toString().equals(dummy) && routing.getSelectedItemPosition() == 1, "Product changes preserve subscription and separate routing selection");
                    phoneApps.setChecked(false);
                    require(productModes.getCheckedRadioButtonId() == -1 && !startButton.isEnabled(), "Both inputs off clears product selection and disables Start");
                    lan.setChecked(lanEnabled);
                    CharSequence masked = secret.getTransformationMethod().getTransformation(secret.getText(), secret);
                    require(masked.length() == dummy.length() && !masked.toString().equals(dummy), "Dummy subscription actually masked");
                    require(session.snapshot() == before, "Opening and option changes never start service or request VPN");
                    languageButton.performClick(); appearance.performClick();
                    require(secret.getText().toString().equals(dummy), "Language/theme preserve typed subscription");
                    require(routing.getSelectedItemPosition() == 1 && background.isChecked() != allowBackground, "Language/theme preserve routing and background choices");
                    require(secret.getTransformationMethod() instanceof PasswordTransformationMethod, "Hot appearance changes preserve masking");
                    require(session.snapshot() == before, "Language/theme do not restart native session");
                    secret.setText("");
                } catch (Throwable error) { failure[0] = error; }
            });
            if (failure[0] != null) throw new AssertionError(failure[0]);
            result.putString("stream", "PASS: actual password transformation, privacy flags, three non-starting product modes, independent routing/LAN/phone/background controls and hot language/theme preservation; no service started\n");
        } catch (Throwable failure) {
            result.putString("stream", "FAIL: " + failure.getClass().getSimpleName() + " (dummy-only UI regression)\n");
            resultCode = Activity.RESULT_CANCELED;
        } finally {
            if (activity != null) { final Activity current = activity; runOnMainSync(current::finish); waitForIdleSync(); }
            android.content.SharedPreferences.Editor edit = prefs.edit();
            if (hadLanguage) edit.putBoolean("english", language); else edit.remove("english");
            if (hadTheme) edit.putBoolean("dark", dark); else edit.remove("dark");
            if (hadRouting) edit.putString("routing_mode", routingMode); else edit.remove("routing_mode");
            if (hadLan) edit.putBoolean("lan_enabled", lanEnabled); else edit.remove("lan_enabled");
            if (hadBackground) edit.putBoolean(BackgroundPolicy.PREFERENCE_KEY, allowBackground); else edit.remove(BackgroundPolicy.PREFERENCE_KEY);
            edit.commit();
        }
        finish(resultCode, result);
    }
}
