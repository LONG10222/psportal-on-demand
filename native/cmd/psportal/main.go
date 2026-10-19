// SPDX-License-Identifier: GPL-3.0-only
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/psportal/psportal/native/engine"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

func main() {
	path := flag.String("config", "config.json", "path to native JSON configuration")
	check := flag.Bool("check", false, "validate configuration without binding or downloading")
	version := flag.Bool("version", false, "show version")
	desktopChild := flag.Bool("desktop-child", false, "emit JSON readiness and stop when parent closes stdin")
	status := flag.Duration("status-interval", 0, "print sanitized status JSON periodically, e.g. 10s")
	flag.Parse()
	if *version {
		fmt.Println("PSPortal native 0.2; embedded Mihomo 1.19.32; GPL-3.0-only")
		return
	}
	file, err := os.Open(*path)
	if err != nil {
		fatal("cannot read configuration")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || info.Size() > 1024*1024 {
		fatal("configuration exceeds 1 MiB or cannot be read")
	}
	data := make([]byte, info.Size())
	if _, err = io.ReadFull(file, data); err != nil {
		fatal("cannot read configuration")
	}
	cfg, err := engine.ParseConfig(string(data))
	if err != nil {
		fatal(err.Error())
	}
	if *check {
		fmt.Println("Configuration valid")
		return
	}
	app, err := engine.New(cfg)
	if err != nil {
		fatal(err.Error())
	}
	if err = app.Start(); err != nil {
		fatal("listener could not bind; check the LAN address and port")
	}
	if *desktopChild {
		ready, _ := json.Marshal(map[string]any{"event": "ready", "engine": "mihomo-adapters", "listen_host": cfg.ListenHost, "listen_port": cfg.ListenPort})
		fmt.Println(string(ready))
	} else {
		fmt.Printf("PSPortal listening on %s:%d; encrypted node pool wakes on demand. Ctrl+C to stop.\n", cfg.ListenHost, cfg.ListenPort)
	}
	defer app.Stop()
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(quit)
	control := &runtimeControl{app: app}
	var parentClosed <-chan struct{}
	if *desktopChild {
		closed := make(chan struct{})
		parentClosed = closed
		go func() {
			defer close(closed)
			scanner := bufio.NewScanner(os.Stdin)
			scanner.Buffer(make([]byte, 4096), 4097)
			for scanner.Scan() {
				line := scanner.Text()
				if strings.TrimSpace(line) == "stop" {
					return
				}
				control.accept(line)
			}
		}()
		if *status <= 0 {
			*status = time.Second
		}
		control.publish()
	}
	if *status <= 0 {
		select {
		case <-quit:
		case <-parentClosed:
		}
		return
	}
	ticker := time.NewTicker(*status)
	defer ticker.Stop()
	for {
		select {
		case <-quit:
			return
		case <-parentClosed:
			return
		case <-ticker.C:
			control.publish()
		}
	}
}
func fatal(message string) { fmt.Fprintln(os.Stderr, "PSPortal:", message); os.Exit(1) }
