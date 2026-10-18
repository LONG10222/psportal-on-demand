// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func testRequest(first, headers string) (Request, error) {
	return ParseRequest([]byte(first + "\r\n" + headers + "\r\n\r\n"))
}
func TestParseRequestRewriting(t *testing.T) {
	r, err := testRequest("GET http://example.com/a?b=1 HTTP/1.1", "Host: example.com\r\nProxy-Authorization: Basic secret\r\nProxy-Authenticate: private\r\nProxy-Connection: keep-alive\r\nConnection: keep-alive, X-Hop\r\nKeep-Alive: 100\r\nX-Hop: private\r\nTE: trailers\r\nAuthorization: Bearer origin\r\nX-End: yes")
	if err != nil {
		t.Fatal(err)
	}
	for _, external := range []bool{false, true} {
		forwarded := string(r.ForwardedHeader(external))
		target := "/a?b=1"
		if external {
			target = "http://example.com:80/a?b=1"
		}
		if !strings.HasPrefix(forwarded, "GET "+target+" HTTP/1.1\r\n") {
			t.Fatal(forwarded)
		}
		for _, denied := range []string{"secret", "private", "keep-alive", "trailers", "X-Hop", "Proxy-"} {
			if strings.Contains(forwarded, denied) {
				t.Fatal(forwarded)
			}
		}
		for _, want := range []string{"Authorization: Bearer origin", "X-End: yes", "Connection: close"} {
			if !strings.Contains(forwarded, want) {
				t.Fatal(forwarded)
			}
		}
	}
	r, err = testRequest("CONNECT [2606:4700::1111]:443 HTTP/1.1", "Host: [2606:4700::1111]:443")
	if err != nil || r.Host != "2606:4700::1111" || r.Port != 443 {
		t.Fatalf("%+v %v", r, err)
	}
	r, err = testRequest("GET http://example.com?q=1 HTTP/1.1", "Host: example.com")
	if err != nil || r.Path != "/?q=1" {
		t.Fatalf("%+v %v", r, err)
	}
	r, err = testRequest("CONNECT example.com HTTP/1.0", "X-Test: ok")
	if err != nil || r.Port != 443 {
		t.Fatalf("%+v %v", r, err)
	}
}
func TestParseRequestRejectsSmuggling(t *testing.T) {
	for _, headers := range []string{
		"Host: example.com\r\nContent-Length: 0\r\nTransfer-Encoding: chunked",
		"Host: example.com\r\nContent-Length: 1\r\nContent-Length: 1",
		"Host: example.com\r\nContent-Length: 1, 1", "Host: example.com\r\nContent-Length: +1", "Host: example.com\r\nContent-Length: -1",
		"Host: example.com\r\nTransfer-Encoding: gzip, chunked", "Host: example.com\r\nTransfer-Encoding: chunked\r\nTransfer-Encoding: chunked",
		"Host: example.com\r\nConnection: content-length", "Host: example.com\r\nConnection: Host", "Host: example.com\r\nConnection: x,,y",
		"Host: example.com\r\nX-Test : yes", "Host: example.com\r\n X-Test: folded", "Host: example.com\r\nX-Test: a\nb", "Host: example.com\r\nX-Test: a\rb", "Host: example.com\r\nX-Test: a\x00b", "Host: example.com\r\nX-Test: a\x7fb",
		"Host: example.com\r\nHost: example.com", "Host: other.example", "Host: example.com:443", "Host: example.com\r\nUpgrade: websocket", "X-Test: missing host",
	} {
		t.Run(headers, func(t *testing.T) {
			if _, err := testRequest("GET http://example.com/ HTTP/1.1", headers); err == nil {
				t.Fatal("accepted unsafe headers")
			}
		})
	}
	for _, first := range []string{"GET / HTTP/1.1", "GET https://example.com/ HTTP/1.1", "GET http://u:p@example.com/ HTTP/1.1", "GET http://example.com/a#f HTTP/1.1", "GET http://example.com\\evil/ HTTP/1.1", "GET http://example.com:0/ HTTP/1.1", "GET http://example.com:65536/ HTTP/1.1", "GET http://example.com:/ HTTP/1.1", "GET http://127.1/ HTTP/1.1", "GET http://0x7f000001/ HTTP/1.1", "GET http://01.2.3.4/ HTTP/1.1", "CONNECT [fe80::1%eth0]:443 HTTP/1.1", "GET  http://example.com/ HTTP/1.1", "GET\thttp://example.com/ HTTP/1.1", "GET http://example.com/ HTTP/2"} {
		t.Run(first, func(t *testing.T) {
			if _, err := testRequest(first, "Host: example.com"); err == nil {
				t.Fatal("accepted unsafe target")
			}
		})
	}
}
func TestParseRequestBodyAndLimits(t *testing.T) {
	for _, test := range []struct {
		first, headers string
		status         int
	}{
		{"CONNECT example.com:443 HTTP/1.1", "Host: example.com:443\r\nContent-Length: 1", 400},
		{"GET http://example.com/ HTTP/1.1", "Host: example.com\r\nExpect: something", 417},
		{"GET http://example.com/ HTTP/1.1", "Host: example.com\r\nX-Test: " + strings.Repeat("a", MaxLineBytes), 431},
		{"GET http://example.com/ HTTP/1.1", "Host: example.com\r\n" + strings.Repeat("X: y\r\n", 101), 431},
	} {
		_, err := testRequest(test.first, test.headers)
		var pe *ProtocolError
		if !errors.As(err, &pe) || pe.Status != test.status {
			t.Fatalf("got %v want %d", err, test.status)
		}
	}
}

