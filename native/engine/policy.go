// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"regexp"
	"strings"
)

// ErrDestinationDenied and ErrResolutionFailed distinguish a policy refusal from
// an unavailable or malformed DNS result. Neither permits an external fallback.
var (
	ErrDestinationDenied = errors.New("destination is not permitted")
	ErrResolutionFailed  = errors.New("destination lookup failed")
)

var ipv4RejectNetworks = []string{
	"0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
	"169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
	"192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24",
	"203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
}
var ipv6RejectNetworks = []string{
	"::/3", "4000::/2", "8000::/1", "2001::/23", "2001:db8::/32", "2002::/16", "3fff::/20",
}
var (
	local4              = prefixes([]string{"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"})
	deny4               = prefixes(ipv4RejectNetworks)
	local6              = netip.MustParsePrefix("fc00::/7")
	external6           = netip.MustParsePrefix("2000::/3")
	deny6               = prefixes(ipv6RejectNetworks[3:])
	labelPattern        = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`)
	numericLabelPattern = regexp.MustCompile(`^(?:[0-9]+|0x[0-9a-f]+)$`)
)

func prefixes(networks []string) []netip.Prefix {
	out := make([]netip.Prefix, len(networks))
	for i, network := range networks {
		out[i] = netip.MustParsePrefix(network)
	}
	return out
}
func inPrefixes(address netip.Addr, networks []netip.Prefix) bool {
	for _, network := range networks {
		if network.Contains(address) {
			return true
		}
	}
	return false
}

func IsIPv4(host string) bool {
	addr, err := netip.ParseAddr(host)
	return err == nil && addr.Is4()
}
func IsIPv6(host string) bool {
	addr, err := netip.ParseAddr(host)
	return err == nil && addr.Is6() && addr.Zone() == ""
}
func NormalizeHost(host string) string {
	host = strings.ToLower(host)
	if !strings.Contains(host, ":") {
		host = strings.TrimSuffix(host, ".")
	}
	return host
}
func ValidName(host string) bool {
	if len(host) < 1 || len(host) > 253 {
		return false
	}
	allNumeric := true
	for _, label := range strings.Split(host, ".") {
		if !labelPattern.MatchString(label) {
			return false
		}
		if !numericLabelPattern.MatchString(label) {
			allNumeric = false
		}
	}
	return !allNumeric
}

// Destination returns local, external, name, or deny. Only RFC1918 and IPv6
// ULA addresses are direct; Go's broader IsPrivate/IsGlobalUnicast are not used.
func Destination(host string) string {
	host = NormalizeHost(host)
	if IsIPv4(host) {
		addr := netip.MustParseAddr(host)
		if inPrefixes(addr, local4) {
			return "local"
		}
		if inPrefixes(addr, deny4) {
			return "deny"
		}
		return "external"
	}
	if strings.Contains(host, ":") {
		if !IsIPv6(host) {
			return "deny"
		}
		addr := netip.MustParseAddr(host)
		if local6.Contains(addr) {
			return "local"
		}
		if external6.Contains(addr) && !inPrefixes(addr, deny6) {
			return "external"
		}
		return "deny"
	}
	if !ValidName(host) || host == "localhost" || strings.HasSuffix(host, ".localhost") {
		return "deny"
	}
	return "name"
}
func LocalIP(host string) bool {
	return (IsIPv4(host) || IsIPv6(host)) && Destination(host) == "local"
}

// BackendRejectRules must precede backend routing rules. DNS resolution must
// remain enabled: never add no-resolve or a DIRECT exception to these rules.
func BackendRejectRules() []string {
	out := []string{"DOMAIN-SUFFIX,localhost,REJECT"}
	for _, network := range ipv4RejectNetworks {
		out = append(out, "IP-CIDR,"+network+",REJECT")
	}
	for _, network := range ipv6RejectNetworks {
		out = append(out, "IP-CIDR6,"+network+",REJECT")
	}
	return out
}

type Route struct{ Kind, Address string }

type ipResolver interface {
	LookupIPAddr(context.Context, string) ([]net.IPAddr, error)
}

var systemResolver ipResolver = &net.Resolver{StrictErrors: true}

// ResolveDestination checks every result exposed by the OS/Go resolver. The
// resolver is the DNS trust boundary; this API does not expose wire questions
// or CNAME chains for independent validation. Local results are pinned
// numerically, and a single denied answer rejects the complete destination.
func ResolveDestination(ctx context.Context, host string, port int) (Route, error) {
	return resolveDestination(ctx, systemResolver, host, port)
}

func resolveDestination(ctx context.Context, resolver ipResolver, host string, port int) (Route, error) {
	if port < 1 || port > 65535 {
		return Route{}, ErrDestinationDenied
	}
	host = NormalizeHost(host)
	kind := Destination(host)
	if kind == "deny" {
		return Route{}, ErrDestinationDenied
	}
	if kind == "local" {
		return Route{Kind: kind, Address: host}, nil
	}
	if kind == "external" {
		return Route{Kind: kind}, nil
	}
	answers, err := resolver.LookupIPAddr(ctx, host)
	if err != nil {
		return Route{}, fmt.Errorf("%w: %w", ErrResolutionFailed, err)
	}
	if len(answers) == 0 {
		return Route{}, fmt.Errorf("%w: no addresses", ErrResolutionFailed)
	}
	firstLocal := ""
	hasExternal := false
	for _, answer := range answers {
		if answer.Zone != "" {
			return Route{}, fmt.Errorf("%w: scoped DNS address", ErrDestinationDenied)
		}
		// Preserve the resolver's 4/16-byte address family. Calling IP.String or
		// Unmap would collapse IPv4-mapped AAAA answers and bypass IPv6 denials.
		// Pure-Go /etc/hosts lookups may also return mapped 16-byte IPv4;
		// these ambiguous results intentionally fail closed. Prefer numeric
		// LAN destinations or ordinary DNS A records for such aliases.
		addr, ok := netip.AddrFromSlice(answer.IP)
		if !ok {
			return Route{}, fmt.Errorf("%w: malformed address", ErrResolutionFailed)
		}
		address := addr.String()
		switch Destination(address) {
		case "external":
			hasExternal = true
		case "local":
			if firstLocal == "" {
				firstLocal = address
			}
		default:
			return Route{}, fmt.Errorf("%w: denied DNS answer", ErrDestinationDenied)
		}
	}
	if hasExternal {
		return Route{Kind: "external"}, nil
	}
	if firstLocal == "" {
		return Route{}, ErrResolutionFailed
	}
	return Route{Kind: "local", Address: firstLocal}, nil
}
