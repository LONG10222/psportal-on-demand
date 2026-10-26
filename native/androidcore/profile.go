// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"unicode"

	"github.com/metacubex/mihomo/common/yaml"
	"github.com/metacubex/mihomo/component/process"
	MC "github.com/metacubex/mihomo/config"
	"github.com/metacubex/mihomo/log"
	"github.com/metacubex/mihomo/tunnel"
	"github.com/psportal/psportal/native/engine"
)

const profileLimit = 10 * 1024 * 1024
const generatedGroup = "PSPORTAL-OUTBOUND"
const autoGroup = "PSPORTAL-AUTO"
const fastestGroup = "PSPORTAL-FASTEST"
const preferGroup = "PSPORTAL-PREFER"

var nodeTypes = map[string]bool{"ss": true, "ssr": true, "socks5": true, "http": true, "vmess": true, "vless": true, "snell": true, "trojan": true, "hysteria": true, "hysteria2": true, "tuic": true, "anytls": true}
var ruleTypes = map[string]bool{"DOMAIN": true, "DOMAIN-SUFFIX": true, "DOMAIN-KEYWORD": true, "IP-CIDR": true, "IP-CIDR6": true, "DST-PORT": true, "NETWORK": true, "MATCH": true}

type profile struct {
	raw       *MC.RawConfig
	names     []string
	generated bool
	ignored   []string
}

