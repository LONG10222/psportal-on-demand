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
    @Override public void onStart() {
        Bundle result = new Bundle(); Activity activity = null;
        android.content.SharedPreferences prefs = getTargetContext().getSharedPreferences("ui", 0);
        boolean hadLanguage = prefs.contains("english"), language = prefs.getBoolean("english", false);
        boolean hadTheme = prefs.contains("dark"), dark = prefs.getBoolean("dark", true);
        int resultCode = Activity.RESULT_OK;
        try {
            activity = startActivitySync(new Intent(getTargetContext(), MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            final Activity current = activity;
            final Throwable[] failure = new Throwable[1];
            runOnMainSync(() -> {
                try {
                    List<View> views = new ArrayList<>(); walk(current.getWindow().getDecorView(), views);
                    EditText secret = null; Switch appearance = null; Button languageButton = null;
                    for (View view : views) {
                        if (view instanceof EditText && (((EditText)view).getInputType() & InputType.TYPE_MASK_VARIATION) == InputType.TYPE_TEXT_VARIATION_PASSWORD) secret = (EditText)view;
                        if (view instanceof Switch) appearance = (Switch)view;
                        if (view instanceof Button && (((Button)view).getText().toString().equals("English") || ((Button)view).getText().toString().equals("中文"))) languageButton = (Button)view;
                    }
                    require(secret != null && appearance != null && languageButton != null, "Simple-home controls present");
                    require((current.getWindow().getAttributes().flags & WindowManager.LayoutParams.FLAG_SECURE) != 0, "Secure window retained");
                    require(!secret.isSaveEnabled(), "Secret view-state saving disabled");
                    require(secret.getImportantForAutofill() == View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS, "Autofill disabled");
                    require(secret.getTransformationMethod() instanceof PasswordTransformationMethod, "Password transformation retained after singleLine");
                    String dummy = "https://example.invalid/DUMMY-NOT-A-SECRET";
                    secret.setText(dummy);
                    CharSequence masked = secret.getTransformationMethod().getTransformation(secret.getText(), secret);
                    require(masked.length() == dummy.length() && !masked.toString().equals(dummy), "Dummy subscription actually masked");
                    SessionController session = ((PortalApplication)current.getApplication()).session();
                    SessionController.Snapshot before = session.snapshot();
                    require(before.phase == SessionController.Phase.STOPPED, "Opening never starts service");
                    languageButton.performClick(); appearance.performClick();
                    require(secret.getText().toString().equals(dummy), "Language/theme preserve typed subscription");
                    require(secret.getTransformationMethod() instanceof PasswordTransformationMethod, "Hot appearance changes preserve masking");
                    require(session.snapshot() == before, "Language/theme do not restart native session");
                    secret.setText("");
                } catch (Throwable error) { failure[0] = error; }
            });
            if (failure[0] != null) throw new AssertionError(failure[0]);
            result.putString("stream", "PASS: actual password transformation, privacy flags and hot language/theme preservation; no service started\n");
        } catch (Throwable failure) {
            result.putString("stream", "FAIL: " + failure.getClass().getSimpleName() + " (dummy-only UI regression)\n");
            resultCode = Activity.RESULT_CANCELED;
        } finally {
            if (activity != null) { final Activity current = activity; runOnMainSync(current::finish); }
            android.content.SharedPreferences.Editor edit = prefs.edit();
            if (hadLanguage) edit.putBoolean("english", language); else edit.remove("english");
            if (hadTheme) edit.putBoolean("dark", dark); else edit.remove("dark");
            edit.commit();
        }
        finish(resultCode, result);
    }
}
