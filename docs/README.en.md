# StarPass

On-demand proxying for phones and LAN devices.

[中文](../README.md) · [Downloads](https://github.com/LONG10222/psportal-on-demand/releases) · [Builds](https://github.com/LONG10222/psportal-on-demand/actions) · [Issues](https://github.com/LONG10222/psportal-on-demand/issues)

## Download

Releases contain archived development builds. The compact Android UI is built by the current pull request; the older c1d2d3a archive does not include it. See [installation details](downloads.zh-CN.md). CI Android APKs are unsigned; iOS device builds require signing.

## Quick start

**Android:** enter a public HTTPS subscription, choose Game / Mixed / Clash and routing, then tap **Connect**. Grant Android VPN consent when phone proxying is selected. Use **Sharing** for a LAN device's manual HTTP proxy address, **Proxies** for live node controls, **Settings** for background/recovery options, and **Help** for details.

**Desktop:** paste once to import, then select **Start sharing**, or reuse an existing Clash proxy. Linked mode leaves the original client's nodes and core under its control. Windows chooses the default Mihomo automatically. See the [desktop guide](../portable/docs/desktop.md).

## Platforms

- [Android](../native/android/README.md): embedded Mihomo, optional phone VPN and LAN sharing.
- [Windows / macOS / Linux](../portable/README.md): standalone or existing-client sharing.
- [iOS](../native/ios/README.md): foreground sharing, with separately documented background limits.
- [OpenWrt / iStoreOS](router-readme.en.md): standalone or OpenClash linkage.

LAN HTTP/HTTPS CONNECT forwards TCP, not arbitrary game UDP. Use trusted networks and remove a device's manual proxy when finished. Build, emulator and physical-device evidence remain separate; see [validation](../VALIDATION-LOCAL.md).

## Development and license

[Native engine](../native/README.md) · [Security](../SECURITY.md) · [Changelog](../CHANGELOG.md)

Information structure references [Clash Meta for Android](https://github.com/MetaCubeX/ClashMetaForAndroid); README organization references [Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev) and [v2rayNG](https://github.com/2dust/v2rayNG). Existing StarPass artwork is retained.

Router and desktop wrapper: [MIT](../LICENSE). Mihomo-linked native engine and Android app: [GPL-3.0-only](../native/LICENSE). Retain matching source and dependency notices when distributing binaries.

Router: [game and accelerator workspaces](router-workspaces.en.md), one-button game sharing and read-only OpenClash subscription import.

Router: [fixed entries and three modes](router-fixed-entry.en.md), direct forwarding when disabled and linked OpenClash controls.

Router: [traffic, subscription usage and in-page upgrades](router-monitoring-updates.en.md).
