# Live runtime controls

The desktop child communicates only through its parent's existing stdin/stdout
pipes. This adds no HTTP control listener, OS proxy/VPN setting or permission.
Opening the window does not load or test subscription nodes. The explicit
**Load live nodes** and **Test latency** actions may wake the owned core.

Status records report the listener address and preparing, listening, waking,
forwarding, error or stopped state. `connected_clients` is the number of distinct
allowed source IPv4 addresses with an active accepted connection. Two sockets
from the same IP count as one client. `active_connections` counts sockets
separately. Neither count is a claim to discover every device on the LAN.

Direct subscription mode keeps the complete provider pool available for live
manual selection. Fixed selection never silently chooses another node. The old
`auto` mode retains Hong Kong/Japan fallback order; `fastest` is a separate
measured-latency policy. A healthy current node changes only when the same
challenger beats it by more than `switch_threshold_ms` (default 50 ms) in two
completed measurement rounds and at least 30 seconds have passed since the last
switch. A time-limited partial measurement round retains completed results but
does not advance switching stability; the UI reports how many nodes were tested.
Initial partial selection uses only the healthy measurements already available.
An unhealthy current node can fail over immediately. Initial/cold-start
selection chooses the measured best immediately. Automatic measurement intervals
are at least 30 seconds and otherwise follow `health_interval`. Health probes do
not wake a sleeping core. A failed or untested node has no displayed delay;
measured zero milliseconds is distinct from a missing value.

For an imported complete profile, Load discovers existing select, fallback and
url-test groups with eligible leaf nodes.
Choose a group explicitly before testing or selecting its eligible leaf nodes.
Manual and fastest selection affect only that owned group; fallback/url-test
groups use Mihomo's fixed override and retain their upstream health semantics:
a fallback may clear an unhealthy preference, and url-test may route through a
healthy alternative. The live selected node reports the effective route, while
the saved manual preference remains separate. Use a select group when a stable
manual route is required. The imported rule
and group graph is not rewritten. Nested groups and direct/bypass actions are
not managed leaf nodes. The external engine's other leaf protocols remain
available, including protocols beyond the embedded engine's supported subset.
Profiles without an eligible existing group containing proxy leaf nodes cannot use
these controls. Linked Clash mode delegates all node management to Clash and
never calls its controller. Manual/automatic policies are saved per group in
`node_policies`, restored after idle restarts and cleared when a new subscription
or complete profile is imported. Recent observed client rows are retained for
five minutes; idle historical clients do not increase the live-device count.

A failed selection is reported as an error. If a selector update may have
succeeded but verification fails, the previous exact member is restored and
verified where possible. When the actual choice cannot be verified, the UI does
not retain a stale selected-node claim. Existing accepted streams are preserved
when the selector changes; new traffic uses the new choice.

## Protocol and resource limits

Each stdin command is one JSON line, at most 4096 bytes, with `command` equal to
`status`, `prepare`, `test` or `select`. A bounded integer `request_id` is echoed
as `last_command_id`; `busy` and `command_error` describe completion. Selection
uses `selection_mode`, `preferred_node`, optional `switch_threshold_ms` and, for
complete profiles, `selection_group`. The literal `stop` and stdin EOF retain
the shutdown contract. Current desktop compatibility events retain the
`PSPORTAL_EVENT ` prefix and legacy `id`/`action` requests (`nodes`, `select`,
`test`, `latency`). Both request formats share the same single-operation busy
gate, owned selector implementation and saved per-group policies.

Status lines are bounded to 2 MiB by the desktop reader and schema validator.
Node and group names are bounded to 256 UTF-8 bytes and inventories to 1000
entries. Imported group status exposes its name, current member and eligible
node count; full membership lists stay in the owned runtime. Subscription input
retains the 10 MiB limit. Each owned Mihomo controller response retains a 1 MiB
read limit: an exceptionally large/dense profile can exceed it and receives an
explicit `Controller response too large` error instead of an incomplete success.
No subscription URLs, credentials or raw adapter definitions are sent in status.

## External-core startup readiness

The tested external core is official Mihomo **v1.19.32**, with its `-post-up`
hook. Controller responses and an open TCP listener alone do not mean Mihomo's
forwarding tunnel is running. The owned process now writes a fresh random hex
nonce using its post-up hook, which runs after configuration is applied and the
tunnel enters its running state. The parent requires that exact bounded marker
and the existing authenticated-controller/listener checks before forwarding any
user request. User traffic is never replayed as a readiness retry.

The hook contains only a constant `echo`, generated hexadecimal nonce and
constant filename, in the private session working directory. No subscription,
node name, configured path or other user string is interpolated into the shell
command. Existing executable/config paths are resolved before the working
directory changes. The marker is removed before each launch and with session
cleanup, is not a source/archive asset, and cannot be reused from a previous
start. CRLF/trailing whitespace from Windows `echo` is accepted only around the
exact nonce. Missing, stale or oversized markers fail closed within the startup
deadline; an executable that rejects `-post-up` reports the unsupported startup
requirement instead of claiming readiness. No OS networking settings change.
