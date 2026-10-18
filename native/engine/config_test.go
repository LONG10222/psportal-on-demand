// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"encoding/json"
	"strings"
	"testing"
)

func validConfig() Config {
	c := DefaultConfig()
	c.ListenHost = "192.168.1.10"
	c.AllowedClients = []string{"192.168.1.50"}
	c.SubscriptionURL = "https://provider.example/sub"
	return c
}
func TestConfigDefaultsAndValidation(t *testing.T) {
	c := validConfig()
	b, _ := json.Marshal(c)
	got, err := ParseConfig(string(b))
	if err != nil || got.ListenPort != 10081 {
		t.Fatalf("valid config: %+v %v", got, err)
	}
	for name, change := range map[string]func(*Config){
		"wildcard": func(c *Config) { c.ListenHost = "0.0.0.0" }, "loopback_mixed_clients": func(c *Config) { c.ListenHost = "127.0.0.1" }, "public_client": func(c *Config) { c.AllowedClients = []string{"8.8.8.8"} }, "empty_clients": func(c *Config) { c.AllowedClients = nil }, "duplicate_ports": func(c *Config) { c.APIPort = c.ListenPort }, "http_subscription": func(c *Config) { c.SubscriptionURL = "http://example.com" }, "private_subscription": func(c *Config) { c.SubscriptionURL = "https://192.168.1.1/sub" }, "userinfo": func(c *Config) { c.SubscriptionURL = "https://user:secret@example.com" }, "fixed_without_name": func(c *Config) { c.SelectionMode = "fixed" }, "reserved_name": func(c *Config) { c.PreferredNode = "Di_re-ct" }, "bidi_name": func(c *Config) { c.PreferredNode = "abc\u202Edef" }, "oversized_max": func(c *Config) { c.MaxConnections = 4097 },
	} {
		t.Run(name, func(t *testing.T) {
			c := validConfig()
			change(&c)
			if c.Validate() == nil {
				t.Fatal("invalid configuration accepted")
			}
		})
	}
}
func TestConfigStrictJSON(t *testing.T) {
	b, _ := json.Marshal(validConfig())
	for _, raw := range []string{"null", "[]", string(b) + " {}", strings.TrimSuffix(string(b), "}") + `,"unrecognized":true}`, string(b) + "trailing"} {
		if _, err := ParseConfig(raw); err == nil {
			t.Fatalf("accepted %s", raw)
		}
	}
}
func TestReservedNames(t *testing.T) {
	for _, name := range []string{"", "GLOBAL", "REJECT", "reject_drop", "pass-rule", "dns", "rematch", "AUTO", "a`b", " x", "a\n", "a\u2066b"} {
		if validNodeName(name) {
			t.Fatalf("accepted %q", name)
		}
	}
	for _, name := range []string{"香港 1", "Tokyo 🇯🇵", "MyNode-42"} {
		if !validNodeName(name) {
			t.Fatalf("rejected %q", name)
		}
	}
}

func TestLoopbackOnlyMode(t *testing.T) {
	c := validConfig()
	c.ListenHost = "127.0.0.1"
	c.AllowedClients = []string{"127.0.0.1"}
	if err := c.Validate(); err != nil {
		t.Fatal(err)
	}
	c.ListenHost = "192.168.1.10"
	if c.Validate() == nil {
		t.Fatal("LAN listener accepted loopback allowlist")
	}
}
