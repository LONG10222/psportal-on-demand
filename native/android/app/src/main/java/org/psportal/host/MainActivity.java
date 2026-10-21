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
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.ColorFilter;
import android.graphics.PixelFormat;
import android.graphics.drawable.Drawable;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.net.VpnService;
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
import android.widget.ImageView;
import android.widget.ProgressBar;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import org.json.JSONObject;
import org.psportal.engine.androidmobile.Androidmobile;
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

/** Simple Chinese-first LAN-sharing home with explicit routing and lifecycle options. */
public final class MainActivity extends Activity {
    private static final int REQUEST_NOTIFICATIONS = 101, REQUEST_LAN = 102, REQUEST_PHONE_VPN = 103;
    private static final String[] MODES = {"auto", "prefer", "fixed", "fastest"};
    private static final String[] ROUTING_MODES = {"rule", "global", "direct"};
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService preparation = Executors.newSingleThreadExecutor();
    private final List<View> configurationViews = new ArrayList<>();
    private final List<Label> labels = new ArrayList<>();
    private SessionController session;
    private ScrollView scroll;
    private LinearLayout advanced, shell, about;
    private final LinearLayout[] pages = new LinearLayout[4];
    private final Button[] navigation = new Button[4];
    private int selectedPage;
    private TextView shareSteps;
    private EditText phone, portal, port, subscription, preferred, idle, threshold;
    private Spinner selection, routing;
    private RadioGroup productModes;
    private final int[] productModeIds = new int[ProductMode.values().length];
    private TextView productModeDescription;
    private TextView status, network, metrics, address, accounting, engine, nodeSummary, phoneVpnStatus, profileWarning;
    private ProgressBar usage;
    private Button start, manualStart, stop, repair, advancedToggle, loadNodes, testNodes, chooseNode, chooseGroup, fastest;
    private AlertDialog nodeDialog;
    private long nodeDialogSession, nodeUiGeneration;
    private Switch appearance, backgroundSharing, phoneApps, lanSharing;
    private HostConfig pendingConfig;
    private Future<?> pendingPreparation;
    private SessionController.Snapshot launchSnapshot;
    private boolean visible, english, dark, preparing, launchRequested, pendingAutomatic, clearingSubscription, addressChoiceOpen;
    private boolean vpnConsentPending, resumeAfterVpnConsent, vpnConsentGranted, showVpnConsentDenied;
    private boolean updatingProductMode;
    private long preparationGeneration;
    private SubscriptionAccounting subscriptionInfo;

