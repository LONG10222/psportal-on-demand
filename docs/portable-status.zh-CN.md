# 跨平台开发版：验证结果与剩余条件

更新：2026-10-18 UTC。这是开发预览版，不是所有平台已完成实机验收的声明。

## 同一套产品结构

- 原有 `src/`、LuCI、OpenWrt 安装流程保持独立
- `portable/` 是同一个桌面界面，默认 external 独立 Mihomo，也可明确选择 experimental embedded
- `native/engine` 是 Go 共享引擎；桌面 CLI/界面子进程、Android JNI 与 iOS framework 复用它
- embedded 只接受文档列出的受限节点协议/配置与公网节点地址。固定节点不存在或不可用时失败关闭，不会偷偷切换另一引擎
- 这是 HTTP/HTTPS CONNECT 按需代理，不是 UDP、完整 VPN 或游戏画面串流服务

## 已有证据

1. 路由器：3,744 项 Lua 断言、LuCI 检查与打包检查通过；真实路由器/Mihomo/LuCI 版本仍需验收
2. external 桌面：PR #2 的 Linux 真实 Mihomo/打包流量测试、实际 Tk 窗口 Start/Stop/restart/close，以及 Windows/macOS 打包程序配置检查、监听、拒绝、EOF 退出和再次启动均通过
3. 统一桌面：CI run 39109675559 的 Linux、Windows、macOS 实际系统任务全部通过，包含两种引擎的实际 Tk 窗口、冻结应用窗口、真实 Mihomo 与受控 HTTP/CONNECT 流量。Windows/macOS 后续增加完整运行库来源与许可证发布门禁：Windows 已通过；macOS 的全部 63 个二进制来源、完整通知与 163 项运行测试通过，最终归档目录清单检查仍在修复，最终发布须等待该门禁通过
4. 原生 CLI：CI run 39110679832 的 Linux/Windows/macOS 各 amd64 与 arm64，共六个真实系统运行任务全部通过；203 个测试结果、vet、实际 CLI 与完整源码打包检查通过，Linux/macOS 另通过 race。Windows 未执行 race。完整 vendored 对应源码已离线重建/测试
5. Android：真实 arm64/x86_64 AAR 与 APK 编译成功，90 项 JVM 断言与配置往返通过，lint 无错误，16 KiB 对齐通过。开发签名通用 APK 在 API26 模拟器通过实际前台服务、JNI 监听、HTTP/CONNECT、来源白名单及移除任务清理测试；API36 ATD 另通过通知拒绝/批准、服务启动及停止。来自模拟器既有接口的合成客户端不代表真实 Portal。已提供 arm64 独立安装包，签名与内容一致性通过，但未在 ARM64 物理设备运行。独立 x86_64 包的精确安装与启动已通过，完整重测继续中。API36 系统镜像没有可用局域网地址且默认禁用 Doze，不能据此声称锁屏/Doze 已通过；未修改网络或省电设置来掩盖该限制
6. iOS：CI run 39110679850 的 arm64 Simulator Release 应用实际安装启动成功，14 项 XCTest 中 13 项通过、1 项物理设备 Data Protection 测试明确跳过。三项真实 GoMobile 桥接测试覆盖 HTTP、CONNECT、拒绝未授权来源、停止监听和已接受套接字、重新启动；其他生命周期测试使用明确标注的测试替身。unsigned iPhoneOS arm64 编译/链接通过。模拟器 app、未签名设备 app 与完整对应源码分别提供；未签名设备 app 不能直接安装，仍需 Apple 签名/配置与真实 iPhone 验证

[独立核心桌面 PR #2](https://github.com/LONG10222/psportal-on-demand/pull/2) · [统一原生与移动端 PR #3](https://github.com/LONG10222/psportal-on-demand/pull/3)

## 必须区分的验收层级

编译、受控回环流量、实际操作系统运行、模拟器、手机实机、Portal与真实Wi-Fi/订阅是不同证据。跨编译不能替代运行，模拟器不能替代真实Portal。具体工作流的提交号、日志、二进制SHA与随包验证报告才对应那次产物。

Linux图形包使用Debian13的Python3.13/Tk8.6，需GLIBC_2.38符号、系统zlib/libxcb、X11或XWayland及字体环境。其他发行版未保证兼容；包内静态原生CLI可单独试用。

Android需明确启动前台服务并测试锁屏/Doze；iOS只能在应用前台保持代理。不能通过虚构VPN用途承诺iOS后台局域网代理。真实设备安装、签名、商店交付和平台权限各有独立条件。

## 下载与许可

通过测试的CI任务才上传对应产物，开发产物暂存期较短。原生二进制必须与同次完整对应源码、依赖源码和许可证一并保留。私有签名密钥、订阅与凭据不进入源码或公开产物。

所有版本均不自动修改防火墙、系统代理、DNS、VPN或开机服务。配置Portal前先确认自己的地址、允许客户端和可信订阅；不要公开监听给不可信网络。
