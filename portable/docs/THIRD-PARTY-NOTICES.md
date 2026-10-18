# Third-party runtime and build notices

PS Portal On-Demand is distributed under the repository's MIT license. A frozen executable also contains Python and Tcl/Tk runtime components, PyInstaller bootloader code, and platform-dependent native libraries. Mihomo is not bundled; its own upstream license applies when obtained separately.

The build script retains the repository license, the installed Python license when available, and the installed PyInstaller COPYING notice including its bootloader exception. The supplied Tcl/Tk license terms are retained too; confirm the exact runtime versions during native release review. Original copyright notices in collected runtime files remain intact. Python's license includes additional notices for portions of its standard library.

Authoritative license sources:

- Python: https://docs.python.org/3/license.html
- Tcl: https://github.com/tcltk/tcl/blob/core-9-0-branch/license.terms
- Tk: https://github.com/tcltk/tk/blob/core-9-0-branch/license.terms
- PyInstaller: https://github.com/pyinstaller/pyinstaller/blob/v6.16.0/COPYING.txt
- Mihomo (not bundled): https://github.com/MetaCubeX/mihomo/blob/Meta/LICENSE

Release gate: audit the exact bundled native libraries and retain their complete matching license files before any public redistribution. The set depends on the Python installation and target OS; this development build is not a completed third-party-license audit. Check Tcl/Tk, OpenSSL, compression, ffi, graphics/font and platform runtime libraries where present. Do not assume a link substitutes for a required copyright notice.
