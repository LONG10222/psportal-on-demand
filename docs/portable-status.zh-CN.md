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
3. 统一 Linux 图形包：CI run 39108633515 的121项测试全部通过、零跳过，包含两种引擎实际打包窗口的启动、停止、再次启动、关闭取消/确认、真实 Mihomo 与打包流量；45个运行库ELF与21份完整版权文件核验通过
4. 原生 CLI：CI run 39107706960 的 Linux/Windows/macOS 各 amd64与arm64，共六个真实系统运行任务全部通过；各40个顶层测试、203个测试结果、vet与实际CLI检查通过，Linux/macOS另通过race。Windows未执行race。完整 vendored 对应源码已离线重建/测试
5. Android：真实 arm64/x86_64 AAR与APK编译成功，90项JVM断言与配置往返通过，lint无错误，16KiB对齐通过。开发签名APK已在API26模拟器安装运行，实际前台服务、JNI监听、HTTP/CONNECT与来源白名单受控测试通过。来自同一模拟器两个既有接口的合成客户端不代表真实Portal。移除任务的服务清理回归正在修复；新版签名包和较新API运行验收仍待完成
6. iOS：CI run 39108633642 的真实 arm64 Simulator应用已编译、链接并实际启动，11项XCTest中10项通过，1项物理设备Data Protection测试明确跳过，零失败。应用、对应源码与许可同包保存。iPhoneOS编译、签名后实机安装与真实Portal仍是独立验收条件

[独立核心桌面 PR #2](https://github.com/LONG10222/psportal-on-demand/pull/2) · [统一原生与移动端 PR #3](https://github.com/LONG10222/psportal-on-demand/pull/3)

## 必须区分的验收层级

编译、受控回环流量、实际操作系统运行、模拟器、手机实机、Portal与真实Wi-Fi/订阅是不同证据。跨编译不能替代运行，模拟器不能替代真实Portal。具体工作流的提交号、日志、二进制SHA与随包验证报告才对应那次产物。

Linux图形包使用Debian13的Python3.13/Tk8.6，需GLIBC_2.38符号、系统zlib/libxcb、X11或XWayland及字体环境。其他发行版未保证兼容；包内静态原生CLI可单独试用。

Android需明确启动前台服务并测试锁屏/Doze；iOS只能在应用前台保持代理。不能通过虚构VPN用途承诺iOS后台局域网代理。真实设备安装、签名、商店交付和平台权限各有独立条件。

## 下载与许可

通过测试的CI任务才上传对应产物，开发产物暂存期较短。原生二进制必须与同次完整对应源码、依赖源码和许可证一并保留。私有签名密钥、订阅与凭据不进入源码或公开产物。

所有版本均不自动修改防火墙、系统代理、DNS、VPN或开机服务。配置Portal前先确认自己的地址、允许客户端和可信订阅；不要公开监听给不可信网络。
