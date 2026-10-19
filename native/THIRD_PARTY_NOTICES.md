# Native engine licensing

The original OpenWrt/Lua project keeps its original MIT LICENSE at the repository root.

This `native/` implementation embeds **Mihomo v1.19.32**, licensed under GNU GPL
version 3. The combined native application is distributed under GPL-3.0-only;
see `native/LICENSE`. The native source files are licensed under GPL-3.0-only.
Do not distribute a combined binary as MIT-only or without corresponding source,
license and third-party notices required by the applicable licenses.

- Upstream: https://github.com/MetaCubeX/mihomo
- Pinned release: https://github.com/MetaCubeX/mihomo/tree/v1.19.32
- Commit: 88dcbf7f1614a67c3b36b848ee3592dfa92ada36
- Upstream license: https://github.com/MetaCubeX/mihomo/blob/v1.19.32/LICENSE

Go dependencies and their exact module versions/checksums are recorded in `go.mod`
and `go.sum`. Run `scripts/licenses.sh` to collect dependency licenses into a
release directory. Preserve that directory with distributed artifacts and provide
corresponding source/build instructions. Android and Apple app-store distribution
requires independent review of GPL and store terms; no store compatibility claim
is made here.

The pinned local derivative in `third_party/mihomo` preserves complete upstream
source and license and applies documented concurrency and embedding-lifecycle corrections. Its
`PSPORTAL-PATCHES` directory contains original checksums, exact patch and
provenance. `scripts/verify_mihomo_patch.py` checks the retained source before
source packaging; dependency notices identify the replacement actually built.
