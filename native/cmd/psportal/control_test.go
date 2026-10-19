// SPDX-License-Identifier: GPL-3.0-only
package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestParseRuntimeCommands(t *testing.T) {
	for _, line := range []string{
		`{"command":"status"}`, `{"command":"prepare","request_id":1}`, `{"command":"test","request_id":2}`,
		`{"command":"select","selection_mode":"fixed","preferred_node":"Japan","request_id":3}`,
		`{"command":"select","selection_mode":"fastest","switch_threshold_ms":0,"request_id":4}`,
	} {
		if _, err := parseCommand(line); err != nil {
			t.Fatalf("%s: %v", line, err)
		}
	}
	for _, line := range []string{`null`, `[]`, `{}`, `{"command":"stop"}`, `{"command":"status","secret":1}`, `{"command":"test","request_id":-1}`, `{"command":"status"} {}`, strings.Repeat(" ", 4097)} {
		if _, err := parseCommand(line); err == nil {
			t.Fatalf("accepted %q", line)
		}
	}
}

type fixtureRuntime struct {
	entered, release chan struct{}
	once             sync.Once
}

func (f *fixtureRuntime) Status() string {
	return `{"event":"status","state":"listening","core_state":"stopped"}`
}
func (f *fixtureRuntime) Prepare() error {
	f.once.Do(func() { close(f.entered) })
	<-f.release
	return errors.New("fixture failure")
}
func (f *fixtureRuntime) TestNodes() error                                  { return f.Prepare() }
func (f *fixtureRuntime) SelectNode(string, string) error                   { return nil }
func (f *fixtureRuntime) SelectNodeWithThreshold(string, string, int) error { return nil }

func controlSnapshots(t *testing.T, c *runtimeControl, out *bytes.Buffer) []map[string]any {
	t.Helper()
	c.outputMu.Lock()
	defer c.outputMu.Unlock()
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	snapshots := make([]map[string]any, 0, len(lines))
	for _, line := range lines {
		var s map[string]any
		if err := json.Unmarshal([]byte(line), &s); err != nil {
			t.Fatal(err, line)
		}
		snapshots = append(snapshots, s)
	}
	return snapshots
}
func TestRuntimeStatusResponsiveDuringOperation(t *testing.T) {
	app := &fixtureRuntime{entered: make(chan struct{}), release: make(chan struct{})}
	var out bytes.Buffer
	c := &runtimeControl{app: app, output: &out}
	c.accept(`{"command":"prepare","request_id":7}`)
	select {
	case <-app.entered:
	case <-time.After(time.Second):
		t.Fatal("prepare did not start")
	}
	c.accept(`{"command":"status"}`)
	c.accept(`{"command":"select","request_id":8,"selection_mode":"fastest"}`)
	snapshots := controlSnapshots(t, c, &out)
	if len(snapshots) != 3 || snapshots[1]["busy"] != true || snapshots[2]["last_command_id"] != float64(8) {
		t.Fatal(snapshots)
	}
	close(app.release)
	deadline := time.Now().Add(time.Second)
	for {
		snapshots = controlSnapshots(t, c, &out)
		last := snapshots[len(snapshots)-1]
		if last["busy"] == false && last["last_command_id"] == float64(7) {
			if last["command_error"] != "fixture failure" {
				t.Fatal(last)
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("operation did not complete", snapshots)
		}
		time.Sleep(time.Millisecond)
	}
}

type largeRuntime struct {
	fixtureRuntime
	raw string
}

func (f *largeRuntime) Status() string { return f.raw }
func TestRuntimePublishDoesNotExpandNodeLabels(t *testing.T) {
	nodeName := strings.Repeat("<>&", 85)
	nodes := make([]map[string]any, 1000)
	for i := range nodes {
		nodes[i] = map[string]any{"name": nodeName, "healthy": true, "delay_ms": 0}
	}
	var source bytes.Buffer
	encoder := json.NewEncoder(&source)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(map[string]any{"event": "status", "state": "listening", "nodes": nodes}); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	c := &runtimeControl{app: &largeRuntime{raw: source.String()}, output: &out}
	c.publish()
	if out.Len() >= 1024*1024 || strings.Contains(out.String(), `\u003c`) {
		t.Fatal("CLI expanded valid labels", out.Len())
	}
	if len(controlSnapshots(t, c, &out)) != 1 {
		t.Fatal("not one status line")
	}
}
