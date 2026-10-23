# 下载与安装

## 当前入口

- **[软路由已验证代码 · 5da0753](https://github.com/LONG10222/psportal-on-demand/actions/runs/39958952749)**：进入成功的 checks 运行页面，在 Artifacts 下载 `starpass-router-source-5da075302716ec1199bdefcb110d6ae43aff1d46` 并解开外层 ZIP。内有 `luci-app-starpass.ipk`、`starpass-router-source.tar.gz` 和各自 `.sha256`。[安装与使用](router-readme.zh-CN.md) · [实机与安卓验证](router-validation-2026-10-23.zh-CN.md)。
- **[软路由当前分支构建](https://github.com/LONG10222/psportal-on-demand/actions/workflows/check.yml?query=branch%3Afix%2Frouter-install-validation-20261023)**：按提交确认 checks 通过。Actions 产物会过期；过期后从[匹配源码](https://github.com/LONG10222/psportal-on-demand/archive/5da075302716ec1199bdefcb110d6ae43aff1d46.zip)按[构建步骤](router-readme.zh-CN.md#从匹配源码构建)生成。文档提交和后续 CI 不代表重新完成实体设备验收。

IPK 仅供 opkg 固件，由包管理器安装 Lua/LuCI 依赖，包内没有代理核心。apk 固件使用源码安装器。软路由页面提供概览与折叠设置、独立/联动模式、保存/启停、节点快照和帮助；实体 PS Portal／Quest 游戏与串流仍待验收。

- [测试归档 Releases](https://github.com/LONG10222/psportal-on-demand/releases)：`starpass-test-20261020-c1d2d3a` 保留已验证的整合测试包及校验信息。
- [当前分支 Actions](https://github.com/LONG10222/psportal-on-demand/actions)：Android 四页精简界面、升级校验和全平台更新入口由对应 PR 构建，旧归档不包含这些更新。原始 CI APK 未签名。

以下列举早期交付方式及历史产物，不应作为最新版本入口。

## 获取历史构建产物

当前产物来自开发分支 `feat/unified-native-ports`，不代表 `main` 或正式发行版。这些早期链接不包含后来归档的整合测试版本。

- [桌面 GUI：run 39113880648](https://github.com/LONG10222/psportal-on-demand/actions/runs/39113880648)（Mac/Linux 任务通过；同轮 Windows 测试夹具失败，已验收 Windows 包见下方版本表）
- [原生 CLI：run 39113880825](https://github.com/LONG10222/psportal-on-demand/actions/runs/39113880825)
- [Android 未签名构建：run 39113880584](https://github.com/LONG10222/psportal-on-demand/actions/runs/39113880584)
- [iOS 模拟器与未签名设备构建：run 39113880593](https://github.com/LONG10222/psportal-on-demand/actions/runs/39113880593)（最终归档解压、资源校验和 Simulator 安装启动通过）

先确认目标平台的任务及产物门禁通过，再在运行页面底部 Artifacts 下载；同一轮其他平台失败不等于该产物未通过，但不能把整轮称为成功。GitHub 可能要求登录；产物有保留期限，过期后旧链接不能继续下载。查看[仓库 Actions 列表](https://github.com/LONG10222/psportal-on-demand/actions)寻找该分支的后续成功构建；这里不承诺历史二进制永久保留。源码可从对应提交下载。不要从来历不明的镜像下载核心。

CI 的桌面产物是完整归档。为适应文件传输大小限制，另有三个独立小包的交付形式；二者是不同打包方式，不需要把完整 CI 归档与三小包混合。两种形式都应保留完整匹配源码与许可证。

从 Actions 下载的 ZIP 可能是产物容器：先解开它，再按其中的 `SHA256SUMS` 核对并解开实际程序 ZIP/tar.gz。保留同包源码和许可。Windows 打开 `PSPortalProxy/PSPortalProxy.exe`，Linux 运行 `PSPortalProxy/PSPortalProxy`，macOS 打开 `PSPortalProxy.app`；若归档额外带父目录，以包内说明为准。

## 桌面三包安装

每个平台的 `runtime`、`native-engine`、`corresponding-source` 必须来自同一交付版本。先核对交付说明或配套 `SHA256SUMS` 中对应文件的校验值，再解压到同一个父目录。不要把三个包分别解压为三套程序，也不要混用旧版同名文件。每个小包都是普通归档，不需要拼接。

### Windows x64

在 PowerShell 的下载目录执行：

```powershell
Expand-Archive .\PSPortalProxy-windows-x64-runtime.zip -DestinationPath .\PSPortalProxy-Windows -Force
Expand-Archive .\PSPortalProxy-windows-x64-native-engine.zip -DestinationPath .\PSPortalProxy-Windows -Force
Expand-Archive .\PSPortalProxy-windows-x64-corresponding-source.zip -DestinationPath .\PSPortalProxy-Windows -Force
```

打开 `PSPortalProxy-Windows\PSPortalProxy\PSPortalProxy.exe`。无需另外安装 Python。当前 GUI 运行证据来自 Windows Server 2025 x64，不能据此保证所有 Windows 版本或 ARM64 GUI 均可用。

这是未做 Authenticode 签名的开发版。遇到安全提示时自行核对来源；本项目不要求关闭系统安全保护。默认 external 模式需另行选择可信的 Windows Mihomo 可执行文件。

### macOS Apple Silicon

```sh
mkdir -p PSPortalProxy-macOS
tar -xzf PSPortalProxy-macos-arm64-runtime.tar.gz -C PSPortalProxy-macOS
tar -xzf PSPortalProxy-macos-arm64-native-engine.tar.gz -C PSPortalProxy-macOS
tar -xzf PSPortalProxy-macos-arm64-corresponding-source.tar.gz -C PSPortalProxy-macOS
open PSPortalProxy-macOS/PSPortalProxy.app
```

保留符号链接与可执行权限。原生引擎最低加载版本为 macOS 13；实际验证环境为 macOS 15 / Apple Silicon，不保证所有 macOS 13+ 环境或 Intel Mac GUI。

`eccd6b1b` 修正版完成最终 app 的 ad-hoc 完整性封装、严格嵌套签名验证及归档解压后的实际启动。它替换 `0b3529de` 的旧 Mac 包，三件需全部重下。ad-hoc 不是 Developer ID 签名或 Apple 公证；Gatekeeper 是否允许下载后的应用是另一条件，不要关闭系统保护来规避它。

### Linux x86_64

```sh
mkdir -p PSPortalProxy-linux
tar -xzf PSPortalProxy-linux-x86_64-runtime.tar.gz -C PSPortalProxy-linux
tar -xzf PSPortalProxy-linux-x86_64-native-engine.tar.gz -C PSPortalProxy-linux
tar -xzf PSPortalProxy-linux-x86_64-corresponding-source.tar.gz -C PSPortalProxy-linux
cd PSPortalProxy-linux/PSPortalProxy
./PSPortalProxy
```

实测 Debian 13 / glibc 2.41。包内 ELF 需要 GLIBC_2.38 符号，宿主还需 `libz.so.1`、`libxcb.so.1`、X11 或 XWayland 与可用字体。不能只根据 glibc 版本推断所有发行版兼容。使用保留 Linux 权限的文件系统与解压工具；不需要管理员权限或额外安装 Python。

### 界面配置

1. 本机地址填实际局域网 IPv4，例如 `192.168.1.2`；允许客户端填 Portal 的另一个固定 IPv4，例如 `192.168.1.30`
2. 端口默认 `10081`。不要填 `0.0.0.0`；`127.0.0.1` 仅用于本机测试，Portal 无法连接
3. 填可信 HTTPS 订阅。桌面选择非空本地 provider 路径时，以该文件为准；清空后才使用 URL
4. 默认 `external` 使用独立 Mihomo；实验性 `embedded` 使用随包 `psportal-native`。不要把 `psportal-native` 选为外部 Mihomo
5. `auto` 按香港、日本、其他节点选择；`prefer` 首选完整节点名并保留回退；`fixed` 只用完整指定名，失败不会换节点或外网直连
6. 保存、启动，等待界面状态 `Listening`。保存配置不等于订阅已下载或外网已可用；首个外网请求才触发核心启动
7. Portal 手动 HTTP 代理填写本机地址和端口，保持原有 IP、网关、DNS 设置。停止使用时恢复 Portal 的代理设置

电脑保持唤醒，双方网络需互通。程序不会自动添加防火墙规则；只考虑可信私有网络的必要访问，不要将代理暴露到公网。源码运行、配置字段和故障排查见[桌面指南](../portable/docs/desktop.md)。

## Android

选择手机架构匹配的 APK：常见 64 位 ARM 手机使用 `arm64-v8a`，`x86_64` 用于对应设备/模拟器。最低 Android 8 / API26，当前 target API36。每个分架构 APK 可独立安装，不用合并或同时安装另一架构。

开发签名包与 CI 未签名 APK 不同。CI 的未签名 APK 不能直接安装，需使用自己管理的签名流程；项目测试密钥不在仓库中。签名不等于商店发布或真机验证。

应用内填写手机局域网地址、Portal 地址、端口与 HTTPS 订阅，主动启动前台服务。Portal 代理填写手机 IP。可从应用或通知停止；从最近任务移除会停止服务。不要依靠前台服务推断所有厂商省电策略均能持续联网。

精确 x86_64 APK 已在 API26 模拟器完成 HTTP/CONNECT、来源限制、Home/最近任务/通知停止、重启和 30 秒屏幕休眠测试；ARM64 手机、Doze、真实 Portal 尚未验收。安装包需与 `psportal-android-complete-source.zip` 及许可证一起保留。构建说明见 [Android README](../native/android/README.md)。

## iOS

- **Simulator app**：适用于 Apple Silicon Mac 的 iOS Simulator，不能装进 iPhone
- **Unsigned device app**：针对 iPhoneOS arm64 构建，但未签名，不能直接安装；需 Xcode、相应签名/配置和设备条件

iOS 只能在前台托管代理，进入后台会停止连接。不能通过滥用 VPN 扩展获得后台局域网代理常驻。Simulator 的安装/HTTP/CONNECT 测试不能证明真机本地网络授权、Data Protection、耗电或 Portal 行为。

选择设备后，预编译 Simulator app 可用 Xcode 的 `xcrun simctl install booted /path/to/PSPortalHost.app` 安装，并以 `xcrun simctl launch booted org.psportal.host.foreground` 启动。具体 app 文件名与最低系统要求以对应归档指南为准。构建、签名条件和前台限制见 [iOS README](../native/ios/README.md)。

## 原生 CLI 与源码

Linux、Windows、macOS 各有 amd64 / arm64 CLI；它和桌面 GUI 的架构支持范围不同。按系统/架构选包，使用[原生配置示例](../native/config.example.json)：

```sh
./psportal -config config.json -check
./psportal -config config.json -status-interval 10s
```

Windows 使用 `psportal.exe`。CLI 不安装系统服务，不修改系统网络设置。完整配置、支持的节点协议和离线 vendor 构建见[原生引擎说明](../native/README.md)。

每个二进制必须配套它自己的对应源码，不要用最新源码替代旧包源码。Windows 生成的源码归档保留 CRLF 和非可执行脚本权限；在 POSIX 重建前，应在工作副本中规范脚本换行并恢复可执行位，原归档保持不变。

## 已验证产物的版本

下表标识实际产物，不能将它们统一当作最新提交的二进制。新的 CI 状态以工作流结果为准。

| 产物 | 提交 / 构建证据 |
| --- | --- |
| Linux x86_64 GUI 三包 | `4ef16d63` · [run 39109675559](https://github.com/LONG10222/psportal-on-demand/actions/runs/39109675559) |
| Windows x64 GUI 三包 | `5925e67b` · [run 39111614703](https://github.com/LONG10222/psportal-on-demand/actions/runs/39111614703) |
| macOS arm64 GUI 修正版 | `eccd6b1b` · [run 39113880648](https://github.com/LONG10222/psportal-on-demand/actions/runs/39113880648) · Mac 任务通过；同轮 Windows 新测试夹具的路径格式失败另行修复 |
| 六平台原生 CLI | [run 39113880825](https://github.com/LONG10222/psportal-on-demand/actions/runs/39113880825) 全通过，二进制与已保留包一致 |
| Android 开发签名 ARM64 / x86_64 | APK SHA256 分别以 `8f1c2295` / `224d5181` 开头；精确完整值见随包 manifest 与补充运行证据 |
| iOS 隐私资源与最终归档修正版 | `eccd6b1b` · [run 39113880593](https://github.com/LONG10222/psportal-on-demand/actions/runs/39113880593) 通过；设备 app 仍未签名 |

完整测试边界见[验证记录](portable-status.zh-CN.md)。公网加密节点的移动端唤醒/闲置/再次唤醒、真实订阅、Portal/手机/Wi-Fi 与路由器实机仍有独立验收条件。不要向 Issue 上传订阅链接、账户 token 或签名私钥。
