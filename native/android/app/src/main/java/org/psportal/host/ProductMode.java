// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

/** Session input presets only. They never change rule/global/direct routing or start a service. */
public enum ProductMode {
    GAME(true, false), MIXED(true, true), CLASH(false, true);

    public final boolean lanEnabled, phoneVpn;
    ProductMode(boolean lanEnabled, boolean phoneVpn) {
        this.lanEnabled = lanEnabled; this.phoneVpn = phoneVpn;
    }
    public static ProductMode fromInputs(boolean lan, boolean phone) {
        for (ProductMode mode : values()) if (mode.lanEnabled == lan && mode.phoneVpn == phone) return mode;
        return null;
    }
    public static boolean canChange(SessionController.Phase phase, boolean setupPending, boolean phoneVpnActive) {
        return (phase == SessionController.Phase.STOPPED || phase == SessionController.Phase.ERROR) && !setupPending && !phoneVpnActive;
    }
    public String label(boolean english) {
        switch (this) {
            case GAME: return english ? "Game" : "游戏";
            case MIXED: return english ? "Mixed" : "混合";
            default: return "Clash";
        }
    }
    public String description(boolean english) {
        switch (this) {
            case GAME:
                return english ? "Game mode: connect a console or another device using its manual HTTP proxy. LAN HTTP/HTTPS CONNECT, TCP only; game acceleration and UDP streaming are not guaranteed. Phone apps stay untouched. Start, device connection and successful Internet access are separate checks." :
                        "游戏模式：给游戏机等设备设置手动 HTTP 代理后接入。局域网 HTTP/HTTPS CONNECT 仅支持 TCP，不保证游戏加速或 UDP 串流；不接管本机应用。服务启动、设备接入和外网访问成功需要分别确认。";
            case MIXED:
                return english ? "Mixed mode: share the LAN proxy and proxy this phone’s apps together. Start requires Android VPN consent. LAN input is TCP-only; phone UDP needs a supported node." :
                        "混合模式：同时共享局域网代理与代理本机应用。点击启动后须获 Android VPN 授权。局域网入口仅支持 TCP；本机 UDP 需节点支持。";
            default:
                return english ? "Clash mode: embedded Mihomo for this phone’s apps only, with no LAN listener. Start requires Android VPN consent. No separate Clash app is needed." :
                        "Clash 模式：仅使用内置 Mihomo 代理本机应用，不开放局域网监听。点击启动后须获 Android VPN 授权，无需另装 Clash。";
        }
    }
}