// sanitizeProfile is a whitelist before Mihomo parsing. In particular the
// upstream parser may access provider/geodata files; never pass source RawConfig.
func sanitizeProfile(body []byte, cfg Config) (profile, error) {
	var out profile
	if len(body) == 0 || len(body) > profileLimit {
		return out, errors.New("subscription is empty or exceeds 10 MiB")
	}
	var input map[string]any
	if yaml.Unmarshal(body, &input) != nil || input == nil {
		return out, errors.New("subscription must be a Clash/Mihomo YAML or JSON object")
	}
	for _, key := range []string{"proxy-providers", "rule-providers", "sub-rules"} {
		if value, ok := input[key]; ok && value != nil {
			if m, ok := value.(map[string]any); !ok || len(m) > 0 {
				return out, fmt.Errorf("unsupported subscription feature: %s (use inline proxies and rules)", key)
			}
		}
	}
	raw := MC.DefaultRawConfig()
	raw.LogLevel = log.SILENT
	raw.Mode = tunnel.Rule
	if cfg.RoutingMode == "global" {
		raw.Mode = tunnel.Global
	}
	if cfg.RoutingMode == "direct" {
		raw.Mode = tunnel.Direct
	}
	raw.IPv6 = true
	raw.FindProcessMode = process.FindProcessOff
	raw.DNS = MC.RawDNS{Enable: false, UseHosts: false, UseSystemHosts: false, DefaultNameserver: []string{"1.1.1.1"}, NameServer: []string{"1.1.1.1"}}
	raw.Tun = MC.RawTun{}
	raw.NTP = MC.RawNTP{}
	raw.IPTables = MC.RawIPTables{}
	raw.Profile = MC.RawProfile{}
	raw.GeoXUrl = MC.RawGeoXUrl{}
	raw.GeoAutoUpdate = false
	raw.ExternalUIURL = ""
	raw.BindAddress = "127.0.0.1"
	raw.LanAllowedIPs = nil
	raw.Experimental = MC.RawExperimental{}
	if cfg.PhoneVPN {
		configureVPNDNS(raw)
	}
	proxies, ok := input["proxies"].([]any)
	if !ok || len(proxies) < 1 || len(proxies) > 1000 {
		return out, errors.New("subscription must contain 1 to 1000 inline proxy nodes")
	}
	seen := map[string]bool{"DIRECT": true, "REJECT": true, "REJECT-DROP": true, "COMPATIBLE": true, "PASS": true, "PASS-RULE": true, "GLOBAL": true, generatedGroup: true, autoGroup: true, fastestGroup: true, preferGroup: true}
	for _, item := range proxies {
		node, ok := item.(map[string]any)
		if !ok {
			return out, errors.New("invalid proxy node")
		}
		name, _ := node["name"].(string)
		kind, _ := node["type"].(string)
		if !safeName(name) || seen[name] || !nodeTypes[kind] {
			return out, errors.New("subscription contains an invalid, duplicate or unsupported proxy node")
		}
		if unsafeOptions(node) {
			return out, errors.New("subscription node contains unsupported file, network or routing options")
		}
		server, _ := node["server"].(string)
		k := engine.Destination(server)
		if k != "external" && k != "name" {
			return out, errors.New("proxy endpoints must be public addresses")
		}
		if v, exists := node["udp"]; exists {
			if _, ok := v.(bool); !ok {
				return out, errors.New("proxy udp option must be a boolean")
			}
		}
		if !cfg.PhoneVPN {
			node["udp"] = false
		}
		node["tfo"] = false
		node["mptcp"] = false
		raw.Proxy = append(raw.Proxy, node)
		out.names = append(out.names, name)
		seen[name] = true
	}
	groups := []any{}
	if g, ok := input["proxy-groups"]; ok {
		groups, ok = g.([]any)
		if !ok {
			return out, errors.New("invalid proxy-groups")
		}
	}
	if len(groups) > 256 {
		return out, errors.New("proxy-groups exceeds 256 groups")
	}
	for _, item := range groups {
		source, ok := item.(map[string]any)
		if !ok {
			return out, errors.New("invalid proxy group")
		}
		name, _ := source["name"].(string)
		kind, _ := source["type"].(string)
		if !safeName(name) || (seen[name] && name != "GLOBAL") {
			return out, errors.New("invalid or duplicate proxy group name")
		}
		if kind != "select" && kind != "url-test" && kind != "fallback" && kind != "load-balance" {
			return out, errors.New("unsupported proxy group type")
		}
		for _, key := range []string{"use", "include-all", "include-all-providers", "include-all-proxies", "filter", "exclude-filter", "dialer-proxy", "interface-name", "routing-mark"} {
			if _, exists := source[key]; exists {
				return out, fmt.Errorf("unsupported proxy group option: %s", key)
			}
		}
		refs, ok := source["proxies"].([]any)
		if !ok || len(refs) < 1 || len(refs) > 1256 {
			return out, errors.New("proxy group requires bounded inline proxies")
		}
		for _, ref := range refs {
			s, ok := ref.(string)
			if !ok || !safeName(s) {
				return out, errors.New("invalid proxy group reference")
			}
		}
		group := map[string]any{"name": name, "type": kind, "proxies": refs, "empty-fallback": "REJECT", "disable-udp": !cfg.PhoneVPN, "url": cfg.HealthURL, "interval": cfg.HealthInterval, "timeout": cfg.HealthTimeout, "lazy": true}
		// Preserve only side-effect-free algorithm options. Unknown group keys fail
		// rather than silently changing how a subscription routes traffic.
		for key, value := range source {
			switch key {
			case "name", "type", "proxies", "url", "interval", "timeout", "lazy", "empty-fallback", "disable-udp", "hidden", "icon":
			case "tolerance", "strategy", "default-selected", "max-failed-times", "expected-status":
				group[key] = value
			default:
				return out, fmt.Errorf("unsupported proxy group option: %s", key)
			}
		}
		if value, exists := source["disable-udp"]; exists {
			disabled, ok := value.(bool)
			if !ok {
				return out, errors.New("group disable-udp must be a boolean")
			}
			group["disable-udp"] = disabled || !cfg.PhoneVPN
		}
		if kind == "select" {
			group["interval"] = 0
		}
		raw.ProxyGroup = append(raw.ProxyGroup, group)
		seen[name] = true
	}
	out.generated = len(groups) == 0
	if !out.generated && cfg.SelectionMode != "auto" {
		return out, errors.New("subscription policy groups require selection_mode auto; select within the source profile")
	}
	if out.generated {
		refs := make([]any, len(out.names))
		for i, name := range out.names {
			refs[i] = name
		}
		raw.ProxyGroup = append(raw.ProxyGroup, map[string]any{"name": autoGroup, "type": "fallback", "proxies": refs, "url": cfg.HealthURL, "interval": cfg.HealthInterval, "timeout": cfg.HealthTimeout, "lazy": true, "empty-fallback": "REJECT", "disable-udp": !cfg.PhoneVPN}, map[string]any{"name": fastestGroup, "type": "url-test", "proxies": refs, "url": cfg.HealthURL, "interval": cfg.HealthInterval, "timeout": cfg.HealthTimeout, "tolerance": cfg.SwitchThresholdMS, "lazy": true, "empty-fallback": "REJECT", "disable-udp": !cfg.PhoneVPN})
		selected := autoGroup
		if cfg.SelectionMode == "fixed" || cfg.SelectionMode == "prefer" {
			if !seen[cfg.PreferredNode] {
				return out, errors.New("preferred node is missing from subscription")
			}
			selected = cfg.PreferredNode
		}
		if cfg.SelectionMode == "fastest" {
			selected = fastestGroup
		}
		if cfg.PreferredNode != "" {
			preferred := []any{cfg.PreferredNode}
			for _, n := range out.names {
				if n != cfg.PreferredNode {
					preferred = append(preferred, n)
				}
			}
			raw.ProxyGroup = append(raw.ProxyGroup, map[string]any{"name": preferGroup, "type": "fallback", "proxies": preferred, "url": cfg.HealthURL, "interval": cfg.HealthInterval, "timeout": cfg.HealthTimeout, "lazy": true, "empty-fallback": "REJECT", "disable-udp": !cfg.PhoneVPN})
			if cfg.SelectionMode == "prefer" {
				selected = preferGroup
			}
		}
		choices := append([]any{autoGroup, fastestGroup}, refs...)
		if cfg.PreferredNode != "" {
			choices = append(choices, preferGroup)
		}
		raw.ProxyGroup = append(raw.ProxyGroup, map[string]any{"name": generatedGroup, "type": "select", "proxies": choices, "default-selected": selected, "empty-fallback": "REJECT", "disable-udp": !cfg.PhoneVPN})
	}
	hasGlobal := false
	for _, g := range raw.ProxyGroup {
		if g["name"] == "GLOBAL" {
			hasGlobal = true
		}
	}
	defaultTarget := out.names[0]
	if out.generated {
		defaultTarget = generatedGroup
	} else if len(raw.ProxyGroup) > 0 {
		defaultTarget = raw.ProxyGroup[0]["name"].(string)
	}
	if !hasGlobal {
		raw.ProxyGroup = append(raw.ProxyGroup, map[string]any{"name": "GLOBAL", "type": "select", "proxies": append([]any{defaultTarget}, stringsToAny(out.names)...), "default-selected": defaultTarget, "empty-fallback": "REJECT", "disable-udp": !cfg.PhoneVPN})
	}
	rules := []any{}
	if r, ok := input["rules"]; ok {
		rules, ok = r.([]any)
		if !ok {
			return out, errors.New("invalid subscription rules")
		}
	}
	if len(rules) > 20000 {
		return out, errors.New("subscription exceeds 20000 rules")
	}
	for _, item := range rules {
		if rule, ok := item.(string); !ok || len(rule) > 4096 {
			return out, errors.New("invalid subscription rule")
		}
	}
	// An explicit global mode never evaluates source rules. Keep the original
	// inline nodes/groups, but do not parse inactive GEOIP/provider rules or
	// trigger geodata acquisition for them. Rule mode still validates every rule.
	if len(rules) == 0 || cfg.RoutingMode == "global" {
		raw.Rule = []string{"MATCH," + defaultTarget}
		if len(rules) > 0 && cfg.RoutingMode == "global" {
			out.ignored = append(out.ignored, "rules (explicit global mode)")
		}
	} else {
		for _, item := range rules {
			rule, ok := item.(string)
			if !ok || len(rule) > 4096 {
				return out, errors.New("invalid subscription rule")
			}
			kind, _, _ := strings.Cut(rule, ",")
			if !ruleTypes[kind] {
				return out, fmt.Errorf("unsupported rule type: %s (geodata, providers and process rules are unavailable)", kind)
			}
			raw.Rule = append(raw.Rule, rule)
		}
		if !strings.HasPrefix(raw.Rule[len(raw.Rule)-1], "MATCH,") {
			return out, errors.New("inline rules must end with an explicit MATCH rule")
		}
	}
	for key := range input {
		switch key {
		case "proxies", "proxy-groups", "rules", "proxy-providers", "rule-providers", "sub-rules":
		default:
			switch key {
			case "tun", "dns", "external-controller", "external-controller-tls", "external-controller-unix", "external-controller-pipe", "listeners", "ntp", "hosts", "iptables", "interface-name", "routing-mark", "external-ui", "external-ui-url", "external-ui-name", "profile", "sniffer", "tls", "port", "socks-port", "mixed-port", "redir-port", "tproxy-port", "mode", "allow-lan", "bind-address", "geodata-mode", "geox-url", "geo-auto-update", "find-process-mode", "authentication", "secret":
				out.ignored = append(out.ignored, key)
			default:
				if !containsString(out.ignored, "other") {
					out.ignored = append(out.ignored, "other")
				}
			}
		}
	}
	sort.Strings(out.ignored)
	out.raw = raw
	return out, nil
}
func stringsToAny(values []string) []any {
	out := make([]any, len(values))
	for i, v := range values {
		out[i] = v
	}
	return out
}
func safeName(s string) bool {
	return len(s) > 0 && len(s) <= 256 && strings.TrimSpace(s) == s && strings.IndexFunc(s, func(r rune) bool { return unicode.IsControl(r) || unicode.In(r, unicode.Cf) }) < 0
}
func unsafeOptions(v any) bool {
	switch x := v.(type) {
	case map[string]any:
		for k, value := range x {
			switch strings.ToLower(k) {
			case "dialer-proxy", "interface-name", "routing-mark", "certificate", "private-key", "ca", "ca-str", "client-cert", "client-key", "ech-opts", "ip-version", "ip", "xhttp-opts", "realm-opts", "server-url", "stun":
				return true
			}
			if unsafeOptions(value) {
				return true
			}
		}
	case []any:
		for _, value := range x {
			if unsafeOptions(value) {
				return true
			}
		}
	}
	return false
}

func containsString(items []string, s string) bool {
	for _, v := range items {
		if v == s {
			return true
		}
	}
	return false
}
