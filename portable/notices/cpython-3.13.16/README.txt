Supplemental runtime notices for the audited CPython 3.13.16 build.

These supplement, not replace, the exact installed Python LICENSE (including
Tcl/Tk and Microsoft Distributable Code notices), PyInstaller COPYING, and
platform-specific runtime inventories. Do not use this set to clear a different
Python/component version or an unrelated DLL/framework origin.

The interpreter is unmodified upstream CPython, packaged as a frozen application
with a selected standard-library subset. The application does not claim authorship
of these components. Full component license texts are retained unchanged;
explicit copyright headers are extracted unchanged where upstream keeps them in
source files. manifest.json records exact upstream URLs and source/file hashes.

HACL generated hash routines use MIT. Their KaRaMeL/FStar support headers use
Apache 2.0; the complete text is in openssl-license.txt and the CPython license
reference. mimalloc's MIT text is in CPython-history-and-component-licenses.rst;
its exact bundled-header copyright is retained separately. XZ 5.2.5 liblzma is
the library component described in xz.txt; no XZ command-line tools are bundled.
OpenSSL full Apache license and upstream author attribution are both retained.

This source audit is an engineering provenance check, not a legal certification.
The runtime binary inventory must separately establish which files are shipped,
where they came from, and that installed versions match the audited source.

BLAKE2 is statically compiled into the Windows interpreter. Its unchanged
reference/wrapper attribution and complete CC0 text are retained separately.
