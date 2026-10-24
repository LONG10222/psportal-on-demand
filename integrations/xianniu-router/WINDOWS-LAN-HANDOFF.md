# 星渡 + 鲜牛：Windows 启动、局域网共享

目标是在星渡中选择鲜牛 provider，一台 Windows 电脑启动服务后，为选中的局域网设备提供游戏加速。当前只验证鲜牛，后续适配器沿用统一接口。

## 已有源码

- 本分支的 `portable/docs/accelerator-mode.zh-CN.md`、`portable/portalproxy/windows_accelerator.py`、`accelerator_proxy.py`、`steam_host.py`、`accelerator_pac.py` 和 `proxy.py`：已有 Windows 加速器模式、标准本机代理适配及 LAN 共享。
- 本目录的 `src/xianniu_router/protocol.py`、`control.py`、`auth_web.py`、`auth_api.py`、`member_time.py`：已验证的原生协议、官方账号、会员计时和续期基础。
- `runtime.py`、`http_streams.py`、`http_proxy.py`：原生传输与 HTTP 字节流适配。Linux 透明套接字、procd、UCI 和 N1 存储路径需要与 Windows provider 解耦。

## 优先设计

星渡负责设备、共享入口、UI、生命周期与私有配置；provider 负责官方登录、会员状态、游戏/区服/线路、start/stop、续期和原生 TCP/UDP 流。先做到一个真实会话可稳定使用，再讨论多设备同游戏与多游戏并发。

本地状态和账号凭据保存在 Windows 用户私有目录，不放在安装目录、PAC、状态接口或仓库。沿用已有独立加速器配置，不覆盖用户其他星渡模式、订阅或日常鲜牛客户端。

界面保留官方账号、剩余时长、设备卡片、游戏库和一键启动。Steam 商店默认直连的策略需要与现有“仅 Steam 网页”预览区分，不能沿用旧 Steam 限定逻辑后宣称覆盖全部游戏。

## 关键网络问题

HTTP/CONNECT 只接管主动使用该代理的 TCP。完整游戏 UDP 必须有可验证的流量入口，例如实际受支持的客户端/隧道、转发路径或热点/共享网络。只启动电脑、把请求从电脑发出，不能证明鲜牛驱动接管了其他设备的游戏流量。

先只读调查现有网卡、路由和实际可达设备；比较代理、受支持客户端与热点/路由方案，再选择最少影响现有网络的实现。不能用 ARP 欺骗或暗改 DHCP/网关来制造接管。

用户已有约束：保留主路由 PPPoE/WAN/DHCP、保留 PS5 网关和 DNS，不新增硬件；设备手动 Wi-Fi 代理可以使用。若完整 UDP 需要改变上述条件，先给出可审阅设计和证据，再由用户决定，不自动越过约束。

## 验收

从安装/源码构建的独立预览开始：账号状态与持久化 → 真实节点与会员计时 → LAN TCP → LAN UDP → 目标游戏/NAT。必须区分 PC 本机成功、N1 本机成功和外部设备游戏成功。

记录实际设备来源、选中的游戏/节点、传输是否经过 provider，以及启停后如何恢复。官方计时和会话限制照常执行；官方 stop 没有独立 session ID，同账号多入口并发可能互相影响，不能无验证地启动/停止另一入口拥有的会话。

不修改主路由上网设置，不自动卸载或覆盖现有客户端，不购买会员，不规避官方验证或限制。公开发布内容只含代码、模拟测试和去标识化验证结论。
