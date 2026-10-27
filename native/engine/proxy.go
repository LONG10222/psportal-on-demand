// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const (
	MaxHeaderBytes = 65536
	MaxHeaderCount = 100
	MaxLineBytes   = 8192
)

// Core retains one shared backend for the complete lifetime of an external
// connection. Local traffic never calls Acquire or Release.
type Core interface {
	Acquire(context.Context) (string, error)
	Release()
}

// ExternalDialer is implemented by embedded cores that return an already
// connected target stream, rather than the address of an HTTP proxy backend.
// It must apply independent destination rejection when resolving remotely.
type ExternalDialer interface {
	DialExternal(context.Context, string, int) (net.Conn, error)
}

type ProtocolError struct {
	Message string
	Status  int
}

func (e *ProtocolError) Error() string { return e.Message }
func protocolError(message string, status ...int) error {
	code := 400
	if len(status) > 0 {
		code = status[0]
	}
	return &ProtocolError{Message: message, Status: code}
}

type Header struct{ Name, Value string }
type Request struct {
	Method, Host, Path, Version string
	Port                        int
	Headers                     []Header
	ContentLength               *uint64
	Chunked, ExpectContinue     bool
	ConnectionHeaders           map[string]bool
}

func (r Request) Authority() string { return net.JoinHostPort(r.Host, strconv.Itoa(r.Port)) }

