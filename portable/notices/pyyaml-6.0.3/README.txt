PyYAML 6.0.3 / LibYAML 0.2.5 frozen-runtime provenance

manifest.json records the exact official PyPI CPython 3.13 Windows x64,
Linux x64 and macOS arm64 wheel hashes, their extension member hashes, and
all 17 yaml Python module hashes. These are separate from the reviewed
CPython runtime. The extension is never relabeled as a distro library.

PyYAML-LICENSE.txt and LibYAML-LICENSE.txt are the complete upstream notices.
The unmodified PyYAML source distribution and LibYAML release source archive
are fetched by scripts/fetch_yaml_sources.py into the generated build cache
and copied into desktop archives. Binary archives are never committed here. The retained upstream
6.0.3 CI recipe pins LibYAML to 0.2.5; yaml._yaml.get_version_string() must
agree at build/inventory time. URLs and SHA-256 hashes are in manifest.json.

Retaining these sources is additional transparency, not a claim that the
independent MIT-licensed desktop YAML parser is part of the native Go engine.
The native engine's own complete corresponding-source archive remains under
native/corresponding-source.tar.gz and is checked separately.

No manifest alone proves a Windows/macOS/Linux build worked. Host-native
frozen GUI/runtime tests, exact library imports, byte provenance and archive
checks must all pass before an audited development artifact can be uploaded.

Run python scripts/fetch_yaml_sources.py before build.py. Exact cache files
are reusable offline; changed hashes fail without replacing the cache.
