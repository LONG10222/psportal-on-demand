# Router game and accelerator modes

StarPass opens in game mode. The selected mode is saved and survives service restarts.

## Game mode

After initial setup, use the single Start / Stop button. Advanced settings stay collapsed. The listener starts at boot when enabled; external device traffic wakes the owned Mihomo core. After 60 seconds without external data, the core stops. LAN requests do not extend that timer.

Choose an existing OpenClash subscription as the source to read its metadata without starting OpenClash. StarPass can borrow its installed core executable while using a separate configuration, loopback backend and runtime directory. Subscription refresh is explicit. The older “reuse running OpenClash” backend is a separate option and requires that service to be running.

For a preferred Hysteria2 node, verify its actual protocol in the core details, select “preferred with fallback”, and enter its exact subscription name, such as `HK Hysteria2 Example`. This prefers one named node; it does not discover every new Hysteria node automatically. Fallback remains Hong Kong, Japan, then other regions. Fixed mode intentionally disables fallback.

## Accelerator mode

Install the compatible Xianniu router module, then select Accelerator on the StarPass page. The game listener stops and the page opens the existing account, game, device and line workspace. Select a device, game and official line before starting. Use the proxy address displayed by that workspace; it may differ from game mode.

Free projects never resume or suspend whole-account billing. Paid sessions stop and obtain official confirmation before pausing account time. Stop an active accelerator session before returning to game mode. Reboot preserves the workspace but does not resume paid acceleration.

The services can be installed together; the current workspace runs them exclusively and does not chain their exits.

## PS5 and Portal

A manual HTTP proxy on Portal covers requests made by Portal that honor that setting. PS5 game connections originate from PS5. The Portal proxy does not automatically capture PS5 TCP/UDP, and local Remote Play streaming should stay on the LAN.

The iStoreOS 22 / fw3 adapter provides manual HTTP and local SOCKS entry points. Whole-device TCP/UDP interception requires the supported fw4/nftables backend and a route that actually sends the selected device traffic through the soft router. HTTP success is not PS5 game acceptance.

See [validation and limitations](router-workspaces-validation-2026-10-26.md). No subscriptions, accounts or device configuration are included in the source or packages.

While official billing is active, both pages update an estimated countdown every second and resync the official balance every 60 seconds. Paused balances stay fixed. The estimate is not a vendor settlement record.

Device notes and game profiles use normalized MAC addresses as primary keys. Last-seen IP is metadata. Expand Notes on a device card to edit its label. A different device taking the old IP does not inherit that label. Legacy IP records with known MACs migrate on the next save.
