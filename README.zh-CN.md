# PS Portal On-Demand

简体中文 · [English](README.md)

运行在 OpenWrt / iStoreOS 上的 PS Portal 按需 HTTP 代理。一个 Lua 监听进程常驻局域网，只有指定 Portal 发出外网 HTTP 请求或 HTTPS 隧道请求时，才启动独立的 Mihomo 进程。外网会话连续 60 秒没有客户端数据收发后，关闭代理核心。

监听器只接受一个指定客户端 IP。访问私有地址时直接连接局域网，不启动核心。节点来自使用者自己的 Clash/Mihomo 订阅，优先香港，其次日本，最后尝试其他地区。OpenClash 无需保持运行。

仓库提供源码、安装脚本、交互配置和测试，不包含订阅、节点密码、Mihomo 二进制或实际部署的网络配置。本文所有地址都是示例，需要替换成自己的信息。

## 工作原理

```text
Portal → 手动设置的 HTTP 代理 → Lua 监听器
                               ├─ 私有地址 → 直接连接局域网
                               └─ 外网地址 → 启动 Mihomo → 自有订阅
                                                           香港 → 日本 → 其他地区
                               外网客户端数据空闲 60 秒 → 关闭 Mihomo
```

- 开机只启动监听器。核心处于关闭状态，等待外网请求。
- 只建立 TCP 连接、没有发送完整代理请求，不会启动核心。
- 局域网流量和节点健康检查不延长外网空闲时间。
- 空闲关闭会断开外网长连接；后续新请求会重新启动核心。
- 节点选择采用 Mihomo `fallback` 组和有序过滤器。同一地区内部保留订阅顺序，按可用性选择，不是测速后选最低延迟。
- 只有核心运行期间才进行健康检查和订阅更新。更高优先级节点恢复后，可以在后续检查中重新被选中。

这里的“空闲”指外网客户端会话没有数据收发。Portal 的后台请求、应用保活同样算流量，程序无法判断使用者是否正在玩游戏。首次请求、失败重试、后台访问都可能唤醒核心。这是进程按需启停机制，不是流量隐藏工具，也不保证设备完全不产生网络活动。

## 运行条件

- 带 `procd`、UCI、Lua 5.1 和 LuCI Lua 库的 OpenWrt / iStoreOS。运行测试环境为 iStoreOS 22.03.6，其他版本需要自行验证。
- 软路由已有稳定、可访问的局域网 IPv4 地址。
- 在原有 DHCP 服务器上为 Portal 保留 IPv4 地址。
- 与软路由 CPU 架构匹配的 Mihomo 核心，以及返回 Clash/Mihomo YAML（包含 `proxies:`）的 HTTPS 订阅。普通 Base64 节点列表不支持。
- 软路由能够直接解析并通过 HTTPS 访问订阅服务器。订阅下载走直连，避免“必须先有节点才能下载节点”的启动依赖。

使用 `opkg` 的固件，缺少依赖时通常可以安装：

```sh
opkg update
opkg install lua luci-lib-nixio luci-lib-jsonc luci-lib-base libuci-lua
```

软件包应与已安装固件匹配。安装器会先检查所需 Lua 模块。可选集成测试还需要 `curl`、`jsonfilter`，日常监听器不依赖它们。