type fixtureCore struct {
	endpoint                       string
	acquisitions, releases, active atomic.Int64
	err                            error
}

func (c *fixtureCore) Acquire(context.Context) (string, error) {
	if c.err != nil {
		return "", c.err
	}
	c.acquisitions.Add(1)
	c.active.Add(1)
	return c.endpoint, nil
}
func (c *fixtureCore) Release() { c.releases.Add(1); c.active.Add(-1) }
func fixture(t *testing.T, handler func(net.Conn)) string {
	t.Helper()
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			c, e := ln.Accept()
			if e != nil {
				return
			}
			wg.Add(1)
			go func() {
				defer wg.Done()
				defer c.Close()
				_ = c.SetDeadline(time.Now().Add(5 * time.Second))
				handler(c)
			}()
		}
	}()
	t.Cleanup(func() { _ = ln.Close(); wg.Wait() })
	return ln.Addr().String()
}
func startTestProxy(t *testing.T, core Core, change func(*Proxy)) *Proxy {
	t.Helper()
	p := NewProxy(Config{ListenHost: "127.0.0.1", ListenPort: 0, AllowedClients: []string{"127.0.0.1"}, RequestTimeout: 1, MaxConnections: 128}, core)
	if change != nil {
		change(p)
	}
	if err := p.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = p.Stop() })
	return p
}
func proxyConnect(t *testing.T, p *Proxy) net.Conn {
	t.Helper()
	c, err := net.DialTimeout("tcp", p.Status()["listen_address"].(string), time.Second)
	if err != nil {
		t.Fatal(err)
	}
	_ = c.SetDeadline(time.Now().Add(4 * time.Second))
	return c
}
func proxyExchange(t *testing.T, p *Proxy, request string) string {
	t.Helper()
	c := proxyConnect(t, p)
	defer c.Close()
	if _, err := io.WriteString(c, request); err != nil {
		t.Fatal(err)
	}
	b, err := io.ReadAll(c)
	if err != nil && len(b) == 0 {
		t.Fatal(err)
	}
	return string(b)
}
func waitReleased(t *testing.T, c *fixtureCore) {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if c.active.Load() == 0 {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("core reference leaked")
}
func fixtureHeader(t *testing.T, r *bufio.Reader) []byte {
	t.Helper()
	header, err := readHeader(r)
	if err != nil {
		t.Error(err)
	}
	return header
}

const emptyOK = "HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"

func TestProxyExternalHTTPStreaming(t *testing.T) {
	captured := make(chan string, 1)
	endpoint := fixture(t, func(c net.Conn) {
		r := bufio.NewReader(c)
		head := fixtureHeader(t, r)
		body := make([]byte, 5)
		if _, err := io.ReadFull(r, body); err != nil {
			t.Error(err)
		}
		captured <- string(head) + string(body)
		_, _ = io.WriteString(c, "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
	})
	core := &fixtureCore{endpoint: endpoint}
	p := startTestProxy(t, core, nil)
	response := proxyExchange(t, p, "POST http://8.8.8.8/upload HTTP/1.1\r\nHost: 8.8.8.8\r\nContent-Length: 5\r\nProxy-Authorization: hidden\r\n\r\nhello")
	if !strings.HasSuffix(response, "OK") {
		t.Fatal(response)
	}
	head := <-captured
	if !strings.HasPrefix(head, "POST http://8.8.8.8:80/upload") || strings.Contains(head, "hidden") || !strings.HasSuffix(head, "hello") {
		t.Fatal(head)
	}
	waitReleased(t, core)
	if core.acquisitions.Load() != 1 || core.releases.Load() != 1 {
		t.Fatal("incorrect core references")
	}
}
func TestProxyCONNECTHalfClose(t *testing.T) {
	endpoint := fixture(t, func(c net.Conn) {
		r := bufio.NewReader(c)
		head := fixtureHeader(t, r)
		if strings.Contains(string(head), "hidden") {
			t.Error("proxy credentials leaked")
		}
		_, _ = io.WriteString(c, "HTTP/1.1 200 Connection Established\r\n\r\n")
		body, err := io.ReadAll(r)
		if err != nil {
			t.Error(err)
		}
		_, _ = io.WriteString(c, "echo:"+string(body))
	})
	core := &fixtureCore{endpoint: endpoint}
	p := startTestProxy(t, core, nil)
	c := proxyConnect(t, p)
	defer c.Close()
	_, _ = io.WriteString(c, "CONNECT 8.8.8.8:443 HTTP/1.1\r\nHost: 8.8.8.8:443\r\nProxy-Authorization: hidden\r\n\r\nhello")
	r := bufio.NewReader(c)
	head := fixtureHeader(t, r)
	if !strings.Contains(string(head), "200 Connection Established") {
		t.Fatal(string(head))
	}
	if core.active.Load() != 1 {
		t.Fatal("core released during active tunnel")
	}
	_ = c.(*net.TCPConn).CloseWrite()
	body, err := io.ReadAll(r)
	if err != nil || string(body) != "echo:hello" {
		t.Fatalf("%q %v", body, err)
	}
	waitReleased(t, core)
}
func TestProxyLocalPinnedOriginAndCONNECT(t *testing.T) {
	for _, method := range []string{"GET", "CONNECT"} {
		t.Run(method, func(t *testing.T) {
			endpoint := fixture(t, func(c net.Conn) {
				r := bufio.NewReader(c)
				if method == "GET" {
					head := fixtureHeader(t, r)
					if !strings.HasPrefix(string(head), "GET /status HTTP/1.1") {
						t.Error(string(head))
					}
					_, _ = io.WriteString(c, emptyOK)
				} else {
					body := make([]byte, 4)
					_, _ = io.ReadFull(r, body)
					_, _ = c.Write(body)
				}
			})
			core := &fixtureCore{}
			var dialed string
			p := startTestProxy(t, core, func(p *Proxy) {
				p.resolver = &fakeResolver{answers: fixtureAnswers("192.168.1.10")}
				p.dial = func(ctx context.Context, network, address string) (net.Conn, error) {
					dialed = address
					return (&net.Dialer{}).DialContext(ctx, network, endpoint)
				}
			})
			target := "GET http://printer.lan:8765/status"
			body := ""
			if method == "CONNECT" {
				target = "CONNECT printer.lan:8765"
				body = "ping"
			}
			response := proxyExchange(t, p, target+" HTTP/1.1\r\nHost: printer.lan:8765\r\n\r\n"+body)
			if !strings.Contains(response, "200") || dialed != "192.168.1.10:8765" {
				t.Fatalf("%q dial=%s", response, dialed)
			}
			if method == "CONNECT" && !strings.HasSuffix(response, "ping") {
				t.Fatal(response)
			}
			if core.acquisitions.Load() != 0 {
				t.Fatal("LAN woke core")
			}
		})
	}
}
func TestProxyDenialBeforeCore(t *testing.T) {
	core := &fixtureCore{}
	p := startTestProxy(t, core, nil)
	for _, target := range []string{"127.0.0.1", "169.254.169.254", "localhost", "foo.localhost", "100.64.0.1", "[::1]"} {
		for _, method := range []string{"GET", "CONNECT"} {
			first := "GET http://" + target + "/"
			host := target
			if method == "CONNECT" {
				first = "CONNECT " + target + ":80"
				host = target + ":80"
			}
			response := proxyExchange(t, p, first+" HTTP/1.1\r\nHost: "+host+"\r\n\r\n")
			if !strings.Contains(response, "403 Forbidden") {
				t.Fatalf("%s: %s", target, response)
			}
		}
	}
	if core.acquisitions.Load() != 0 {
		t.Fatal("denied destination woke core")
	}
}
func TestProxyDNSFailureBeforeCore(t *testing.T) {
	for _, test := range []struct {
		name     string
		resolver *fakeResolver
		status   string
	}{
		{"mixed denied", &fakeResolver{answers: fixtureAnswers("8.8.8.8", "127.0.0.1")}, "403"},
		{"NXDOMAIN", &fakeResolver{err: errors.New("NXDOMAIN")}, "502"},
		{"no answers", &fakeResolver{}, "502"},
	} {
		t.Run(test.name, func(t *testing.T) {
			core := &fixtureCore{}
			p := startTestProxy(t, core, func(p *Proxy) { p.resolver = test.resolver })
			response := proxyExchange(t, p, "GET http://fixture.example/ HTTP/1.1\r\nHost: fixture.example\r\n\r\n")
			if !strings.Contains(response, test.status) {
				t.Fatal(response)
			}
			if core.acquisitions.Load() != 0 {
				t.Fatal("DNS failure woke core")
			}
		})
	}
}
func TestProxyClientAllowlistAndConnectionLimit(t *testing.T) {
	// Admission checks happen before request parsing. Read the rejection without
	// racing a request write against the server's close: Windows may discard the
	// queued response when unread request bytes cause a TCP reset on close.
	admissionResponse := func(p *Proxy) string {
		c := proxyConnect(t, p)
		defer c.Close()
		response, err := io.ReadAll(c)
		if err != nil {
			t.Fatal(err)
		}
		return string(response)
	}
	core := &fixtureCore{}
	p := startTestProxy(t, core, func(p *Proxy) { p.cfg.AllowedClients = []string{"192.168.1.55"} })
	response := admissionResponse(p)
	if !strings.Contains(response, "403 Forbidden") {
		t.Fatal(response)
	}
	if stats := p.Status(); stats["denied_clients"].(uint64) != 1 || stats["accepted"].(uint64) != 0 {
		t.Fatalf("unapproved peer was not rejected at admission: %v", stats)
	}
	p = startTestProxy(t, core, func(p *Proxy) { p.cfg.MaxConnections = 1 })
	c := proxyConnect(t, p)
	defer c.Close()
	_, _ = io.WriteString(c, "GET ")
	deadline := time.Now().Add(time.Second)
	for p.Status()["active"].(uint64) != 1 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if p.Status()["active"].(uint64) != 1 {
		t.Fatal("first client did not occupy the connection slot")
	}
	response = admissionResponse(p)
	if !strings.Contains(response, "503 Service Unavailable") {
		t.Fatal(response)
	}
	if stats := p.Status(); stats["accepted"].(uint64) != 1 || stats["active"].(uint64) != 1 {
		t.Fatalf("over-limit peer was accepted: %v", stats)
	}
	if core.acquisitions.Load() != 0 {
		t.Fatal("unapproved client woke core")
	}
}
func TestProxyChunkedTrailers(t *testing.T) {
	endpoint := fixture(t, func(c net.Conn) {
		r := bufio.NewReader(c)
		head := fixtureHeader(t, r)
		if strings.Contains(string(head), "Trailer:") {
			t.Error("Trailer leaked")
		}
		want := "5\r\nhello\r\n0\r\n\r\n"
		body := make([]byte, len(want))
		_, err := io.ReadFull(r, body)
		if err != nil || string(body) != want {
			t.Errorf("%q %v", body, err)
		}
		_, _ = io.WriteString(c, emptyOK)
	})
	core := &fixtureCore{endpoint: endpoint}
	p := startTestProxy(t, core, nil)
	response := proxyExchange(t, p, "POST http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\nTransfer-Encoding: chunked\r\nTrailer: X-Trailer\r\n\r\n0005\r\nhello\r\n0\r\nX-Trailer: discard\r\nProxy-Authorization: secret\r\n\r\n")
	if !strings.Contains(response, "200 OK") {
		t.Fatal(response)
	}
	waitReleased(t, core)
}
func TestProxyNoPipelining(t *testing.T) {
	endpoint := fixture(t, func(c net.Conn) {
		r := bufio.NewReader(c)
		_ = fixtureHeader(t, r)
		_ = c.SetReadDeadline(time.Now().Add(50 * time.Millisecond))
		b := make([]byte, 1)
		if n, _ := r.Read(b); n != 0 {
			t.Error("pipelined request forwarded")
		}
		_, _ = io.WriteString(c, emptyOK)
	})
	core := &fixtureCore{endpoint: endpoint}
	p := startTestProxy(t, core, nil)
	response := proxyExchange(t, p, "GET http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\n\r\nGET http://127.0.0.1/ HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
	if !strings.Contains(response, "200 OK") {
		t.Fatal(response)
	}
	waitReleased(t, core)
	if core.acquisitions.Load() != 1 {
		t.Fatal("second request handled")
	}
}
func TestProxyExpectContinue(t *testing.T) {
	endpoint := fixture(t, func(c net.Conn) {
		r := bufio.NewReader(c)
		head := fixtureHeader(t, r)
		if strings.Contains(string(head), "Expect:") {
			t.Error("Expect leaked")
		}
		body := make([]byte, 5)
		_, err := io.ReadFull(r, body)
		if err != nil || string(body) != "hello" {
			t.Errorf("%q %v", body, err)
		}
		_, _ = io.WriteString(c, emptyOK)
	})
	core := &fixtureCore{endpoint: endpoint}
	p := startTestProxy(t, core, nil)
	c := proxyConnect(t, p)
	defer c.Close()
	_, _ = io.WriteString(c, "POST http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\nContent-Length: 5\r\nExpect: 100-continue\r\n\r\n")
	r := bufio.NewReader(c)
	if got := string(fixtureHeader(t, r)); got != "HTTP/1.1 100 Continue\r\n\r\n" {
		t.Fatal(got)
	}
	_, _ = io.WriteString(c, "hello")
	body, _ := io.ReadAll(r)
	if !strings.Contains(string(body), "200 OK") {
		t.Fatal(string(body))
	}
	waitReleased(t, core)
}
func TestProxyMalformedBodiesReleaseCore(t *testing.T) {
	for _, test := range []struct {
		name, headers, body string
		halfClose           bool
	}{
		{"extension", "Transfer-Encoding: chunked", "5;ext=unsupported\r\nhello\r\n0\r\n\r\n", false},
		{"bad chunk terminator", "Transfer-Encoding: chunked", "1\r\naXX", false},
		{"truncated content length", "Content-Length: 5", "hi", true},
		{"folded trailer", "Transfer-Encoding: chunked", "0\r\n X-Secret: forbidden\r\n\r\n", false},
	} {
		t.Run(test.name, func(t *testing.T) {
			endpoint := fixture(t, func(c net.Conn) { r := bufio.NewReader(c); _ = fixtureHeader(t, r); _, _ = io.ReadAll(r) })
			core := &fixtureCore{endpoint: endpoint}
			p := startTestProxy(t, core, nil)
			c := proxyConnect(t, p)
			defer c.Close()
			_, _ = io.WriteString(c, "POST http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\n"+test.headers+"\r\n\r\n"+test.body)
			if test.halfClose {
				_ = c.(*net.TCPConn).CloseWrite()
			}
			response, _ := io.ReadAll(c)
			if !strings.Contains(string(response), "400 Bad Request") {
				t.Fatal(string(response))
			}
			waitReleased(t, core)
			if core.releases.Load() != 1 {
				t.Fatal("reference not released")
			}
		})
	}
}
func TestProxyBackendFailures(t *testing.T) {
	t.Run("CONNECT rejection", func(t *testing.T) {
		endpoint := fixture(t, func(c net.Conn) {
			_ = fixtureHeader(t, bufio.NewReader(c))
			_, _ = io.WriteString(c, "HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
		})
		core := &fixtureCore{endpoint: endpoint}
		p := startTestProxy(t, core, nil)
		response := proxyExchange(t, p, "CONNECT 8.8.8.8:443 HTTP/1.1\r\nHost: 8.8.8.8:443\r\n\r\n")
		if !strings.Contains(response, "502 Bad Gateway") {
			t.Fatal(response)
		}
		waitReleased(t, core)
	})
	t.Run("startup failure", func(t *testing.T) {
		core := &fixtureCore{err: errors.New("startup failed")}
		p := startTestProxy(t, core, nil)
		response := proxyExchange(t, p, "GET http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\n\r\n")
		if !strings.Contains(response, "502 Bad Gateway") {
			t.Fatal(response)
		}
		if core.releases.Load() != 0 {
			t.Fatal("released unacquired core")
		}
	})
	t.Run("upstream timeout", func(t *testing.T) {
		endpoint := fixture(t, func(c net.Conn) { _ = fixtureHeader(t, bufio.NewReader(c)); _, _ = io.Copy(io.Discard, c) })
		core := &fixtureCore{endpoint: endpoint}
		p := startTestProxy(t, core, func(p *Proxy) { p.timeout = 50 * time.Millisecond })
		response := proxyExchange(t, p, "GET http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\n\r\n")
		if !strings.Contains(response, "504 Gateway Timeout") {
			t.Fatal(response)
		}
		waitReleased(t, core)
	})
}
func TestProxyStopReleasesTunnel(t *testing.T) {
	endpoint := fixture(t, func(c net.Conn) {
		_ = fixtureHeader(t, bufio.NewReader(c))
		_, _ = io.WriteString(c, "HTTP/1.1 200 OK\r\n\r\n")
		_, _ = io.Copy(io.Discard, c)
	})
	core := &fixtureCore{endpoint: endpoint}
	p := startTestProxy(t, core, nil)
	c := proxyConnect(t, p)
	defer c.Close()
	_, _ = io.WriteString(c, "CONNECT 8.8.8.8:443 HTTP/1.1\r\nHost: 8.8.8.8:443\r\n\r\n")
	_ = fixtureHeader(t, bufio.NewReader(c))
	if core.active.Load() != 1 {
		t.Fatal("tunnel not acquired")
	}
	if err := p.Stop(); err != nil {
		t.Fatal(err)
	}
	if core.active.Load() != 0 || core.releases.Load() != 1 || p.Status()["active"].(uint64) != 0 {
		t.Fatal("shutdown leaked reference")
	}
	if err := p.Start(); err != nil {
		t.Fatal("restart:", err)
	}
}
func TestProxyHeaderTimeoutAndBindConflict(t *testing.T) {
	p := startTestProxy(t, &fixtureCore{}, func(p *Proxy) { p.timeout = 30 * time.Millisecond })
	c := proxyConnect(t, p)
	defer c.Close()
	response, _ := io.ReadAll(c)
	if !strings.Contains(string(response), "504 Gateway Timeout") {
		t.Fatal(string(response))
	}
	_, port, _ := net.SplitHostPort(p.Status()["listen_address"].(string))
	cfg := p.cfg
	cfg.ListenPort, _ = strconv.Atoi(port)
	duplicate := NewProxy(cfg, &fixtureCore{})
	if err := duplicate.Start(); err == nil {
		_ = duplicate.Stop()
		t.Fatal("bind conflict not detected")
	}
}

type directFixtureCore struct {
	fixtureCore
	endpoint string
	targets  chan string
}

func (c *directFixtureCore) DialExternal(ctx context.Context, host string, port int) (net.Conn, error) {
	c.targets <- net.JoinHostPort(host, strconv.Itoa(port))
	return (&net.Dialer{}).DialContext(ctx, "tcp", c.endpoint)
}
func TestProxyEmbeddedExternalDialer(t *testing.T) {
	for _, method := range []string{"GET", "CONNECT"} {
		t.Run(method, func(t *testing.T) {
			endpoint := fixture(t, func(c net.Conn) {
				if method == "GET" {
					head := fixtureHeader(t, bufio.NewReader(c))
					if !strings.HasPrefix(string(head), "GET /status HTTP/1.1") {
						t.Error(string(head))
					}
					_, _ = io.WriteString(c, emptyOK)
				} else {
					body := make([]byte, 4)
					_, _ = io.ReadFull(c, body)
					_, _ = c.Write(body)
				}
			})
			core := &directFixtureCore{endpoint: endpoint, targets: make(chan string, 1)}
			p := startTestProxy(t, core, nil)
			first := "GET http://8.8.8.8:8765/status"
			body := ""
			if method == "CONNECT" {
				first = "CONNECT 8.8.8.8:8765"
				body = "ping"
			}
			response := proxyExchange(t, p, fmt.Sprintf("%s HTTP/1.1\r\nHost: 8.8.8.8:8765\r\n\r\n%s", first, body))
			if !strings.Contains(response, "200") {
				t.Fatal(response)
			}
			if got := <-core.targets; got != "8.8.8.8:8765" {
				t.Fatal(got)
			}
			waitReleased(t, &core.fixtureCore)
		})
	}
}

func TestProxyHeaderDeadlineDoesNotResetOnTrickle(t *testing.T) {
	p := startTestProxy(t, &fixtureCore{}, func(p *Proxy) { p.timeout = 80 * time.Millisecond })
	c := proxyConnect(t, p)
	defer c.Close()
	done := make(chan struct{})
	go func() {
		defer close(done)
		for i := 0; i < 30; i++ {
			if _, err := io.WriteString(c, "G"); err != nil {
				return
			}
			time.Sleep(15 * time.Millisecond)
		}
	}()
	start := time.Now()
	response, _ := io.ReadAll(c)
	_ = c.Close()
	<-done
	if !strings.Contains(string(response), "504 Gateway Timeout") {
		t.Fatal(string(response))
	}
	if elapsed := time.Since(start); elapsed > 300*time.Millisecond {
		t.Fatalf("header deadline extended by trickle: %s", elapsed)
	}
}

// Embedding net.Conn hides its concrete CloseWrite method, as adapter wrappers
// do. Upstream must be followed to retain half-close through these wrappers.
type wrappedFixtureConn struct{ net.Conn }

func (c *wrappedFixtureConn) Upstream() any { return c.Conn }

type wrappedFixtureCore struct {
	fixtureCore
	endpoint string
}

func (c *wrappedFixtureCore) DialExternal(ctx context.Context, _ string, _ int) (net.Conn, error) {
	conn, err := (&net.Dialer{}).DialContext(ctx, "tcp", c.endpoint)
	if err != nil {
		return nil, err
	}
	return &wrappedFixtureConn{&wrappedFixtureConn{conn}}, nil
}
func TestProxyWrappedExternalHalfClose(t *testing.T) {
	endpoint := fixture(t, func(c net.Conn) {
		body, err := io.ReadAll(c)
		if err != nil {
			t.Error(err)
			return
		}
		_, _ = io.WriteString(c, "echo:"+string(body))
	})
	core := &wrappedFixtureCore{endpoint: endpoint}
	p := startTestProxy(t, core, nil)
	c := proxyConnect(t, p)
	defer c.Close()
	_, _ = io.WriteString(c, "CONNECT 8.8.8.8:443 HTTP/1.1\r\nHost: 8.8.8.8:443\r\n\r\nhello")
	r := bufio.NewReader(c)
	if head := string(fixtureHeader(t, r)); !strings.Contains(head, "200 Connection Established") {
		t.Fatal(head)
	}
	if err := c.(*net.TCPConn).CloseWrite(); err != nil {
		t.Fatal(err)
	}
	response, err := io.ReadAll(r)
	if err != nil || string(response) != "echo:hello" {
		t.Fatalf("half-close response %q: %v", response, err)
	}
	waitReleased(t, &core.fixtureCore)
}

type cyclicWrapper struct{}

func (c *cyclicWrapper) Upstream() any { return c }

type ownHalfCloser struct {
	cyclicWrapper
	calls int
}

func (c *ownHalfCloser) CloseWrite() error { c.calls++; return nil }
func TestHalfCloseWrapperTraversalBounded(t *testing.T) {
	if err := closeWriteUpstream(&cyclicWrapper{}); err == nil {
		t.Fatal("wrapper cycle was not detected by depth limit")
	}
	c := &ownHalfCloser{}
	if err := closeWriteUpstream(c); err != nil || c.calls != 1 {
		t.Fatalf("protocol-aware half-close bypassed: %v %d", err, c.calls)
	}
	if err := closeWriteUpstream(struct{}{}); err != nil {
		t.Fatal("non-half-closable streams should be tolerated")
	}
}

type netConnFixtureWrapper struct{ net.Conn }

func (c *netConnFixtureWrapper) NetConn() net.Conn { return c.Conn }

type countedHalfConn struct {
	net.Conn
	calls int
}

func (c *countedHalfConn) CloseWrite() error { c.calls++; return nil }
func TestHalfCloseNetConnWrapper(t *testing.T) {
	c := &countedHalfConn{}
	if err := closeWriteUpstream(&netConnFixtureWrapper{c}); err != nil || c.calls != 1 {
		t.Fatalf("NetConn half-close was not forwarded: %v %d", err, c.calls)
	}
}
