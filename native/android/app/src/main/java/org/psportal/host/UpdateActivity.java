// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.ContextThemeWrapper;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** User initiated GitHub release updates. Android owns source consent and installation. */
public final class UpdateActivity extends Activity {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private volatile HttpURLConnection connection;
    private volatile boolean closed;
    private boolean english, dark, busy;
    private TextView status, notes;
    private ProgressBar progress;
    private Button action, check;
    private Asset asset;
    private File ready;

    static final class Asset {
        final String name, url, hash, title, notes;
        final long size; final int version;
        Asset(JSONObject json, String tag, String title, String notes) throws Exception {
            name = json.getString("name"); url = json.getString("browser_download_url");
            hash = UpdatePolicy.digest(json.getString("digest")); size = json.getLong("size");
            version = UpdatePolicy.version(name); this.title = title.substring(0, Math.min(160, title.length()));
            this.notes = notes.substring(0, Math.min(32768, notes.length()));
            if (!"uploaded".equals(json.getString("state")) || version < 0 || size < 1024 ||
                    size > UpdatePolicy.MAX_APK || !UpdatePolicy.assetUrl(url, tag, name)) throw new IOException("metadata");
        }
    }
    static Asset select(JSONObject release, long installed, String[] abis) throws Exception {
        if (release.getBoolean("draft") || release.getBoolean("prerelease")) return null;
        String tag = release.getString("tag_name"), title = release.optString("name", tag);
        String notes = release.optString("body", "");
        JSONArray assets = release.getJSONArray("assets"); Asset best = null; int rank = Integer.MAX_VALUE;
        for (int i = 0; i < assets.length(); i++) {
            JSONObject json = assets.getJSONObject(i); String name = json.optString("name", "");
            int version = UpdatePolicy.version(name), preference = UpdatePolicy.preference(name, abis);
            if (version <= installed || preference == Integer.MAX_VALUE) continue;
            Asset candidate = new Asset(json, tag, title, notes);
            if (best == null || version > best.version || (version == best.version && preference < rank)) { best = candidate; rank = preference; }
        }
        return best;
    }
    private String t(String zh, String en) { return english ? en : zh; }
    private int dp(int n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state); getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        english = getSharedPreferences("ui", MODE_PRIVATE).getBoolean("english", false);
        dark = getSharedPreferences("ui", MODE_PRIVATE).getBoolean("dark", true);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(dark ? Color.rgb(19,22,43) : Color.rgb(246,245,252)); setContentView(root);
        root.setOnApplyWindowInsetsListener((v, insets) -> { v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom()); return insets; });
        ScrollView scroll = new ScrollView(this); root.addView(scroll, new LinearLayout.LayoutParams(-1,-1));
        LinearLayout body = new LinearLayout(this); body.setOrientation(LinearLayout.VERTICAL); body.setPadding(dp(20),dp(12),dp(20),dp(24)); scroll.addView(body);
        button(body, t("‹ 返回设置", "‹ Settings"), v -> finish());
        text(body, t("应用更新", "App updates"), 24);
        try { text(body, t("当前版本 ", "Installed ") + installed().versionName, 14); } catch (Exception ignored) { /* own package always exists */ }
        status = text(body, "", 16); status.setTag("update_status");
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal); body.addView(progress); progress.setVisibility(android.view.View.GONE);
        notes = text(body, "", 15); notes.setTextIsSelectable(true);
        action = button(body, "", v -> { if (ready == null) download(); else installRequested(); }); action.setTag("update_action"); action.setVisibility(android.view.View.GONE);
        check = button(body, t("检查更新", "Check for updates"), v -> check()); check.setTag("update_check");
        text(body, t("正式版 · GitHub Releases", "Stable · GitHub Releases"), 13);
        check();
    }
    private TextView text(LinearLayout parent, String value, int size) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setPadding(0,dp(10),0,dp(10));
        view.setTextColor(dark ? Color.rgb(240,244,250) : Color.rgb(27,39,56)); parent.addView(view); return view;
    }
    private Button button(LinearLayout parent, String text, android.view.View.OnClickListener listener) {
        Button button = new Button(this); button.setText(text); button.setAllCaps(false); button.setMinHeight(dp(48));
        button.setOnClickListener(listener); parent.addView(button, new LinearLayout.LayoutParams(-1,-2)); return button;
    }
    private void ui(Runnable task) { main.post(() -> { if (!closed) task.run(); }); }
    private void busy(boolean value) {
        busy = value; check.setEnabled(!value); action.setEnabled(!value);
        progress.setVisibility(value ? android.view.View.VISIBLE : android.view.View.GONE);
    }
    private void fail(Exception error) {
        String message = error.getMessage();
        ui(() -> { busy(false);
            if ("APK identity".equals(message)) status.setText(t("更新包的签名、版本或设备要求不匹配，请等待维护者修复发布包。", "Update signature, version or device requirements do not match. Wait for a corrected release."));
            else if ("storage".equals(message)) status.setText(t("存储空间不足或无法写入，请清理空间后重试。", "Storage is full or unavailable. Free space and retry."));
            else if ("integrity".equals(message) || "size".equals(message)) status.setText(t("更新包校验失败，请重新下载。", "Update verification failed. Download it again."));
            else status.setText(t("无法获取更新，请检查网络或稍后重试。", "Cannot retrieve the update. Check your network or try later."));
        });
    }
    private PackageInfo installed() throws PackageManager.NameNotFoundException { return getPackageManager().getPackageInfo(getPackageName(), flags()); }
    private static int flags() { return Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES; }
    private static long version(PackageInfo info) { return Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode; }
    private static HashSet<Signature> signers(PackageInfo info) {
        Signature[] signs = Build.VERSION.SDK_INT >= 28 ? info.signingInfo == null ? null : info.signingInfo.getApkContentsSigners() : info.signatures;
        return signs == null ? new HashSet<>() : new HashSet<>(Arrays.asList(signs));
    }
    private void verifyApk(File file, Asset expected) throws Exception {
        try (InputStream in = new FileInputStream(file)) { UpdatePolicy.copyVerified(in, new java.io.OutputStream() { @Override public void write(int b) {} @Override public void write(byte[] b, int offset, int len) {} }, expected.size, expected.hash, count -> {}); }
        PackageInfo archive = getPackageManager().getPackageArchiveInfo(file.getAbsolutePath(), flags()); PackageInfo current = installed();
        if (archive == null || !getPackageName().equals(archive.packageName) || version(archive) != expected.version ||
                version(archive) <= version(current) || signers(current).isEmpty() || !signers(current).equals(signers(archive)) ||
                archive.applicationInfo == null || archive.applicationInfo.minSdkVersion > Build.VERSION.SDK_INT) throw new IOException("APK identity");
    }
    private HttpURLConnection open(String address, boolean metadata) throws Exception {
        for (int redirects = 0; redirects < 6; redirects++) {
            if (closed || Thread.currentThread().isInterrupted()) throw new IOException("cancelled");
            if (metadata ? !UpdatePolicy.ENDPOINT.equals(address) : !UpdatePolicy.downloadUrl(address)) throw new IOException("host");
            HttpURLConnection next = (HttpURLConnection)new URL(address).openConnection(); connection = next;
            next.setInstanceFollowRedirects(false); next.setConnectTimeout(15000); next.setReadTimeout(30000);
            next.setRequestProperty("User-Agent", "StarPass-Android-Updater"); next.setRequestProperty("Accept", metadata ? "application/vnd.github+json" : "application/octet-stream");
            int code = next.getResponseCode();
            if (code >= 300 && code <= 399) { String location = next.getHeaderField("Location"); address = location == null ? "" : new URL(new URL(address), location).toString(); next.disconnect(); continue; }
            return next;
        }
        throw new IOException("redirects");
    }
    private void check() {
        if (busy) return;
        asset = null; ready = null; notes.setText(""); action.setVisibility(android.view.View.GONE); busy(true); progress.setIndeterminate(true);
        status.setText(t("正在检查…", "Checking…"));
        worker.submit(() -> {
            try {
                HttpURLConnection response = open(UpdatePolicy.ENDPOINT, true); int code = response.getResponseCode();
                if (code == 404) { ui(() -> { busy(false); status.setText(t("尚未发布正式更新", "No stable release has been published yet")); }); return; }
                if (code != 200) throw new IOException("HTTP");
                ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] buffer = new byte[8192];
                try (InputStream in = response.getInputStream()) { int n; while ((n = in.read(buffer)) != -1) { if (closed || bytes.size() + n > 2*1024*1024) throw new IOException("metadata size"); bytes.write(buffer,0,n); } }
                Asset found = select(new JSONObject(bytes.toString(StandardCharsets.UTF_8.name())), version(installed()), Build.SUPPORTED_ABIS);
                ui(() -> { busy(false); asset = found;
                    if (found == null) status.setText(t("当前没有适用于此设备的更新", "No update is available for this device"));
                    else { status.setText(found.title + " · " + Math.round(found.size / 1048576.0) + " MB"); notes.setText(found.notes); action.setText(t("下载更新", "Download update")); action.setVisibility(android.view.View.VISIBLE); }
                });
            } catch (Exception error) { fail(error); }
            finally { HttpURLConnection active = connection; if (active != null) active.disconnect(); }
        });
    }
    private void download() {
        if (busy || asset == null) return;
        Asset expected = asset; busy(true); progress.setIndeterminate(false); progress.setProgress(0); status.setText(t("正在下载…", "Downloading…"));
        worker.submit(() -> {
            File part = null;
            try {
                File directory = new File(getFilesDir(), "updates"); if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("storage");
                File destination = new File(directory, "update-" + expected.hash + ".apk");
                if (!destination.isFile()) {
                    if (directory.getUsableSpace() < expected.size + 16*1024*1024) throw new IOException("storage");
                    part = File.createTempFile("download-", ".part", directory);
                    HttpURLConnection response = open(expected.url, false); if (response.getResponseCode() != 200) throw new IOException("HTTP");
                    final long deadline = System.nanoTime() + 15L*60*1000000000; final int[] last = {-1};
                    try (InputStream input = response.getInputStream(); FileOutputStream output = new FileOutputStream(part)) {
                        UpdatePolicy.copyVerified(input, output, expected.size, expected.hash, count -> {
                            if (closed || System.nanoTime() > deadline) throw new IOException("cancelled");
                            int percent = (int)(count * 100 / expected.size); if (percent != last[0]) { last[0] = percent; ui(() -> progress.setProgress(percent)); }
                        }); output.getFD().sync();
                    }
                    verifyApk(part, expected);
                    if (!part.renameTo(destination)) throw new IOException("storage");
                } else {
                    try { verifyApk(destination, expected); }
                    catch (Exception invalid) { destination.delete(); throw invalid; }
                }
                // Only the current immutable package is retained; never touch profiles or keys.
                File[] obsolete = directory.listFiles();
                if (obsolete != null) for (File old : obsolete) if (!old.equals(destination) &&
                        old.getName().matches("update-[0-9a-f]{64}\\.apk")) old.delete();
                ui(() -> { ready = destination; busy(false); status.setText(t("已下载并通过校验", "Downloaded and verified")); action.setText(t("安装更新", "Install update")); });
            } catch (Exception error) { fail(error); }
            finally { if (part != null && part.exists()) part.delete(); HttpURLConnection active = connection; if (active != null) active.disconnect(); }
        });
    }
    private boolean running() {
        SessionController.Phase phase = ((PortalApplication)getApplication()).session().snapshot().phase;
        return (phase != SessionController.Phase.STOPPED && phase != SessionController.Phase.ERROR) || PhoneVpnService.isActive();
    }
    private void installRequested() {
        if (busy || ready == null || asset == null) return;
        if (running()) { status.setText(t("请先在概览中停止连接，再安装更新。", "Stop your connection in Overview before installing.")); return; }
        if (!getPackageManager().canRequestPackageInstalls()) {
            new AlertDialog.Builder(new ContextThemeWrapper(this, dark ? android.R.style.Theme_Material_Dialog_Alert : android.R.style.Theme_Material_Light_Dialog_Alert))
                .setTitle(t("允许安装更新", "Allow update installation"))
                .setMessage(t("请在系统设置中允许星渡安装应用，然后返回点击‘安装更新’。", "Allow StarPass to install apps in system settings, then return and tap Install update."))
                .setNegativeButton(t("取消", "Cancel"), null).setPositiveButton(t("打开设置", "Open settings"), (d,w) -> {
                    try { startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName()))); }
                    catch (android.content.ActivityNotFoundException error) { status.setText(t("此设备无法打开安装权限设置", "Install permission settings are unavailable")); }
                }).show(); return;
        }
        busy(true); File file = ready; Asset expected = asset;
        worker.submit(() -> { try { verifyApk(file, expected); ui(() -> {
            busy(false); if (running()) { status.setText(t("请先停止连接", "Stop your connection first")); return; }
            Uri uri = UpdateApkProvider.uri(file);
            Intent install = new Intent(Intent.ACTION_VIEW).setDataAndType(uri, UpdateApkProvider.MIME)
                .setClipData(ClipData.newRawUri("StarPass update", uri)).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            try { startActivity(install); status.setText(t("请在系统窗口确认安装；取消后可重试。", "Confirm installation in the system window. You can retry after cancelling.")); }
            catch (android.content.ActivityNotFoundException | SecurityException error) { status.setText(t("无法打开系统安装程序，请检查安装权限。", "Cannot open the system installer. Check installation permission.")); }
        }); } catch (Exception error) { ready = null; fail(error); } });
    }
    @Override public void onDestroy() {
        closed = true; HttpURLConnection active = connection; if (active != null) active.disconnect();
        worker.shutdownNow(); main.removeCallbacksAndMessages(null); super.onDestroy();
    }
}
