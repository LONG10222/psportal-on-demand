// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.ContextThemeWrapper;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import org.json.JSONObject;
import org.psportal.engine.mobile.Mobile;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.text.DateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** Simple home mirrors the current Apple clients; native service ownership is unchanged. */
public final class MainActivity extends Activity {
    private static final int REQUEST_NOTIFICATIONS = 101, REQUEST_LAN = 102;
    private static final String[] MODES = {"auto", "prefer", "fixed", "fastest"};
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService preparation = Executors.newSingleThreadExecutor();
    private final List<View> configurationViews = new ArrayList<>();
    private final List<Label> labels = new ArrayList<>();
    private SessionController session;
    private ScrollView scroll;
    private LinearLayout advanced;
    private EditText phone, portal, port, subscription, preferred, idle, threshold;
    private Spinner selection;
    private TextView status, network, metrics, address, accounting, engine, nodeSummary;
    private ProgressBar usage;
    private Button start, manualStart, stop, advancedToggle, loadNodes, testNodes, chooseNode, fastest;
    private Switch appearance;
    private HostConfig pendingConfig;
    private Future<?> pendingPreparation;
    private SessionController.Snapshot launchSnapshot;
    private boolean visible, english, dark, preparing, launchRequested, pendingAutomatic, clearingSubscription, addressChoiceOpen;
    private long preparationGeneration;
    private SubscriptionAccounting subscriptionInfo;

    private static final class Label {
        final TextView view; final String zh, en;
        Label(TextView view, String zh, String en) { this.view = view; this.zh = zh; this.en = en; }
    }
    private final Runnable renderTick = new Runnable() {
        @Override public void run() { if (visible) { render(); main.postDelayed(this, 500); } }
    };
    private SharedPreferences prefs() { return getSharedPreferences("ui", MODE_PRIVATE); }
    private String t(String zh, String en) { return english ? en : zh; }
    private Locale locale() { return english ? Locale.ENGLISH : Locale.SIMPLIFIED_CHINESE; }
    private Context dialogContext() { return new ContextThemeWrapper(this, dark ? android.R.style.Theme_Material_Dialog_Alert : android.R.style.Theme_Material_Light_Dialog_Alert); }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        english = prefs().getBoolean("english", false);
        dark = prefs().getBoolean("dark", true);
        session = ((PortalApplication)getApplication()).session();
        scroll = new ScrollView(this);
        LinearLayout layout = column();
        layout.setPadding(dp(20), dp(16), dp(20), dp(32));
        scroll.setFillViewport(true);
        scroll.addView(layout);
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        setContentView(scroll);
        LinearLayout heading = new LinearLayout(this);
        heading.setGravity(android.view.Gravity.CENTER_VERTICAL);
        TextView title = text(heading, "OnDemand", "OnDemand", 25, true, false);
        title.setLayoutParams(new LinearLayout.LayoutParams(0, -2, 1));
        Button language = button(heading, "English", "中文", false, v -> switchLanguage());
        language.setLayoutParams(new LinearLayout.LayoutParams(-2, dp(48)));
        layout.addView(heading);
        text(layout, "按需局域网代理", "On-demand LAN proxy", 14, false, true);

