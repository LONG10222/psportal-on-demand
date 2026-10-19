// SPDX-License-Identifier: GPL-3.0-only
package mobile

import (
	"encoding/json"
	"net"
	"testing"

	"github.com/psportal/psportal/native/engine"
)

func TestLegacyAndRuntimeStatusCompatibility(t *testing.T) {
	Stop()
	defer Stop()
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	listener.Close()
	cfg := engine.DefaultConfig()
	cfg.ListenHost = "127.0.0.1"
	cfg.ListenPort = port
	cfg.AllowedClients = []string{"127.0.0.1"}
	cfg.SubscriptionURL = "https://provider.example/fixture"
	raw, _ := json.Marshal(cfg)
	if err := Start(string(raw)); err != nil {
		t.Fatal(err)
	}
	var legacy, runtime map[string]any
	if err := json.Unmarshal([]byte(Status()), &legacy); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal([]byte(RuntimeStatus()), &runtime); err != nil {
		t.Fatal(err)
	}
	if legacy["state"] != "stopped" || legacy["service_state"] != "listening" || legacy["running"] != true || legacy["active"] != float64(0) {
		t.Fatal("legacy iOS contract changed", legacy)
	}
	if runtime["state"] != "listening" || runtime["core_state"] != "stopped" || runtime["node_management"] != true {
		t.Fatal(runtime)
	}
	if err := SelectNode("fixed", "Fixture"); err == nil {
		t.Fatal("selected unloaded node")
	}
	Stop()
	if err := json.Unmarshal([]byte(RuntimeStatus()), &runtime); err != nil || runtime["running"] != false || runtime["state"] != "stopped" {
		t.Fatal(runtime, err)
	}
	if err := Prepare(); err == nil {
		t.Fatal("prepared stopped engine")
	}
	if err := TestNodes(); err == nil {
		t.Fatal("tested stopped engine")
	}
	if err := SelectNodeWithThreshold("fastest", "", 50); err == nil {
		t.Fatal("selected stopped engine")
	}
}
