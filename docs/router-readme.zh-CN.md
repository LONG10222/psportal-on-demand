# 星渡 StarPass · 软路由

[游戏与加速器工作区](router-workspaces.zh-CN.md)

在 OpenWrt / iStoreOS 上，为支持手动 HTTP 代理的设备提供按需共享。

简体中文 · [English](router-readme.en.md) · [项目首页](../README.md) · [实机验收](router-validation-2026-10-23.zh-CN.md)

## 选择模式

| 模式 | 核心与节点 | 空闲时 |
| --- | --- | --- |
| 独立按需核心 | 星渡管理自己的 Mihomo、HTTPS 订阅和节点策略 | 回收自己的核心；外网请求再次唤醒 |
| 复用 OpenClash | 复用已运行的代理；订阅、节点、规则和测速在 OpenClash 管理 | 只回收星渡自己的会话，OpenClash 继续运行 |

两种模式都限制为一个允许的设备 IPv4，默认端口 `10081`、空闲超时 `60` 秒。安装和保存只做准备，点击“启动共享”才启动并启用开机自启。

## 下载

- [已验证代码 5da0753 的构建](https://github.com/LONG10222/psportal-on-demand/actions/runs/39958952749)：在页面底部 Artifacts 下载 `starpass-router-source-5da075302716ec1199bdefcb110d6ae43aff1d46`，解开外层 ZIP。
- [当前开发分支构建](https://github.com/LONG10222/psportal-on-demand/actions/workflows/check.yml?query=branch%3Afix%2Frouter-install-validation-20261023)：确认目标提交的 checks 成功；文档更新不等于重新完成设备验收。
- [完整匹配源码](https://github.com/LONG10222/psportal-on-demand/archive/5da075302716ec1199bdefcb110d6ae43aff1d46.zip) · [草稿 PR #27](https://github.com/LONG10222/psportal-on-demand/pull/27)。

GitHub 下载产物可能需要登录，Actions 产物有保存期限。过期后可从对应提交重新构建，步骤见下文；[Releases](https://github.com/LONG10222/psportal-on-demand/releases) 中的旧测试归档不包含本轮软路由改动。

| 文件 | 用途 |
| --- | --- |
| `luci-app-starpass.ipk` / `.sha256` | opkg 固件的无核心 LuCI 包及校验值 |
| `starpass-router-source.tar.gz` / `.sha256` | 源码安装器、测试和文档及校验值 |

IPK 由包管理器安装 Lua/LuCI 依赖，不包含 Mihomo。OpenWrt apk 固件使用源码安装器；本轮没有原生 OpenWrt APK 或 iStore 上架包。

## 安装

### opkg 固件

把 IPK 和配套校验文件上传到路由器 `/tmp`，以 root SSH 执行：

```sh
cd /tmp
sha256sum -c luci-app-starpass.sha256
opkg install ./luci-app-starpass.ipk
```

在包管理器按固件源安装依赖后，打开 **服务 → StarPass / 星渡**。LuCI 使用 legacy CBI，需要 `luci-compat`；安装器会检查现有环境。首次安装不启动共享。

### 源码安装器

适用于源码管理的安装，或使用 apk 的固件。先按当前固件的软件源准备 Lua、LuCI/procd、nixio、jsonc、UCI Lua、curl 和 CA 依赖；不同包管理器的源和包不能混用。opkg 固件所需包名为：

```sh
opkg update
opkg install lua luci-compat luci-lib-nixio luci-lib-jsonc luci-lib-base libuci-lua curl ca-bundle
```

把源码 tar 和校验文件上传到 `/tmp` 后执行：

```sh
cd /tmp
sha256sum -c starpass-router-source.sha256
tar -xzf starpass-router-source.tar.gz
cd starpass-router-source
sh install.sh --openclash
```

独立模式首次安装使用 `sh install.sh`；可用 `--core /可信路径/mihomo` 指定匹配架构的可执行核心。缺少核心时仍可先安装和保存；独立启动前会检查核心。已知的 `/usr/bin/mihomo`、`/etc/openclash/core/clash_meta` 可自动发现，详见[高级配置](guide.zh-CN.md)。联动时只复用已运行的 OpenClash 入口。

已有 opkg 安装用 IPK 升级，源码安装器会拒绝直接覆盖包管理器文件。已有配置保持原模式，安装参数不会把它静默切换为联动。

## 接入设备

1. **先准备上游。** 复用模式先在 OpenClash 配好订阅、节点并启动；独立模式准备匹配架构的可信 Mihomo 和自己的 HTTPS Clash/Mihomo 订阅。
2. **展开“接入设置”。** 选择核心模式并填写地址；为目标设备保留稳定的 DHCP 地址。下表仅为示例，不是你的实际网络。

   | 字段 | 示例 |
   | --- | --- |
   | 允许接入的设备 IP | `192.168.50.30` |
   | 路由器地址 | `192.168.50.2` |
   | 代理端口 | `10081` |
   | 局域网 DNS | 主路由或可用 LAN DNS，例如 `192.168.50.1` |

3. **保存配置。** 独立模式的新订阅链接不会回显；留空保留原链接，保存后点“更新订阅”。有本地种子时也可用 CLI 导入，见[配置指南](guide.zh-CN.md)。
4. **启动共享。** 页面明确显示监听状态。在设备的手动 HTTP 代理中填 `192.168.50.2:10081`，保持设备原有 IP、网关、DNS 设置。
5. **验证目标功能。** 先确认设备网页访问，再测试具体游戏或串流。结束后点击“停止共享”，并关闭设备上的手动代理。

首页保留共享状态、保存的代理地址和启停；“节点与策略”展示历史快照，可本地筛选。高级设置放空闲时间/引导 DNS，帮助保留接入和更新说明。

| 操作 | 行为 |
| --- | --- |
| 保存配置 | 校验并保存；不下载、不启停 |
| 应用已保存配置 | 重启已启用的共享，可能中断连接；已停止的共享保持停止 |
| 启动共享 / 停止共享 | 启动并启用自启 / 停止并取消自启 |
| 刷新快照 | 读取就绪核心；不唤醒休眠核心，不测速 |
| 更新订阅 | 独立模式显式下载缓存；运行中的核心可能重载节点并中断连接 |

未保存的修改会提示先保存，停止仍可用。独立节点策略支持自动地区回退、首选后回退和仅固定节点；名称需精确匹配。固定节点不可用时拒绝星渡转发的外网请求。联动节点和测速在 OpenClash 操作。

## 已验证与边界

N1 / iStoreOS 24.10.8 ARM64 已完成实际 LuCI 操作、opkg 安装/升级、真实 HTTP/HTTPS、并发、空闲恢复及 procd 故障恢复。最终 `5da0753` 的 28 个静态文件逐字节核对，CI 与本机安装包一致。

MuMu Android 15 的临时应用通过系统代理完成 HTTP 200、HTTPS 204，重启共享后恢复。停止共享时，该客户端回退直连；手动代理不能当作断网保护。每轮均还原模拟器代理并移除临时应用。

HTTP/HTTPS CONNECT 只承载 TCP。实体 PS Portal／Quest 的游戏/串流、物理 Wi-Fi 质量、目标 N1 整机重启、长期运行和独立真实订阅恢复仍待验收。监听就绪、有连接或节点快照不等于外网/游戏成功。[完整证据与未完成项](router-validation-2026-10-23.zh-CN.md)。

## 更新与回退

更新前停止共享，保留旧包/源码与配置。IPK 使用 `opkg install /tmp/新版.ipk`；源码安装使用匹配版本的 `sh install.sh`。两者均保留现有配置并在本机 `/etc/portalproxy-backups/` 保存私有升级备份；备份可能含订阅凭据，不要公开上传。

升级不自动启动。opkg 的 `portalproxy-opkg` 是另存的新默认配置，不要覆盖自己的配置。若需回退，先停止共享、核对备份与旧包，再恢复匹配版本；不要盲目覆盖程序文件。源码安装器可恢复可捕获的写入失败，备份不是系统快照，也不保证断电恢复。

```sh
opkg remove luci-app-starpass  # opkg 安装：卸载并保留配置/provider/私有备份
sh uninstall.sh               # 源码安装：卸载并保留配置
```

明确要清除保留配置时，先卸载 opkg 包，再使用匹配源码的 `sh uninstall.sh --purge`；独立备份仍保留。卸载后关闭设备的手动代理，外部 OpenClash 由自身管理。

## 命令与排查

```sh
portalproxy setup                  # 交互配置，仅保存
portalproxy check                  # 检查配置和依赖
portalproxy enable                 # 启动并开启自启
portalproxy disable                # 停止并关闭自启
portalproxy apply                  # 应用已保存配置
portalproxy status                 # 状态，不代表外网测试
portalproxy nodes                  # 本地节点快照
portalproxy nodes-refresh          # 显式刷新；不唤醒
portalproxy prefer preferred '日本 A' # 保存精确首选名称
portalproxy subscription-update    # 独立订阅更新
portalproxy logs                   # 清洗后的本插件日志
portalproxy diagnose               # 配置检查、状态与日志
```

手动修改 `/etc/config/portalproxy` 后先 `portalproxy check`，再明确 `portalproxy apply`。日志、截图和 Issue 不要附带订阅、认证头、私钥或私有备份。

## 从匹配源码构建

在完整仓库源码根目录运行（需要 Python 3；包不含核心）：

```sh
python3 scripts/build-router-ipk.py luci-app-starpass.ipk --version 0.1.0+git5da075302716-1
python3 scripts/build-router-source.py starpass-router-source.tar.gz
```

检查构建脚本输出的 SHA-256。[构建、测试与高级配置](guide.zh-CN.md) · [OpenClash 联动细节](openclash-linked.zh-CN.md) · [更新日志](../CHANGELOG.md) · [安全反馈](../SECURITY.md)。路由器包装层为 [MIT](../LICENSE)，Mihomo 核心遵循其[上游许可](https://github.com/MetaCubeX/mihomo)。
