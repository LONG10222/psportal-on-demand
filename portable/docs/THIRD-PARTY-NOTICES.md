# Third-party runtime and build notices

PS Portal On-Demand is distributed under the repository's MIT license. A frozen executable also contains Python and Tcl/Tk runtime components, PyInstaller bootloader code, and platform-dependent native libraries. The default external-engine build does not bundle Mihomo; the optional embedded-engine build includes its GPL-licensed adapter code and complete corresponding source, as described below.

The build script retains the repository license, the installed Python license when available, and the installed PyInstaller COPYING notice including its bootloader exception. The supplied Tcl/Tk license terms are retained too; confirm the exact runtime versions during native release review. Original copyright notices in collected runtime files remain intact. Python's license includes additional notices for portions of its standard library.

Authoritative license sources:

- Python: https://docs.python.org/3/license.html
- Tcl: https://github.com/tcltk/tcl/blob/core-9-0-branch/license.terms
- Tk: https://github.com/tcltk/tk/blob/core-9-0-branch/license.terms
- PyInstaller: https://github.com/pyinstaller/pyinstaller/blob/v6.16.0/COPYING.txt
- PyYAML 6.0.3 (MIT): the desktop profile importer uses this pinned dependency. Its complete notice is retained in `PyYAML-LICENSE.txt`; bundled C-extension components must also be included in the exact-runtime inventory.
- Mihomo (not bundled): https://github.com/MetaCubeX/mihomo/blob/Meta/LICENSE

Release gate: audit the exact bundled native libraries and retain their complete matching license files before any public redistribution. The set depends on the Python installation and target OS; builds without a completed exact-runtime inventory remain gated. Check Tcl/Tk, OpenSSL, compression, ffi, graphics/font and platform runtime libraries where present. Do not assume a link substitutes for a required copyright notice.

## Audited Debian Linux build option

`build.py --debian-runtime-notices` is limited to the tested distro Python 3.13/Tk 8.6 runtime. It fails on unmapped ELF components and retains the complete installed Debian copyright files for the exact bundled objects, plus a SHA256 manifest. The known component set includes Python, Tcl/Tk, OpenSSL, libffi, bzip2, xz, zlib/zstd, Brotli, Expat, PNG, FreeType, Fontconfig and X11 client libraries. FreeType is used under the FTL option. See `licenses/debian/README.txt` and full notices in that package. This does not automatically approve a different OS or Python distribution.

When explicitly selected with `--native-engine` and `--native-source`, the package also includes the separate native GPL-3.0 engine process. Its matching full source/vendor archive and complete dependency notices are included under `native/`. The default external-core package does not include this component.