var (
	tokenPattern         = regexp.MustCompile("^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
	requestLinePattern   = regexp.MustCompile(`^([A-Z]{1,32}) ([!-~]+) (HTTP/1\.[01])$`)
	ipv6AuthorityPattern = regexp.MustCompile(`^\[([^\]]+)\](?::([0-9]{1,5}))?$`)
	authorityPattern     = regexp.MustCompile(`^([^:\[\]]+)(?::([0-9]{1,5}))?$`)
	lengthPattern        = regexp.MustCompile(`^[0-9]{1,19}$`)
	chunkPattern         = regexp.MustCompile(`^[0-9a-fA-F]{1,16}\r\n$`)
	statusPattern        = regexp.MustCompile(`^HTTP/1\.[01] ([0-9]{3})(?: [\x20-\x7e]*)?$`)
	hopHeaders           = map[string]bool{
		"connection": true, "proxy-connection": true, "proxy-authorization": true,
		"proxy-authenticate": true, "keep-alive": true, "te": true, "trailer": true,
		"transfer-encoding": true, "upgrade": true,
	}
)

func ParseAuthority(authority string, defaultPort int) (string, int, error) {
	if authority == "" || strings.ContainsAny(authority, "@/?#\\%") {
		return "", 0, protocolError("invalid authority")
	}
	var match []string
	if strings.HasPrefix(authority, "[") {
		match = ipv6AuthorityPattern.FindStringSubmatch(authority)
		if match == nil || !IsIPv6(match[1]) {
			return "", 0, protocolError("invalid IPv6 authority")
		}
	} else {
		match = authorityPattern.FindStringSubmatch(authority)
		if match == nil {
			return "", 0, protocolError("invalid authority")
		}
		host := NormalizeHost(match[1])
		if !IsIPv4(host) && !ValidName(host) {
			return "", 0, protocolError("invalid host")
		}
	}
	host := NormalizeHost(match[1])
	port := defaultPort
	if match[2] != "" {
		port, _ = strconv.Atoi(match[2])
	}
	if port < 1 || port > 65535 {
		return "", 0, protocolError("invalid port")
	}
	return host, port, nil
}
func headerLines(data []byte) ([]string, error) {
	if len(data) > MaxHeaderBytes {
		return nil, protocolError("headers too large", 431)
	}
	if !bytes.HasSuffix(data, []byte("\r\n\r\n")) {
		return nil, protocolError("incomplete headers")
	}
	lines := strings.Split(string(data[:len(data)-4]), "\r\n")
	if len(lines) > MaxHeaderCount+1 {
		return nil, protocolError("too many headers", 431)
	}
	for _, line := range lines {
		if len(line) > MaxLineBytes {
			return nil, protocolError("header line too long", 431)
		}
		for i := 0; i < len(line); i++ {
			if (line[i] < 32 && line[i] != '\t') || line[i] == 127 {
				return nil, protocolError("invalid header control character")
			}
		}
	}
	return lines, nil
}
func parseFields(lines []string) ([]Header, error) {
	fields := make([]Header, 0, len(lines))
	for _, line := range lines {
		if line == "" || line[0] == ' ' || line[0] == '\t' {
			return nil, protocolError("invalid or folded header")
		}
		name, value, ok := strings.Cut(line, ":")
		if !ok || !tokenPattern.MatchString(name) {
			return nil, protocolError("invalid header name")
		}
		fields = append(fields, Header{name, strings.Trim(value, " \t")})
	}
	return fields, nil
}
func ParseRequest(data []byte) (Request, error) {
	var r Request
	lines, err := headerLines(data)
	if err != nil {
		return r, err
	}
	match := requestLinePattern.FindStringSubmatch(lines[0])
	if match == nil {
		return r, protocolError("invalid request line")
	}
	r.Method, r.Version = match[1], match[3]
	target := match[2]
	if strings.ContainsAny(target, "\\#") {
		return r, protocolError("invalid request target")
	}
	defaultPort := 80
	if r.Method == "CONNECT" {
		defaultPort = 443
	}
	authority := target
	if r.Method != "CONNECT" {
		if !strings.HasPrefix(target, "http://") {
			return r, protocolError("absolute-form HTTP target required")
		}
		authority = target[len("http://"):]
		if pos := strings.IndexAny(authority, "/?"); pos >= 0 {
			r.Path = authority[pos:]
			authority = authority[:pos]
		}
		if r.Path == "" {
			r.Path = "/"
		}
		if strings.HasPrefix(r.Path, "?") {
			r.Path = "/" + r.Path
		}
	}
	r.Host, r.Port, err = ParseAuthority(authority, defaultPort)
	if err != nil {
		return r, err
	}
	r.Headers, err = parseFields(lines[1:])
	if err != nil {
		return r, err
	}
	values := map[string][]string{}
	for _, field := range r.Headers {
		name := strings.ToLower(field.Name)
		values[name] = append(values[name], field.Value)
	}
	hosts := values["host"]
	if len(hosts) > 1 || (r.Version == "HTTP/1.1" && len(hosts) == 0) {
		return r, protocolError("exactly one Host is required")
	}
	if len(hosts) == 1 {
		h, p, e := ParseAuthority(hosts[0], defaultPort)
		if e != nil {
			return r, e
		}
		if h != r.Host || p != r.Port {
			return r, protocolError("Host disagrees with request target")
		}
	}
	lengths, encodings := values["content-length"], values["transfer-encoding"]
	if len(lengths) > 1 || len(encodings) > 1 || (len(lengths) > 0 && len(encodings) > 0) {
		return r, protocolError("ambiguous body framing")
	}
	if len(lengths) > 0 {
		if !lengthPattern.MatchString(lengths[0]) {
			return r, protocolError("invalid Content-Length")
		}
		length, e := strconv.ParseUint(lengths[0], 10, 64)
		if e != nil {
			return r, protocolError("invalid Content-Length")
		}
		r.ContentLength = &length
	}
	r.Chunked = len(encodings) > 0
	if r.Chunked && (strings.ToLower(encodings[0]) != "chunked" || r.Version != "HTTP/1.1") {
		return r, protocolError("unsupported Transfer-Encoding")
	}
	if r.Method == "CONNECT" && (r.Chunked || (r.ContentLength != nil && *r.ContentLength != 0)) {
		return r, protocolError("CONNECT cannot carry a framed request body")
	}
	if _, ok := values["upgrade"]; ok {
		return r, protocolError("HTTP upgrade is unsupported; use CONNECT")
	}
	r.ConnectionHeaders = map[string]bool{}
	for _, name := range []string{"connection", "proxy-connection"} {
		for _, value := range values[name] {
			for _, rawToken := range strings.Split(value, ",") {
				token := strings.ToLower(strings.Trim(rawToken, " \t"))
				if !tokenPattern.MatchString(token) {
					return r, protocolError("invalid Connection token")
				}
				if token == "host" || token == "content-length" || token == "transfer-encoding" {
					return r, protocolError("Connection cannot remove framing headers")
				}
				r.ConnectionHeaders[token] = true
			}
		}
	}
	expects := values["expect"]
	if len(expects) > 0 && (len(expects) != 1 || strings.ToLower(expects[0]) != "100-continue" || r.Method == "CONNECT") {
		return r, protocolError("unsupported expectation", 417)
	}
	r.ExpectContinue = len(expects) > 0
	return r, nil
}
func (r Request) ForwardedHeader(external bool) []byte {
	target := r.Path
	if r.Method == "CONNECT" {
		target = r.Authority()
	} else if external {
		target = "http://" + r.Authority() + r.Path
	}
	var b strings.Builder
	fmt.Fprintf(&b, "%s %s %s\r\nHost: %s\r\n", r.Method, target, r.Version, r.Authority())
	for _, field := range r.Headers {
		name := strings.ToLower(field.Name)
		if hopHeaders[name] || r.ConnectionHeaders[name] || name == "host" || name == "content-length" || name == "expect" {
			continue
		}
		fmt.Fprintf(&b, "%s: %s\r\n", field.Name, field.Value)
	}
	if r.Chunked {
		b.WriteString("Transfer-Encoding: chunked\r\n")
	} else if r.ContentLength != nil {
		fmt.Fprintf(&b, "Content-Length: %d\r\n", *r.ContentLength)
	}
	if r.Method != "CONNECT" {
		b.WriteString("Connection: close\r\n")
	}
	b.WriteString("\r\n")
	return []byte(b.String())
}

// Proxy handles one strict HTTP request per connection; CONNECT is a byte
// tunnel. The bounded parser intentionally avoids net/http's lenient parsing.
type clientRecord struct {
	Active   uint64 `json:"active"`
	Accepted uint64 `json:"accepted"`
	LastSeen int64  `json:"last_seen"`
}

type Proxy struct {
	cfg         Config
	core        Core
	timeout     time.Duration
	allowed     map[string]bool
	lifeMu      sync.Mutex
	mu          sync.Mutex
	listener    net.Listener
	ctx         context.Context
	cancel      context.CancelFunc
	closing     bool
	connections map[net.Conn]struct{}
	wg          sync.WaitGroup
	clients     map[string]*clientRecord
	stats       map[string]uint64
	lastError   string
	traffic     TrafficMeter
	resolver    ipResolver
	dial        func(context.Context, string, string) (net.Conn, error)
}

func NewProxy(cfg Config, core Core) *Proxy {
	return &Proxy{cfg: cfg, core: core, timeout: time.Duration(cfg.RequestTimeout) * time.Second,
		allowed: map[string]bool{}, clients: map[string]*clientRecord{}, connections: map[net.Conn]struct{}{},
		stats:    map[string]uint64{"accepted": 0, "denied_clients": 0, "local_requests": 0, "external_requests": 0, "errors": 0, "active": 0, "waking": 0, "forwarding": 0},
		resolver: systemResolver, dial: (&net.Dialer{}).DialContext}
}
func (p *Proxy) Start() error {
	p.lifeMu.Lock()
	defer p.lifeMu.Unlock()
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.listener != nil {
		return errors.New("proxy is already started")
	}
	if p.timeout <= 0 || p.cfg.MaxConnections < 1 {
		return errors.New("request_timeout and max_connections must be positive")
	}
	if !IsIPv4(p.cfg.ListenHost) {
		return errors.New("listen_host must be an IPv4 address")
	}
	if len(p.cfg.AllowedClients) == 0 {
		return errors.New("allowed_clients must not be empty")
	}
	allowed := map[string]bool{}
	for _, ip := range p.cfg.AllowedClients {
		if !IsIPv4(ip) {
			return errors.New("allowed_clients must contain explicit IPv4 addresses")
		}
		allowed[ip] = true
	}
	listener, err := net.Listen("tcp4", net.JoinHostPort(p.cfg.ListenHost, strconv.Itoa(p.cfg.ListenPort)))
	if err != nil {
		return err
	}
	p.listener = listener
	p.allowed = allowed
	p.closing = false
	p.ctx, p.cancel = context.WithCancel(context.Background())
	p.wg.Add(1)
	go p.accept(listener, p.ctx)
	return nil
}
func (p *Proxy) Stop() error {
	p.lifeMu.Lock()
	defer p.lifeMu.Unlock()
	p.mu.Lock()
	p.closing = true
	if p.cancel != nil {
		p.cancel()
	}
	if p.listener != nil {
		_ = p.listener.Close()
		p.listener = nil
	}
	for c := range p.connections {
		_ = c.Close()
	}
	p.mu.Unlock()
	p.wg.Wait()
	p.mu.Lock()
	clear(p.clients)
	p.mu.Unlock()
	return nil
}
func (p *Proxy) Status() map[string]any {
	p.mu.Lock()
	defer p.mu.Unlock()
	out := map[string]any{"running": p.listener != nil, "listen_address": ""}
	if p.listener != nil {
		out["listen_address"] = p.listener.Addr().String()
	}
	clients := make([]map[string]any, 0)
	activeDevices := 0
	now := time.Now().Unix()
	keys := make([]string, 0, len(p.clients))
	for ip, item := range p.clients {
		if item.Active == 0 && now-item.LastSeen >= 300 {
			delete(p.clients, ip)
			continue
		}
		keys = append(keys, ip)
	}
	sort.Strings(keys)
	for _, ip := range keys {
		item := p.clients[ip]
		if item.Active > 0 {
			activeDevices++
		}
		clients = append(clients, map[string]any{"ip": ip, "active": item.Active, "accepted": item.Accepted, "last_seen": item.LastSeen})
	}
	out["devices"] = clients
	out["active_devices"] = activeDevices
	for key, value := range p.stats {
		out[key] = value
	}
	activeIPs := make([]string, 0, activeDevices)
	for _, ip := range keys {
		if p.clients[ip].Active > 0 {
			activeIPs = append(activeIPs, ip)
		}
	}
	out["client_ips"], out["connected_clients"], out["active_connections"] = activeIPs, activeDevices, p.stats["active"]
	out["error"] = p.lastError
	out["traffic"] = p.traffic.Snapshot()
	return out
}
func (p *Proxy) increment(key string) { p.mu.Lock(); p.stats[key]++; p.mu.Unlock() }
func (p *Proxy) accept(listener net.Listener, ctx context.Context) {
	defer p.wg.Done()
	for {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		p.mu.Lock()
		if p.closing {
			p.mu.Unlock()
			_ = conn.Close()
			continue
		}
		p.connections[conn] = struct{}{}
		p.wg.Add(1)
		p.mu.Unlock()
		go func() {
			defer p.wg.Done()
			defer func() { _ = conn.Close(); p.mu.Lock(); delete(p.connections, conn); p.mu.Unlock() }()
			p.handle(ctx, conn)
		}()
	}
}

type timedConn struct {
	net.Conn
	timeout time.Duration
	// Set only by the single reader before header parsing, preventing a
	// slow client from extending the total header timeout one byte at a time.
	readLimit  time.Time
	readClosed atomic.Bool
}

func (c *timedConn) Read(b []byte) (int, error) {
	if c.readClosed.Load() {
		return 0, net.ErrClosed
	}
	deadline := time.Now().Add(c.timeout)
	if !c.readLimit.IsZero() && c.readLimit.Before(deadline) {
		deadline = c.readLimit
	}
	_ = c.Conn.SetReadDeadline(deadline)
	if c.readClosed.Load() {
		// CloseRead may have raced with the deadline refresh above. Never
		// let a new read restore the idle timeout after cancellation.
		_ = c.Conn.SetReadDeadline(time.Now())
		return 0, net.ErrClosed
	}
	return c.Conn.Read(b)
}
func (c *timedConn) Write(b []byte) (int, error) {
	_ = c.Conn.SetWriteDeadline(time.Now().Add(c.timeout))
	return c.Conn.Write(b)
}
func (c *timedConn) CloseRead() error {
	c.readClosed.Store(true)
	// Socket shutdown alone need not cancel a pending asynchronous read on
	// Windows. An expired deadline wakes Go's poller without closing writes.
	err := c.Conn.SetReadDeadline(time.Now())
	if half, ok := c.Conn.(interface{ CloseRead() error }); ok {
		if closeErr := half.CloseRead(); closeErr != nil {
			return closeErr
		}
	}
	return err
}
func (c *timedConn) CloseWrite() error { return closeWriteUpstream(c.Conn) }

// Adapter wrappers commonly expose Upstream while their embedded net.Conn
// interface hides CloseWrite. Preserve TCP/TLS half-close without bypassing
// wrappers that implement their own protocol-aware CloseWrite. Bound traversal
// so a malformed wrapper cycle cannot hang shutdown or an active connection.
func closeWriteUpstream(conn any) error {
	for depth := 0; depth < 32; depth++ {
		if half, ok := conn.(interface{ CloseWrite() error }); ok {
			return half.CloseWrite()
		}
		if wrapper, ok := conn.(interface{ Upstream() any }); ok {
			conn = wrapper.Upstream()
			continue
		}
		if wrapper, ok := conn.(interface{ NetConn() net.Conn }); ok {
			conn = wrapper.NetConn()
			continue
		}
		return nil
	}
	return errors.New("connection wrapper depth exceeded during half-close")
}
func readLine(reader *bufio.Reader) ([]byte, error) {
	line, err := reader.ReadSlice('\n')
	if errors.Is(err, bufio.ErrBufferFull) {
		return nil, protocolError("header line too long", 431)
	}
	if err != nil {
		if errors.Is(err, io.EOF) {
			return nil, protocolError("incomplete headers")
		}
		return nil, err
	}
	if !bytes.HasSuffix(line, []byte("\r\n")) {
		return nil, protocolError("invalid line ending")
	}
	return line, nil
}
func readHeader(reader *bufio.Reader) ([]byte, error) {
	data := make([]byte, 0, 1024)
	for {
		line, err := readLine(reader)
		if err != nil {
			return nil, err
		}
		if len(line) > MaxLineBytes+2 || len(data)+len(line) > MaxHeaderBytes {
			return nil, protocolError("headers too large", 431)
		}
		data = append(data, line...)
		if len(line) == 2 {
			return data, nil
		}
	}
}
func writeAll(writer io.Writer, data []byte) error {
	for len(data) > 0 {
		n, err := writer.Write(data)
		if err != nil {
			return err
		}
		if n == 0 {
			return io.ErrShortWrite
		}
		data = data[n:]
	}
	return nil
}
func copyExactly(reader io.Reader, writer io.Writer, length uint64) error {
	buf := make([]byte, 65536)
	for length > 0 {
		next := uint64(len(buf))
		if length < next {
			next = length
		}
		n, err := io.ReadFull(reader, buf[:int(next)])
		if err != nil {
			if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
				return protocolError("incomplete request body")
			}
			return err
		}
		if err = writeAll(writer, buf[:n]); err != nil {
			return err
		}
		length -= uint64(n)
	}
	return nil
}
func forwardBody(reader *bufio.Reader, writer io.Writer, request Request) error {
	if !request.Chunked {
		if request.ContentLength != nil {
			return copyExactly(reader, writer, *request.ContentLength)
		}
		return nil
	}
	for {
		line, err := readLine(reader)
		if err != nil {
			return err
		}
		if !chunkPattern.Match(line) {
			return protocolError("invalid chunk size")
		}
		size, err := strconv.ParseUint(string(line[:len(line)-2]), 16, 64)
		if err != nil {
			return protocolError("invalid chunk size")
		}
		if size == 0 {
			total := 0
			for count := 0; count <= MaxHeaderCount; count++ {
				trailer, err := readLine(reader)
				if err != nil {
					return err
				}
				total += len(trailer)
				if total > MaxHeaderBytes || len(trailer) > MaxLineBytes {
					return protocolError("trailers too large", 431)
				}
				if len(trailer) == 2 {
					return writeAll(writer, []byte("0\r\n\r\n"))
				}
				lines, err := headerLines(append(append([]byte("TRAILERS\r\n"), trailer...), '\r', '\n'))
				if err != nil {
					return err
				}
				if _, err = parseFields(lines[1:]); err != nil {
					return err
				}
			}
			return protocolError("too many trailers", 431)
		}
		if err = writeAll(writer, []byte(strconv.FormatUint(size, 16)+"\r\n")); err != nil {
			return err
		}
		if err = copyExactly(reader, writer, size); err != nil {
			return err
		}
		var end [2]byte
		if _, err = io.ReadFull(reader, end[:]); err != nil {
			if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
				return protocolError("incomplete chunk terminator")
			}
			return err
		}
		if end != [2]byte{'\r', '\n'} {
			return protocolError("invalid chunk terminator")
		}
		if err = writeAll(writer, end[:]); err != nil {
			return err
		}
	}
}
func pump(reader io.Reader, writer *timedConn, responded *atomic.Bool) error {
	buf := make([]byte, 65536)
	for {
		n, err := reader.Read(buf)
		if n > 0 {
			if responded != nil {
				responded.Store(true)
			}
			if writeErr := writeAll(writer, buf[:n]); writeErr != nil {
				return writeErr
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				_ = writer.CloseWrite()
				return nil
			}
			return err
		}
	}
}

