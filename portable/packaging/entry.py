"""Frozen entry point: GUI by default, same executable for the owned backend."""
import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--backend':
        del sys.argv[1]
        from portalproxy.__main__ import main as backend_main
        return backend_main()
    if len(sys.argv) > 1 and sys.argv[1] == '--smoke-test':
        # Does not create a window, bind a socket, run Mihomo or fetch a URL.
        import tkinter
        import yaml
        from yaml import _yaml
        assert yaml.__version__ == '6.0.3' and _yaml.get_version_string() == '0.2.5'
        fixture = 'proxies: [{name: fixture, type: direct}]\nproxy-groups: []\nrules: [MATCH,DIRECT]\n'
        assert yaml.safe_load(fixture)['proxies'][0]['name'] == 'fixture'
        assert yaml.load(fixture, Loader=yaml.CSafeLoader) == yaml.safe_load(fixture)
        from portalproxy import config, core, proxy, desktop
        tkinter.Tcl().eval('info patchlevel')
        print('PS Portal On-Demand bundled imports, YAML/LibYAML parse and Tcl initialization OK')
        return 0
    from portalproxy.desktop import main as desktop_main
    return desktop_main()


if __name__ == '__main__':
    raise SystemExit(main())
