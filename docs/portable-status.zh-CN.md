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
3. 最新统一 Linux 包：108 项测试中107项通过，1项图形显示测试在本地跳过。原生引擎40个顶层测试、203个测试结果、race、vet和实际 CLI 检查通过。完整 vendored 对应源码已离线重建/测试
4. Android：真实 arm64/x86_64 AAR与APK编译成功，90项JVM断言与配置往返通过，lint无错误，16KiB对齐通过。专用开发签名APK的v2/v3签名验证通过；模拟器运行验收另计
5. iOS：源码、生成接口和本地结构/脚本测试通过；实际 Xcode/Simulator/XCTest 验收由 PR #3 工作流执行，运行成功前不能称为已通过

[独立核心桌面 PR #2](https://github.com/LONG10222/psportal-on-demand/pull/2) · [统一原生与移动端 PR #3](https://github.com/LONG10222/psportal-on-demand/pull/3)

## 必须区分的验收层级

编译、受控回环流量、实际操作系统运行、模拟器、手机实机、Portal与真实Wi-Fi/订阅是不同证据。跨编译不能替代运行，模拟器不能替代真实Portal。具体工作流的提交号、日志、二进制SHA与随包验证报告才对应那次产物。

Linux图形包使用Debian13的Python3.13/Tk8.6，需GLIBC_2.38符号、系统zlib/libxcb、X11或XWayland及字体环境。其他发行版未保证兼容；包内静态原生CLI可单独试用。

Android需明确启动前台服务并测试锁屏/Doze；iOS只能在应用前台保持代理。不能通过虚构VPN用途承诺iOS后台局域网代理。真实设备安装、签名、商店交付和平台权限各有独立条件。

## 下载与许可

通过测试的CI任务才上传对应产物，开发产物暂存期较短。原生二进制必须与同次完整对应源码、依赖源码和许可证一并保留。私有签名密钥、订阅与凭据不进入源码或公开产物。

所有版本均不自动修改防火墙、系统代理、DNS、VPN或开机服务。配置Portal前先确认自己的地址、允许客户端和可信订阅；不要公开监听给不可信网络。
