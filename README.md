# PS Portal On-Demand

为 PlayStation Portal 提供按需启动的 HTTP/HTTPS 代理。外网请求唤醒代理核心，空闲后关闭；局域网连接直连。

[下载与安装](docs/downloads.zh-CN.md) · [路由器指南](README.zh-CN.md) · [桌面指南](portable/docs/desktop.md) · [验证记录](docs/portable-status.zh-CN.md)

## 功能

- 独立运行，不依赖 OpenClash 服务，不改系统代理、DNS 或 VPN
- 使用自己的 Clash/Mihomo 订阅，支持自动选择、首选回退和固定节点
- 按客户端 IP 限制接入；活跃外网连接不会被空闲计时器中断
- Windows、macOS、Linux 共用桌面界面；Android 与 iOS 使用共享原生引擎

本项目处理 HTTP 和 HTTPS CONNECT，不转发任意 UDP，也不能保证 Portal 的所有流量都会使用手动代理。真实 Portal/Wi-Fi 与订阅节点仍需验收。

## 平台

当前提供开发预览版，尚未发布正式 Release。

| 平台 | 可用形式 | 说明 |
| --- | --- | --- |
| OpenWrt / iStoreOS | Lua 服务、可选 LuCI 页面 | 原有路由器版本；需目标设备验收 |
| Windows x64 | 桌面程序 | 无需另装 Python；未做代码签名 |
| macOS Apple Silicon | 桌面 `.app` | 至少 macOS 13，实测 macOS 15；未做 Developer ID 签名或公证 |
| Linux x86_64 | 桌面程序 | 实测 Debian 13；需 GLIBC_2.38 符号及图形环境 |
| Linux / Windows / macOS | amd64、arm64 原生 CLI | 六种组合已在对应系统运行；功能仍为实验性 |
| Android | arm64-v8a、x86_64 APK | Android 8+，开发签名；运行证据来自 x86_64 模拟器 |
| iOS | arm64 Simulator、未签名设备构建 | 仅前台运行；设备版需自行签名与配置 |

架构、运行条件和每个产物对应的提交见[下载说明](docs/downloads.zh-CN.md)。编译、模拟器测试和手机实测不等价。

## 快速开始

### 桌面

1. 下载并解压匹配系统的完整桌面归档。若拿到的是 `runtime`、`native-engine`、`corresponding-source` 三个小包，**解压到同一个目录**；不要混用不同版本
2. 打开桌面程序，填写本机局域网 IPv4、Portal 的固定 IPv4、端口（默认 `10081`）和自己的 HTTPS 订阅
3. 选择引擎：默认 `external` 使用自行准备的可信 [Mihomo](https://github.com/MetaCubeX/mihomo/releases)；实验性 `embedded` 使用随包原生引擎。两者失败时不会自动互换
4. 保存并启动监听，等到状态显示就绪。Portal 的手动 HTTP 代理填写这台电脑的地址和端口，IP/网关/DNS 保持原有设置

电脑需保持运行并与 Portal 网络互通。完整解压命令、运行依赖和移动端安装见[安装说明](docs/downloads.zh-CN.md)。路由器用户直接看[OpenWrt / iStoreOS 安装](README.zh-CN.md#快速开始)，不要在桌面执行 `install.sh`。

### 节点选择

| 模式 | 行为 |
| --- | --- |
| `auto` | 香港 → 日本 → 其他节点，结合健康状态选择 |
| `prefer` | 优先指定节点，不可用时按自动顺序回退 |
| `fixed` | 只用指定节点；名称不存在或节点不可用时失败，不换节点、不直连外网 |

`prefer` / `fixed` 填写订阅中的**完整节点名**。桌面还可选择本地 provider 文件；非空文件路径优先于 URL。移动端使用 HTTPS 订阅。内置引擎只导入节点数据，不接受完整配置中的脚本、系统路由或任意文件引用；支持范围见[原生引擎说明](native/README.md)。

## 使用限制

只在可信局域网使用，不要把监听端口转发到公网。IP 白名单不是身份认证；订阅 URL 可能含凭据，不要贴到日志或 Issue。程序不自动放行防火墙。

Android 需要用户主动启动前台服务；关屏短时测试通过不代表 Doze 或所有手机省电策略均可用。iOS 切到后台会停止代理，不提供后台常驻承诺。真实手机、Portal 和公网加密节点端到端验证仍有缺口，详见[验证记录](docs/portable-status.zh-CN.md)。

## 文档与开发

- [路由器配置、OpenClash 共存与排障](docs/guide.zh-CN.md) · [English router guide](docs/router-readme.en.md)
- [节点偏好与 LuCI](docs/node-preferences.zh-CN.md)
- [桌面源码运行与测试](portable/README.md)
- [原生引擎与构建](native/README.md) · [Android](native/android/README.md) · [iOS](native/ios/README.md)
- [安全说明](SECURITY.md) · [GitHub Actions](https://github.com/LONG10222/psportal-on-demand/actions)

## 许可证

原有路由器代码与桌面包装层使用 [MIT](LICENSE)。链接 Mihomo 的原生引擎使用 [GPL-3.0-only](native/LICENSE)，依赖遵循各自许可证。分发原生程序时，请保留同版本完整对应源码、vendor 依赖和许可证；不要只转发二进制。
