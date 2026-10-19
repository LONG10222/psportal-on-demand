// SPDX-License-Identifier: GPL-3.0-only
// Package androidcore embeds Mihomo's configuration executor and rule tunnel.
// It is intentionally separate from the desktop/iOS adapter-only engine.
package androidcore

import (
	"encoding/json"
	"errors"
	"github.com/psportal/psportal/native/engine"
)

type Config struct {
	engine.Config
	RoutingMode string `json:"routing_mode"`
	LANEnabled  bool   `json:"lan_enabled"`
	PhoneVPN    bool   `json:"phone_vpn"`
}

func ParseConfig(text string) (Config, error) {
	var fields map[string]json.RawMessage
	if len(text) > 1024*1024 || json.Unmarshal([]byte(text), &fields) != nil || fields == nil {
		return Config{}, errors.New("invalid Android configuration")
	}
	mode := "rule"
	lan, phone := true, false
	for key, target := range map[string]*bool{"lan_enabled": &lan, "phone_vpn": &phone} {
		if raw, ok := fields[key]; ok {
			if json.Unmarshal(raw, target) != nil {
				return Config{}, errors.New("invalid session option")
			}
			delete(fields, key)
		}
	}
	if !lan && !phone {
		return Config{}, errors.New("enable LAN sharing or phone VPN")
	}
	if !lan {
		fields["listen_host"] = json.RawMessage(`"127.0.0.1"`)
		fields["allowed_clients"] = json.RawMessage(`["127.0.0.1"]`)
	}
	if raw, ok := fields["routing_mode"]; ok {
		if json.Unmarshal(raw, &mode) != nil {
			return Config{}, errors.New("routing_mode must be rule, global or direct")
		}
		delete(fields, "routing_mode")
	}
	if mode != "rule" && mode != "global" && mode != "direct" {
		return Config{}, errors.New("routing_mode must be rule, global or direct")
	}
	raw, _ := json.Marshal(fields)
	cfg, err := engine.ParseConfig(string(raw))
	if err != nil {
		return Config{}, err
	}
	if cfg.SubscriptionFile != "" {
		return Config{}, errors.New("Android supports subscription_url only")
	}
	return Config{Config: cfg, RoutingMode: mode, LANEnabled: lan, PhoneVPN: phone}, nil
}
