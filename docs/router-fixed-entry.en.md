# Three modes, fixed proxy entries

Install the paired `xianniu-router_0.5.1_all.ipk` and `luci-app-starpass.ipk` from this branch’s Actions artifacts. Existing settings are preserved and privately backed up. Confirm the LAN address, LAN DNS, allowed game device and subscription source once in Advanced Settings.

Configure the device once. Game and StarPass modes share the same address and port; the accelerator keeps its own fixed entry. Use the addresses displayed by your router. Wi-Fi, device IP and gateway stay as configured.

| Feature | Enabled | Disabled |
| --- | --- | --- |
| Game | Allowed game device → on-demand Mihomo | Direct through the router's default route |
| StarPass | Shared entry → OpenClash | Same entry, direct |
| Accelerator | Accelerator entry → native local SOCKS | Same entry, direct |

The shared entry follows the currently enabled game or StarPass feature, and is direct when both are off. Stopping StarPass does not automatically start game mode. The accelerator entry is independent.

A small listener stays running when a feature is off. Direct forwarding uses the existing LAN DNS and the soft router's default route. Ordinary Internet access continues; destinations blocked on the direct connection do not become accessible while the proxy is off. Existing TCP sessions reconnect when the exit changes.

Game and StarPass are mutually exclusive. Starting one stops the other. The accelerator may run independently. Only the configured game device uses the game subscription; other LAN clients on the shared entry remain direct while game mode is selected.

Switching from the accelerator page to StarPass stops the owned session and confirms official paid-time pause before completing the transition. Free projects retain their separate billing rules. Returning to the accelerator page or rebooting does not resume a paid session.

StarPass reuses the installed OpenClash configuration, core and management page. A running OpenClash instance is reused. Otherwise, a manual-proxy-only instance is registered with its service: TUN, redir, tproxy and fake-IP are disabled, and the original global DNS/firewall startup script is not run. The source YAML stays unchanged. Its enable flag follows the feature. While the manual instance is owned, OpenClash’s original boot entry is temporarily disabled; StarPass restores the manual instance at boot. The previous boot setting is restored on feature shutdown. OpenClash on/off state is observed in both directions. Starting OpenClash through its own full startup controls still follows that plugin's original network settings.

Persistent entries start at boot. The enabled game or StarPass feature is restored separately from the selected page. The gateway binds the LAN address and accepts clients in that LAN subnet. MAC notes and device profiles remain local. HTTP/HTTPS proxying does not capture arbitrary game UDP.

The paired packages are `luci-app-starpass 0.3.5` and `xianniu-router 0.5.1`. The source installer also requires Python and the accelerator module's shared HTTP library. Existing configurations are privately backed up before enabling `gateway_enabled=1`; the old game listener moves to loopback while its public device endpoint stays the same.