建议使用近期稳定版 [Mihomo](https://github.com/MetaCubeX/mihomo/releases)。配置依赖有序过滤器、订阅健康检查和按 URL 记录的代理健康状态，相关语义见上游[代理组](https://wiki.metacubex.one/config/proxy-groups/)和[代理集合](https://wiki.metacubex.one/config/proxy-providers/)文档。本项目不自动下载或升级核心。

## 安装

通过 SSH 登录运行服务的 OpenWrt 软路由，使用 root 执行：

```sh
cd /tmp
git clone https://github.com/LONG10222/psportal-on-demand.git
cd psportal-on-demand
sh install.sh
portalproxy setup
```

没有 Git 时，可以下载源码压缩包：

```sh
cd /tmp
curl -fL https://github.com/LONG10222/psportal-on-demand/archive/refs/heads/main.tar.gz -o portal-source.tar.gz
tar -xzf portal-source.tar.gz
cd psportal-on-demand-main
sh install.sh
portalproxy setup
```

安装器依次查找已有的项目核心、`/etc/openclash/core/clash_meta`、`/usr/bin/mihomo`，并复制到本项目私有目录。也可以指定核心：

```sh
sh install.sh --core /path/to/mihomo
```

仅安装不会启动服务。交互配置通过校验后，才启动监听器并设置监听器开机自启。代理核心自身的开机启动保持关闭。

### 配置示例

假设主路由为 `192.168.50.1`，软路由为 `192.168.50.2`，Portal 的 DHCP 保留地址为 `192.168.50.30`。以下示例不能直接照抄到不同网段。

| 配置向导提示 | 示例及说明 |
| --- | --- |
| OpenWrt LAN IPv4 address | `192.168.50.2`，软路由已经拥有的局域网地址 |
| Portal reserved IPv4 address | `192.168.50.30`，在现有 DHCP 服务器中为 Portal 保留 |
| LAN DNS server | `192.168.50.1`，用于判断域名是否解析到私有地址 |
| Working bootstrap DNS | `192.168.50.1`，或多个实际可用的 DNS IPv4，用空格分隔 |
| HTTP proxy port | `10081`，软路由上没有被占用的端口 |
| External idle timeout | `60` 秒 |
| HTTPS subscription URL | 自己的 Clash/Mihomo 订阅，输入时不回显 |
| Optional YAML seed | 已存在的本地 Clash/Mihomo YAML 文件，也可以留空 |
| Outbound routing mark | 一般为 `0`，OpenClash 共存说明见后文 |

先固定 Portal 的 DHCP 租约，再配置允许访问的客户端地址。本项目不创建 DHCP 保留条目，也不修改软路由的 LAN 地址。向导可以读取现有地址作为默认值，但不会给接口重新分配地址。

可选 YAML 文件会复制成初始订阅缓存。软路由已有同一订阅的配置文件时，可以减少首次启动的等待时间。只导入可信文件；文件保存在本地，不会上传或提交到仓库。没有缓存时，首次唤醒需要下载订阅，Portal 若先超时，可以稍等后重试。

### Portal 端设置

1. 连接平时使用的 Wi-Fi。如果原网络使用 DHCP，IP、网关和 DNS 可以保持自动。
2. 在该网络的高级设置里启用手动 HTTP 代理。
3. 填软路由局域网地址和本项目监听端口。按上述示例，应填 `192.168.50.2`、`10081`。
4. 先测试联网，再连接 PS5，进入游戏检查串流。

Wi-Fi 连接本身必须正常。代理无法修复 Wi-Fi 密码错误、无线加密兼容性、信号差、访客隔离或 DHCP 失败。PS5 不需要设置同样的代理。通过联网测试，也不等于已经验证游戏串流可用。

## 日常使用

```sh
portalproxy status     # 查看监听器、核心、空闲计时和请求计数
portalproxy check      # 只校验已保存配置，不启动核心
portalproxy restart   # 重新加载本项目配置，会断开正在使用的代理会话
portalproxy stop      # 停止监听器和核心，本次开机生效
portalproxy start     # 启动已经配置好的监听器
portalproxy disable   # 停止服务并关闭监听器开机启动
portalproxy enable    # 开启监听器自启并立即启动
portalproxy setup     # 交互修改配置；订阅留空保留原 URL
```

正常状态变化：监听器运行、核心关闭 → Portal 请求外网 → 核心运行 → 外网客户端数据空闲 60 秒 → 核心关闭。主循环约每 250 毫秒检查一次，进程退出还会有少量延迟。

`stop` 不取消下次开机启动，需要跨重启停用时使用 `disable`。停止服务不会自动删除 Portal 上的手动代理；需要恢复普通联网路径时，在 Portal 上关闭手动代理设置。

### 与 OpenClash 共存

本项目有独立的配置、订阅缓存、管理密钥、进程和核心副本。OpenClash 的启停不直接控制本项目生命周期。

部分 OpenClash 固件会放行标记为 `6666` 或进程组为 `nogroup` 的流量。向导检测到 `/etc/init.d/openclash` 时，会建议这个标记，也可以改成 `0` 或固件实际使用的其他值。选 `6666` 时，本项目两个进程以 `nogroup` 为主组运行，生成配置也会为核心及订阅节点的出站连接设置对应标记。这使用已有的绕过约定，不添加防火墙规则。

自定义全局 TUN、策略路由、DNS 劫持或不同防火墙实现，仍可能影响出站路径。应在实际固件上确认标记是否有效，不能仅凭服务名称不同，就认定与所有 OpenClash 模式或后续版本完全隔离。

## 参数说明

配置文件位于 `/etc/config/portalproxy`。初次部署用 `portalproxy setup`；修改高级选项时，在软路由本地编辑文件，再执行 `portalproxy check` 和 `portalproxy restart`。

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `enabled` | 配置前为 `0` | 向导完成后设为 `1` |
| `listen_ip` | 必填 | 软路由已有的私有局域网 IPv4，不允许通配监听 |
| `client_ip` | 必填 | 唯一允许访问的客户端 IPv4 |
| `local_dns` | 必填 | 判断局域网域名所用的 IPv4 DNS 服务器 |
| `bootstrap_dns` | 与 `local_dns` 相同 | 实际可用的 DNS IPv4，多个用空格分隔，用于订阅及节点域名引导解析 |
| `subscription_url` | 必填 | 自有 HTTPS Clash/Mihomo YAML 订阅 |
| `subscription_user_agent` | `clash.meta` | 下载订阅时的 User-Agent |
| `listen_port` | `10081` | 局域网 HTTP 代理端口 |
| `backend_port` | `18680` | 核心内部 HTTP 端口，仅回环地址 |
| `api_port` | `18681` | 核心管理 API，仅回环地址，使用随机生成的密钥 |
| `dns_port` | `18653` | 核心 DNS 端口，仅回环地址 |
| `idle_seconds` | `60` | 外网空闲秒数，范围 10–3600 |
| `wakeup_timeout` | `12` | 监听器等待核心就绪的秒数，范围 3–60 |
| `health_interval` | `60` | 核心运行期间节点检查间隔，单位秒 |
| `health_timeout` | `5000` | 节点检查超时，单位毫秒 |
| `health_url` | Google 连通性检查 HTTPS 地址 | 应通过节点返回 HTTP 204 |
| `subscription_interval` | `21600` | 核心运行期间订阅刷新间隔，单位秒 |
| `doh_url` | `https://1.1.1.1/dns-query` | 经选中节点解析外网目标域名的 DoH |
| `routing_mark` | `0` | 可选出站连接标记 |
| `core_path` | `/usr/libexec/portalproxy/mihomo` | 本项目独立 Mihomo 核心路径 |

四个端口必须互不相同且没有被占用。修改 `listen_port` 后，也要修改 Portal 上的手动代理端口。这些端口都不是订阅商的节点端口。

订阅只在核心运行期间刷新；核心关闭时，不存在每六小时唤醒一次的定时下载。地区识别依据节点名称，支持中文名称、HK/JP 单词标签、地区旗帜、Hong Kong 和 Japan。无法识别的节点放在最后尝试。所有节点都不可用时，请求失败，不会悄悄切换成外网直连。

## 流量范围与边界

只处理主动发往监听器的 HTTP 代理请求和 HTTPS `CONNECT` 隧道。不提供透明代理、TUN、SOCKS、UDP 转发，也不改变设备默认网关。PS5 本地音视频串流可能使用直连 UDP，仍按原局域网路径传输。本项目不能改善无线射频质量，也不保证外网远程串流效果。

私有 IPv4、回环、链路本地、CGNAT、IPv6 ULA/链路本地字面地址及 `::1` 会视为本地目标。通过 `local_dns` 仅解析到私有 IPv4 的域名，也可以绕过核心。这是地址分类，不代表能确认某个名称物理上位于家中；跨路由的私有网络仍属于私有地址。当前版本不支持 IPv6 客户端监听，也不支持只返回 IPv6 的局域网 DNS 名称分类。

访问限制依据来源 IPv4，不依据 MAC 地址。应正确保留 DHCP 地址，在可信局域网使用，不要把监听端口映射到 WAN 或暴露给不可信网络。

手动填写的私有代理地址，只有在 Portal 能访问它的网络中才有效。离家连接另一处 Wi-Fi 时，需要另行满足到家中网络的可达条件；本项目不会建立远程回家通道。

## 排查

| 现象 | 检查方向 |
| --- | --- |
| Wi-Fi 本身连接失败 | 先解决无线连接和 DHCP，代理运行在更上层 |
| 代理拒绝连接 | `portalproxy status`、软路由实际 LAN 地址、端口和监听器状态 |
| 客户端被拒绝 | Portal 当前 IPv4 是否与 `client_ip` 一致，DHCP 保留是否生效 |
| 首次请求返回 503 | 订阅下载、节点可用性、检查地址、引导 DNS；重试或适当增加 `wakeup_timeout` |
| 核心一直不关闭 | Portal 后台请求或保活可能在刷新空闲计时 |
| 核心反复被唤醒 | 检查 Portal 后台活动，失败的外网尝试也会触发启动 |
| 相同节点在别处能用 | 订阅格式、核心版本、订阅能否直连下载、标记与现有防火墙是否兼容 |
| 联网通过但连不上 PS5 | PS5 远程游玩设置、账号配对、局域网隔离、NAT 和实际串流路径 |
| 地区优先级不符合预期 | 节点命名、健康检查可达性；名称匹配不等于真实地理位置校验 |

状态文件在 `/tmp/portalproxy/status.json`，生命周期记录在 `/tmp/portalproxy/events.log`。监听器不记录请求 URL 或订阅 URL，但系统日志中的 Mihomo/procd 错误可能包含订阅商或连接细节。先在本地检查，分享前删去私人信息。

## 升级、备份与卸载

取得新版源码后重新执行 `sh install.sh`，再执行 `portalproxy restart`。已有项目配置会保留。覆盖已安装版本前，安装器会把本项目的配置、缓存和程序目录打包到 `/etc/portalproxy-backups/`，目录和文件仅 root 可读。备份可能包含订阅令牌和节点密码，只保存在软路由，不会上传。

```sh
sh uninstall.sh          # 删除本项目服务和程序，保留配置、缓存及备份
sh uninstall.sh --purge  # 同时删除本项目配置和缓存，仍保留备份
```

卸载后，在 Portal 上关闭手动代理。脚本只管理 `portalproxy`、`portalproxy-core`，不改写网络、DHCP、DNS、防火墙、Wi-Fi 或 OpenClash 配置。

## 开发与测试

```sh
lua5.1 tests/unit.lua
python3 tests/packaging.py
```

单元测试覆盖请求解析边界、私有地址判断、参数校验和地区排序配置。打包测试覆盖暂存安装、保留配置、私有文件权限、备份与卸载。CI 在 Ubuntu 运行这两组测试。

需要在可管理的 OpenWrt 环境中验证完整启停链路时，运行离线集成测试：

```sh
sh tests/router-smoke.sh
# 用真实核心校验生成配置，仅解析配置、不启动代理服务
sh tests/core-config.sh /path/to/mihomo
# 可选：按完整 60 秒验证空闲关闭
IDLE_SECONDS=60 sh tests/router-smoke.sh
```

测试只在回环地址使用 `21081`–`21084` 端口和临时 `procd` 服务名，运行前需要确认端口空闲。它检查局域网 HTTP/CONNECT 直连、拒绝第二个来源 IP、外网请求唤醒、局域网流量持续期间的空闲关闭，以及再次唤醒。不使用真实订阅，也不验证真实节点。不要同时运行多份；退出时会清理自身临时服务。

## 隐私与许可

运行数据和备份位于源码目录之外。交互向导输入订阅时不回显，也不把订阅放进进程命令行。UCI 和运行配置限制为 root 读取，不实现遥测或自动上传。订阅节点原有参数保留其自身语义，TLS 等选项应由使用者核对。

分享排查材料前请阅读 [SECURITY.md](SECURITY.md)。项目源码使用 MIT 许可。Mihomo 属于独立上游项目，遵循它自己的许可；本仓库不分发核心二进制。本项目与 Sony、PlayStation 没有关联。
