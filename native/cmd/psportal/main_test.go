// SPDX-License-Identifier: GPL-3.0-only
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"os"
	"os/exec"
	"testing"
	"time"

	"github.com/psportal/psportal/native/engine"
)

func TestDesktopChildHelper(t *testing.T) {
	if os.Getenv("PSPORTAL_TEST_CHILD") != "1" {
		return
	}
	flag.CommandLine = flag.NewFlagSet("psportal-fixture", flag.ExitOnError)
	os.Args = []string{os.Args[0], "--config", os.Getenv("PSPORTAL_TEST_CONFIG"), "--desktop-child"}
	main()
	os.Exit(0)
}

func TestDesktopChildStatusAndStopEOF(t *testing.T) {
	for _, stop := range []bool{true, false} {
		t.Run(map[bool]string{true: "stop", false: "EOF"}[stop], func(t *testing.T) {
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
			config, err := json.Marshal(cfg)
			if err != nil {
				t.Fatal(err)
			}
			path := t.TempDir() + "/config.json"
			if err := os.WriteFile(path, config, 0600); err != nil {
				t.Fatal(err)
			}
			cmd := exec.Command(os.Args[0], "-test.run=^TestDesktopChildHelper$")
			cmd.Env = append(os.Environ(), "PSPORTAL_TEST_CHILD=1", "PSPORTAL_TEST_CONFIG="+path)
			stdin, err := cmd.StdinPipe()
			if err != nil {
				t.Fatal(err)
			}
			stdout, err := cmd.StdoutPipe()
			if err != nil {
				t.Fatal(err)
			}
			if err := cmd.Start(); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { stdin.Close(); _ = cmd.Process.Kill() })
			lines := make(chan string, 16)
			go func() {
				defer close(lines)
				scanner := bufio.NewScanner(stdout)
				for scanner.Scan() {
					lines <- scanner.Text()
				}
			}()
			next := func() map[string]any {
				t.Helper()
				select {
				case line, ok := <-lines:
					if !ok {
						t.Fatal("child closed output")
					}
					var s map[string]any
					if err := json.Unmarshal([]byte(line), &s); err != nil {
						t.Fatal(err, line)
					}
					return s
				case <-time.After(5 * time.Second):
					t.Fatal("child status blocked")
					return nil
				}
			}
			if s := next(); s["event"] != "ready" {
				t.Fatal(s)
			}
			if s := next(); s["event"] != "status" || s["state"] != "listening" || s["connected_clients"] != float64(0) {
				t.Fatal(s)
			}
			fmt.Fprintln(stdin, `{"command":"select","selection_mode":"fixed","preferred_node":"Fixture","request_id":5}`)
			for {
				s := next()
				if s["last_command_id"] == float64(5) && s["busy"] == false {
					if s["command_error"] != "load live nodes before selecting" {
						t.Fatal(s)
					}
					break
				}
			}
			if stop {
				fmt.Fprintln(stdin, "stop")
			} else {
				stdin.Close()
			}
			done := make(chan error, 1)
			go func() { done <- cmd.Wait() }()
			select {
			case err := <-done:
				if err != nil {
					t.Fatal(err)
				}
			case <-time.After(5 * time.Second):
				t.Fatal("child ignored stop/EOF")
			}
		})
	}
}
