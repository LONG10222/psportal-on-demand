# 跨平台验证记录

更新：2026-10-18 UTC。以下是开发预览版证据，不是全部设备或网络条件已验收的声明。安装与对应产物版本见[下载说明](downloads.zh-CN.md)。

## 已验证范围

| 平台 / 组件 | 已通过 | 尚未证明 |
| --- | --- | --- |
| OpenWrt / LuCI | 3,744 项 Lua 断言、页面检查和打包检查 | 目标路由器、Mihomo/LuCI 版本实机兼容 |
| Linux x86_64 GUI | Debian 13；实际冻结 Tk 窗口、两种引擎生命周期、真实 Mihomo 受控流量；完整运行库来源/许可与源码核验 | 所有发行版、真实 Portal/订阅 |
| Windows x64 GUI | 实际打包窗口打开/正常关闭；源码 Tk 的双引擎 Start/Stop/restart；真实 Mihomo/原生测试；25 个运行库路径来源与许可核验 | Windows 全版本/ARM64 GUI；打包窗口的全部控件交互；代码签名 |
| macOS arm64 GUI | 实际窗口与双引擎源码 Tk 测试；最终 app 的严格嵌套代码签名检查；最终归档解压后的 LaunchServices 窗口启动/正常退出；64 个二进制来源路径核验 | Intel GUI、所有 macOS 版本；Developer ID/公证；真实 Portal |
| 原生 CLI | Linux、Windows、macOS 各 amd64/arm64 六个真实系统任务；每项 203 个测试/子测试、CLI 检查和源码/许可打包；Linux/macOS race | Windows race；真实订阅/Portal/所有节点协议 |
| Android | 90 项 JVM 断言、lint、签名与 16 KiB 静态对齐；精确 x86_64 APK 的 API26 实际 HTTP/CONNECT/来源过滤、重启、Home/Recents/通知 Stop；30 秒 Asleep 期间传输 | ARM64 手机/16 KiB 实机；Doze/OEM 省电；真实 Portal；公网加密节点全链路 |
| iOS | Simulator 实际安装启动；15 项 XCTest 中 14 通过、1 项硬件保护测试跳过；三项真实 GoMobile TCP 测试；实际 bundle 隐私用途清单/许可证；unsigned iPhoneOS 构建；最终归档解压后的精确 Simulator app 安装启动 | 真机签名安装、本地网络权限、Data Protection/备份、耗电、Portal；公网加密节点全链路 |

Windows/macOS 的“打包窗口启动/退出”与“源码 Tk 全流程交互”是不同证据，不把后者冒充前者。原生测试中的真实 Mihomo 适配器使用受控 SOCKS5 上游，不是加密节点互联网端到端测试。

## 构建与产物对应

- Linux GUI：`4ef16d63`，[run 39109675559](https://github.com/LONG10222/psportal-on-demand/actions/runs/39109675559)
- Windows GUI：`5925e67b`，[run 39111614703](https://github.com/LONG10222/psportal-on-demand/actions/runs/39111614703)
- 修正后的 macOS GUI：`eccd6b1b`，[run 39113880648](https://github.com/LONG10222/psportal-on-demand/actions/runs/39113880648) 的 Mac 任务通过。此前 `0b3529de` 包在添加 native 目录后未重新封装完整资源签名，已被替换，勿混用旧三包
- 原生六平台：[run 39113880825](https://github.com/LONG10222/psportal-on-demand/actions/runs/39113880825) 全通过；二进制与已保留版本哈希一致
- Android 精确 APK：arm64-v8a SHA256 `8f1c22953c4d0315bb02d9a111c803074f8b7c29629240caf5ac4a247be67762`；x86_64 SHA256 `224d5181a9d3717ad906f2fbb312e6bea435f7d7f485aeb3ff8f6dbeef86a489`
- iOS 隐私资源与最终归档修正版：`eccd6b1b`，[run 39113880593](https://github.com/LONG10222/psportal-on-demand/actions/runs/39113880593) 通过。最终 ZIP 解压后核对文件/模式/链接与资源，再安装并启动精确 Simulator app；设备构建仍未签名，Simulator 的 linker 签名不等于商店分发签名

`eccd6b1b` 同轮 Windows 任务因新增 Mac 测试夹具使用 Windows 路径分隔符而失败；修复只修改测试夹具，不改变已验收的 Windows 程序。最新提交的整体 CI 结果请看 [PR #3](https://github.com/LONG10222/psportal-on-demand/pull/3)，不要用某个平台成功代替整轮成功。

每份二进制保留其自己的提交、完整对应源码、依赖和校验值。独立静态复核已将三桌面共 30 个冻结 Python 模块/入口与精确 Git 源码逐项比对；同时核对架构、依赖、压缩包路径/链接、源码配套和 Android 签名。它不替代实际系统或设备测试。

## 仍需真实环境的验收

1. 手机/Portal/Wi-Fi：物理设备连接、本地网络授权、真实网络隔离/防火墙、长时间使用与耗电
2. 公网节点：实际订阅获取、节点协议兼容、健康排序、加密节点唤醒/闲置/再次唤醒。移动端已测 LAN 直连不会唤醒核心；正式 JNI/GoMobile 不包含测试拨号注入。缺少受控公网 HTTPS 订阅和代理节点，不能用本地直连代替该验证
3. Android 省电：API26 关屏 30 秒只是 ADB 连接的模拟器观察；API36 镜像默认禁用 Doze，完整系统镜像无可用局域网地址，未修改设置来制造通过结果
4. iOS：仅前台托管，进入后台停止。Apple 不允许把 Packet Tunnel 扩展当成后台局域网代理服务器；未签名设备构建需另行签名/配置，Simulator 无法证明真机隐私与硬件保护行为
5. 发行：Windows 无 Authenticode，macOS 无 Developer ID/公证，Android 为开发签名，iOS 设备包未签名。未宣称商店审核、自动更新或跨平台正式发行完成

## 使用与许可边界

项目是 HTTP/HTTPS CONNECT 按需代理，不是 UDP 游戏串流服务或完整 VPN。桌面默认独立 Mihomo，实验性 embedded 与移动端使用受限原生适配器。固定节点失败时不静默换节点、换引擎或外网直连。

不自动修改系统防火墙、代理、DNS、VPN 或开机服务。原生程序分发时须同时保留完整对应源码、vendor 依赖与 GPL/第三方通知；原始路由器与包装代码保持原许可证。
