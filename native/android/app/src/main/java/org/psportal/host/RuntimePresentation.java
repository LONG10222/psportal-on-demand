// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

/** Native state and connection counts are distinct from a successfully opened listener. */
public final class RuntimePresentation {
    public enum State { STOPPED, PREPARING, LISTENING, WAKING, FORWARDING, READY, STOPPING, ERROR, UNKNOWN }
    private RuntimePresentation() {}
    /** Never echo untrusted profile keys or values into the status panel. */
    static String settingLabel(String key, boolean english) {
        if (key == null) return english ? "Other settings" : "其他设置";
        switch (key) {
            case "dns": return "DNS";
            case "hosts": return english ? "Hosts mappings" : "Hosts 映射";
            case "sniffer": return english ? "Protocol sniffing" : "协议嗅探";
            case "mode": return english ? "Routing mode" : "分流模式";
            case "tun": case "iptables": return english ? "Tunnel / firewall" : "隧道 / 防火墙";
            case "port": case "socks-port": case "mixed-port": case "redir-port": case "tproxy-port":
            case "listeners": case "allow-lan": case "bind-address": case "authentication":
            case "skip-auth-prefixes": case "lan-allowed-ips": case "lan-disallowed-ips":
                return english ? "Listeners / access controls" : "监听 / 接入设置";
            case "external-controller": case "external-controller-tls": case "external-controller-unix":
            case "external-controller-pipe": case "external-ui": case "external-ui-url": case "secret":
                return english ? "Controller / dashboard" : "控制接口 / 面板";
            case "find-process-mode": case "interface-name": case "routing-mark":
                return english ? "Process / network routing" : "进程 / 网络路由";
            case "ipv6": return "IPv6";
            case "profile": return english ? "Profile cache" : "配置缓存";
            case "log-level": return english ? "Logging" : "日志";
            case "geox-url": case "geo-auto-update": case "geo-update-interval": case "geodata-mode":
                return english ? "Geodata settings" : "地理数据库设置";
            default: return english ? "Other settings" : "其他设置";
        }
    }
    static String profileError(String code, boolean english) {
        if (code == null) return "";
        switch (code) {
            case "profile_unsupported": return english ? "This subscription requires unsupported features. For inline nodes with GEOIP rules, stop and explicitly choose Global routing; Rule mode needs a supported inline rule profile." : "订阅含暂不支持的功能。若是带 GEOIP 规则的内联节点订阅，可停止后明确选择“全局”；规则模式需使用受支持的内联规则。";
            case "profile_selection_required": return english ? "This subscription owns its policy groups. Stop, choose Auto node selection, then retry." : "订阅自带策略组。请停止，将节点策略改为“自动”后重试。";
            case "profile_invalid": return english ? "The subscription profile is invalid or incomplete. Check its supported inline nodes, groups and rules." : "订阅配置无效或不完整，请检查内联节点、策略组与规则。";
            case "download_failed": return english ? "Subscription download failed. Check the HTTPS link and connection; the link is never shown in errors." : "订阅下载失败，请检查 HTTPS 链接和网络。错误信息不会显示订阅链接。";
            default: return "";
        }
    }
    public static State state(SessionController.Phase phase, boolean preparing, Boolean listening,
                              String coreState, Long connections, boolean error) {
        if (preparing) return State.PREPARING;
        switch (phase) {
            case STARTING: return State.PREPARING;
            case STOPPING: return State.STOPPING;
            case ERROR: case FAULTED: return State.ERROR;
            case STOPPED: return State.STOPPED;
            default: break;
        }
        if (error) return State.ERROR;
        if (listening == null) return State.UNKNOWN;
        if (!listening) return State.ERROR;
        if ("preparing".equals(coreState)) return State.PREPARING;
        if ("listening".equals(coreState)) return State.LISTENING;
        if ("forwarding".equals(coreState)) return State.FORWARDING;
        if ("starting".equals(coreState) || "waking".equals(coreState)) return State.WAKING;
        if ("failed".equals(coreState) || "error".equals(coreState)) return State.ERROR;
        if (connections != null && connections > 0) return State.FORWARDING;
        if ("stopped".equals(coreState)) return State.LISTENING;
        if ("running".equals(coreState)) return State.READY;
        return State.UNKNOWN;
    }
}
