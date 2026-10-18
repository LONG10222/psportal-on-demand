# Selection semantics: source-review evidence

This is a source review and offline configuration-test record. No Mihomo binary,
router, installer, proxy, subscription endpoint or live health check was run.
Compatibility of an installed core still requires target-device verification.
Passing a config parser alone does not prove every supplied field is implemented.

## Pinned upstream reviewed

Official MetaCubeX/mihomo tag **v1.19.19**, retrieved 2026-10-18:

- [groupbase.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.19/adapter/outboundgroup/groupbase.go), Git blob `9e705677e4d8cb5c033499721ab9450677624866`
- [group parser.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.19/adapter/outboundgroup/parser.go), Git blob `4640685594b790fe8227bfe07b7105d46c5454ef`
- [selector.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.19/adapter/outboundgroup/selector.go), Git blob `7bc138fdc708ea84871931b80de73392fe570b73`
- [constant/adapters.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.19/constant/adapters.go), Git blob `07ae5de1d8c9d6ed71f7d5f35d83596b93c8183c`
- [provider.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.19/adapter/provider/provider.go), Git blob `c9007892f5e2197236a8a126dd9dec24e8bfb7f1`
- [resource/fetcher.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.19/component/resource/fetcher.go), Git blob `a48e7bc82f2bd07973c65c388587499d3d130226`
- [API proxies.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.19/hub/route/proxies.go), Git blob `f100adbb7d21b99482cad8b2a046fb24dd6ab4b6`

## Ordered filters and reject sentinel

`NewGroupBase` splits filters on backticks and compiles segments with `regexp2`
(which supports negative lookahead). `GetProxies` iterates filter segments before
provider nodes and dedupes by name. Exact preferred name, Hong Kong, Japan and
other-node segments therefore express that order, preserving provider order
inside each tier. The escaping test checks bytes, not regex-engine execution.

This version does not implement `default-selected` or `empty-fallback` and returns
`COMPATIBLE` for an empty group. Those fields alone do not establish fail-closed
behavior. All modes therefore include static `proxies: [REJECT]` plus SUBSCRIPTION.
The parser prepends a Compatible provider for static proxies. GroupBase preserves
those static proxies and filters the dynamic provider, then globally reorders
when there is more than one provider and filter.

Auto/preferred end with `^(?!REJECT$).*` then `^REJECT$`: other regions precede
the sentinel. Fixed mode has only the exact preferred name then `^REJECT$`.
Selector chooses the first available entry when its internal selection is not
present, so a missing fixed name resolves to REJECT. No mutable selection cache
or newer `default-selected` support is required.

## Live replacement and direct-route exclusions

`Fetcher.startPullLoop` creates an fswatch watcher for a file provider, and its
callback reloads the file immediately. An update can therefore affect a running
core. A one-time readiness check or a pre-download sleeping-core check cannot
alone prevent a later empty-group fallback. The static sentinel addresses this
at the group itself, including when the provider changes after initial readiness.

Group `exclude-type` compares adapter type strings case-insensitively after
filtering. Provider `exclude-type` compares the configured type before parsing
adapters. Both reject `Direct`, `Compatible`, `Pass`, and `Dns` types. `Reject`
remains eligible for the sentinel. This prevents a direct-type provider node with
a friendly name becoming a later fallback; it is not a full sandbox for arbitrary
untrusted node configurations. Users must trust their subscription provider.

`GET /proxies` uses `ProxiesWithProviders()`, so the response contains provider
nodes for resolving the group's actual selected terminal node. Readiness must
reject built-in/non-proxy selections and require the configured exact name in
fixed mode. Cached UI snapshots never establish runtime readiness.

## Offline and remaining checks

`tests/selection.lua` tests validation, controls/separator injection, bounded
names, Unicode/punctuation, regex metacharacter escaping, tier order, sentinel
configuration, exclusions and independent render tables. Run with Lua 5.1 or
`texlua tests/selection.lua`. `tests/unit.lua` tests the rendered file provider.

Before claiming router compatibility, verify with the actual core: preferred
healthy/unhealthy/deleted; fixed healthy/unhealthy/missing; empty subscription;
live provider replacement; direct-type provider entries; and status/refresh
while sleeping, including the unchanged external idle timer.
