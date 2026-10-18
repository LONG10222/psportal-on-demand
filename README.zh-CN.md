# PS Portal On-Demand

[![CI](https://github.com/LONG10222/psportal-on-demand/actions/workflows/check.yml/badge.svg)](https://github.com/LONG10222/psportal-on-demand/actions/workflows/check.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

简体中文 | [English](README.md)

PS Portal 的 OpenWrt / iStoreOS 按需代理。访问外网时启动 Mihomo，空闲 60 秒后自动关闭。

- **按需启停**：监听器开机自启，代理核心由外网请求唤醒。
- **自动选线**：使用自己的订阅，按香港 → 日本 → 其他地区依次选择可用节点。
- **单设备接入**：通过 IP 白名单限制客户端，Portal 手动设置 HTTP 代理即可使用。
- **独立运行**：使用独立的核心和配置，OpenClash 无需启动；局域网请求直接连接。

## 快速开始

### 1. 准备

- 一台 OpenWrt / iStoreOS 软路由，带 Lua 5.1、LuCI 和 procd。
- 与设备架构匹配的 [Mihomo 核心](https://github.com/MetaCubeX/mihomo/releases)。已有 OpenClash 核心可以直接复用。
- 自己的 HTTPS Clash/Mihomo YAML 订阅。
- 在主路由 DHCP 中为 Portal 保留一个 IP 地址。

### 2. 安装

SSH 登录软路由，以 root 执行：

```sh
cd /tmp
curl -fL https://github.com/LONG10222/psportal-on-demand/archive/refs/heads/main.tar.gz -o portal-source.tar.gz
tar -xzf portal-source.tar.gz
cd psportal-on-demand-main
sh install.sh
portalproxy setup
```

安装器会查找已有项目核心、`/etc/openclash/core/clash_meta` 和 `/usr/bin/mihomo`。需要指定其他核心时，把安装命令换成：

```sh
sh install.sh --core /path/to/mihomo
```

缺少 Lua 依赖时安装：

```sh
opkg update
opkg install lua luci-lib-nixio luci-lib-jsonc luci-lib-base libuci-lua
```

### 3. 配置

运行 `portalproxy setup`，按提示填写。下面使用示例网段，地址换成自己的：

| 向导提示 | 示例 |
| --- | --- |
| OpenWrt LAN IPv4 address | 软路由地址 `192.168.50.2` |
| Portal reserved IPv4 address | Portal 保留地址 `192.168.50.30` |
| LAN DNS server | 主路由 `192.168.50.1` |
| Working bootstrap DNS | `192.168.50.1` |
| HTTP proxy port | `10081` |
| External idle timeout | `60` |
| HTTPS subscription URL | 填自己的订阅，输入不回显 |
| Optional local Clash/Mihomo YAML seed file | 可留空，或填已有配置文件路径 |
| Outbound routing mark | 无 OpenClash 用 `0`；共存配置见[使用文档](docs/guide.zh-CN.md#openclash-共存) |

完成后监听器立即运行，并在开机时启动。

在 **Portal → Wi-Fi → 当前网络 → 高级设置** 中：

- IP、网关、DNS 保持自动。
- HTTP 代理改为手动，地址填软路由 IP，端口填上面设置的端口。
- 按示例应填 `192.168.50.2:10081`。

连接网络后，即可登录 PlayStation 服务并连接 PS5。首次下载订阅可能需要稍等后重试。

## 常用命令

```sh
portalproxy status     # 查看运行状态
portalproxy setup      # 修改配置
portalproxy check      # 检查配置
portalproxy restart    # 重启服务
portalproxy stop       # 停止服务
portalproxy disable    # 停止并取消开机启动
portalproxy enable     # 启动并开启开机启动
```

配置文件：`/etc/config/portalproxy`。修改后执行 `portalproxy check` 和 `portalproxy restart`。

## 更新与卸载

下载新版源码，重新执行 `sh install.sh`，再运行 `portalproxy restart`。原配置保留，升级备份位于 `/etc/portalproxy-backups/`。

```sh
sh uninstall.sh          # 卸载，保留配置
sh uninstall.sh --purge  # 卸载并删除配置
```

卸载后关闭 Portal 的手动代理设置。

## 文档

- [参数、OpenClash 共存、排查与测试](docs/guide.zh-CN.md)
- [更新记录](CHANGELOG.md)
- [安全问题与诊断信息](SECURITY.md)

## 许可

[MIT](LICENSE)。代理核心由 [Mihomo](https://github.com/MetaCubeX/mihomo) 提供，遵循其上游许可。