    private static final class Label {
        final TextView view; final String zh, en;
        Label(TextView view, String zh, String en) { this.view = view; this.zh = zh; this.en = en; }
    }
    private final Runnable renderTick = new Runnable() {
        @Override public void run() { if (visible) { render(); main.postDelayed(this, 500); } }
    };
    private final Runnable networkTick = new Runnable() {
        @Override public void run() { if (visible) { refreshNetwork(); main.postDelayed(this, 2000); } }
    };
    private SharedPreferences prefs() { return getSharedPreferences("ui", MODE_PRIVATE); }
    private String t(String zh, String en) { return english ? en : zh; }
    private Locale locale() { return english ? Locale.ENGLISH : Locale.SIMPLIFIED_CHINESE; }
    private Context dialogContext() { return new ContextThemeWrapper(this, dark ? android.R.style.Theme_Material_Dialog_Alert : android.R.style.Theme_Material_Light_Dialog_Alert); }
    private boolean canChangeProductMode() {
        return ProductMode.canChange(session.snapshot().phase,
                pendingConfig != null || preparing || launchRequested || addressChoiceOpen || vpnConsentPending,
                PhoneVpnService.isActive());
    }
    private void syncProductMode() {
        if (updatingProductMode || productModes == null || lanSharing == null || phoneApps == null) return;
        ProductMode mode = ProductMode.fromInputs(lanSharing.isChecked(), phoneApps.isChecked());
        updatingProductMode = true;
        if (mode == null) productModes.clearCheck(); else productModes.check(productModeIds[mode.ordinal()]);
        updatingProductMode = false;
        productModeDescription.setText(mode == null ? t("全部接入已关闭。请选择一种使用模式后再启动。", "All inputs are off. Choose a use mode before starting.") : mode.shortDescription(english));
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        english = prefs().getBoolean("english", false);
        dark = prefs().getBoolean("dark", true);
        session = ((PortalApplication)getApplication()).session();
        shell = column();
        shell.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        setContentView(shell);
        LinearLayout heading = new LinearLayout(this); heading.setGravity(android.view.Gravity.CENTER_VERTICAL);
        heading.setPadding(dp(16), dp(4), dp(16), dp(4));
        TextView title = text(heading, "星渡 StarPass", "星渡 StarPass", 22, true, false);
        title.setLayoutParams(new LinearLayout.LayoutParams(0, -2, 1));
        Button language = button(heading, "English", "中文", false, v -> switchLanguage());
        language.setLayoutParams(new LinearLayout.LayoutParams(-2, dp(48)));
        Button help = button(heading, "帮助", "Help", false, v -> showUsageHelp());
        help.setTag("help"); help.setLayoutParams(new LinearLayout.LayoutParams(-2, dp(48)));
        shell.addView(heading);
        scroll = new ScrollView(this); scroll.setFillViewport(true);
        LinearLayout layout = column(); layout.setPadding(dp(16), dp(8), dp(16), dp(16));
        scroll.addView(layout); shell.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        for (int i = 0; i < pages.length; i++) { pages[i] = column(); pages[i].setTag("page_" + i); layout.addView(pages[i]); }
        LinearLayout home = pages[0], nodes = pages[1], sharing = pages[2], settings = pages[3];
        home.setTag("page_overview"); nodes.setTag("page_nodes"); sharing.setTag("page_sharing"); settings.setTag("page_settings");

        LinearLayout stateCard = card(home);
        status = text(stateCard, "已停止", "Stopped", 20, true, false);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        network = text(stateCard, "正在识别网络", "Detecting network", 13, false, true);
        metrics = text(stateCard, "", "", 14, false, true);
        phoneVpnStatus = text(stateCard, "", "", 13, false, true);
        profileWarning = text(stateCard, "", "", 12, false, true);
        LinearLayout modeCard = card(home);
        productModes = new RadioGroup(this); productModes.setTag("product_modes"); productModes.setOrientation(LinearLayout.HORIZONTAL);
        for (ProductMode mode : ProductMode.values()) {
            RadioButton choice = new RadioButton(this); choice.setId(View.generateViewId());
            productModeIds[mode.ordinal()] = choice.getId(); choice.setTag("product_mode_" + mode.name().toLowerCase(Locale.ROOT));
            bind(choice, mode.label(false), mode.label(true)); choice.setTextSize(14); choice.setMinimumHeight(dp(48));
            productModes.addView(choice, new RadioGroup.LayoutParams(0, -2, 1)); configurationViews.add(choice);
        }
        modeCard.addView(productModes);
        productModes.addOnLayoutChangeListener((view, left, top, right, bottom, oldLeft, oldTop, oldRight, oldBottom) -> updateProductModeLayout(right - left));
        productModeDescription = text(modeCard, "", "", 13, false, true);
        LinearLayout subscriptionCard = card(home);
        subscription = input(subscriptionCard, "订阅链接 · HTTPS", "Subscription link · HTTPS", "",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        subscription.setTransformationMethod(android.text.method.PasswordTransformationMethod.getInstance());
        subscription.setHint(t("在这里粘贴订阅链接", "Paste your subscription here"));
        subscription.setSaveEnabled(false);
        subscription.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        subscription.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            public void onTextChanged(CharSequence s, int start, int before, int count) {
                if (!clearingSubscription) { subscriptionInfo = null; renderAccounting(); }
            }
            public void afterTextChanged(Editable s) {}
        });
        TextView routingLabel = text(subscriptionCard, "分流", "Routing", 13, false, true);
        routing = new Spinner(this); routing.setId(View.generateViewId()); routing.setTag("routing_mode");
        routingLabel.setLabelFor(routing.getId()); routing.setMinimumHeight(dp(48)); subscriptionCard.addView(routing);
        configurationViews.add(routing); updateRoutingModes(routingIndex(prefs().getString("routing_mode", "rule")));
        start = button(subscriptionCard, "连接", "Connect", true, v -> beginStart(true));
        stop = button(subscriptionCard, "停止", "Stop", true, v -> stopRequested());
        accounting = text(subscriptionCard, "", "", 13, false, true);
        accounting.setOnClickListener(v -> showAccountingDetails());
        accounting.setContentDescription(t("查看订阅用量详情", "View subscription usage details"));
        usage = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal); usage.setMax(100); usage.setVisibility(View.GONE);
        subscriptionCard.addView(usage, new LinearLayout.LayoutParams(-1, dp(4)));

        section(nodes, "节点", "Proxies");
        LinearLayout nodeCard = card(nodes);
        nodeSummary = text(nodeCard, "连接后可加载节点", "Connect to load proxies", 14, false, true);
        loadNodes = button(nodeCard, "加载实时节点", "Load live nodes", false, v -> nodeAction("prepare", "", ""));
        testNodes = button(nodeCard, "重新测速", "Test latency again", false, v -> nodeAction("test", "", ""));
        chooseNode = button(nodeCard, "选择节点", "Select a node", false, v -> chooseLiveNode());
        chooseGroup = button(nodeCard, "选择策略组", "Select a group", false, v -> chooseLiveGroup());
        fastest = button(nodeCard, "自动选择低延迟节点", "Use lowest-latency selection", false, v -> nodeAction("select", "fastest", ""));

        section(sharing, "局域网共享", "LAN sharing");
        LinearLayout guide = card(sharing);
        address = text(guide, "连接后显示共享地址", "Connect to see the sharing address", 18, true, false); address.setTextIsSelectable(true);
        shareSteps = text(guide, "同一 Wi-Fi → 设备 HTTP 代理 → 手动填写地址和端口", "Same Wi-Fi → device HTTP proxy → enter address and port", 14, false, true);
        button(guide, "连接指南", "Connection guide", false, v -> showHelpTopic(1));

        section(settings, "接入", "Traffic inputs");
        LinearLayout inputCard = card(settings);
        lanSharing = new Switch(this); lanSharing.setTag("lan_enabled"); bind(lanSharing, "局域网共享", "LAN sharing");
        lanSharing.setChecked(prefs().getBoolean("lan_enabled", true)); lanSharing.setPadding(dp(8), dp(12), dp(8), dp(12)); inputCard.addView(lanSharing); configurationViews.add(lanSharing);
        phoneApps = new Switch(this); phoneApps.setTag("phone_apps"); bind(phoneApps, "代理本机应用", "Proxy phone apps");
        phoneApps.setChecked(PhoneVpnService.isRequested()); phoneApps.setPadding(dp(8), dp(12), dp(8), dp(12)); inputCard.addView(phoneApps); configurationViews.add(phoneApps);
        lanSharing.setOnCheckedChangeListener((view, checked) -> { prefs().edit().putBoolean("lan_enabled", checked).apply(); refreshNetwork(); render(); });
        phoneApps.setOnCheckedChangeListener((view, checked) -> {
            if (!checked && PhoneVpnService.isRequested()) PhoneVpnService.stop(this);
            else if (checked && (!session.snapshot().canStart() || PhoneVpnService.isActive())) {
                phoneApps.setChecked(false); return;
            }
            render();
        });
        productModes.setOnCheckedChangeListener((group, checkedId) -> {
            if (updatingProductMode) return;
            if (!canChangeProductMode()) { syncProductMode(); return; }
            for (ProductMode mode : ProductMode.values()) if (productModeIds[mode.ordinal()] == checkedId) {
                // Presets only update the next session's inputs. The existing
                // Start path still owns every permission and VPN consent check.
                updatingProductMode = true; vpnConsentGranted = false; resumeAfterVpnConsent = false;
                lanSharing.setChecked(mode.lanEnabled); phoneApps.setChecked(mode.phoneVpn);
                updatingProductMode = false; syncProductMode(); refreshNetwork(); render(); return;
            }
        });
        // End product-mode presets.
        backgroundSharing = new Switch(this); backgroundSharing.setTag("background_sharing"); bind(backgroundSharing, "允许后台运行", "Allow background operation");
        backgroundSharing.setChecked(prefs().getBoolean(BackgroundPolicy.PREFERENCE_KEY, BackgroundPolicy.DEFAULT_ALLOW_BACKGROUND));
        backgroundSharing.setPadding(dp(8), dp(12), dp(8), dp(12)); inputCard.addView(backgroundSharing); configurationViews.add(backgroundSharing);
        backgroundSharing.setOnCheckedChangeListener((view, checked) -> prefs().edit().putBoolean(BackgroundPolicy.PREFERENCE_KEY, checked).apply());
        advancedToggle = button(settings, "高级网络设置 ▾", "Advanced network settings ▾", false, v -> advanced.setVisibility(advanced.getVisibility() == View.GONE ? View.VISIBLE : View.GONE));
        advanced = card(settings); advanced.setVisibility(View.GONE);
        phone = input(advanced, "本机私网 IPv4", "Local private IPv4", prefs().getString("phone", ""), InputType.TYPE_CLASS_PHONE);
        Button choose = button(advanced, "选择本机地址", "Choose local address", false, v -> chooseAddress()); configurationViews.add(choose);
        portal = input(advanced, "接入设备 IPv4（逗号分隔）", "Client IPv4 allowlist (comma-separated)", prefs().getString("portal", ""), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        port = input(advanced, "代理端口", "Proxy port", prefs().getString("port", "10081"), InputType.TYPE_CLASS_NUMBER);
        text(advanced, "节点策略", "Node policy", 14, true, false);
        selection = new Spinner(this); selection.setMinimumHeight(dp(48)); advanced.addView(selection); configurationViews.add(selection); updateModes(prefs().getInt("mode", 0));
        preferred = input(advanced, "准确节点名称", "Exact node name", prefs().getString("preferred", ""), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        idle = input(advanced, "空闲回收（秒）", "Idle release (seconds)", prefs().getString("idle", "60"), InputType.TYPE_CLASS_NUMBER);
        threshold = input(advanced, "测速容差（毫秒）", "Latency tolerance (ms)", prefs().getString("threshold", "50"), InputType.TYPE_CLASS_NUMBER);
        manualStart = button(advanced, "使用手动配置启动", "Start with manual settings", false, v -> beginStart(false));
        repair = button(settings, "修复本应用网络", "Repair app network", false, v -> repairRequested());
        appearance = new Switch(this); appearance.setTag("appearance"); bind(appearance, "深色外观", "Dark appearance"); appearance.setChecked(dark);
        appearance.setPadding(dp(8), dp(12), dp(8), dp(12)); settings.addView(appearance);
        appearance.setOnCheckedChangeListener((view, checked) -> { dark = checked; prefs().edit().putBoolean("dark", dark).apply(); applyTheme(shell); updateModes(selection.getSelectedItemPosition()); updateRoutingModes(routing.getSelectedItemPosition()); updateNavigation(); applySystemBars(); });
        engine = text(settings, "内置 Mihomo", "Embedded Mihomo", 13, false, true);
        button(settings, "关于星渡", "About StarPass", false, v -> about.setVisibility(about.getVisibility() == View.GONE ? View.VISIBLE : View.GONE));
        about = card(settings); about.setVisibility(View.GONE); navigatorHero(about);
        button(about, "开源许可", "Open-source licenses", false, v -> showLicenses());
        LinearLayout navBar = new LinearLayout(this); navBar.setPadding(dp(8), dp(4), dp(8), dp(8)); shell.addView(navBar);
        String[] zh = {"概览", "节点", "共享", "设置"}, en = {"Overview", "Proxies", "Sharing", "Settings"};
        for (int i = 0; i < navigation.length; i++) { final int page = i; navigation[i] = button(navBar, zh[i], en[i], false, v -> showPage(page)); navigation[i].setTag("tab_" + i); navigation[i].setTextSize(13); navigation[i].setLayoutParams(new LinearLayout.LayoutParams(0, -2, 1)); }
        refreshNetwork(); renderAccounting(); applyTheme(shell); applySystemBars(); showPage(0); render();
    }

    /** Navigation changes presentation only; it never edits session input or secret text. */
    private void showPage(int page) {
        selectedPage = Math.max(0, Math.min(page, pages.length - 1));
        for (int i = 0; i < pages.length; i++) pages[i].setVisibility(i == selectedPage ? View.VISIBLE : View.GONE);
        scroll.scrollTo(0, 0); updateNavigation();
    }
    private void updateNavigation() {
        for (int i = 0; i < navigation.length; i++) if (navigation[i] != null) {
            boolean selected = i == selectedPage; navigation[i].setSelected(selected);
            navigation[i].setBackgroundTintList(ColorStateList.valueOf(selected ? Color.rgb(92, 77, 174) : dark ? Color.rgb(30, 34, 54) : Color.rgb(240, 241, 246)));
            navigation[i].setTextColor(selected ? Color.WHITE : dark ? Color.rgb(177, 191, 209) : Color.rgb(82, 98, 119));
        }
    }
    private void showUsageHelp() {
        String[] topics = english ? new String[]{"Modes and routing", "Connect a LAN device", "Phone VPN", "Background operation", "Subscriptions and usage", "Proxy selection", "Repair connections"} :
                new String[]{"用途与分流", "连接局域网设备", "本机 VPN", "后台运行", "订阅与用量", "节点选择", "连接修复"};
        new AlertDialog.Builder(dialogContext()).setTitle(t("使用帮助", "Help")).setItems(topics, (dialog, index) -> showHelpTopic(index)).show();
    }
    private void showHelpTopic(int topic) {
        String body;
        switch (topic) {
            case 0: body = ProductMode.GAME.description(english) + "\n\n" + ProductMode.MIXED.description(english) + "\n\n" + ProductMode.CLASH.description(english) + "\n\n" +
                    t("规则按订阅规则分流；全局使用所选代理；直连从本机访问。仅影响明确接入本应用的流量。", "Rule follows subscription rules, Global uses the selected proxy, and Direct connects from this phone. Only explicitly selected traffic is affected."); break;
            case 1: body = t("1. 设备加入同一可互通的 Wi-Fi。\n2. 在设备 Wi-Fi 设置中选择 HTTP 代理 → 手动。\n3. 填写共享页地址和端口，认证关闭。\n4. 在设备打开网页，再验证目标游戏功能。\n\nIP 变化后重新连接并更新地址。停止使用后关闭设备的手动 HTTP 代理。仅支持 HTTP/HTTPS CONNECT TCP，不保证 UDP 游戏或串流可用。", "1. Join the same reachable Wi-Fi.\n2. Open device Wi-Fi settings → HTTP Proxy → Manual.\n3. Enter the Sharing address and port; leave authentication off.\n4. Open a webpage on the device, then test the intended game feature.\n\nUpdate device settings after an IP change. Turn its HTTP proxy off when finished. HTTP/HTTPS CONNECT only; UDP games and streaming are not guaranteed. A connection does not prove Internet access; verify on the device."); break;
            case 2: body = t("本机代理默认关闭，开启后仍需点击连接并通过 Android VPN 授权；其他 VPN 正在运行时会提示冲突。本应用不会接管第二个 VPN。\n\n支持 TCP 和节点支持的 UDP；不支持 ICMP。代理本机时，访问家中设备等局域网功能可能不可用，直连模式也一样。关闭本机代理可恢复原来的联网方式。", "Phone proxying defaults off. Connect requires Android VPN consent; another active VPN produces a conflict message. This app does not take over a second VPN.\n\nTCP and supported-node UDP are supported; ICMP (ping) is unsupported. UDP unsupported by the selected node is blocked, without direct fallback. Local-device apps may fail while phone VPN is active, including in Direct mode. Turn it off to restore normal networking."); break;
            case 3: body = t("允许后台运行时，回到桌面、锁屏或移出最近任务可继续本次代理；关闭后离开页面即停止。运行通知提供停止按钮。Android 强行停止、省电和厂商限制仍可能中断服务。", "Background operation continues this session on Home, lock and removal from Recents. When disabled, leaving the screen stops proxying. The notification provides Stop; force-stop, battery and OEM controls may still interrupt service."); break;
            case 4: body = t("订阅仅保留在本次内存，不保存到设置；连接后和离开应用时清空。用量来自服务器响应头快照，点击用量可查看获取时间。缺失字段不代表无限流量。", "The subscription stays in session memory and is not saved to settings. It clears after Connect and when leaving the app. Usage is a server-header snapshot; tap it for retrieval time. Missing fields do not mean unlimited data."); break;
            case 5: body = t("先连接，再在节点页加载实时节点。加载会唤醒核心，测速会产生探测请求。完整订阅使用已有策略组；只可选择手动组的已有路线。连接使用中或本机 VPN 开启时不能切换路线。", "Connect, then load live nodes in Proxies. Loading wakes the core and latency tests send probes. Full profiles keep their policy groups; only existing manual-group choices can be selected. Route changes wait until connections and phone VPN are off. Choices survive idle core release for this session and reset after Stop."); break;
            default: body = t("在设置中选择“修复本应用网络”，停止本应用代理、清理隧道并重新检测网络，不自动重连、不修改系统 DNS/Wi-Fi，也不关闭其他 VPN。局域网设备仍需关闭其手动 HTTP 代理。", "Choose Repair app network in Settings to stop this app, clean up its tunnel and check the network. This does not reconnect, change system DNS/Wi-Fi or stop other VPNs. LAN devices must turn off their manual HTTP proxy.");
        }
        ScrollView detail = new ScrollView(this); TextView copy = new TextView(this); copy.setText(body); copy.setTextColor(dark ? Color.rgb(240, 244, 250) : Color.rgb(27, 39, 56)); copy.setTextSize(15); copy.setPadding(dp(22), dp(12), dp(22), dp(12)); detail.addView(copy);
        new AlertDialog.Builder(dialogContext()).setTitle(t("使用说明", "Usage guide")).setView(detail).setPositiveButton(t("好", "OK"), null).show();
    }

    /** Static decorative artwork only: never polls, animates or handles input. */
    private final class NavigatorBackdrop extends Drawable {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        @Override public void draw(Canvas canvas) {
            RectF bounds = new RectF(getBounds());
            paint.setShader(new android.graphics.LinearGradient(bounds.left, bounds.top, bounds.right, bounds.bottom,
                    new int[]{Color.rgb(26, 28, 64), Color.rgb(40, 43, 87), Color.rgb(29, 61, 83)},
                    null, android.graphics.Shader.TileMode.CLAMP));
            canvas.drawRoundRect(bounds, dp(22), dp(22), paint); paint.setShader(null);
            int saved = canvas.save();
            android.graphics.Path clip = new android.graphics.Path();
            clip.addRoundRect(bounds, dp(22), dp(22), android.graphics.Path.Direction.CW);
            canvas.clipPath(clip);
            paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(dp(1));
            paint.setColor(Color.rgb(82, 88, 134));
            float cx = bounds.right - dp(48), cy = bounds.centerY();
            canvas.drawCircle(cx, cy, dp(82), paint); canvas.drawCircle(cx, cy, dp(116), paint);
            paint.setStyle(Paint.Style.FILL); paint.setColor(Color.rgb(178, 197, 230));
            // Deterministic stars avoid motion and never cover the text's left region.
            float[][] stars = {{.71f,.13f},{.94f,.24f},{.89f,.83f},{.65f,.91f},{.54f,.09f}};
            for (float[] star : stars) canvas.drawCircle(bounds.left + bounds.width() * star[0],
                    bounds.top + bounds.height() * star[1], dp(1), paint);
            canvas.restoreToCount(saved);
        }
        @Override public void setAlpha(int alpha) { /* Opaque, static decorative surface. */ }
        @Override public void setColorFilter(ColorFilter filter) { /* No runtime image treatment. */ }
        @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
    }
    private void navigatorHero(LinearLayout parent) {
        LinearLayout hero = new LinearLayout(this); hero.setTag("navigator_hero");
        hero.setGravity(android.view.Gravity.CENTER_VERTICAL); hero.setPadding(dp(18), dp(16), dp(18), dp(16));
        hero.setBackground(new NavigatorBackdrop());
        LinearLayout copy = column();
        TextView eyebrow = text(copy, "STARPASS · 星海航线", "STARPASS · STARSEA", 12, true, false);
        eyebrow.setTag("hero_secondary");
        TextView name = text(copy, "星海领航员", "Your starsea navigator", 23, true, false); name.setTag("hero_text");
        TextView subtitle = text(copy, "让连接简单一点。\n先选用途，再准备出发。",
                "A calmer way to connect.\nChoose your use, then get ready.", 14, false, false); subtitle.setTag("hero_secondary");
        hero.addView(copy, new LinearLayout.LayoutParams(0, -2, 1));
        ImageView mark = new ImageView(this); mark.setImageResource(R.mipmap.ic_launcher);
        mark.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        mark.setScaleType(ImageView.ScaleType.FIT_CENTER);
        LinearLayout.LayoutParams portrait = new LinearLayout.LayoutParams(dp(104), dp(104));
        portrait.setMarginStart(dp(12)); hero.addView(mark, portrait);
        LinearLayout.LayoutParams placement = new LinearLayout.LayoutParams(-1, -2);
        placement.topMargin = dp(14); parent.addView(hero, placement);
        hero.addOnLayoutChangeListener((view, left, top, right, bottom, oldLeft, oldTop, oldRight, oldBottom) -> {
            boolean stacked = right - left < dp(320) || getResources().getConfiguration().fontScale > 1.2f;
            int orientation = stacked ? LinearLayout.VERTICAL : LinearLayout.HORIZONTAL;
            if (hero.getOrientation() == orientation) return;
            hero.setOrientation(orientation);
            copy.setLayoutParams(stacked ? new LinearLayout.LayoutParams(-1, -2) : new LinearLayout.LayoutParams(0, -2, 1));
            LinearLayout.LayoutParams imageLayout = new LinearLayout.LayoutParams(dp(104), dp(104));
            imageLayout.setMarginStart(stacked ? 0 : dp(12)); imageLayout.topMargin = stacked ? dp(10) : 0;
            imageLayout.gravity = android.view.Gravity.END; mark.setLayoutParams(imageLayout);
        });
    }

    private LinearLayout column() { LinearLayout view = new LinearLayout(this); view.setOrientation(LinearLayout.VERTICAL); return view; }
    private LinearLayout card(LinearLayout parent) {
        LinearLayout card = column(); card.setTag("card"); card.setPadding(dp(18), dp(16), dp(18), dp(16));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2); lp.bottomMargin = dp(12); parent.addView(card, lp); return card;
    }
    private void section(LinearLayout parent, String zh, String en) { TextView label = text(parent, zh, en, 16, true, false); label.setPadding(dp(8), dp(20), 0, dp(10)); }
    private void bind(TextView view, String zh, String en) { labels.add(new Label(view, zh, en)); view.setText(t(zh, en)); }
    private TextView text(LinearLayout parent, String zh, String en, int size, boolean bold, boolean secondary) {
        TextView text = new TextView(this); bind(text, zh, en); text.setTextSize(size); text.setTag(secondary ? "secondary" : "text");
        if (bold) text.setTypeface(null, Typeface.BOLD); text.setPadding(0, dp(7), 0, dp(7)); text.setLineSpacing(dp(2), 1.08f);
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
        button.setAllCaps(false); button.setMinHeight(dp(primary ? 56 : 48));
        if (primary) button.setTypeface(null, Typeface.BOLD); button.setOnClickListener(listener);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2); lp.topMargin = dp(6); parent.addView(button, lp); return button;
    }
    /** Presentation only: keep large text and narrow phones from clipping mode names. */
    private void updateProductModeLayout(int width) {
        boolean stacked = width < dp(310) || getResources().getConfiguration().fontScale > 1.2f;
        int orientation = stacked ? LinearLayout.VERTICAL : LinearLayout.HORIZONTAL;
        if (productModes.getOrientation() == orientation) return;
        productModes.setOrientation(orientation);
        for (int i = 0; i < productModes.getChildCount(); i++)
            productModes.getChildAt(i).setLayoutParams(stacked ?
                    new RadioGroup.LayoutParams(-1, -2) : new RadioGroup.LayoutParams(0, -2, 1));
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private String value(EditText input) { return input.getText().toString(); }
    private void applySystemBars() {
        getWindow().setStatusBarColor(dark ? Color.rgb(19, 22, 43) : Color.rgb(246, 245, 252));
        getWindow().setNavigationBarColor(dark ? Color.rgb(19, 22, 43) : Color.rgb(246, 245, 252));
        getWindow().getDecorView().setSystemUiVisibility(dark ? 0 : View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
    }
    private void applyTheme(View view) {
        int foreground = dark ? Color.rgb(240, 244, 250) : Color.rgb(27, 39, 56);
        int secondary = dark ? Color.rgb(177, 191, 209) : Color.rgb(82, 98, 119);
        int accent = Color.rgb(92, 77, 174);
        if (view == scroll || view == shell) view.setBackgroundColor(dark ? Color.rgb(19, 22, 43) : Color.rgb(246, 245, 252));
        if ("card".equals(view.getTag())) { GradientDrawable background = new GradientDrawable(); background.setColor(dark ? Color.rgb(31, 35, 59) : Color.WHITE); background.setCornerRadius(dp(18)); background.setStroke(dp(1), dark ? Color.rgb(57, 62, 91) : Color.rgb(220, 218, 237)); view.setBackground(background); }
        if (view instanceof TextView) ((TextView)view).setTextColor(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled}, new int[]{}}, new int[]{dark ? Color.rgb(105, 110, 120) : Color.rgb(130, 136, 147), "secondary".equals(view.getTag()) ? secondary : foreground}));
        if (view instanceof TextView && "hero_text".equals(view.getTag())) ((TextView)view).setTextColor(Color.WHITE);
        if (view instanceof TextView && "hero_secondary".equals(view.getTag())) ((TextView)view).setTextColor(Color.rgb(207, 213, 240));
        if (view instanceof Button) { boolean primary = "primary".equals(view.getTag()); view.setBackgroundTintList(ColorStateList.valueOf(primary ? accent : dark ? Color.rgb(46, 48, 78) : Color.rgb(233, 230, 247))); if (primary) ((Button)view).setTextColor(Color.WHITE); }
        if (view instanceof EditText) {
            view.setBackgroundTintList(ColorStateList.valueOf(secondary));
            ((EditText)view).setHintTextColor(secondary);
        }
        if (view instanceof RadioButton) ((RadioButton)view).setButtonTintList(new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{dark ? Color.rgb(112, 174, 255) : accent, secondary}));
        if (view instanceof ProgressBar) ((ProgressBar)view).setProgressTintList(ColorStateList.valueOf(accent));
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) applyTheme(((ViewGroup)view).getChildAt(i));
    }
    private void updateModes(int selected) {
        String[] names = { t("自动：订阅策略 / 节点回退", "Auto: profile policies / node fallback"), t("首选节点，故障时回退", "Prefer a node, fall back on failure"), t("固定，不自动换节点", "Fixed, no fallback"), t("自动低延迟", "Lowest latency") };
        ArrayAdapter<String> adapter = new ArrayAdapter<>(new ContextThemeWrapper(this, dark ? android.R.style.Theme_Material : android.R.style.Theme_Material_Light), android.R.layout.simple_spinner_item, names);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); selection.setAdapter(adapter); selection.setSelection(Math.min(MODES.length - 1, Math.max(0, selected)));
    }
    private static int routingIndex(String mode) {
        for (int i = 0; i < ROUTING_MODES.length; i++) if (ROUTING_MODES[i].equals(mode)) return i;
        return 0;
    }
    private String routingLabel(String mode) {
        if ("rule".equals(mode)) return t("规则", "Rule");
        if ("global".equals(mode)) return t("全局", "Global");
        if ("direct".equals(mode)) return t("直连", "Direct");
        return t("未提供", "Not provided");
    }
    private void updateRoutingModes(int selected) {
        String[] names = {routingLabel("rule"), routingLabel("global"), routingLabel("direct")};
        ArrayAdapter<String> adapter = new ArrayAdapter<>(new ContextThemeWrapper(this, dark ? android.R.style.Theme_Material : android.R.style.Theme_Material_Light), android.R.layout.simple_spinner_item, names);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        routing.setAdapter(adapter); routing.setSelection(Math.min(ROUTING_MODES.length - 1, Math.max(0, selected)));
    }
    private void switchLanguage() {
        english = !english; prefs().edit().putBoolean("english", english).apply();
        for (Label label : labels) label.view.setText(t(label.zh, label.en));
        subscription.setHint(t("在这里粘贴订阅链接", "Paste your subscription here"));
        accounting.setContentDescription(t("查看订阅用量详情", "View subscription usage details"));
        updateModes(selection.getSelectedItemPosition()); updateRoutingModes(routing.getSelectedItemPosition()); refreshNetwork(); renderAccounting(); render(); updateNavigation();
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
        if (lanSharing != null && !lanSharing.isChecked()) description = t("仅代理本机应用时，无需局域网地址；请确保网络可用", "Phone-app-only mode needs no LAN address; keep an Internet connection available");
        else if (!automaticNetworkAllowed() && !PhoneVpnService.isActive()) description = t("请连接可互通的 Wi-Fi 或有线局域网", "Connect to a reachable Wi-Fi or Ethernet LAN");
        else if (addresses.isEmpty()) description = t("当前网段需使用高级手动配置", "This network needs advanced manual setup");
        else description = t("局域网 · ", "LAN · ") + addresses.get(0).address + (addresses.size() > 1 ? t(" · 多个地址，启动时选择", " · choose an address at Start") : "");
        if (!description.contentEquals(network.getText())) network.setText(description);
    }
    private void chooseAddress() {
        List<String> addresses = NetworkAddresses.localPrivateIpv4();
        if (addresses.isEmpty()) { message(t("未找到私网 IPv4，请先连接可信 Wi-Fi。", "No private IPv4 found. Connect to trusted Wi-Fi first.")); return; }
        new AlertDialog.Builder(dialogContext()).setTitle(t("选择本机地址", "Choose local address"))
                .setItems(addresses.toArray(new String[0]), (dialog, item) -> phone.setText(addresses.get(item))).show();
    }
    private void showVpnConflict() {
        new AlertDialog.Builder(dialogContext())
                .setTitle(t("请先关闭其他 VPN", "Close the other VPN first"))
                .setMessage(t("Android 同一用户通常只能运行一个 VPN。请先在系统设置中关闭已有 VPN，再返回点击启动。本次没有启动；修复本应用网络只清理本应用。", "Android permits one active VPN per user/profile. Close the existing VPN in Settings, return and press Start. Nothing started. Repair app network cleans up this app only."))
                .setPositiveButton(t("打开 VPN 设置", "Open VPN settings"), (dialog, which) -> {
                    try { startActivity(new Intent(android.provider.Settings.ACTION_VPN_SETTINGS)); }
                    catch (RuntimeException unavailable) { message(t("请手动打开系统设置 → VPN。", "Open system Settings → VPN manually.")); }
                }).setNegativeButton(t("取消", "Cancel"), null).show();
    }
    private void repairRequested() {
        nodeUiGeneration++; dismissNodeDialog(); cancelPending();
        phoneApps.setChecked(false); PhoneVpnService.stop(this);
        launchRequested = false;
        try { startService(new Intent(this, ProxyService.class).setAction(ProxyService.ACTION_REPAIR)); }
        catch (RuntimeException denied) { message(t("无法请求清理，请在系统设置中强行停止本应用后重试。", "Cleanup could not be requested. Force stop this app in Settings and retry.")); }
        refreshNetwork(); render();
    }
    private void beginStart(boolean automatic) {
        if (preparing || launchRequested || pendingConfig != null || addressChoiceOpen || PhoneVpnService.isActive() || !session.snapshot().canStart()) return;
        if (!lanSharing.isChecked() && !phoneApps.isChecked()) return;
        if (phoneApps.isChecked() && PhoneVpnService.hasVpnConflict(this)) {
            showVpnConflict(); return;
        }
        vpnConsentGranted = false;
        if (!lanSharing.isChecked()) { configureStart(null); return; }
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
        if (preparing || launchRequested || pendingConfig != null || PhoneVpnService.isActive() || !session.snapshot().canStart()) return;
        try {
            boolean shareLan = lanSharing.isChecked();
            String host = !shareLan ? "" : local == null ? value(phone).trim() : local.address;
            List<String> clients = !shareLan ? java.util.Collections.emptyList() : local == null ? Arrays.asList(value(portal).trim().split("[,，\\s]+")) : LanSetup.clients(local.address, local.prefix);
            pendingConfig = new HostConfig(host, clients, shareLan ? value(port) : "10081", value(subscription), MODES[selection.getSelectedItemPosition()], value(preferred), value(idle), Integer.parseInt(value(threshold)), ROUTING_MODES[routing.getSelectedItemPosition()], shareLan, phoneApps.isChecked());
            if (shareLan && !NetworkAddresses.isAssigned(host)) throw new IllegalArgumentException();
            pendingAutomatic = shareLan && local != null;
        } catch (IllegalArgumentException invalid) {
            pendingConfig = null;
            message(t("请检查 HTTPS 订阅（443 端口）、本机与设备私网地址、代理端口和节点设置。订阅链接不会写入错误信息。", "Check the public HTTPS subscription (port 443), local/client private addresses, proxy port and node settings. The URL is never included in errors.")); return;
        }
        continueStart(); render();
    }
    private void cancelPending() {
        pendingConfig = null; preparing = false; preparationGeneration++; resumeAfterVpnConsent = false;
        if (pendingPreparation != null) { pendingPreparation.cancel(true); pendingPreparation = null; }
        render();
    }
    private void continueStart() {
        if (!visible || pendingConfig == null) { pendingConfig = null; return; }
        if (pendingConfig.lanEnabled && Permissions.requiresLocalNetwork(this) && !Permissions.localNetworkGranted(this)) {
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
        if (phoneApps.isChecked()) {
            if (PhoneVpnService.hasVpnConflict(this)) {
                cancelPending(); showVpnConflict(); return;
            }
            if (!vpnConsentGranted) {
                try {
                    Intent consent = VpnService.prepare(this);
                    if (consent != null) {
                        vpnConsentPending = true;
                        startActivityForResult(consent, REQUEST_PHONE_VPN);
                        render(); return;
                    }
                    vpnConsentGranted = true;
                } catch (RuntimeException unavailable) {
                    vpnConsentPending = false; phoneApps.setChecked(false); cancelPending();
                    message(t("Android 无法申请 VPN 授权，本次未启动。可关闭本机选项，仅使用局域网共享。", "Android could not request VPN consent. Nothing started. Turn off phone-app proxying to use LAN sharing alone.")); return;
                }
            }
        }
        prepareAndLaunch();
    }
    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_PHONE_VPN) return;
        vpnConsentPending = false;
        if (resultCode == RESULT_OK && pendingConfig != null && phoneApps.isChecked()) {
            vpnConsentGranted = true;
            if (visible) continueStart(); else resumeAfterVpnConsent = true;
        } else {
            phoneApps.setChecked(false); vpnConsentGranted = false; cancelPending();
            showVpnConsentDenied = true;
            if (visible) showVpnConsentDenied();
        }
        render();
    }
    private void showVpnConsentDenied() {
        showVpnConsentDenied = false;
        message(t("未授权 VPN，本次未启动。请选择局域网共享，或重新开启本机选项后再试。", "VPN consent was not granted; nothing started. Choose LAN sharing, or enable phone-app proxying again to retry."));
    }
    private void prepareAndLaunch() {
        final HostConfig requested = pendingConfig; pendingConfig = null;
        final boolean automatic = pendingAutomatic;
        final long generation = ++preparationGeneration; preparing = true; render();
        pendingPreparation = preparation.submit(() -> {
            HostConfig prepared = null; SubscriptionAccounting info = null;
            try {
                if (Thread.currentThread().isInterrupted()) return;
                if (requested.lanEnabled && !NetworkAddresses.isAssigned(requested.listenHost)) throw new IllegalArgumentException();
                int chosenPort = automatic ? LanSetup.choosePort(requested.listenHost, requested.listenPort) : requested.listenPort;
                prepared = new HostConfig(requested.listenHost, requested.allowedClients, String.valueOf(chosenPort), requested.subscriptionUrl, requested.selectionMode, requested.preferredNode, String.valueOf(requested.idleSeconds), requested.switchThresholdMs, requested.routingMode, requested.lanEnabled, requested.phoneVpn);
                if (Thread.currentThread().isInterrupted()) return;
                JSONObject raw = new JSONObject(Androidmobile.subscriptionInfo(requested.subscriptionUrl));
                info = new SubscriptionAccounting(raw.optString("upload", ""), raw.optString("download", ""), raw.optString("total", ""), raw.optString("expire", ""), System.currentTimeMillis() / 1000);
            } catch (Exception | LinkageError failure) { /* Never show native exception text or credentials. */ }
            final HostConfig ready = prepared; final SubscriptionAccounting accounting = info;
            main.post(() -> {
                if (generation != preparationGeneration || !visible || isFinishing() || isDestroyed()) return;
                preparing = false; pendingPreparation = null;
                if (ready == null || ready.lanEnabled && !NetworkAddresses.isAssigned(ready.listenHost) || automatic && !automaticNetworkAllowed()) {
                    message(t("准备失败：请检查局域网地址、可用端口和已打包的原生引擎。", "Preparation failed. Check the LAN address, available port and bundled native engine.")); render(); return;
                }
                subscriptionInfo = accounting;
                if (ready.lanEnabled) { phone.setText(ready.listenHost); port.setText(String.valueOf(ready.listenPort)); }
                saveNonSecretFields(); renderAccounting(); launch(ready);
            });
        });
    }
    private void launch(HostConfig config) {
        if (config.phoneVpn) {
            try {
                if (!vpnConsentGranted || VpnService.prepare(this) != null || PhoneVpnService.hasVpnConflict(this)) {
                    phoneApps.setChecked(false); vpnConsentGranted = false;
                    message(t("VPN 授权或连接状态已变化，本次未启动。请检查后重试。", "VPN consent or connection state changed; nothing started. Check it and retry.")); render(); return;
                }
            } catch (RuntimeException unavailable) {
                phoneApps.setChecked(false); vpnConsentGranted = false;
                message(t("无法确认 Android VPN 授权，本次未启动。", "Android VPN consent could not be verified; nothing started.")); render(); return;
            }
        }
        prefs().edit().putBoolean("network_lost", false).apply();
        Intent intent = new Intent(this, ProxyService.class).setAction(ProxyService.ACTION_START)
                .putExtra(ProxyService.EXTRA_CONFIG, config.toJson(new java.io.File(getFilesDir(), "runtime").getAbsolutePath()))
                .putExtra(ProxyService.EXTRA_ADDRESS, config.listenHost).putExtra(ProxyService.EXTRA_PORT, config.listenPort)
                .putExtra(ProxyService.EXTRA_PHONE_APPS, config.phoneVpn && vpnConsentGranted)
                .putExtra(ProxyService.EXTRA_LAN_ENABLED, config.lanEnabled);
        try { launchSnapshot = session.snapshot(); launchRequested = true; startForegroundService(intent); }
        catch (RuntimeException denied) { launchRequested = false; session.rejectedStart(); }
        clearingSubscription = true; subscription.setText(""); clearingSubscription = false;
        render();
    }
    private void stopRequested() {
        nodeUiGeneration++;
        dismissNodeDialog();
        cancelPending(); PhoneVpnService.stop(this);
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
                .putBoolean("lan_enabled", lanSharing.isChecked()).putString("routing_mode", ROUTING_MODES[routing.getSelectedItemPosition()]).putBoolean(BackgroundPolicy.PREFERENCE_KEY, backgroundSharing.isChecked())
                .putInt("mode", selection.getSelectedItemPosition()).putString("preferred", value(preferred)).putString("idle", value(idle)).putString("threshold", value(threshold)).apply();
    }
    private void nodeAction(String action, String mode, String name) {
        nodeAction(session.sessionId(), action, mode, name);
    }
    private void nodeAction(long sessionId, String action, String mode, String name) {
        int improvement;
        try { improvement = Integer.parseInt(value(threshold)); if (improvement < 0 || improvement > 60000) throw new NumberFormatException(); }
        catch (NumberFormatException invalid) { message(t("阈值需为 0–60000 毫秒。", "The threshold must be 0–60000 ms.")); return; }
        session.control(sessionId, action, mode, name, improvement); render();
    }
    private static String safeNodeName(String name) {
        return RuntimeNodePresentation.safeName(name);
    }
    private void chooseLiveNode() {
        nodeUiGeneration++;
        final long sessionId = session.sessionId();
        if (!canSelectInSession(sessionId)) return;
        try {
            JSONObject state = new JSONObject(session.snapshot().nativeStatus);
            org.json.JSONArray nodes = state.optJSONArray("nodes"); if (nodes == null) return;
            List<String> names = new ArrayList<>(), labels = new ArrayList<>();
            for (int i = 0; i < Math.min(nodes.length(), 500); i++) {
                JSONObject node = nodes.optJSONObject(i); if (node == null) continue;
                String name = safeNodeName(node.optString("name", "")); if (name.isEmpty()) continue;
                names.add(name); Long delay = count(node, "delay_ms");
                Boolean healthy = node.opt("healthy") instanceof Boolean ? node.optBoolean("healthy") : null;
                labels.add((name.equals(state.optString("selected_node", "")) ? "✓ " : "") + name + " · " + RuntimeNodePresentation.latency(delay, healthy, english));
            }
            if (names.isEmpty()) { message(t("先加载节点并测速。", "Load and test nodes first.")); return; }
            showNodeDialog(sessionId, t("固定节点（不静默回退）", "Fixed node (no silent fallback)"), labels,
                    index -> { if (canSelectInSession(sessionId)) nodeAction(sessionId, "select", "fixed", names.get(index)); });
        } catch (org.json.JSONException invalid) { message(t("节点状态暂不可用。", "Node status is unavailable.")); }
    }
    private boolean canSelectInSession(long sessionId) {
        if (!visible || isFinishing() || isDestroyed() || sessionId != session.sessionId()) return false;
        SessionController.Snapshot snapshot = session.snapshot();
        try {
            JSONObject state = new JSONObject(snapshot.nativeStatus);
            return RuntimeNodePresentation.canSelect(snapshot.phase, session.commandPending(), count(state, "active_connections"), PhoneVpnService.isActive());
        } catch (org.json.JSONException invalid) { return false; }
    }
    private void dismissNodeDialog() {
        AlertDialog current = nodeDialog; nodeDialog = null;
        if (current != null) current.dismiss();
    }
    private void showNodeDialog(long sessionId, String title, List<String> labels, java.util.function.IntConsumer chosen) {
        if (!canSelectInSession(sessionId)) return;
        dismissNodeDialog();
        AlertDialog dialog = new AlertDialog.Builder(dialogContext()).setTitle(title)
                .setItems(labels.toArray(new String[0]), (view, index) -> chosen.accept(index))
                .setNegativeButton(t("取消", "Cancel"), null).create();
        nodeDialog = dialog; nodeDialogSession = sessionId;
        dialog.setOnDismissListener(view -> { if (nodeDialog == dialog) nodeDialog = null; });
        dialog.show();
    }
    private void chooseLiveGroup() {
        nodeUiGeneration++;
        final long sessionId = session.sessionId();
        if (!canSelectInSession(sessionId)) return;
        try {
            JSONObject state = new JSONObject(session.snapshot().nativeStatus);
            org.json.JSONArray groups = state.optJSONArray("policy_groups");
            if (!state.optBoolean("group_management", false) || groups == null) return;
            List<String> names = new ArrayList<>(), labels = new ArrayList<>();
            for (int i = 0; i < Math.min(groups.length(), 257); i++) {
                JSONObject group = groups.optJSONObject(i); if (group == null) continue;
                String name = safeNodeName(group.optString("name", ""));
                Boolean selectable = group.opt("selectable") instanceof Boolean ? group.optBoolean("selectable") : null;
                if (name.isEmpty() || !RuntimeNodePresentation.selectableGroup(selectable, count(group, "choice_count"))) continue;
                String selected = safeNodeName(group.optString("selected", ""));
                names.add(name); labels.add(name + " → " + (selected.isEmpty() ? t("未提供", "Not provided") : selected));
            }
            if (names.isEmpty()) { message(t("当前没有可手动选择的策略组，请先加载实时节点。", "No manual select groups are available. Load live nodes first.")); return; }
            showNodeDialog(sessionId, t("选择手动策略组", "Choose a manual select group"), labels,
                    index -> loadGroupChoices(sessionId, names.get(index)));
        } catch (org.json.JSONException invalid) { message(t("策略组状态暂不可用。", "Policy-group status is unavailable.")); }
    }
    private void loadGroupChoices(long sessionId, String groupName) {
        if (!canSelectInSession(sessionId)) return;
        final long uiGeneration = nodeUiGeneration;
        session.groupChoices(sessionId, groupName, raw -> {
            if (uiGeneration != nodeUiGeneration || !canSelectInSession(sessionId)) return;
            try {
                JSONObject state = new JSONObject(raw);
                org.json.JSONArray choices = state.optJSONArray("choices");
                if (!groupName.equals(state.optString("group", "")) || choices == null || choices.length() == 0 || choices.length() > 1256)
                    throw new org.json.JSONException("Unavailable group choices");
                List<String> names = new ArrayList<>(), labels = new ArrayList<>();
                for (int i = 0; i < choices.length(); i++) {
                    Object item = choices.opt(i); if (!(item instanceof String)) continue;
                    String name = safeNodeName((String)item); if (name.isEmpty()) continue;
                    names.add(name); labels.add((name.equals(state.optString("selected", "")) ? "✓ " : "") + name);
                }
                if (names.isEmpty()) throw new org.json.JSONException("Unavailable group choices");
                showNodeDialog(sessionId, groupName, labels, index -> {
                    if (canSelectInSession(sessionId)) { session.selectGroup(sessionId, groupName, names.get(index)); render(); }
                });
            } catch (org.json.JSONException invalid) {
                message(t("策略组选择暂不可用，请重新加载后重试。", "Group choices are unavailable. Load live nodes and retry."));
            }
        });
        render();
    }
    private static Long count(JSONObject state, String key) {
        Object value = state.opt(key); if (!(value instanceof Number)) return null;
        double raw = ((Number)value).doubleValue(); long number = ((Number)value).longValue();
        return number >= 0 && Double.isFinite(raw) && raw == number ? number : null;
    }
    private void render() {
        if (status == null) return;
        syncProductMode();
        SessionController.Snapshot snapshot = session.snapshot();
        if (nodeDialog != null && !canSelectInSession(nodeDialogSession)) dismissNodeDialog();
        if (snapshot != launchSnapshot) launchRequested = false;
        boolean editable = snapshot.canStart() && !PhoneVpnService.isActive() && pendingConfig == null && !preparing && !launchRequested && !addressChoiceOpen;
        for (View view : configurationViews) view.setEnabled(editable);
        // Phone routing may be stopped independently while LAN sharing continues.
        // Turning it back on requires a new stopped-session Start and consent check.
        phoneApps.setEnabled(editable || snapshot.phase == SessionController.Phase.RUNNING && phoneApps.isChecked());
        boolean hasSelectedTraffic = lanSharing.isChecked() || phoneApps.isChecked();
        start.setEnabled(editable && hasSelectedTraffic); manualStart.setEnabled(editable && hasSelectedTraffic);
        repair.setEnabled(snapshot.phase != SessionController.Phase.STOPPING);
        stop.setEnabled(preparing || pendingConfig != null || launchRequested || PhoneVpnService.isActive() || snapshot.isActive() && snapshot.phase != SessionController.Phase.STOPPING);
        JSONObject nativeState;
        try { nativeState = new JSONObject(snapshot.nativeStatus); } catch (org.json.JSONException invalid) { nativeState = new JSONObject(); }
        Boolean running = nativeState.opt("running") instanceof Boolean ? nativeState.optBoolean("running") : null;
        String activeMode = nativeState.optString("routing_mode", "");
        String coreName = "mihomo-full-core".equals(nativeState.optString("engine", "")) ? t("内置 Mihomo 完整核心", "Embedded Mihomo full core") : t("核心状态未提供", "Core status not provided");
        engine.setText(snapshot.isActive() ? coreName + " · " + t("模式：", "Mode: ") + routingLabel(activeMode) : t("内置代理引擎 · 启动后显示实际模式", "Embedded proxy engine · applied mode appears after Start"));
        phoneVpnStatus.setText(phoneVpnDescription());
        boolean vpnFeedback = phoneApps.isChecked() || PhoneVpnService.isRequested() || vpnConsentPending ||
                Arrays.asList("consent_required", "permission_denied", "revoked", "vpn_conflict", "no_network", "core_unavailable", "start_failed").contains(PhoneVpnService.stateCode());
        phoneVpnStatus.setVisibility(vpnFeedback ? View.VISIBLE : View.GONE);
        boolean showStop = preparing || pendingConfig != null || launchRequested || PhoneVpnService.isActive() || snapshot.isActive();
        start.setVisibility(showStop ? View.GONE : View.VISIBLE); stop.setVisibility(showStop ? View.VISIBLE : View.GONE);
        String overrideWarning = profileOverrides(nativeState);
        profileWarning.setText(overrideWarning); profileWarning.setVisibility(overrideWarning.isEmpty() ? View.GONE : View.VISIBLE);
        Long connections = count(nativeState, "active_connections");
        Long clients = count(nativeState, "connected_clients");
        boolean nodesAvailable = snapshot.phase == SessionController.Phase.RUNNING && nativeState.optBoolean("node_management", false);
        boolean nodeEditable = snapshot.phase == SessionController.Phase.RUNNING && !session.commandPending();
        boolean canSelectRoute = RuntimeNodePresentation.canSelect(snapshot.phase, session.commandPending(), connections, PhoneVpnService.isActive());
        boolean canSelectNode = nodesAvailable && canSelectRoute;
        loadNodes.setEnabled(nodeEditable); testNodes.setEnabled(nodeEditable); chooseNode.setEnabled(canSelectNode); fastest.setEnabled(canSelectNode); threshold.setEnabled(editable);
        chooseGroup.setEnabled(canSelectRoute && nativeState.optBoolean("group_management", false));
        String nodeText = snapshot.phase == SessionController.Phase.RUNNING && !nodesAvailable ?
                t("订阅规则与自动策略由核心管理。加载后可查看并选择手动策略组中的已有路线。", "The core manages this profile’s rules and automatic policies. Load live nodes to inspect and choose existing routes in manual select groups.") :
                t("启动后可加载节点并测速", "Load and test nodes after starting");
        if (nodesAvailable) {
            String selected = safeNodeName(nativeState.optString("selected_node", ""));
            String mode = nativeState.optString("selection_mode", "");
            if (!Arrays.asList(MODES).contains(mode)) mode = t("未提供", "Not provided");
            nodeText = t("当前路线 / 策略组：", "Selected route / group: ") + (selected.isEmpty() ? t("尚未选择", "Not selected") : selected) + "\n" + t("策略：", "Policy: ") + mode;
        }
        if (snapshot.phase == SessionController.Phase.RUNNING) {
            if (!canSelectRoute && !session.commandPending()) nodeText += "\n" + t("连接使用中、本机 VPN 开启或状态未知时不可切换路线。", "Route changes wait until there are no connections or phone VPN and status is available.");
            if (session.commandPending()) nodeText += "\n" + t("正在处理节点 / 策略组请求…", "Processing node / group request…");
            if (session.commandFailed()) nodeText += "\n" + t("节点 / 策略组操作失败，会话保持运行；请检查订阅和网络。", "Node / group action failed; the session stays running. Check the subscription and network.");
        }
        String groupSummary = policyGroups(nativeState);
        if (!groupSummary.isEmpty()) nodeText += "\n" + groupSummary;
        nodeSummary.setText(nodeText);
        boolean hasError = !nativeState.optString("error", "").isEmpty();
        RuntimePresentation.State state = RuntimePresentation.state(snapshot.phase, preparing || pendingConfig != null || launchRequested, running, nativeState.optString("state", ""), connections, hasError);
        String display;
        switch (state) {
            case PREPARING: display = vpnConsentPending ? t("等待 Android VPN 授权，尚未启动…", "Awaiting Android VPN consent; nothing has started…") : t("正在准备订阅信息与所选代理…", "Preparing subscription info and selected proxy options…"); break;
            case LISTENING: display = nativeState.optBoolean("lan_enabled", lanSharing.isChecked()) ? t("监听已就绪 · 等待设备接入", "Listening · waiting for a device") : t("代理核心已就绪 · 本机 VPN 状态见下方", "Core ready · phone VPN status is shown below"); break;
            case WAKING: display = t("正在唤醒上游核心…", "Waking the upstream core…"); break;
            case FORWARDING: display = t("设备使用中 · 正在转发", "Device in use · forwarding"); break;
            case READY: display = nativeState.optBoolean("lan_enabled", lanSharing.isChecked()) ? t("监听已就绪 · 核心待命", "Listening · core ready") : t("代理核心已就绪 · 本机 VPN 状态见下方", "Core ready · phone VPN status is shown below"); break;
            case STOPPING: display = t("正在停止并关闭连接…", "Stopping and closing connections…"); break;
            case ERROR: display = snapshot.phase == SessionController.Phase.FAULTED ? t("核心清理失败，请强行停止应用后重试", "Native cleanup failed. Force stop this app before retrying") : t("运行错误 · 请检查网络、端口和订阅后重试", "Runtime error · check network, port and subscription, then retry"); break;
            case UNKNOWN: display = t("监听状态暂不可用，正在等待真实数据", "Listener status unavailable; waiting for real data"); break;
            default: display = t("已停止", "Stopped");
        }
        String profileError = RuntimePresentation.profileError(nativeState.optString("error_code", ""), english);
        if (hasError && !profileError.isEmpty()) display = profileError;
        if (snapshot.phase == SessionController.Phase.RUNNING && !snapshot.error.isEmpty())
            display = t("状态数据超出安全上限，暂时无法确认运行详情；仍可停止监听。", "Status exceeds the safety limit; runtime details are unavailable. Stop remains available.");
        if (state == RuntimePresentation.State.STOPPED && prefs().getBoolean("network_lost", false))
            display = t("网络已变化或断开，代理已停止。请重新准备，并更新局域网设备地址。", "The network changed or disconnected and proxying stopped. Prepare again and update LAN client addresses.");
        if (!display.contentEquals(status.getText())) status.setText(display);
        String counts = "";
        if (snapshot.phase == SessionController.Phase.RUNNING) {
            counts = t("局域网设备：", "LAN devices: ") + (clients == null ? t("未提供", "Not provided") : clients) + t(" · 连接：", " · Connections: ") + (connections == null ? t("未提供", "Not provided") : connections);
            if (clients == null && count(nativeState, "active") != null) counts += "\n" + t("外部连接：", "External connections: ") + count(nativeState, "active");

        }
        if (!nativeState.optBoolean("lan_enabled", lanSharing.isChecked())) counts = "";
        metrics.setText(counts); metrics.setVisibility(counts.isEmpty() ? View.GONE : View.VISIBLE);
        boolean showAddress = snapshot.phase == SessionController.Phase.RUNNING && Boolean.TRUE.equals(running) && nativeState.optBoolean("lan_enabled", lanSharing.isChecked());
        shareSteps.setVisibility(showAddress ? View.VISIBLE : View.GONE);
        String host = value(phone), number = value(port);
        address.setText(showAddress && !host.isEmpty() ? t("服务器：", "Server: ") + host + "\n" + t("端口：", "Port: ") + number : !lanSharing.isChecked() ? t("局域网共享已关闭，不开放代理端口", "LAN sharing is off; no LAN proxy port is open") : t("连接后显示共享地址", "Connect to see the sharing address"));
    }
    private String profileOverrides(JSONObject state) {
        org.json.JSONArray settings = state.optJSONArray("ignored_profile_settings");
        if (settings == null || settings.length() == 0) return "";
        java.util.LinkedHashSet<String> names = new java.util.LinkedHashSet<>();
        for (int i = 0; i < Math.min(settings.length(), 64); i++)
            names.add(RuntimePresentation.settingLabel(settings.optString(i, ""), english));
        if (settings.length() > 64) names.add(RuntimePresentation.settingLabel("", english));
        String warning = t("订阅设置已由本应用覆盖：", "Profile settings overridden by this app: ") + String.join(t("、", ", "), names);
        if (names.contains(RuntimePresentation.settingLabel("dns", english)) || names.contains(RuntimePresentation.settingLabel("hosts", english)) || names.contains(RuntimePresentation.settingLabel("sniffer", english)))
            warning += t("。DNS、Hosts 或嗅探差异可能影响原订阅的分流结果。", ". DNS, hosts or sniffing differences may change how the original profile routes traffic.");
        return warning;
    }
    private String policyGroups(JSONObject state) {
        org.json.JSONArray groups = state.optJSONArray("policy_groups");
        if (groups == null || groups.length() == 0) return "";
        StringBuilder result = new StringBuilder(t("实际策略组：", "Live policy groups:"));
        String owner = safeNodeName(state.optString("selected_group", ""));
        if (!owner.isEmpty()) result.append("\n").append(t("顶层选择组：", "Top-level selection group: ")).append(owner);
        for (int i = 0; i < Math.min(groups.length(), 20); i++) {
            JSONObject group = groups.optJSONObject(i); if (group == null) continue;
            String name = safeNodeName(group.optString("name", "")); if (name.isEmpty()) continue;
            String selected = safeNodeName(group.optString("selected", ""));
            result.append("\n").append(name).append(" → ").append(selected.isEmpty() ? t("当前选择未提供", "Current selection not provided") : selected);
        }
        if (groups.length() > 20) result.append("\n").append(t("仅显示前 20 个策略组", "Showing the first 20 policy groups"));
        return result.toString();
    }
    private String phoneVpnDescription() {
        String state = PhoneVpnService.stateCode();
        switch (state) {
            case "starting": return t("本机应用：正在建立 VPN…", "Phone apps: establishing VPN…");
            case "running": return t("本机应用：VPN 已开启（本应用自身除外）", "Phone apps: VPN on (this app is excluded)");
            case "stopping": return t("本机应用：正在停止 VPN…", "Phone apps: stopping VPN…");
            case "consent_required": case "permission_denied": case "revoked":
                return t("本机应用：VPN 授权未获批准或已撤销", "Phone apps: VPN consent is missing or revoked");
            case "vpn_conflict": return t("本机应用：其他 VPN 冲突，未接管流量", "Phone apps: another VPN conflicts; traffic is not captured");
            case "no_network": return t("本机应用：没有可用网络，VPN 未连接", "Phone apps: no usable network; VPN is not connected");
            case "core_unavailable": case "start_failed": return t("本机应用：VPN 启动失败，请停止后重试", "Phone apps: VPN start failed; stop and retry");
            default: return vpnConsentPending ? t("本机应用：等待 Android VPN 授权", "Phone apps: awaiting Android VPN consent") : t("本机应用：VPN 已关闭，普通应用不经此代理", "Phone apps: VPN off; ordinary apps do not use this proxy");
        }
    }
    private void renderAccounting() {
        if (accounting == null) return;
        if (subscriptionInfo == null) {
            accounting.setText(""); accounting.setVisibility(View.GONE);
            if (usage != null) usage.setVisibility(View.GONE); return;
        }
        accounting.setVisibility(View.VISIBLE);
        String missing = t("未提供", "Not provided");
        String expiry = missing;
        if (subscriptionInfo.expires != null) {
            Date date = new Date(subscriptionInfo.expires * 1000);
            expiry = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT, locale()).format(date);
            if (date.before(new Date())) expiry += t(" · 已到期", " · Expired");
        }
        accounting.setText(SubscriptionAccounting.bytes(subscriptionInfo.used, missing, locale()) + " / " + SubscriptionAccounting.bytes(subscriptionInfo.total, missing, locale()) +
                "\n" + t("到期：", "Expires: ") + expiry + t(" · 服务器快照", " · Server snapshot"));
        usage.setVisibility(subscriptionInfo.percent() < 0 ? View.GONE : View.VISIBLE); usage.setProgress(Math.max(0, subscriptionInfo.percent()));
    }
    private void showAccountingDetails() {
        if (subscriptionInfo == null) return;
        String missing = t("未提供", "Not provided");
        String updated = subscriptionInfo.updatedAt == null ? missing : DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT, locale()).format(new Date(subscriptionInfo.updatedAt * 1000));
        message(t("剩余流量：", "Remaining: ") + SubscriptionAccounting.bytes(subscriptionInfo.remaining, missing, locale()) + "\n" + t("获取时间：", "Retrieved: ") + updated + "\n" + t("服务器快照 · 非实时", "Server snapshot · not live"));
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
        super.onStart(); visible = true; main.post(networkTick); main.post(renderTick);
        if (resumeAfterVpnConsent) { resumeAfterVpnConsent = false; continueStart(); }
        if (showVpnConsentDenied) showVpnConsentDenied();
        if (prefs().getBoolean("network_lost", false)) { prefs().edit().putBoolean("network_lost", false).apply(); message(t("网络已变化或断开，代理已停止。请重新准备；使用局域网共享时更新设备地址。", "The network changed or disconnected and proxying stopped. Prepare again; update client addresses when sharing over LAN.")); }
    }
    @Override public void onStop() {
        visible = false;
        nodeUiGeneration++;
        dismissNodeDialog();
        // The OS VPN consent activity is the sole allowed continuation while hidden.
        // No listener or tunnel has started yet; all other departures cancel setup.
        if (!vpnConsentPending) {
            pendingConfig = null; preparing = false; preparationGeneration++;
            if (pendingPreparation != null) { pendingPreparation.cancel(true); pendingPreparation = null; }
        }
        main.removeCallbacks(renderTick); main.removeCallbacks(networkTick); saveNonSecretFields();
        if (!vpnConsentPending && BackgroundPolicy.stopWhenUiHidden(backgroundSharing.isChecked(), isChangingConfigurations()) &&
                (launchRequested || session.snapshot().isActive() || PhoneVpnService.isActive())) {
            PhoneVpnService.stop(this);
            startService(new Intent(this, ProxyService.class).setAction(ProxyService.ACTION_STOP));
            launchRequested = false;
        }
        clearingSubscription = true; subscription.setText(""); clearingSubscription = false; super.onStop();
    }
    @Override public void onDestroy() { main.removeCallbacksAndMessages(null); preparation.shutdownNow(); super.onDestroy(); }
}
