"""Bundled UI translations. Engine/config values and diagnostics remain original."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile

ZH = {
    'Sharing an existing client: keep that client running with its proxy enabled. StarPass does not need a separate subscription or core; verify access on the connected device.': '正在复用已有客户端：请保持该客户端运行并开启代理。星渡无需另选订阅或核心；请在接入设备上验证访问。',
    'Before you start': '使用前检查',
    'Choose trusted Mihomo…': '选择可信的 Mihomo 核心…',
    'Paste a valid HTTPS subscription, or select a local configuration in Advanced settings.': '先粘贴有效的 HTTPS 订阅链接；也可以在高级设置中选择本地配置。',
    'Select your trusted Mihomo executable, or use Share existing Clash. StarPass does not download a core automatically.': '首次使用需要选择你已获取的可信 Mihomo 可执行文件，或点击“复用已有 Clash / 系统代理”。星渡不会自动下载核心。',
    'Select a matching native engine in Advanced settings, or switch to external Mihomo.': '请在高级设置中选择对应平台的内嵌引擎，或切换到外部 Mihomo。',
    'Subscription and engine paths are present. Prepare & start will validate the contents and choose an available port; Internet access is not verified yet.': '已找到订阅来源和核心文件。点击“一键准备并启动”后会校验内容、选择可用端口；这不代表已经验证外网可用。',
    '1. Prepare the service: paste a subscription and click Prepare & start. First use also needs a trusted core or an existing Clash client.': '第 1 步：粘贴订阅，点击“一键准备并启动”。首次使用还需选择可信核心，或复用已有 Clash；可先点“使用前检查”。',
    '3. A device connected, but request errors were recorded. Check its proxy settings and the selected node. A connection is not proof of Internet access.': '第 3 步：设备已接入，但有请求错误。请检查设备代理设置和所选节点；接入成功不代表外网已连通。',
    '3. A device connected. Open the intended service on that device to verify access; this is not proof that game UDP or streaming uses the proxy.': '第 3 步：设备已接入，请在该设备打开目标服务验证访问。这不代表游戏 UDP 或串流已经经过代理。',
    '2. Configure the local app with 127.0.0.1 and the displayed port. System-wide proxying is not enabled automatically.': '第 2 步：在本机应用中填写 127.0.0.1 和显示的端口；不会自动接管整个系统的流量。',
    '2. Connect the game device to the same reachable LAN, then follow LAN sharing to enter the displayed HTTP proxy address.': '第 2 步：让游戏设备接入同一可互通局域网，按“局域网共享”页面填写显示的 HTTP 代理地址。',
    'When finished, turn off the proxy setting on the device before stopping StarPass. Do not disable firewall or certificate protection.': '结束使用时，先关闭设备上的代理设置，再停止星渡。不要关闭防火墙或证书安全保护。',

    'The saved provider is now a full profile. Import it again before starting.': '已保存的节点文件现在包含完整配置，请重新导入后再启动。',
    'Using your selected local file. Import subscription explicitly to replace this override.': '正在使用手动选择的本地文件；如需替换，请点击“导入订阅”。',
    'LAN listener IPv4 (saved for Game / Mixed)': '局域网监听 IPv4（游戏 / 混合模式）',
    'HTTP proxy port': 'HTTP 代理端口',
    'Allowed device IPv4 addresses (comma-separated)': '允许的设备 IPv4（逗号分隔）',
    'Product mode does not match the listener address and allowed devices.': '所选模式与监听地址或允许设备列表不匹配。',
    'Previous settings could not be restored on disk. Review the configuration before restarting.': '未能在磁盘上恢复之前的设置，请在重新启动前检查配置。',
    'StarPass · games and everyday browsing': '星渡 · 游戏与日常上网',
    'Close StarPass?': '关闭星渡 StarPass？',
    'Product mode': '使用模式',
    'Game mode': '游戏模式', 'Mixed mode': '混合模式', 'Clash mode': 'Clash 模式',
    'Game devices only: LAN HTTP/CONNECT proxy; the listener host IP is excluded. UDP game acceleration is not provided.': '仅游戏设备：局域网 HTTP/CONNECT 代理，本机监听 IP 不在允许名单中。不提供 UDP 游戏加速。',
    'Game devices + local apps: LAN HTTP/CONNECT proxy, including this computer. Configure each app manually.': '游戏设备 + 本机应用：局域网 HTTP/CONNECT 代理，包含本机。需在各应用中手动配置代理。',
    'Local apps only: HTTP/CONNECT on 127.0.0.1, with no LAN access. Full profiles require external Mihomo; embedded support is limited.': '仅本机应用：仅监听 127.0.0.1，不开放局域网。完整配置需外部 Mihomo；内嵌引擎能力有限。',
    'Configure apps manually with the local address below. System proxy and VPN settings stay unchanged.': '请在应用中手动填写本机代理地址；系统代理及 VPN 设置不会改变。',
    'Detect the current LAN for quick setup. Manual device lists are kept; automatic lists follow the subnet. Advanced Start keeps your manual address.': '快速启动识别当前局域网。手动设备名单保持不变，自动名单随网段更新；高级启动保留手动监听地址。',
    'Choose Game, Mixed or Clash mode.': '请选择游戏、混合或 Clash 模式。',
    'Game and Mixed modes need a private LAN IPv4 address. Use Prepare & start or Advanced settings.': '游戏和混合模式需要局域网 IPv4 地址，请使用“一键准备并启动”或高级设置。',
    'Allowed devices must be specific private LAN IPv4 addresses.': '允许的设备必须是具体的局域网 IPv4 地址。',
    'Game mode needs at least one allowed device other than this computer.': '游戏模式至少需要一个本机之外的允许设备地址。',
    'Choose at most 256 allowed device addresses.': '最多允许 256 个设备地址。',

    'Select a node or enable automatic lowest latency.': '选择节点手动切换，或启用自动最低延迟选择。',
    'Could not safely identify one active physical LAN interface. Use Advanced settings.': '无法确定唯一的活动物理局域网接口，请使用高级设置。',
    'Connect this computer to a private Wi-Fi or Ethernet network first.': '请先让电脑接入 Wi-Fi 或有线局域网。',
    'Device counts unavailable in embedded mode': '实验性内嵌模式暂不提供设备统计',
    'Devices': '设备连接', 'Proxy clients': '代理接入设备',
    'Devices using this proxy, grouped by source IP.': '按来源 IP 查看使用本代理的设备。',
    'Live proxy nodes': '节点选择', 'Load nodes': '加载节点', 'Switch node': '切换节点',
    'Test latency': '测试延迟', 'Auto · lowest latency': '自动选择最低延迟',
    'Latency': '延迟', 'Selected': '选中状态', 'Current': '当前', 'Manual': '手动',
    'Device IP': '设备 IP', 'Connections': '连接数', 'Requests': '累计接入', 'Last seen': '最近接入',
    'Ready · waiting for a device': '已启动 · 等待设备接入',
    'Devices are using the proxy': '设备正在使用代理',
    '{devices} active devices · {connections} connections': '{devices} 台活跃设备 · {connections} 条连接',
    'Errors: {count}': '错误：{count}',
    'Active counts mean open proxy connections. Recent devices stay visible for five minutes; this is not a list of all Wi-Fi devices.': '活跃数指当前未关闭的代理连接。最近接入设备保留 5 分钟；此处不代表 Wi-Fi 上的全部设备。',
    'Node controls are managed by the existing Clash client.': '当前关联已有 Clash：请在 Clash 中选择节点、测速和设置自动选择。',
    'Live node controls require the external Mihomo engine.': '实时节点切换需要外部 Mihomo 引擎；实验性内嵌模式保留原策略。',
    'Choose a node, then click Switch node.': '请先选择列表中的节点，再点击“切换节点”，或双击该节点。',
    'Start the listener first.': '请先启动监听服务。',
    'Start the listener, then load nodes. This wakes only our own core.': '启动监听后点击“加载节点”；此操作仅唤醒我们自己的核心。',
    'Testing latency…': '正在测试延迟…', 'Updating nodes…': '正在加载或切换节点…',
    'Selection applied; preference could not be saved.': '选择已生效，但偏好设置未能保存。',
    'Node operation failed. Check the selected group and engine logs.': '节点操作失败，请检查所选策略组及引擎日志。',
    'Current: {node} · Policy: {policy}': '当前：{node} · 策略：{policy}',
    'Original subscription policy': '原订阅策略',
    'Retest every {seconds}s while the core runs; sleeping cores stay asleep.': '核心运行期间每 {seconds} 秒重测；空闲休眠时不主动唤醒。',
    'All latency probes failed; current selection kept.': '所有节点测速失败，已保留当前选择。',
    'Latency test failed; current selection kept.': '测速失败，已保留当前选择。',
    'Lowest-latency node selected.': '已选择本次测速中延迟最低的可用节点。',
    'Latency test finished.': '延迟测试完成。',
    'Node switched. Existing connections keep their route.': '节点已切换；已有连接保留原路径，新连接使用新节点。',
    'Preparing': '正在准备', 'Waking': '正在唤醒', 'Forwarding': '正在转发', 'Error': '异常',
    'Cancel preparation': '取消准备', 'Preparation cancelled.': '已取消准备。',
    'Cancel preparation and close?': '取消准备并关闭？',
    'Automatic LAN setup is unavailable on this platform. Use Advanced settings.': '当前平台不支持自动识别局域网，请使用高级设置。',
    'Active devices: {devices} · Connections: {connections}': '活动设备：{devices} · 连接数：{connections}',
    'Active devices count distinct source IPs with open connections.': '活动设备按存在未关闭连接的不同来源 IP 计数。',
    'Health': '可用状态', '{delay} ms': '{delay} 毫秒',
    'Healthy': '可用', 'Unavailable': '不可用', 'Not tested': '尚未测试',
    'Load live nodes': '加载实时节点',
    'Use selected node': '使用所选节点', 'Use fastest auto': '启用最快自动',
    'Fastest switch threshold (ms)': '最快节点切换阈值（毫秒）',
    'Enter a switch threshold from 0 to 60000 ms.': '请输入 0 至 60000 毫秒的切换阈值。',
    'Fastest auto requires a measured improvement, two successful probe rounds and a 30-second cooldown before switching.': '最快自动模式需延迟改善达到阈值、连续两轮探测成功，且距上次切换至少 30 秒才会换节点。',
    'Live changes apply to this run. Loading or testing nodes makes network requests.': '实时调整仅用于本次运行。加载或测试节点会发起网络请求。',
    'Live measurements from this listener. No latency is shown until a probe reports it.': '此监听器提供的实时测量；探测报告前不显示延迟。',
    'Local file preview only. Start the listener and load live nodes to test or switch.': '当前仅预览本地文件。启动监听并加载实时节点后可测试或切换。',
    'Node selection and latency tests are managed by the existing Clash client.': '节点选择与延迟测试由已有 Clash 客户端管理。',
    'Current node: {node} · Mode: {mode}': '当前节点：{node} · 模式：{mode}',
    'Switch threshold: {threshold} ms': '切换阈值：{threshold} 毫秒',
    'Partial latency check: {tested}/{total} nodes tested; automatic selection uses available measurements.': '延迟测试尚未完成：已测试 {tested}/{total} 个节点；自动选择基于当前可用的测量结果。',
    'Applying node command…': '正在执行节点操作…',
    'Start the listener to load live nodes.': '请启动监听器后加载实时节点。',
    'Live node controls are unavailable for this engine.': '此引擎尚未提供实时节点控制。',
    'Waiting for a live engine report.': '正在等待引擎实时报告。',
    'The node command could not be sent. Check the listener status.': '无法发送节点操作，请检查监听器状态。',
    'fastest': '最快自动', 'fixed': '固定', 'prefer': '优先', 'auto': '区域优先自动',
    'profile': '原配置策略', 'Profile group': '配置策略组',
    'Choose a profile group, then load or test its direct nodes.': '请先选择配置中的策略组，再加载或测试其直接节点。',
    'Only the chosen group is managed; original rules and other groups stay unchanged.': '仅控制所选策略组；原有规则及其他策略组保持不变。',
    'Saved manual preference: {node}': '已保存的手动偏好：{node}',
    "The original group's health rules still apply; its current node can differ from the saved preference.": '原策略组的健康检查规则仍然生效，当前节点可能与已保存的偏好不同。',
    'Subscription: {name}': '订阅：{name}', 'Provider: {source}': '来源：{source}',
    'Clash local cache · read-only, not live': 'Clash 本地缓存 · 只读，非实时',
    'Last updated: {when}': '更新于：{when}',
    'Existing proxy': '已有代理联动', 'Managed by existing client': '由原客户端管理',
    'Share existing Clash / system proxy': '复用已有 Clash / 系统代理',
    'Detected local HTTP proxy: {host}:{port}': '检测到本机 HTTP 代理：{host}:{port}',
    'No local HTTP system proxy detected.': '未检测到本机 HTTP 系统代理。',
    'No active loopback HTTP system proxy was detected.': '未检测到已配置的本机 HTTP 代理入口。',
    'Subscription details appear after import.': '导入后显示订阅到期时间与流量信息。',
    'Not provided': '未提供', 'Expired': '已到期',
    'Used: {used} / Total: {total}\nRemaining: {remaining}\nExpires: {expiration}': '已用：{used} / 总量：{total}\n剩余：{remaining}\n到期：{expiration}',
    'Advanced settings…': '高级设置…', 'Simple view': '简洁界面',
    'Paste your subscription to get started.': '粘贴订阅，即可开始',
    'Prepare & start': '一键准备并启动',
    'Detect the LAN address and keep port 10081 when available. Devices on the current local subnet will be allowed to connect.': '自动识别局域网地址，优先使用固定端口 10081；允许当前局域网网段的设备连接。',
    'Current local subnet: {subnet}': '当前局域网网段：{subnet}',
    'Device Wi-Fi setup': '设备 Wi-Fi 设置',
    'Join the same Wi-Fi. In the device Wi-Fi settings choose HTTP Proxy → Manual, enter the server and port above, and leave authentication off.': '让设备接入同一个 Wi-Fi。在设备的 Wi-Fi 设置中选择“HTTP 代理 → 手动”，填写上方服务器和端口，认证保持关闭。',
    'Server: {host}\nPort: {port}': '服务器：{host}\n端口：{port}',
    'Prepare the subscription on Overview first.': '请先在概览页粘贴订阅，完成一键准备。',
    'Connect this Mac to a private Wi-Fi or Ethernet network first.': '请先让 Mac 接入 Wi-Fi 或有线局域网。',
    'This network needs an explicit device allowlist in Advanced settings.': '当前网段需在高级设置中指定设备地址。',
    'Automatic LAN setup is currently available on macOS. Use Advanced settings on this platform.': '当前平台请使用高级设置填写接入地址；自动识别已先在 macOS 实现。',
    'Could not read local network information. Use Advanced settings.': '无法读取本机网络信息，请在高级设置中填写。',
    'No available proxy port was found. Close the conflicting application or use Advanced settings.': '未找到可用端口，请关闭占用端口的程序，或使用高级设置。',
    'Overview': '概览', 'Profiles': '配置', 'Proxies': '代理策略', 'LAN sharing': '局域网共享',
    'Settings': '设置', 'Logs': '日志', 'Language': '语言',
    'Rules': '规则', 'Appearance': '外观', 'Dark': '深色', 'Light': '浅色',
    'Node inventory': '节点列表', 'Name': '名称', 'Protocol': '协议',
    'Imported rules': '导入的规则',
    'Local file preview only. First 500 entries; no latency test or node switch is performed.': '仅预览本地文件前 500 项；不会执行延迟测试或切换节点。',
    'Inspect or import a local profile to view its original rules.': '检查或导入本地配置后，可查看它的原始规则。',
    'On-demand LAN proxy': '按需局域网代理', 'Workspace': '工作空间',
    'Your devices, one connection.': '让你的设备，轻松接入。',
    'A clear view of the listener, engine and device connection.': '查看监听器、核心与设备接入状态。',
    'Import a provider or keep using your HTTPS subscription.': '导入节点文件，或继续使用 HTTPS 订阅。',
    'Choose how nodes are selected without changing engines.': '选择节点策略，保留当前引擎。',
    'Give another device an address it can connect to.': '为其他设备提供可连接的代理地址。',
    'Keep the complete external core and the experimental embedded option.': '保留完整外部核心和实验性内嵌模式。',
    'Original diagnostics, with sensitive values redacted.': '原始诊断记录，敏感内容已脱敏。',
    'Listener': '监听器', 'Upstream core': '上游核心', 'Current engine': '当前引擎',
    'Connection address': '接入地址', 'Not configured': '尚未配置', 'Not reported': '尚未报告',
    'Stopped': '已停止', 'Process running': '正在启动', 'Listening': '正在监听',
    'Stopping…': '正在停止…', 'Stopped with error': '停止异常',
    'starting': '正在启动', 'running': '运行中', 'stopped': '已停止', 'failed': '启动失败',
    'External Mihomo': '外部 Mihomo', 'Embedded · experimental': '内嵌 · 实验性',
    'Quick setup': '快速开始', 'Open configuration': '打开配置', 'Choose config…': '选择配置…',
    'Save / validate': '保存并校验', 'Start listener': '启动监听', 'Stop': '停止',
    'Listener IPv4 (LAN for Portal)': '本机监听 IPv4（局域网地址）',
    'Portal proxy port': '设备代理端口',
    'Portal IPv4 addresses (comma-separated)': '允许接入的设备 IPv4（逗号分隔）',
    'Engine (embedded is experimental)': '代理引擎（内嵌模式为实验性）',
    'Mihomo executable': 'Mihomo 可执行文件', 'Embedded engine executable': '内嵌引擎可执行文件',
    'HTTPS subscription URL': 'HTTPS 订阅链接',
    'Local provider file (overrides URL)': '本地节点文件（优先于订阅链接）',
    'Node selection': '节点选择方式', 'Preferred / fixed node name': '首选 / 固定节点名称',
    'Idle timeout (seconds)': '空闲等待（秒）', 'Local core port': '本地核心端口',
    'Local controller port': '本地控制接口端口', 'Browse…': '浏览…',
    'Core lifecycle': '核心生命周期', 'Access control': '接入控制', 'Configuration file': '配置文件',
    'Subscription and provider': '订阅与节点文件', 'Selection policy': '节点策略',
    'Engine configuration': '引擎配置', 'Local ports': '本地端口', 'Runtime diagnostics': '运行诊断',
    'Copy address': '复制地址', 'Export connection guide…': '导出接入说明…', 'Copied': '已复制',
    'Address copied.': '代理地址已复制。', 'Connection guide exported.': '接入说明已导出。',
    'Configure an address and port first.': '请先填写有效的监听地址和端口。',
    'Devices must support manual HTTP proxy settings. UDP and traffic that ignores proxy settings are not included.': '设备需支持手动 HTTP 代理；UDP 和不使用代理设置的流量不在此接入范围内。',
    'The listener can stay available while the upstream core sleeps. Listening does not prove an Internet connection.': '监听器可在上游休眠时保持可用。“正在监听”不代表外网请求已经成功。',
    'HK → JP → other regions. Prefer keeps fallback; fixed never switches silently.': '香港 → 日本 → 其他地区；prefer 保留回退，fixed 不会静默换节点。',
    'After all related streams close, the idle countdown begins. Active streams protect the core.': '所有相关连接释放后开始空闲计时；活动连接会保护核心。',
    'Opening or switching language never starts a connection.': '打开界面或切换语言不会启动代理连接。',
    'Stop the listener before editing configuration. Language and navigation stay available.': '修改配置前请先停止监听；语言切换和页面导航始终可用。',
    'No system proxy, DNS, VPN or firewall settings are changed.': '不修改系统代理、DNS、VPN 或防火墙设置。',
    'Loopback address: local tests only; another device cannot connect.': '回环地址仅供本机测试，其他设备无法连接。',
    'External mode: separate trusted Mihomo executable. This remains the default fallback.': '外部模式使用独立、可信的完整 Mihomo 核心，默认保留此路径。',
    'Experimental embedded mode: restricted adapter subset, public-only node endpoints. Some subscriptions are unsupported; fixed mode never silently falls back. See desktop.md.': '实验性内嵌模式仅支持受限适配器与公网节点；部分订阅不受支持，固定模式不会静默回退。详见 desktop.md。',
    'Cannot open configuration': '无法打开配置',
    'The file could not be read as a JSON configuration. Choose a different file.': '无法将该文件读取为 JSON 配置，请选择其他文件。',
    'Discard unsaved edits?': '放弃未保存的修改？',
    'Open another configuration and discard these unsaved edits?': '打开其他配置并放弃当前未保存的修改？',
    'Choose your verified Mihomo executable': '选择已经核验的 Mihomo 可执行文件',
    'Choose local Clash/Mihomo provider YAML': '选择本地 Clash/Mihomo 节点 YAML',
    'Choose your verified PSPortal native engine executable': '选择已经核验的 PSPortal 内嵌引擎',
    'Check configuration': '请检查配置', 'Cannot save configuration': '无法保存配置',
    'The configuration could not be saved. Choose a writable location and check file permissions.': '无法保存配置，请选择可写位置并检查文件权限。',
    'Cannot start listener': '无法启动监听',
    'The experimental embedded engine could not start. Check its executable path, OS/CPU compatibility and permissions. No engine switch was made.': '实验性内嵌引擎无法启动，请检查路径、系统架构和权限。未切换到其他引擎。',
    'The listener process could not start. Check the application files and executable permissions.': '监听进程无法启动，请检查程序文件和执行权限。',
    'Close PS Portal On-Demand?': '关闭 PS Portal On-Demand？',
    'Stop the listener and its core, then close?': '停止监听器和其拥有的核心，然后关闭？',
    'Close and discard unsaved configuration edits?': '关闭并放弃未保存的配置修改？',
    'Configuration saved and validated. No connection was made.': '配置已保存并通过校验，尚未建立连接。',
    'Cannot export': '无法导出',
    'Preferences could not be saved. Language changed for this session.': '语言偏好无法保存，本次会话已切换。',
    'Node provider preview': '节点文件预览', 'Inspect local YAML': '检查本地 YAML',
    'No provider inspected.': '尚未检查节点文件。', 'Provider nodes: {nodes} · groups: {groups} · rules: {rules}': '节点 {nodes} 个 · 策略组 {groups} 个 · 规则 {rules} 条',
    'Full profile detected. Preserve its rules with Full profile mode; provider mode only consumes nodes.': '检测到完整配置。请用完整配置模式保留规则；节点文件模式仅使用节点。',
    'Provider preview is local only. No subscription was fetched.': '仅检查本地文件，未下载订阅。',
    'Cannot inspect provider': '无法检查节点文件', 'Choose a local YAML file first.': '请先选择本地 YAML 文件。',
    'Full profile file': '完整配置文件', 'Profile source': '配置来源',
    'Provider / subscription': '节点文件 / 订阅', 'Complete Clash/Mihomo profile': '完整 Clash/Mihomo 配置',
    'Full profile preserves outbound nodes, groups and rules. This host manages only its listener and controller overlay.': '完整配置模式保留出站节点、策略组和规则；本程序单独管理监听及控制接口覆盖。',
    'Import subscription': '导入订阅', 'Export Clash client…': '导出 Clash 客户端配置…',
    'Full profile uses its original groups and rules; provider selection fields do not override them.': '完整配置使用原有策略组和规则；节点文件的选择字段不会覆盖它们。',
    'Enter a valid HTTPS subscription URL.': '请输入有效的 HTTPS 订阅链接。',
    'Importing subscription…': '正在导入订阅…',
    'Subscription import failed. Check the URL and connection.': '订阅导入失败，请检查链接和网络。',
    'Complete profiles require the external Mihomo engine': '完整配置需要使用外部 Mihomo 核心，请先在设置中切换引擎。',
    'Profile could not be read as supported YAML': '无法将配置读取为受支持的 YAML。',
    'Profile must be a YAML object': '配置的最外层必须是 YAML 对象。',
    'Profile must contain 1 byte to 10 MiB': '配置文件大小必须为 1 字节至 10 MiB。',
    'Profile structure exceeds import limits': '配置的嵌套层数或数据量超过导入限制。',
    'Profile has duplicate or non-string keys': '配置包含重复或非文本字段。',
    'Recursive YAML aliases are unsupported': '不支持递归 YAML 别名。',
    'Expanded profile exceeds import limits': '配置展开后的数据量超过导入限制。',
    'Additional profile listeners require a separate supported mode': '配置包含额外监听器，需要独立的接入模式；当前未导入。',
}


def text(key: str, language: str = 'en', **values) -> str:
    result = ZH.get(key, key) if language == 'zh' else key
    return result.format(**values) if values else result


def preference_path(config_path: Path) -> Path:
    return config_path.with_name(config_path.name + '.ui.json')


def load_language(config_path: Path) -> str:
    try:
        with preference_path(config_path).open('rb') as stream:
            raw = stream.read(4097)
        if len(raw) <= 4096:
            value = json.loads(raw)['language']
            if value in ('en', 'zh'):
                return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 'en' if config_path.exists() else 'zh'


def load_theme(config_path: Path) -> str:
    return _preferences(config_path).get('theme', 'dark')


def _preferences(config_path: Path) -> dict:
    try:
        with preference_path(config_path).open('rb') as stream:
            raw = stream.read(4097)
        if len(raw) <= 4096:
            value = json.loads(raw)
            if isinstance(value, dict):
                return {key: value[key] for key, choices in
                        (('language', ('en', 'zh')), ('theme', ('dark', 'light')))
                        if value.get(key) in choices}
    except (OSError, ValueError, TypeError):
        pass
    return {}


def save_language(config_path: Path, language: str) -> None:
    if language not in ('zh', 'en'):
        raise ValueError('unsupported language')
    _save_preference(config_path, 'language', language)


def save_theme(config_path: Path, theme: str) -> None:
    if theme not in ('dark', 'light'):
        raise ValueError('unsupported theme')
    _save_preference(config_path, 'theme', theme)


def _save_preference(config_path: Path, key: str, value: str) -> None:
    preferences = _preferences(config_path)
    preferences[key] = value
    path = preference_path(config_path)
    if path.is_symlink():
        raise ValueError('invalid preferences path')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.ui-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(preferences, stream)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
