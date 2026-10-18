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
        from portalproxy import config, core, proxy, desktop
        tkinter.Tcl().eval('info patchlevel')
        print('PS Portal On-Demand bundled imports and Tcl initialization OK')
        return 0
    from portalproxy.desktop import main as desktop_main
    return desktop_main()


if __name__ == '__main__':
    raise SystemExit(main())
