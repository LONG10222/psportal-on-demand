# Windows 与 LAN 接入设计

## 本轮选择

| 路线 | 可验证传输 | 所需条件 | 本轮结论 |
|---|---|---|---|
| 正常联动已安装鲜牛 | 已有检测器验证真正的 HTTP CONNECT + TLS；电脑出口是否命中驱动另验 | 客户端提供标准入口或官方支持的转发路径 | 保留旧模式。本次检测 inventory_timeout，没有得到可共享代理证据；未修改官方客户端 |
| 原生鲜牛 provider | Windows HTTP、SOCKS5 TCP、SOCKS5 UDP；账号/节点/计时可与传输分开验证 | 正常官方账号、会员及游戏线路 | 采用；复用 0.4.4 官方协议及星渡 HTTP 核心，Windows 独立生命周期和 DPAPI 私有存储 |
| PC 本机 TUN/WFP | 可让不支持代理的 PC 应用进入 provider | 实际捕获模块、驱动、循环排除、退出回滚 | 尚未实现，不用系统代理冒充全应用捕获 |
| Windows 热点 + ICS | 可使连接热点的设备流量经过电脑，仍需实际 TCP/UDP 转发适配器 | 新子网及 NAT/DHCP、设备重新连接并采用该网络的网关/DNS | 当前不启用；与保持 PS5 原网关/DNS 的约束冲突 |
| 现有主路由策略转发 | 可保留终端配置，但流量需由路由实际导向电脑 | 主路由支持并允许配置转发/隧道策略 | 当前无获准配置；不改小米 WAN/PPPoE/DHCP，不采用 ARP 欺骗 |

星渡负责设备授权、共享端口、游戏目录、UI、私有存储和生命周期；provider 负责官方账号、线路、start/stop、计时与原生传输。当前单账号单游戏会话可共享给多个明确授权的代理客户端；不支持同时启动多游戏，也不能保证所有目标游戏协议兼容。

## 入口与证据

SOCKS5 UDP ASSOCIATE 要求应用实际发送 SOCKS UDP 数据报，并将其生命周期绑定 TCP 控制连接；UDP 入口锁定控制连接来源 IP 与首个有效数据报的来源端口。拒绝分片、私网目的地及未请求的响应，限制并发与目标数量。HTTP 使用既有严格解析、公开目的地检查和设备白名单。

官方 stop 未发现独立 session ID。仅本次成功 start 的 managed provider 会 stop；导入的所有内部 ownership 字段均被丢弃。borrowed provider 不 start/stop，不自动重登录或暂停/恢复。首次正常 token 续期成功后才放行转发；续期失败暂停新连接，连续三次失败关闭入口。不会切换到 Mihomo 或直连作为错误回退。Steam 商店直连是明确策略。

独立会话启用前人工确认账号没有其他入口占用。仅勾选确认无法检测后续另一个入口抢占，因此多入口并发仍未支持。start 不确定或 stop 未确认时保留本机归属记录并阻止下一次独立 start，不能用重启程序自动清理未知官方会话。

## 下一步需要决定的网络条件

在所有设备维持现有主路由、网关、DNS和连接方式时，电脑上的代理只能接收应用主动交给它的流量。没有入口就不能验收任意 PS5/Switch 游戏 UDP。可审阅的后续实验是先让一台支持 SOCKS5 UDP 的外部 PC 显式接入；主机则需用户接受改变接入网络/网关/DNS，或主路由提供兼容且获准的流量转发。批准后仍需实现转发、检查 NAT/语音/目标游戏、停止后恢复；开启热点本身不是验收。

依据：[SOCKS5 RFC 1928](https://www.rfc-editor.org/rfc/rfc1928)、[Windows ICS 的 NAT 与 DHCP 语义](https://learn.microsoft.com/en-us/windows/win32/nativewifi/using-hosted-network-and-internet-connection-sharing)、[DPAPI CurrentUser](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)。热点适配器/系统版本实际支持仍需现场验证，此处不承诺现有硬件兼容。
