// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/netip"
	"net/url"
	"path/filepath"
	"regexp"
	"strings"
	"unicode"
)

// Config is shared by desktop and mobile. BackendPort and APIPort are retained
// for configuration compatibility; the embedded adapter engine opens neither.
type Config struct {
	ListenHost       string   `json:"listen_host"`
	ListenPort       int      `json:"listen_port"`
	AllowedClients   []string `json:"allowed_clients"`
	SubscriptionURL  string   `json:"subscription_url,omitempty"`
	SubscriptionFile string   `json:"subscription_file,omitempty"`
	SelectionMode    string   `json:"selection_mode"`
	PreferredNode    string   `json:"preferred_node"`
	BackendPort      int      `json:"backend_port"`
	APIPort          int      `json:"api_port"`
	IdleSeconds      int      `json:"idle_seconds"`
	WakeupTimeout    int      `json:"wakeup_timeout"`
	RequestTimeout   int      `json:"request_timeout"`
	MaxConnections   int      `json:"max_connections"`
	HealthURL        string   `json:"health_url"`
	HealthInterval   int      `json:"health_interval"`
	HealthTimeout    int      `json:"health_timeout"`
	DataDir          string   `json:"data_dir,omitempty"`
}

func DefaultConfig() Config {
	return Config{ListenPort: 10081, BackendPort: 10082, APIPort: 10090, IdleSeconds: 60, WakeupTimeout: 45, RequestTimeout: 30, MaxConnections: 128, SelectionMode: "auto", HealthURL: "https://www.gstatic.com/generate_204", HealthInterval: 300, HealthTimeout: 5000}
}

func ParseConfig(raw string) (Config, error) {
	cfg := DefaultConfig()
	if len(raw) > 1024*1024 {
		return cfg, errors.New("configuration exceeds 1 MiB")
	}
	dec := json.NewDecoder(strings.NewReader(raw))
	dec.DisallowUnknownFields()
	if !strings.HasPrefix(strings.TrimSpace(raw), "{") {
		return cfg, errors.New("configuration must be an object")
	}
	if err := dec.Decode(&cfg); err != nil {
		return cfg, errors.New("invalid configuration JSON or unsupported field")
	}
	var extra any
	if err := dec.Decode(&extra); err != io.EOF {
		return cfg, errors.New("configuration must contain one object")
	}
	if cfg.SelectionMode == "preferred" {
		cfg.SelectionMode = "prefer"
	}
	return cfg, cfg.Validate()
}

func (c Config) Validate() error {
	if !privateIPv4(c.ListenHost) && c.ListenHost != "127.0.0.1" {
		return errors.New("listen_host must be a specific RFC1918 LAN IPv4 address or 127.0.0.1")
	}
	ports := map[int]bool{}
	for _, p := range []int{c.ListenPort, c.BackendPort, c.APIPort} {
		if p < 1024 || p > 65535 || ports[p] {
			return errors.New("listener, backend and API ports must be distinct unprivileged TCP ports")
		}
		ports[p] = true
	}
	if len(c.AllowedClients) == 0 || len(c.AllowedClients) > 256 {
		return errors.New("allowed_clients must contain 1 to 256 specific RFC1918 IPv4 addresses")
	}
	seen := map[string]bool{}
	for _, ip := range c.AllowedClients {
		if (c.ListenHost == "127.0.0.1" && ip != "127.0.0.1") || (c.ListenHost != "127.0.0.1" && !privateIPv4(ip)) || seen[ip] {
			return errors.New("allowed_clients must contain unique RFC1918 IPv4 addresses (or only 127.0.0.1 for loopback mode)")
		}
		seen[ip] = true
	}
	for _, n := range []int{c.IdleSeconds, c.WakeupTimeout, c.RequestTimeout, c.MaxConnections, c.HealthInterval, c.HealthTimeout} {
		if n < 1 || n > 86400 {
			return errors.New("timeout, interval or connection limit outside allowed range")
		}
	}
	if c.MaxConnections > 4096 {
		return errors.New("max_connections exceeds 4096")
	}
	if c.SelectionMode != "auto" && c.SelectionMode != "prefer" && c.SelectionMode != "fixed" {
		return errors.New("selection_mode must be auto, prefer or fixed")
	}
	if c.PreferredNode != "" && !validNodeName(c.PreferredNode) {
		return errors.New("preferred_node is reserved or invalid")
	}
	if c.SelectionMode != "auto" && c.PreferredNode == "" {
		return errors.New("preferred_node is required for prefer/fixed mode")
	}
	if (c.SubscriptionURL == "") == (c.SubscriptionFile == "") {
		return errors.New("configure exactly one of subscription_url or subscription_file")
	}
	if c.SubscriptionURL != "" && !validHTTPS(c.SubscriptionURL) {
		return errors.New("subscription_url must be a public HTTPS URL without userinfo or fragments")
	}
	if c.SubscriptionFile != "" && (!filepath.IsAbs(c.SubscriptionFile) || len(c.SubscriptionFile) > 4096 || strings.ContainsRune(c.SubscriptionFile, 0)) {
		return errors.New("subscription_file must be an absolute file path")
	}
	if !validHTTPS(c.HealthURL) {
		return errors.New("health_url must be a public HTTPS URL without userinfo or fragments")
	}

	return nil
}

func privateIPv4(s string) bool {
	a, e := netip.ParseAddr(s)
	return e == nil && a.Is4() && a.String() == s && (netip.MustParsePrefix("10.0.0.0/8").Contains(a) || netip.MustParsePrefix("172.16.0.0/12").Contains(a) || netip.MustParsePrefix("192.168.0.0/16").Contains(a))
}

var reservedName = regexp.MustCompile(`[\s_-]`)

func validNodeName(s string) bool {
	if len(s) == 0 || len(s) > 256 || strings.TrimSpace(s) != s || strings.ContainsRune(s, '`') {
		return false
	}
	for _, r := range s {
		if unicode.IsControl(r) || unicode.In(r, unicode.Cf) {
			return false
		}
	}
	normalized := strings.ToLower(reservedName.ReplaceAllString(s, ""))
	switch normalized {
	case "direct", "reject", "rejectdrop", "compatible", "pass", "dns", "global", "portal", "auto", "rematch", "passrule":
		return false
	}
	return true
}
func validHTTPS(raw string) bool {
	if raw == "" || len(raw) > 8192 || bytes.IndexFunc([]byte(raw), func(r rune) bool { return unicode.IsSpace(r) || unicode.IsControl(r) }) >= 0 {
		return false
	}
	u, e := url.Parse(raw)
	if e != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil || u.Fragment != "" || u.Opaque != "" {
		return false
	}
	if p := u.Port(); p != "" && p != "443" {
		return false
	}
	kind := Destination(u.Hostname())
	return kind == "external" || kind == "name"
}