        section(layout, "当前网络", "Current network");
        network = text(card(layout), "正在识别网络", "Detecting network", 16, false, false);
        section(layout, "订阅", "Subscription");
        LinearLayout subscriptionCard = card(layout);
        subscription = input(subscriptionCard, "粘贴 HTTPS 订阅链接", "Paste HTTPS subscription URL", "",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        // setSingleLine() may replace the transformation installed by setInputType().
        subscription.setTransformationMethod(android.text.method.PasswordTransformationMethod.getInstance());
        subscription.setSaveEnabled(false);
        subscription.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        subscription.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            public void onTextChanged(CharSequence s, int start, int before, int count) {
                if (!clearingSubscription) { subscriptionInfo = null; renderAccounting(); }
            }
            public void afterTextChanged(Editable s) {}
        });
        accounting = text(subscriptionCard, "", "", 13, false, true);
        usage = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        usage.setMax(100); usage.setVisibility(View.GONE);
        subscriptionCard.addView(usage, new LinearLayout.LayoutParams(-1, dp(6)));
        start = button(subscriptionCard, "一键准备并启动", "Prepare & start", true, v -> beginStart(true));
        text(subscriptionCard, "自动识别真实局域网地址，优先保留端口 10081。允许当前 /24–/30 私网网段的设备连接。", "Detect the real LAN address and keep port 10081 when available. Allow devices on the current private /24–/30 subnet.", 13, false, true);
        text(subscriptionCard, "订阅链接仅留在本次内存，启动后清空，不保存到设置。套餐数据来自服务器响应头，非实时统计。", "The subscription URL stays in session memory, clears after Start and is not saved. Accounting is a server-header snapshot, not live traffic.", 12, false, true);

        section(layout, "运行状态", "Status");
        LinearLayout stateCard = card(layout);
        status = text(stateCard, "", "", 18, true, false);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        metrics = text(stateCard, "", "", 14, false, true);
        engine = text(stateCard, "原生 Mihomo 适配器 · 按需运行", "Native Mihomo adapters · on demand", 13, false, true);
        stop = button(stateCard, "停止监听", "Stop listener", false, v -> stopRequested());
        text(stateCard, "运行期间保留常驻通知，可在通知中停止。移出最近任务会停止服务；省电或厂商限制可能中断网络。", "A persistent notification provides Stop while running. Removing the app from Recents stops the service; battery or OEM controls may interrupt networking.", 12, false, true);

        section(layout, "设备 Wi-Fi 怎么设置", "Device Wi-Fi setup");
        LinearLayout guide = card(layout);
        address = text(guide, "准备后显示服务器和端口", "Server and port appear after preparation", 17, true, false);
        address.setTextIsSelectable(true);
        text(guide, "1. 让设备加入同一个可互通的 Wi-Fi\n2. 打开设备 Wi-Fi 设置 → HTTP 代理 → 手动\n3. 填写上方服务器和端口，认证关闭", "1. Join the same reachable Wi-Fi\n2. Open the device Wi-Fi settings → HTTP Proxy → Manual\n3. Enter the server and port above; leave authentication off", 14, false, false);
        text(guide, "IP 变化后需重新准备并更新设备设置。停止使用时，将设备 HTTP 代理恢复为关闭。仅支持 HTTP/HTTPS CONNECT，不保证 UDP 游戏或串流可用。", "Prepare again and update the device if the IP changes. Turn its HTTP proxy off when finished. HTTP/HTTPS CONNECT only; UDP games and streaming are not guaranteed.", 12, false, true);

        advancedToggle = button(layout, "高级设置 ▾", "Advanced settings ▾", false, v -> {
            advanced.setVisibility(advanced.getVisibility() == View.GONE ? View.VISIBLE : View.GONE);
        });
        advanced = card(layout); advanced.setVisibility(View.GONE);
        phone = input(advanced, "本机私网 IPv4", "Local private IPv4", prefs().getString("phone", ""), InputType.TYPE_CLASS_PHONE);
        Button choose = button(advanced, "选择本机地址", "Choose local address", false, v -> chooseAddress());
        configurationViews.add(choose);
        portal = input(advanced, "手动接入名单（设备 IPv4，逗号分隔）", "Manual client IPv4 allowlist (comma-separated)", prefs().getString("portal", ""), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        port = input(advanced, "代理端口", "Proxy port", prefs().getString("port", "10081"), InputType.TYPE_CLASS_NUMBER);
        text(advanced, "节点策略", "Node selection", 14, true, false);
        selection = new Spinner(this); selection.setMinimumHeight(dp(48)); advanced.addView(selection);
        configurationViews.add(selection); updateModes(prefs().getInt("mode", 0));
        preferred = input(advanced, "准确节点名称", "Exact node name", prefs().getString("preferred", ""), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        idle = input(advanced, "空闲后回收核心（秒）", "Release idle core after (seconds)", prefs().getString("idle", "60"), InputType.TYPE_CLASS_NUMBER);
        manualStart = button(advanced, "使用手动配置启动", "Start with manual settings", false, v -> beginStart(false));
        text(advanced, "运行中的节点", "Live nodes", 16, true, false);
        nodeSummary = text(advanced, "启动后可加载节点并测速", "Load and test nodes after starting", 13, false, true);
        loadNodes = button(advanced, "加载节点并测速", "Load & test nodes", false, v -> nodeAction("prepare", "", ""));
        testNodes = button(advanced, "重新测速", "Test latency again", false, v -> nodeAction("test", "", ""));
        chooseNode = button(advanced, "手动选择节点", "Select a node", false, v -> chooseLiveNode());
        threshold = input(advanced, "自动切换至少快多少毫秒（0–60000）", "Minimum latency improvement to switch (0–60000 ms)", prefs().getString("threshold", "50"), InputType.TYPE_CLASS_NUMBER);
        configurationViews.remove(threshold); // Live policy changes are allowed without restarting.
        fastest = button(advanced, "自动选择低延迟节点", "Use lowest-latency selection", false, v -> nodeAction("select", "fastest", ""));
        text(advanced, "测速会唤醒自有适配器并产生请求。自动低延迟策略周期测速，需要连续两轮改善并满足冷却期，避免频繁切换。", "Tests wake owned adapters and send probe requests. Lowest-latency selection probes periodically and requires two improving rounds plus a hold-down to avoid frequent switching.", 12, false, true);
        text(advanced, "Android 使用现有原生适配器引擎，不声称支持桌面完整 profile 规则或接管其他 Clash 应用。", "Android keeps the existing native adapter engine. It does not claim desktop full-profile rules or control another Clash app.", 12, false, true);
        appearance = new Switch(this); bind(appearance, "深色外观", "Dark appearance"); appearance.setChecked(dark);
        appearance.setPadding(dp(8), dp(12), dp(8), dp(12)); layout.addView(appearance);
        appearance.setOnCheckedChangeListener((view, checked) -> { dark = checked; prefs().edit().putBoolean("dark", dark).apply(); applyTheme(scroll); updateModes(selection.getSelectedItemPosition()); applySystemBars(); });
        button(layout, "开源许可与开发限制", "Licenses and development limits", false, v -> showLicenses());
        text(layout, "不修改系统代理、DNS、VPN 或防火墙。只在可信局域网使用。", "No changes to system proxy, DNS, VPN or firewall. Use only on trusted LANs.", 12, false, true);
        refreshNetwork(); renderAccounting(); applyTheme(scroll); applySystemBars(); render();
    }

    private LinearLayout column() { LinearLayout view = new LinearLayout(this); view.setOrientation(LinearLayout.VERTICAL); return view; }
    private LinearLayout card(LinearLayout parent) {
        LinearLayout card = column(); card.setTag("card"); card.setPadding(dp(16), dp(12), dp(16), dp(12));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2); lp.bottomMargin = dp(12); parent.addView(card, lp); return card;
    }
    private void section(LinearLayout parent, String zh, String en) { TextView label = text(parent, zh, en, 14, true, true); label.setPadding(dp(8), dp(20), 0, dp(10)); }
    private void bind(TextView view, String zh, String en) { labels.add(new Label(view, zh, en)); view.setText(t(zh, en)); }
    private TextView text(LinearLayout parent, String zh, String en, int size, boolean bold, boolean secondary) {
        TextView text = new TextView(this); bind(text, zh, en); text.setTextSize(size); text.setTag(secondary ? "secondary" : "text");
        if (bold) text.setTypeface(null, Typeface.BOLD); text.setPadding(0, dp(7), 0, dp(7));
        parent.addView(text, new LinearLayout.LayoutParams(-1, -2)); return text;
    }
    private EditText input(LinearLayout parent, String zh, String en, String value, int inputType) {
        TextView caption = text(parent, zh, en, 13, false, true);
        EditText input = new EditText(this); input.setId(View.generateViewId()); caption.setLabelFor(input.getId());
        input.setInputType(inputType); input.setSingleLine(true); input.setText(value); input.setTextSize(16);
        input.setMinimumHeight(dp(48)); input.setSaveEnabled(false);
        parent.addView(input, new LinearLayout.LayoutParams(-1, -2)); configurationViews.add(input); return input;
    }
    private Button button(LinearLayout parent, String zh, String en, boolean primary, View.OnClickListener listener) {
        Button button = new Button(this); bind(button, zh, en); button.setTag(primary ? "primary" : "button");
        button.setAllCaps(false); button.setMinHeight(dp(48)); button.setOnClickListener(listener);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2); lp.topMargin = dp(6); parent.addView(button, lp); return button;
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private String value(EditText input) { return input.getText().toString(); }
    private void applySystemBars() {
        getWindow().setStatusBarColor(dark ? Color.BLACK : Color.rgb(245, 247, 252));
        getWindow().setNavigationBarColor(dark ? Color.BLACK : Color.rgb(245, 247, 252));
        getWindow().getDecorView().setSystemUiVisibility(dark ? 0 : View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
    }
    private void applyTheme(View view) {
        int foreground = dark ? Color.rgb(242, 243, 247) : Color.rgb(26, 32, 46);
        int secondary = dark ? Color.rgb(170, 175, 187) : Color.rgb(88, 96, 112);
        int accent = dark ? Color.rgb(48, 138, 255) : Color.rgb(21, 92, 202);
        if (view == scroll) view.setBackgroundColor(dark ? Color.BLACK : Color.rgb(245, 247, 252));
        if ("card".equals(view.getTag())) { GradientDrawable background = new GradientDrawable(); background.setColor(dark ? Color.rgb(29, 30, 34) : Color.WHITE); background.setCornerRadius(dp(20)); view.setBackground(background); }
        if (view instanceof TextView) ((TextView)view).setTextColor(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled}, new int[]{}}, new int[]{dark ? Color.rgb(105, 110, 120) : Color.rgb(130, 136, 147), "secondary".equals(view.getTag()) ? secondary : foreground}));
        if (view instanceof Button) { boolean primary = "primary".equals(view.getTag()); view.setBackgroundTintList(ColorStateList.valueOf(primary ? accent : dark ? Color.rgb(46, 49, 57) : Color.rgb(229, 234, 244))); if (primary) ((Button)view).setTextColor(Color.WHITE); }
        if (view instanceof EditText) view.setBackgroundTintList(ColorStateList.valueOf(secondary));
        if (view instanceof ProgressBar) ((ProgressBar)view).setProgressTintList(ColorStateList.valueOf(accent));
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) applyTheme(((ViewGroup)view).getChildAt(i));
    }
    private void updateModes(int selected) {
        String[] names = { t("自动：香港 → 日本 → 其他", "Auto: Hong Kong → Japan → others"), t("首选，允许回退", "Prefer, with fallback"), t("固定，不自动换节点", "Fixed, no fallback"), t("自动低延迟", "Lowest latency") };
        ArrayAdapter<String> adapter = new ArrayAdapter<>(new ContextThemeWrapper(this, dark ? android.R.style.Theme_Material : android.R.style.Theme_Material_Light), android.R.layout.simple_spinner_item, names);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); selection.setAdapter(adapter); selection.setSelection(Math.min(MODES.length - 1, Math.max(0, selected)));
    }
    private void switchLanguage() {
        english = !english; prefs().edit().putBoolean("english", english).apply();
        for (Label label : labels) label.view.setText(t(label.zh, label.en));
        updateModes(selection.getSelectedItemPosition()); refreshNetwork(); renderAccounting(); render();
    }

    private boolean automaticNetworkAllowed() {
        ConnectivityManager manager = getSystemService(ConnectivityManager.class);
        NetworkCapabilities capabilities = manager.getNetworkCapabilities(manager.getActiveNetwork());
        return capabilities != null && !capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN) &&
                (capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET));
    }
    private void refreshNetwork() {
        List<NetworkAddresses.LocalAddress> addresses = NetworkAddresses.automaticAddresses();
        String description;
        if (!automaticNetworkAllowed()) description = t("请连接可互通的 Wi-Fi 或有线局域网", "Connect to a reachable Wi-Fi or Ethernet LAN");
        else if (addresses.isEmpty()) description = t("当前网段需使用高级手动配置", "This network needs advanced manual setup");
        else description = t("局域网 · ", "LAN · ") + addresses.get(0).address + (addresses.size() > 1 ? t(" · 多个地址，启动时选择", " · choose an address at Start") : "");
        network.setText(description);
    }
    private void chooseAddress() {
        List<String> addresses = NetworkAddresses.localPrivateIpv4();
        if (addresses.isEmpty()) { message(t("未找到私网 IPv4，请先连接可信 Wi-Fi。", "No private IPv4 found. Connect to trusted Wi-Fi first.")); return; }
        new AlertDialog.Builder(dialogContext()).setTitle(t("选择本机地址", "Choose local address"))
                .setItems(addresses.toArray(new String[0]), (dialog, item) -> phone.setText(addresses.get(item))).show();
    }
    private void beginStart(boolean automatic) {
        if (preparing || launchRequested || pendingConfig != null || addressChoiceOpen || !session.snapshot().canStart()) return;
        if (automatic) {
            List<NetworkAddresses.LocalAddress> addresses = NetworkAddresses.automaticAddresses();
            if (!automaticNetworkAllowed() || addresses.isEmpty()) {
                message(t("自动准备需要真实 Wi-Fi/有线私网 /24–/30。蜂窝网络不代表热点已开启；特殊网络请在高级设置中填写明确地址和设备名单。", "Automatic setup needs a real private Wi-Fi/Ethernet /24–/30 network. Cellular does not prove hotspot sharing; use explicit addresses and client allowlist in Advanced for other networks.")); return;
            }
            if (addresses.size() > 1) {
                String[] names = new String[addresses.size()];
                for (int i = 0; i < names.length; i++) names[i] = addresses.get(i).address + "/" + addresses.get(i).prefix + " · " + addresses.get(i).interfaceName;
                addressChoiceOpen = true; render();
                new AlertDialog.Builder(dialogContext()).setTitle(t("选择共享的局域网", "Choose the LAN to share"))
                        .setItems(names, (dialog, item) -> { addressChoiceOpen = false; configureStart(addresses.get(item)); })
                        .setOnDismissListener(dialog -> { addressChoiceOpen = false; render(); }).show();
                return;
            }
            configureStart(addresses.get(0));
        } else configureStart(null);
    }
    private void configureStart(NetworkAddresses.LocalAddress local) {
        if (preparing || launchRequested || pendingConfig != null || !session.snapshot().canStart()) return;
        try {
            String host = local == null ? value(phone).trim() : local.address;
            List<String> clients = local == null ? Arrays.asList(value(portal).trim().split("[,，\\s]+")) : LanSetup.clients(local.address, local.prefix);
            pendingConfig = new HostConfig(host, clients, value(port), value(subscription), MODES[selection.getSelectedItemPosition()], value(preferred), value(idle), Integer.parseInt(value(threshold)));
            if (!NetworkAddresses.isAssigned(host)) throw new IllegalArgumentException();
            pendingAutomatic = local != null;
        } catch (IllegalArgumentException invalid) {
            pendingConfig = null;
            message(t("请检查 HTTPS 订阅（443 端口）、本机与设备私网地址、代理端口和节点设置。订阅链接不会写入错误信息。", "Check the public HTTPS subscription (port 443), local/client private addresses, proxy port and node settings. The URL is never included in errors.")); return;
        }
        continueStart(); render();
    }
    private void cancelPending() {
        pendingConfig = null; preparing = false; preparationGeneration++;
        if (pendingPreparation != null) { pendingPreparation.cancel(true); pendingPreparation = null; }
        render();
    }
    private void continueStart() {
        if (!visible || pendingConfig == null) { pendingConfig = null; return; }
        if (Permissions.requiresLocalNetwork(this) && !Permissions.localNetworkGranted(this)) {
            new AlertDialog.Builder(dialogContext()).setMessage(t("允许本地网络访问，设备才能连接本机。授权前不会开始准备或监听。", "Allow local network access so the device can connect. Preparation and listening wait for permission."))
                    .setPositiveButton(t("继续", "Continue"), (dialog, which) -> requestPermissions(new String[]{Permissions.LOCAL_NETWORK}, REQUEST_LAN))
                    .setNegativeButton(t("取消", "Cancel"), (dialog, which) -> cancelPending()).setOnCancelListener(dialog -> cancelPending()).show(); return;
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            new AlertDialog.Builder(dialogContext()).setMessage(t("需要通知权限，以便运行时显示状态和停止按钮。", "Allow notifications to keep the running status and Stop action visible."))
                    .setPositiveButton(t("继续", "Continue"), (dialog, which) -> requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQUEST_NOTIFICATIONS))
                    .setNegativeButton(t("取消", "Cancel"), (dialog, which) -> cancelPending()).setOnCancelListener(dialog -> cancelPending()).show(); return;
        }
        NotificationManager notifications = getSystemService(NotificationManager.class);
        android.app.NotificationChannel channel = notifications.getNotificationChannel("portal_proxy");
        if (!notifications.areNotificationsEnabled() || channel != null && channel.getImportance() == NotificationManager.IMPORTANCE_NONE) {
            cancelPending(); message(t("请在 Android 设置中开启本应用通知，再重新启动。", "Enable this app's notifications in Android Settings, then start again.")); return;
        }
        prepareAndLaunch();
    }
    private void prepareAndLaunch() {
        final HostConfig requested = pendingConfig; pendingConfig = null;
        final boolean automatic = pendingAutomatic;
        final long generation = ++preparationGeneration; preparing = true; render();
        pendingPreparation = preparation.submit(() -> {
            HostConfig prepared = null; SubscriptionAccounting info = null;
            try {
                if (Thread.currentThread().isInterrupted()) return;
                if (!NetworkAddresses.isAssigned(requested.listenHost)) throw new IllegalArgumentException();
                int chosenPort = automatic ? LanSetup.choosePort(requested.listenHost, requested.listenPort) : requested.listenPort;
                prepared = new HostConfig(requested.listenHost, requested.allowedClients, String.valueOf(chosenPort), requested.subscriptionUrl, requested.selectionMode, requested.preferredNode, String.valueOf(requested.idleSeconds), requested.switchThresholdMs);
                if (Thread.currentThread().isInterrupted()) return;
                JSONObject raw = new JSONObject(Mobile.subscriptionInfo(requested.subscriptionUrl));
                info = new SubscriptionAccounting(raw.optString("upload", ""), raw.optString("download", ""), raw.optString("total", ""), raw.optString("expire", ""));
            } catch (Exception | LinkageError failure) { /* Never show native exception text or credentials. */ }
            final HostConfig ready = prepared; final SubscriptionAccounting accounting = info;
            main.post(() -> {
                if (generation != preparationGeneration || !visible || isFinishing() || isDestroyed()) return;
                preparing = false; pendingPreparation = null;
                if (ready == null || !NetworkAddresses.isAssigned(ready.listenHost) || automatic && !automaticNetworkAllowed()) {
                    message(t("准备失败：请检查局域网地址、可用端口和已打包的原生引擎。", "Preparation failed. Check the LAN address, available port and bundled native engine.")); render(); return;
                }
                subscriptionInfo = accounting; phone.setText(ready.listenHost); port.setText(String.valueOf(ready.listenPort));
                saveNonSecretFields(); renderAccounting(); launch(ready);
            });
        });
    }
    private void launch(HostConfig config) {
        prefs().edit().putBoolean("network_lost", false).apply();
        Intent intent = new Intent(this, ProxyService.class).setAction(ProxyService.ACTION_START)
                .putExtra(ProxyService.EXTRA_CONFIG, config.toJson(new java.io.File(getFilesDir(), "runtime").getAbsolutePath()))
                .putExtra(ProxyService.EXTRA_ADDRESS, config.listenHost).putExtra(ProxyService.EXTRA_PORT, config.listenPort);
        try { launchSnapshot = session.snapshot(); launchRequested = true; startForegroundService(intent); }
        catch (RuntimeException denied) { launchRequested = false; session.rejectedStart(); }
        clearingSubscription = true; subscription.setText(""); clearingSubscription = false;
        render();
    }
    private void stopRequested() {
        cancelPending();
        startService(new Intent(this, ProxyService.class).setAction(ProxyService.ACTION_STOP));
        launchRequested = false; render();
    }
    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode != REQUEST_NOTIFICATIONS && requestCode != REQUEST_LAN) return;
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED && pendingConfig != null && visible) continueStart();
        else { cancelPending(); if (visible) message(t("权限未获批准，代理保持停止。", "Permission was not granted. The proxy remains stopped.")); }
    }
    private void saveNonSecretFields() {
        prefs().edit().putString("phone", value(phone)).putString("portal", value(portal)).putString("port", value(port))
                .putInt("mode", selection.getSelectedItemPosition()).putString("preferred", value(preferred)).putString("idle", value(idle)).putString("threshold", value(threshold)).apply();
    }
    private void nodeAction(String action, String mode, String name) {
        int improvement;
        try { improvement = Integer.parseInt(value(threshold)); if (improvement < 0 || improvement > 60000) throw new NumberFormatException(); }
        catch (NumberFormatException invalid) { message(t("阈值需为 0–60000 毫秒。", "The threshold must be 0–60000 ms.")); return; }
        session.control(action, mode, name, improvement); render();
    }
    private static String safeNodeName(String name) {
        // Node names are server-controlled labels: bound them and reject URL-like secrets.
        if (name.length() > 256 || name.contains("://") || name.contains("?")) return "";
        for (int i = 0; i < name.length(); i++) if (Character.isISOControl(name.charAt(i)) || Character.getType(name.charAt(i)) == Character.FORMAT) return "";
        return name;
    }
    private void chooseLiveNode() {
        try {
            JSONObject state = new JSONObject(session.snapshot().nativeStatus);
            org.json.JSONArray nodes = state.optJSONArray("nodes"); if (nodes == null) return;
            List<String> names = new ArrayList<>(), labels = new ArrayList<>();
            for (int i = 0; i < Math.min(nodes.length(), 500); i++) {
                JSONObject node = nodes.optJSONObject(i); if (node == null) continue;
                String name = safeNodeName(node.optString("name", "")); if (name.isEmpty()) continue;
                names.add(name); Long delay = count(node, "delay_ms");
                labels.add((name.equals(state.optString("selected_node", "")) ? "✓ " : "") + name + " · " + (delay == null ? t("未测得 / 不可用", "Unmeasured / unavailable") : delay + " ms"));
            }
            if (names.isEmpty()) { message(t("先加载节点并测速。", "Load and test nodes first.")); return; }
            new AlertDialog.Builder(dialogContext()).setTitle(t("固定节点（不静默回退）", "Fixed node (no silent fallback)"))
                    .setItems(labels.toArray(new String[0]), (dialog, index) -> nodeAction("select", "fixed", names.get(index))).show();
        } catch (org.json.JSONException invalid) { message(t("节点状态暂不可用。", "Node status is unavailable.")); }
    }
    private static Long count(JSONObject state, String key) {
        Object value = state.opt(key); if (!(value instanceof Number)) return null;
        double raw = ((Number)value).doubleValue(); long number = ((Number)value).longValue();
        return number >= 0 && Double.isFinite(raw) && raw == number ? number : null;
    }
    private void render() {
        if (status == null) return;
        SessionController.Snapshot snapshot = session.snapshot();
        if (snapshot != launchSnapshot) launchRequested = false;
        boolean editable = snapshot.canStart() && pendingConfig == null && !preparing && !launchRequested && !addressChoiceOpen;
        for (View view : configurationViews) view.setEnabled(editable);
        start.setEnabled(editable); manualStart.setEnabled(editable);
        stop.setEnabled(preparing || pendingConfig != null || launchRequested || snapshot.isActive() && snapshot.phase != SessionController.Phase.STOPPING);
        JSONObject nativeState;
        try { nativeState = new JSONObject(snapshot.nativeStatus); } catch (org.json.JSONException invalid) { nativeState = new JSONObject(); }
        Boolean running = nativeState.opt("running") instanceof Boolean ? nativeState.optBoolean("running") : null;
        Long connections = count(nativeState, "active_connections");
        Long clients = count(nativeState, "connected_clients");
        boolean nodesAvailable = snapshot.phase == SessionController.Phase.RUNNING && nativeState.optBoolean("node_management", false);
        boolean nodeEditable = nodesAvailable && !session.commandPending();
        loadNodes.setEnabled(nodeEditable); testNodes.setEnabled(nodeEditable); chooseNode.setEnabled(nodeEditable); fastest.setEnabled(nodeEditable); threshold.setEnabled(!session.commandPending());
        String nodeText = t("启动后可加载节点并测速", "Load and test nodes after starting");
        if (nodesAvailable) {
            String selected = safeNodeName(nativeState.optString("selected_node", ""));
            String mode = nativeState.optString("selection_mode", "");
            if (!Arrays.asList(MODES).contains(mode)) mode = t("未提供", "Not provided");
            nodeText = t("当前节点：", "Selected: ") + (selected.isEmpty() ? t("尚未选择", "Not selected") : selected) + "\n" + t("策略：", "Policy: ") + mode;
            if (session.commandPending()) nodeText += "\n" + t("正在处理节点请求…", "Processing node request…");
            if (session.commandFailed()) nodeText += "\n" + t("节点操作失败，监听保持运行；请检查订阅和网络。", "Node action failed; the listener stays running. Check the subscription and network.");
        }
        nodeSummary.setText(nodeText);
        boolean hasError = !nativeState.optString("error", "").isEmpty();
        RuntimePresentation.State state = RuntimePresentation.state(snapshot.phase, preparing || pendingConfig != null || launchRequested, running, nativeState.optString("state", ""), connections, hasError);
        String display;
        switch (state) {
            case PREPARING: display = t("正在准备订阅信息与局域网监听…", "Preparing subscription info and LAN listener…"); break;
            case LISTENING: display = t("监听已就绪 · 等待设备接入", "Listening · waiting for a device"); break;
            case WAKING: display = t("正在唤醒上游核心…", "Waking the upstream core…"); break;
            case FORWARDING: display = t("设备使用中 · 正在转发", "Device in use · forwarding"); break;
            case READY: display = t("监听已就绪 · 核心待命", "Listening · core ready"); break;
            case STOPPING: display = t("正在停止并关闭连接…", "Stopping and closing connections…"); break;
            case ERROR: display = snapshot.phase == SessionController.Phase.FAULTED ? t("核心清理失败，请强行停止应用后重试", "Native cleanup failed. Force stop this app before retrying") : t("运行错误 · 请检查网络、端口和订阅后重试", "Runtime error · check network, port and subscription, then retry"); break;
            case UNKNOWN: display = t("监听状态暂不可用，正在等待真实数据", "Listener status unavailable; waiting for real data"); break;
            default: display = t("粘贴订阅后，点击一键准备并启动", "Paste a subscription, then tap Prepare & start");
        }
        if (snapshot.phase == SessionController.Phase.RUNNING && !snapshot.error.isEmpty())
            display = t("状态数据超出安全上限，暂时无法确认运行详情；仍可停止监听。", "Status exceeds the safety limit; runtime details are unavailable. Stop remains available.");
        if (!display.contentEquals(status.getText())) status.setText(display);
        String counts = "";
        if (snapshot.phase == SessionController.Phase.RUNNING) {
            counts = t("活动设备：", "Active devices: ") + (clients == null ? t("未提供", "Not provided") : clients) + t(" · 连接：", " · Connections: ") + (connections == null ? t("未提供", "Not provided") : connections);
            if (clients == null && count(nativeState, "active") != null) counts += "\n" + t("外部连接：", "External connections: ") + count(nativeState, "active");
            counts += "\n" + t("设备数仅统计连接到本程序的不同来源 IP，不是所有 Wi-Fi 设备。", "Devices count distinct source IPs connected to this app, not all Wi-Fi devices.");
        }
        metrics.setText(counts); metrics.setVisibility(counts.isEmpty() ? View.GONE : View.VISIBLE);
        boolean showAddress = snapshot.isActive() || launchRequested;
        String host = value(phone), number = value(port);
        address.setText(showAddress && !host.isEmpty() ? t("服务器：", "Server: ") + host + "\n" + t("端口：", "Port: ") + number : t("准备并启动后显示服务器和端口", "Server and port appear after preparation and Start"));
    }
    private void renderAccounting() {
        if (accounting == null) return;
        if (subscriptionInfo == null) {
            accounting.setText(t("准备后显示订阅流量与到期信息，未返回的字段显示“未提供”。", "Accounting appears after preparation. Missing server fields show Not provided."));
            if (usage != null) usage.setVisibility(View.GONE); return;
        }
        String missing = t("未提供", "Not provided");
        String expiry = missing;
        if (subscriptionInfo.expires != null) {
            Date date = new Date(subscriptionInfo.expires * 1000);
            expiry = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT, locale()).format(date);
            if (date.before(new Date())) expiry += t(" · 已到期", " · Expired");
        }
        accounting.setText(t("已用 / 总量：", "Used / total: ") + SubscriptionAccounting.bytes(subscriptionInfo.used, missing, locale()) + " / " + SubscriptionAccounting.bytes(subscriptionInfo.total, missing, locale()) + "\n" + t("剩余流量：", "Remaining: ") + SubscriptionAccounting.bytes(subscriptionInfo.remaining, missing, locale()) + "\n" + t("到期时间：", "Expires: ") + expiry + "\n" + t("服务器快照 · 非实时", "Server snapshot · not live"));
        usage.setVisibility(subscriptionInfo.percent() < 0 ? View.GONE : View.VISIBLE); usage.setProgress(Math.max(0, subscriptionInfo.percent()));
    }
    private void message(String text) { new AlertDialog.Builder(dialogContext()).setMessage(text).setPositiveButton(t("好", "OK"), null).show(); }
    private void showLicenses() {
        try {
            String[] files = getAssets().list("licenses"); if (files == null || files.length == 0) throw new java.io.IOException();
            StringBuilder contents = new StringBuilder();
            for (String file : files) try (InputStream input = getAssets().open("licenses/" + file); ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192]; int read;
                while ((read = input.read(buffer)) != -1) { bytes.write(buffer, 0, read); if (bytes.size() > 4_000_000) throw new java.io.IOException(); }
                contents.append(file).append("\n\n").append(new String(bytes.toByteArray(), StandardCharsets.UTF_8)).append("\n\n");
            }
            ScrollView scroll = new ScrollView(this); TextView text = new TextView(dialogContext()); text.setText(contents.toString()); text.setTextIsSelectable(true); text.setPadding(dp(20), dp(12), dp(20), dp(12)); scroll.addView(text);
            new AlertDialog.Builder(dialogContext()).setTitle(t("开源许可", "Open-source licenses")).setView(scroll).setPositiveButton(t("好", "OK"), null).show();
        } catch (java.io.IOException missing) { message(t("许可资源缺失，请重新构建后再分发。", "License assets are missing. Rebuild before distribution.")); }
    }
    @Override public void onStart() {
        super.onStart(); visible = true; refreshNetwork(); main.post(renderTick);
        if (prefs().getBoolean("network_lost", false)) { prefs().edit().putBoolean("network_lost", false).apply(); message(t("局域网地址已变化，代理已停止。请重新准备并更新设备设置。", "The LAN address changed and the proxy stopped. Prepare again and update the device.")); }
    }
    @Override public void onStop() {
        visible = false; pendingConfig = null; preparing = false; preparationGeneration++;
        if (pendingPreparation != null) { pendingPreparation.cancel(true); pendingPreparation = null; }
        main.removeCallbacks(renderTick); saveNonSecretFields();
        clearingSubscription = true; subscription.setText(""); clearingSubscription = false; super.onStop();
    }
    @Override public void onDestroy() { main.removeCallbacksAndMessages(null); preparation.shutdownNow(); super.onDestroy(); }
}
