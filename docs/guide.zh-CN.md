# 使用文档

[返回 README](../README.zh-CN.md) | [English](guide.md)

## 参数

配置保存在 `/etc/config/portalproxy`，也可以通过 `portalproxy setup` 修改常用选项。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | 配置前 `0` | 向导完成后设为 `1` |
| `listen_ip` | 必填 | 软路由已有的局域网 IPv4 |
| `client_ip` | 必填 | 唯一允许接入的客户端 IPv4 |
| `local_dns` | 必填 | 局域网域名解析服务器 |
| `bootstrap_dns` | `local_dns` | 订阅及节点域名的引导 DNS，多个 IPv4 用空格分隔 |
| `subscription_url` | 必填 | HTTPS Clash/Mihomo YAML 订阅 |
| `subscription_user_agent` | `clash.meta` | 下载订阅的 User-Agent |
| `listen_port` | `10081` | Portal 手动代理端口 |
| `backend_port` | `18680` | 核心 HTTP 端口，仅回环地址 |
| `api_port` | `18681` | 核心 API 端口，仅回环地址 |
| `dns_port` | `18653` | 核心 DNS 端口，仅回环地址 |
| `idle_seconds` | `60` | 外网空闲关闭时间，10–3600 秒 |
| `wakeup_timeout` | `12` | 核心启动等待时间，3–60 秒 |
| `health_interval` | `60` | 节点检查间隔，秒 |
| `health_timeout` | `5000` | 节点检查超时，毫秒 |
| `health_url` | `https://connectivitycheck.gstatic.com/generate_204` | 返回 HTTP 204 的检查地址 |
| `subscription_interval` | `21600` | 订阅刷新间隔，秒 |
| `doh_url` | `https://1.1.1.1/dns-query` | 通过选中节点解析外网域名 |
| `routing_mark` | `0` | 出站连接标记 |
| `core_path` | `/usr/libexec/portalproxy/mihomo` | 独立核心路径 |

四个端口需互不相同。修改 `listen_port` 后，同时修改 Portal 上的代理端口。

```sh
portalproxy check
portalproxy restart
```

## 启停与选线

监听器开机运行，核心按需启动。完整的外网 HTTP 请求或 HTTPS CONNECT 会触发启动；私有地址请求直接连接。外网客户端会话连续 60 秒没有数据收发，核心关闭，空闲外网长连接断开。局域网请求和节点健康检查不刷新空闲时间。

局域网直连只允许 RFC1918 IPv4 和 ULA IPv6。回环、链路本地、CGNAT、IPv4 映射 IPv6 等特殊地址被拒绝。路由器自身的 RFC1918/ULA LAN 地址仍可访问，管理服务需单独保护。详见[目标地址策略及兼容性限制](destination-policy.md)。

Portal 的后台请求、保活和失败重试也会触发启动或延长运行时间。

节点使用 Mihomo `fallback` 组：香港优先，其次日本，最后其他地区；同地区保留订阅顺序。地区来自节点名称，识别中文名称、HK/JP 标签、旗帜、Hong Kong 和 Japan。所有节点不可用时，请求失败。

健康检查和订阅刷新只在核心运行期间执行。订阅经直连下载，`bootstrap_dns` 应填写本网络实际可用的 DNS。可在向导中导入已有 YAML 作为初始缓存。

## OpenClash 共存

核心、配置、订阅缓存和管理 API 与 OpenClash 分开。安装器复制已有核心，不依赖 OpenClash 进程运行。

部分 OpenClash 固件使用 `6666` 标记或 `nogroup` 组绕过自身代理。检测到 OpenClash 时，向导会建议 `6666`；采用该值后，两个项目进程使用 `nogroup` 主组，核心及订阅节点出站连接设置对应标记。未使用 OpenClash 时填 `0`。

自定义 TUN 或策略路由应按实际规则确认绕过标记。项目不添加防火墙规则。

## 排查

| 现象 | 处理 |
| --- | --- |
| 安装提示缺少核心 | 使用 `sh install.sh --core /path/to/mihomo` 指定可执行文件 |
| Portal 无法访问代理 | 检查软路由 IP、端口，以及 Portal 当前 IP 是否与 `client_ip` 相同 |
| 首次连接超时或返回 503 | 检查订阅能否直连下载、DNS 与节点状态；重试或增大 `wakeup_timeout` |
| 核心一直运行或反复启动 | 查看 Portal 是否有后台请求或保活 |
| 联网成功，连不上 PS5 | 检查 PS5 远程游玩设置、配对和局域网隔离 |

```sh
portalproxy status
cat /tmp/portalproxy/events.log
```

监听器只处理手动发来的 HTTP/HTTPS 代理请求。本地 PS5 的 UDP 串流沿用原网络路径；外出使用需要能够访问家中的代理地址。接入白名单按来源 IP 判断，服务用于可信局域网。

分享日志前请按 [SECURITY.md](../SECURITY.md) 去除订阅和设备信息。

## 文件与备份

| 路径 | 内容 |
| --- | --- |
| `/etc/config/portalproxy` | UCI 配置 |
| `/etc/portalproxy/` | 生成配置、订阅缓存、API 密钥 |
| `/etc/portalproxy-backups/` | 升级前的本地备份 |
| `/tmp/portalproxy/status.json` | 运行状态 |
| `/tmp/portalproxy/events.log` | 启停事件 |

`portalproxy stop` 只停止当前服务；`portalproxy disable` 同时取消开机启动。卸载默认保留配置，`--purge` 删除配置和缓存，两种方式均保留备份目录。

## 开发测试

本地测试：

```sh
lua5.1 tests/unit.lua
lua5.1 tests/access.lua
lua5.1 tests/dns.lua
lua5.1 tests/lifecycle.lua
lua5.1 tests/ownership.lua
python3 tests/packaging.py
```

OpenWrt 离线集成测试：

```sh
sh tests/router-smoke.sh
sh tests/core-config.sh /path/to/mihomo
IDLE_SECONDS=60 sh tests/router-smoke.sh
```

集成测试使用回环端口 `21081`–`21084` 和临时 procd 服务，验证回环 HTTP/CONNECT 目标被拒绝、客户端限制、外网唤醒、空闲关闭及再次唤醒。模拟后端会拦截外网测试目标 `1.1.1.1`，不发出互联网请求。端口需空闲，测试不要并行运行。RFC1918/ULA 直连和并发启停由模拟运行环境回归测试覆盖；纯回环测试不能证明真实局域网可达。`core-config.sh` 用真实核心解析示例配置，不启动代理服务。