// duplex preserves a response after client half-close; upstream EOF ends the
// connection. Cancellation wakes both directions and joins their goroutines.
func duplex(client, upstream net.Conn, outgoing, incoming func() error) error {
	send, receive := make(chan error, 1), make(chan error, 1)
	go func() { send <- outgoing() }()
	go func() { receive <- incoming() }()
	var result error
	select {
	case result = <-receive:
		// Stop the upload without closing the client's write side: a backend
		// failure before any response still needs an HTTP error response.
		if half, ok := client.(interface{ CloseRead() error }); ok {
			_ = half.CloseRead()
		} else {
			_ = client.SetReadDeadline(time.Now())
		}
		_ = upstream.Close()
		<-send
	case result = <-send:
		if result == nil {
			result = <-receive
		} else {
			// Keep the client's write side available for the HTTP error response.
			_ = upstream.Close()
			<-receive
		}
	}
	return result
}
func (p *Proxy) handle(ctx context.Context, raw net.Conn) {
	client := &timedConn{Conn: raw, timeout: p.timeout}
	peer, _, err := net.SplitHostPort(raw.RemoteAddr().String())
	if err != nil || !p.allowed[peer] {
		p.increment("denied_clients")
		p.writeError(client, 403)
		return
	}
	p.mu.Lock()
	if p.closing || p.stats["active"] >= uint64(p.cfg.MaxConnections) {
		p.mu.Unlock()
		p.writeError(client, 503)
		return
	}
	p.stats["active"]++
	p.stats["accepted"]++
	item := p.clients[peer]
	if item == nil {
		item = &clientRecord{}
		p.clients[peer] = item
	}
	item.Active++
	item.Accepted++
	item.LastSeen = time.Now().Unix()
	p.mu.Unlock()
	defer func() {
		p.mu.Lock()
		p.stats["active"]--
		item.Active--
		item.LastSeen = time.Now().Unix()
		p.mu.Unlock()
	}()
	var responded atomic.Bool
	err = p.serve(ctx, client, &responded)
	if err == nil {
		return
	}
	p.increment("errors")
	if responded.Load() || ctx.Err() != nil {
		return
	}
	status := 502
	var protocol *ProtocolError
	var timeout net.Error
	switch {
	case errors.As(err, &protocol):
		status = protocol.Status
	case errors.Is(err, ErrDestinationDenied):
		status = 403
	case errors.Is(err, context.DeadlineExceeded):
		status = 504
	case errors.As(err, &timeout) && timeout.Timeout():
		status = 504
	}
	if status == 502 || status == 504 {
		p.mu.Lock()
		p.lastError = "Forwarding failed; check the proxy engine and connectivity"
		p.mu.Unlock()
	}
	p.writeError(client, status)
}
func (p *Proxy) serve(ctx context.Context, client *timedConn, responded *atomic.Bool) error {
	metered := &trafficConn{Conn: client.Conn, meter: &p.traffic}
	client.Conn = metered
	reader := bufio.NewReaderSize(client, MaxLineBytes+2)
	client.readLimit = time.Now().Add(p.timeout)
	header, err := readHeader(reader)
	client.readLimit = time.Time{}
	if err != nil {
		return err
	}
	request, err := ParseRequest(header)
	if err != nil {
		return err
	}
	lookupCtx, cancel := context.WithTimeout(ctx, p.timeout)
	route, err := resolveDestination(lookupCtx, p.resolver, request.Host, request.Port)
	cancel()
	if err != nil {
		return err
	}
	backendProxy := false
	var rawUpstream net.Conn
	if route.Kind == "external" {
		if p.core == nil {
			return errors.New("external core is unavailable")
		}
		startupTimeout := time.Duration(p.cfg.WakeupTimeout) * time.Second
		if startupTimeout <= 0 {
			startupTimeout = p.timeout
		}
		startupCtx, startupCancel := context.WithTimeout(ctx, startupTimeout)
		p.increment("waking")
		endpoint, e := p.core.Acquire(startupCtx)
		p.mu.Lock()
		p.stats["waking"]--
		p.mu.Unlock()
		startupCancel()
		if e != nil {
			return e
		}
		defer p.core.Release()
		p.increment("external_requests")
		connectCtx, connectCancel := context.WithTimeout(ctx, p.timeout)
		defer connectCancel()
		if dialer, ok := p.core.(ExternalDialer); ok {
			rawUpstream, err = dialer.DialExternal(connectCtx, request.Host, request.Port)
		} else {
			backendProxy = true
			rawUpstream, err = p.dial(connectCtx, "tcp", endpoint)
		}
	} else if route.Kind == "local" && LocalIP(route.Address) {
		p.increment("local_requests")
		connectCtx, connectCancel := context.WithTimeout(ctx, p.timeout)
		defer connectCancel()
		rawUpstream, err = p.dial(connectCtx, "tcp", net.JoinHostPort(route.Address, strconv.Itoa(request.Port)))
	} else {
		return ErrDestinationDenied
	}
	if err != nil {
		return err
	}
	if rawUpstream == nil {
		return errors.New("upstream did not return a connection")
	}
	defer rawUpstream.Close()
	metered.setScope(route.Kind)
	p.mu.Lock()
	if p.closing {
		p.mu.Unlock()
		return context.Canceled
	}
	p.stats["forwarding"]++
	p.lastError = ""
	p.connections[rawUpstream] = struct{}{}
	p.mu.Unlock()
	defer func() { p.mu.Lock(); delete(p.connections, rawUpstream); p.stats["forwarding"]--; p.mu.Unlock() }()
	upstream := &timedConn{Conn: rawUpstream, timeout: p.timeout}
	upReader := bufio.NewReaderSize(upstream, MaxLineBytes+2)
	if request.Method == "CONNECT" {
		if backendProxy {
			if err = writeAll(upstream, request.ForwardedHeader(true)); err != nil {
				return err
			}
			upstream.readLimit = time.Now().Add(p.timeout)
			response, e := readHeader(upReader)
			upstream.readLimit = time.Time{}
			if e != nil {
				return e
			}
			lines, e := headerLines(response)
			if e != nil {
				return e
			}
			match := statusPattern.FindStringSubmatch(lines[0])
			if match == nil {
				return protocolError("invalid backend response", 502)
			}
			if _, e = parseFields(lines[1:]); e != nil {
				return protocolError("invalid backend response", 502)
			}
			code, _ := strconv.Atoi(match[1])
			if code < 200 || code >= 300 {
				return protocolError("backend CONNECT failed", 502)
			}
		}
		responded.Store(true)
		if err = writeAll(client, []byte("HTTP/1.1 200 Connection Established\r\n\r\n")); err != nil {
			return err
		}
		return duplex(client, upstream, func() error { return pump(reader, upstream, nil) }, func() error { return pump(upReader, client, nil) })
	}
	if err = writeAll(upstream, request.ForwardedHeader(backendProxy)); err != nil {
		return err
	}
	if request.ExpectContinue {
		if err = writeAll(client, []byte("HTTP/1.1 100 Continue\r\n\r\n")); err != nil {
			return err
		}
	}
	return duplex(client, upstream, func() error { return forwardBody(reader, upstream, request) }, func() error { return pump(upReader, client, responded) })
}
func (p *Proxy) writeError(writer io.Writer, status int) {
	reasons := map[int]string{400: "Bad Request", 403: "Forbidden", 408: "Request Timeout", 413: "Content Too Large", 417: "Expectation Failed", 431: "Request Header Fields Too Large", 502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout"}
	reason, ok := reasons[status]
	if !ok {
		status = 502
		reason = reasons[status]
	}
	body := reason + "\n"
	_ = writeAll(writer, []byte(fmt.Sprintf("HTTP/1.1 %d %s\r\nConnection: close\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n%s", status, reason, len(body), body)))
}
