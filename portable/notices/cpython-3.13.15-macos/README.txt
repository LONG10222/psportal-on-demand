Supplemental notices for the audited CPython 3.13.15 macOS runtime.

Keep the exact installed Python LICENSE and Tcl/Tk8.6.18 license files alongside
this set. They are separate required evidence. The Python core notices include
unchanged full license texts and exact source copyright headers. HACL generated
hashes are MIT; KaRaMeL/FStar support headers are Apache2.0 (full text in the
CPython license reference and openssl-license.txt). BLAKE2 notices and full CC0
legal text are retained. mimalloc's full MIT text is in the CPython reference.

Bundled OpenSSL3.0.21 and static libmpdec4.0.1/liblzma notices are retained here.
The mpdecimal archive SHA256 matches the exact CPython Mac build recipe. XZ5.2.3
liblzma is the library component described in xz-library-notice.txt; no XZ tools
are shipped. The build recipe is provenance only, not an executable build step.
OS-provided /usr/lib zlib, bzip2 and libffi are system dependencies, not files
redistributed in this app. Actual dependency paths and versions must be checked.

PyInstaller thins/relocates/ad-hoc signs macOS Mach-O files. This notice set does
not prove binary origin: retain the independent deterministic transformed-origin
audit, original and packaged hashes, and exact PyInstaller version. Do not clear
other Python/library versions or origins on the basis of this set.

The interpreter source is unmodified upstream; the app freezes a standard-library
subset. This is engineering provenance evidence, not a legal certification.
