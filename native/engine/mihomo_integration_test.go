// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"bufio"
	"context"
	"encoding/binary"
	"fmt"
	"github.com/metacubex/mihomo/adapter"
	"io"
	"net"
	"net/http"
	"net/netip"
	"strings"
	"testing"
	"time"
)

// fixtureDialer is test-only. Production always uses protectedDialer and cannot
// reach this loopback fixture from an untrusted provider's server field.
type fixtureDialer struct{ address string }

func (d fixtureDialer) DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	if address != "9.9.9.9:1080" {
		return nil, fmt.Errorf("unexpected proxy server %q", address)
	}
	return (&net.Dialer{}).DialContext(ctx, network, d.address)
}
func (d fixtureDialer) ListenPacket(context.Context, string, string, netip.AddrPort) (net.PacketConn, error) {
	return nil, fmt.Errorf("UDP not used")
}
func TestMihomoSOCKS5ActualHTTPAndCONNECT(t *testing.T) {
	for _, method := range []string{"HTTP", "CONNECT"} {
		t.Run(method, func(t *testing.T) {
			upstream, err := net.Listen("tcp4", "127.0.0.1:0")
			if err != nil {
				t.Fatal(err)
			}
			defer upstream.Close()
			result := make(chan error, 1)
			go func() {
				conn, err := upstream.Accept()
				if err != nil {
					result <- err
					return
				}
				defer conn.Close()
				conn.SetDeadline(time.Now().Add(5 * time.Second))
				fail := func(err error) { result <- err }
				greeting := make([]byte, 2)
				if _, err = io.ReadFull(conn, greeting); err != nil {
					fail(err)
					return
				}
				methods := make([]byte, int(greeting[1]))
				if _, err = io.ReadFull(conn, methods); err != nil {
					fail(err)
					return
				}
				if greeting[0] != 5 {
					fail(fmt.Errorf("not SOCKS5"))
					return
				}
				conn.Write([]byte{5, 0})
				target := make([]byte, 10)
				if _, err = io.ReadFull(conn, target); err != nil {
					fail(err)
					return
				}
				if target[0] != 5 || target[1] != 1 || target[3] != 1 || net.IP(target[4:8]).String() != "8.8.8.8" || binary.BigEndian.Uint16(target[8:]) != 80 {
					fail(fmt.Errorf("destination was not pinned: %v", target))
					return
				}
				conn.Write([]byte{5, 0, 0, 1, 0, 0, 0, 0, 0, 0})
				if method == "CONNECT" {
					payload, readErr := io.ReadAll(conn)
					if readErr != nil {
						err = readErr
						fail(err)
						return
					}
					if string(payload) != "ping" {
						fail(fmt.Errorf("bad CONNECT payload"))
						return
					}
					conn.Write([]byte("pong"))
					result <- nil
					return
				}
				req, err := http.ReadRequest(bufio.NewReader(conn))
				if err != nil {
					fail(err)
					return
				}
				defer req.Body.Close()
				if req.RequestURI != "/fixture" || req.Host != "8.8.8.8:80" {
					fail(fmt.Errorf("wrong origin request: %s %s", req.RequestURI, req.Host))
					return
				}
				_, err = io.WriteString(conn, "HTTP/1.1 200 OK\r\nContent-Length: 12\r\nConnection: close\r\n\r\nreal-mihomo!")
				result <- err
			}()
			actual, err := adapter.ParseProxy(map[string]any{"name": "Fixture", "type": "socks5", "server": "9.9.9.9", "port": 1080}, adapter.WithDialerForAPI(fixtureDialer{upstream.Addr().String()}))
			if err != nil {
				t.Fatal(err)
			}
			cfg := validConfig()
			cfg.ListenHost = "127.0.0.1"
			cfg.ListenPort = 0
			cfg.AllowedClients = []string{"127.0.0.1"}
			cfg.RequestTimeout = 5
			core := newEmbeddedCore(cfg)
			defer core.Close()
			core.mu.Lock()
			core.nodes = []*node{{proxy: actual, healthy: true}}
			core.state = "running"
			core.mu.Unlock()
			proxy := NewProxy(cfg, core)
			if err = proxy.Start(); err != nil {
				t.Fatal(err)
			}
			defer proxy.Stop()
			client, err := net.DialTimeout("tcp", proxy.Status()["listen_address"].(string), time.Second)
			if err != nil {
				t.Fatal(err)
			}
			defer client.Close()
			client.SetDeadline(time.Now().Add(5 * time.Second))
			reader := bufio.NewReader(client)
			if method == "CONNECT" {
				io.WriteString(client, "CONNECT 8.8.8.8:80 HTTP/1.1\r\nHost: 8.8.8.8:80\r\n\r\n")
				header, err := readHeader(reader)
				if err != nil || !strings.HasPrefix(string(header), "HTTP/1.1 200") {
					t.Fatalf("CONNECT failed: %s %v", header, err)
				}
				io.WriteString(client, "ping")
				if err := client.(*net.TCPConn).CloseWrite(); err != nil {
					t.Fatal(err)
				}
				payload := make([]byte, 4)
				if _, err = io.ReadFull(reader, payload); err != nil || string(payload) != "pong" {
					t.Fatalf("CONNECT payload: %q %v", payload, err)
				}
			} else {
				io.WriteString(client, "GET http://8.8.8.8/fixture HTTP/1.1\r\nHost: 8.8.8.8\r\n\r\n")
				response, err := http.ReadResponse(reader, nil)
				if err != nil {
					t.Fatal(err)
				}
				body, err := io.ReadAll(response.Body)
				response.Body.Close()
				if err != nil || response.StatusCode != 200 || string(body) != "real-mihomo!" {
					t.Fatalf("HTTP relay: %d %q %v", response.StatusCode, body, err)
				}
			}
			if err := <-result; err != nil {
				t.Fatal(err)
			}
		})
	}
}
