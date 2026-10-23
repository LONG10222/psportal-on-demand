"""A fixed selective PAC for the running accelerator listener, without secrets."""
import ipaddress
import json

from .steam_host import STEAM_DOMAINS

_PRIVATE = tuple(ipaddress.IPv4Network(value) for value in
                 ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def make_accelerator_pac(host, port):
    """Return bounded ASCII JavaScript for a private IPv4 listener.

    Loopback is accepted for local transport tests. Steam traffic has exactly
    one proxy choice, so stopping that proxy cannot silently make it direct.
    Other web destinations bypass the Steam-only relay. No DNS PAC helpers are
    needed. The domain list includes Akamai's shared akamaihd.net CDN namespace.
    """
    try:
        if not isinstance(host, str):
            raise ValueError()
        address = ipaddress.IPv4Address(host)
        if str(address) != host or not (address.is_loopback or any(address in network for network in _PRIVATE)):
            raise ValueError()
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('PAC requires a numeric private IPv4 listener and a valid nonzero port') from None
    script = '''function FindProxyForURL(url, host) {
  host = host.toLowerCase();
  if (host.charAt(host.length - 1) === ".") {
    host = host.substring(0, host.length - 1);
  }
  var domains = %s;
  for (var i = 0; i < domains.length; i++) {
    if (host === domains[i] || host.slice(-(domains[i].length + 1)) === "." + domains[i]) {
      return "PROXY %s:%d";
    }
  }
  return "DIRECT";
}
''' % (json.dumps(list(STEAM_DOMAINS), separators=(',', ':')), host, port)
    return script.encode('ascii')
