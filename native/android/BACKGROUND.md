# Android background sharing

This is an in-app continuation preference, not an Android battery or security
setting. It never starts a session by itself. LAN sharing and the optional
phone-app VPN are independent controls; the phone-app VPN has its own explicit
system consent and defaults off. The background preference covers whichever
session options the user selected.

## User-visible contract

- **Background sharing on (default):** after an explicit visible Start, the
  foreground service keeps the current selected session alive when
  the user goes Home, switches apps, locks the screen, or removes the Activity
  from Recents. Continuation is best effort under Android's power/process limits.
- **Background sharing off:** the current run stops when the Activity becomes
  nonvisible. Configuration replacement such as rotation does not stop it.
  Removing the task from Recents also requests a complete stop.
- Stop in the app or its foreground notification ends the current run. Android's
  Active-app Stop and force-stop also end it. There is no boot start, sticky
  restart, alarm, or process-death recovery that silently resumes an old session.
- No subscription token is retained in preferences or notification text to make
  unattended restarts possible. Starting again remains a deliberate user action.

The foreground notification is kept during normal native teardown. Notification
permission and channel visibility are product prerequisites: Android itself does
not require notification permission merely to launch an FGS, but this app does
not serve a hidden LAN proxy. Notification/channel disabling ends a run when the
service next checks, normally every two seconds while its main thread runs.

## Network loss

When LAN sharing is enabled, the service checks that its configured private IPv4 address remains assigned,
normally every two seconds while running. If it disappears, the service stops
the engine and records a generic LAN-address-changed message for the next UI
visit. It does not broaden the listener to all interfaces, guess another LAN,
silently rebind, or alter routing/network settings.

VPN-only sessions must not require a LAN listener/address or apply this LAN
address-loss gate. The VPN lifecycle must handle its own underlying-network
changes without automatically enabling LAN sharing.

This is an address-presence check, not an Internet reachability guarantee. An
upstream outage with the same LAN address does not itself stop the service.
Polling can be delayed by suspend, Doze, or process scheduling. Returning to an
identical address between polls might not be observed; physical network-change
tests remain required.

Recents removal can advance Android's internal service start ID without calling
`onStartCommand`. The service remembers this event even when sharing continues.
A later network-loss teardown uses guarded `stopSelf()` in that case; otherwise
`stopSelfResult()` with the older ID can leave an idle service behind. A newer
delivered command clears the marker and the existing start-ID guard protects a
newer run from an older completion.

## Platform limits and permission choices

For LAN sharing, the target-36 service declares `connectedDevice`, `FOREGROUND_SERVICE`,
`FOREGROUND_SERVICE_CONNECTED_DEVICE`, and `CHANGE_NETWORK_STATE`. The last
permission satisfies a documented connected-device prerequisite; no network
settings API is invoked. Exchanging traffic with an external LAN device fits
the platform's network-connected-device description. The service starts from
visible user interaction and enters foreground state before starting native
work. [Service types](https://developer.android.com/develop/background-work/services/fgs/service-types#connected-device),
[launch restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start).

Phone-only VPN operation must not claim a connected external LAN device. Android
provides `systemExempted` for configured VPN apps. The VPN guide says accepted
connection requests make an app appear in the system's VPN settings list; the
ordinary system consent flow therefore provides the relevant configuration,
without silently changing battery/security settings. A rejected foreground
service type must fail closed rather than switching to an unjustified type.
[VPN foreground type](https://developer.android.com/develop/background-work/services/fgs/service-types#system-exempted),
[VPN user experience](https://developer.android.com/develop/connectivity/vpn#user_experience).

A foreground service improves process priority but does not itself hold the CPU
awake. A partial wake lock can help a task that must continue through ordinary
suspend, with significant battery cost. It is not a guarantee against Doze:
Android may suspend network access and ignore wake locks. No new wake lock,
battery-optimization exemption, or settings prompt is added without measured
device evidence. [Awake API guidance](https://developer.android.com/develop/background-work/background-tasks/awake),
[Doze and App Standby](https://developer.android.com/training/monitoring-device-state/doze-standby).

A Wi-Fi lock is also not a general screen-off remedy on modern Android.
`WIFI_MODE_FULL` is nonfunctional since API 29; the high-performance lock is
deprecated from API 34 and replaced by low-latency behavior, whose restrictions
include foreground use and a screen that is on. No Wi-Fi lock is added.
[WifiManager reference](https://developer.android.com/reference/android/net/wifi/WifiManager#WIFI_MODE_FULL_HIGH_PERF).

Android 13+ Active-app Stop removes the whole app from memory without delivering
callbacks. OS process death likewise cannot depend on `onDestroy` for cleanup;
process sockets close when the process dies. This differs from removing a task
from Recents. Manufacturer battery controls may interrupt a foreground service.
[User-initiated stop](https://developer.android.com/develop/background-work/services/fgs/handle-user-stopping),
[background restrictions](https://developer.android.com/topic/performance/background-optimization).

## iOS boundary

No iOS files or behavior are changed for this Android option. Apple documents
that low-level networking stops when an app is suspended. A temporary background
task is a completion grace period, not permission for an indefinitely running
general LAN proxy. Background transfer APIs do not turn a suspended app into a
socket server. [Apple DTS explanation](https://developer.apple.com/forums/thread/799259),
[background execution](https://developer.apple.com/documentation/uikit/extending-your-app-s-background-execution-time).

## Verification scope

The pure-Java background-policy test covers both setting values, configuration
replacement, UI hiding and Recents removal. Structural guardrails protect the
connected-device type, nonsticky behavior, task-removal cleanup, and absence of
unmeasured battery locks. These do not establish device runtime behavior.

Required device checks: Home, Back, lock/unlock and Recents in both settings;
rotation; notification Stop; Android Active-app Stop; process kill; network loss
after Recents continuation; notification/channel revocation; and prolonged
screen-off/Doze/OEM conditions. Recheck combined lifecycle when the optional
phone-app VPN is enabled. Builds remain unsigned unless a separately authorized
signing identity is available.

Official platform references reviewed 2026-10-19.
