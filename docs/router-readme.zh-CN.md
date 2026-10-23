# 星渡 StarPass

[![CI](https://github.com/LONG10222/psportal-on-demand/actions/workflows/check.yml/badge.svg)](https://github.com/LONG10222/psportal-on-demand/actions/workflows/check.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)

简体中文 | [English](../README.md)

**星渡 StarPass** 是从 PS Portal 局域网代理延伸出的跨平台按需代理开发版，
保留仓库、程序标识和原项目来源。新界面将**游戏设备、混合、本机 Clash**用途分开；
用途模式不等于规则／全局／直连，也不代表任意游戏 UDP 加速。
详见[三种用途、平台对照与验证边界](../docs/starpass-platform-modes.zh-CN.md)。
桌面不会自动修改系统代理、VPN、DNS 或防火墙；Android 本机代理仍需系统 VPN 授权。


PS Portal 的 OpenWrt / iStoreOS 按需代理。独立模式访问外网时启动自己的 Mihomo，空闲 60 秒后关闭；新增 OpenClash 联动模式复用已运行的核心，空闲只关闭本插件自己的连接。

- **按需启停**：监听器开机自启，代理核心由外网请求唤醒。
- **节点偏好**：自己的订阅支持自动地区回退、首选后回退或固定节点；可选登录后的 LuCI 页面。
- **单设备接入**：通过 IP 白名单限制客户端，Portal 手动设置 HTTP 代理即可使用。
- **OpenClash 联动**：只读发现回环入口，复用已有订阅、节点和规则，不启动/停止外部核心；节点管理留在 OpenClash
- **独立运行**：使用独立的核心和配置，OpenClash 无需启动；局域网请求直接连接。

> 第二阶段仍需固定版本 Mihomo/OpenWrt/LuCI 实机验收，详见[节点偏好与验收](../docs/node-preferences.zh-CN.md)。

## 桌面与移动端开发版

路由器有独立核心和外部 OpenClash 联动两种归属模式。Linux、Windows、macOS 请看[桌面使用说明](../portable/docs/desktop.md)；共享原生引擎和移动端请看 [native/README.md](../native/README.md)。不要在桌面系统执行路由器安装脚本。

桌面默认使用独立 Mihomo，也可在同一界面选择实验性的内置共享引擎。Android 由前台服务运行；iOS 默认前台托管；iOS 26+ 限时后台实验仍需实际授权与真机验收。请先看[当前验证结果与平台限制](../docs/portable-status.zh-CN.md)。原生引擎遵循 GPL-3.0，原路由器与包装界面遵循 MIT；分发原生二进制须附带完整对应源码。

## OpenClash 联动快速开始

从本草稿 PR 精确提交或 Actions 的 `starpass-router-source-…` 下载源码安装包；旧 main 压缩包尚不含本次更新。
无需复制核心：`sh install.sh --openclash`，然后 `portalproxy setup` 选择 `openclash`。
在 OpenClash 内先配置并启动订阅／节点；本插件仅设置 LAN 地址、单设备白名单、HTTP 端口与空闲时间。
LuCI 中可选择归属模式，保存后明确应用。已有安装不会被安装参数静默改模式。

[详细联动指南、控制器认证、fake-IP 和验证边界](../docs/openclash-linked.zh-CN.md)。
OpenClash 的最终规则可以选 DIRECT，看到的来源通常是路由器。HTTP 入口不承载游戏 UDP。
本次提供无核心的 `luci-app-starpass` IPK（仅 opkg 固件）和源码安装器。OpenWrt 25.12/apk 固件使用源码安装器，不能重命名 IPK。尚未上架 iStore；[2026-10-23 实机验证与剩余项](router-validation-2026-10-23.zh-CN.md)。

已有 opkg 固件可先核对校验值，再执行 `opkg install /tmp/luci-app-starpass.ipk`，在“服务 → StarPass / 星渡”选择归属、填设备地址并保存，之后单独点“启动共享”。安装和保存均不隐式启动。

## 独立模式快速开始

### 1. 准备

- 一台 OpenWrt / iStoreOS 软路由，带 Lua 5.1、LuCI 和 procd。
- 与设备架构匹配的 [Mihomo 核心](https://github.com/MetaCubeX/mihomo/releases)。已有 OpenClash 核心可以直接复用。
- 自己的 HTTPS Clash/Mihomo YAML 订阅。
- 在主路由 DHCP 中为 Portal 保留一个 IP 地址。

### 2. 安装

SSH 登录软路由，以 root 执行：

```sh
cd /tmp
# 从本开发分支 Actions 下载并核对 starpass-router-source.tar.gz
tar -xzf starpass-router-source.tar.gz
cd starpass-router-source
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
opkg install lua luci-compat luci-lib-nixio luci-lib-jsonc luci-lib-base libuci-lua curl ca-bundle
# apk 固件使用 apk update / apk add 同名依赖，不混装 opkg 包
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
| Outbound routing mark | 无 OpenClash 用 `0`；共存配置见[使用文档](../docs/guide.zh-CN.md#openclash-共存) |

完成后仅保存配置，不启动、不重启。独立模式先导入种子或明确执行订阅更新，再运行 `portalproxy enable`（启动并开机自启）。已有监听器保存后仍使用先前应用的配置，明确 `apply` 才重启。

在 **Portal → Wi-Fi → 当前网络 → 高级设置** 中：

- IP、网关、DNS 保持自动。
- HTTP 代理改为手动，地址填软路由 IP，端口填上面设置的端口。
- 按示例应填 `192.168.50.2:10081`。

没有导入本地种子时，先执行 `portalproxy subscription-update` 下载节点缓存，再连接网络。更新改为明确操作，不再自动定时下载；运行中的核心可能立即载入更新并切换线路。

## 常用命令

```sh
portalproxy status     # 查看运行状态
portalproxy nodes      # 查看缓存节点（不唤醒）
portalproxy prefer preferred '日本 A'  # 保存精确首选名称
portalproxy apply      # 应用设置，会中断连接
portalproxy subscription-update  # 明确下载，运行中可能换线
portalproxy logs       # 只读清洗后的本插件日志
portalproxy diagnose   # 配置、状态与日志；不启动
portalproxy setup      # 只保存配置
portalproxy check      # 检查配置
portalproxy restart    # 重启服务
portalproxy stop       # 停止服务
portalproxy disable    # 停止并取消开机启动
portalproxy enable     # 启动并开启开机启动
```

配置文件：`/etc/config/portalproxy`。修改后执行 `portalproxy check` 和 `portalproxy restart`。

## 更新与卸载

IPK 安装使用 `opkg install /tmp/新版.ipk` 升级，`opkg remove luci-app-starpass` 卸载并保留私有配置。不要用源码安装器覆盖包管理器文件。源码安装使用新版 `sh install.sh`，再明确启动；两种升级均不自动重启，原配置保留，私有备份位于 `/etc/portalproxy-backups/`。更新前停止共享、保留旧安装包/源码与配置，验证备份后再操作；opkg 的 `-opkg` 文件是新默认配置，不要覆盖自己的配置。

```sh
sh uninstall.sh          # 卸载，保留配置
sh uninstall.sh --purge  # 卸载并删除配置
```

卸载后关闭 Portal 的手动代理设置。

## 文档

- [参数、OpenClash 共存、排查与测试](../docs/guide.zh-CN.md)
- [更新记录](../CHANGELOG.md)
- [安全问题与诊断信息](../SECURITY.md)

## 许可

[MIT](../LICENSE)。代理核心由 [Mihomo](https://github.com/MetaCubeX/mihomo) 提供，遵循其上游许可。
