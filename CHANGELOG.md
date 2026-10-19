# Changelog

## Unreleased — 2026-10-19：Windows 原生验证与控制通道修复

- 修复 Windows 传统编码下中文、表情节点名称在桌面与后台之间解码失败或乱码的问题；桌面私有管道固定使用 UTF-8，普通 CLI 保留用户输出编码。
- 控制输入出现无效编码或管道错误时，后台结束监听并清理核心、锁和会话，避免只退出读取线程后遗留服务。
- 在 Windows 11 x64 上重建外部核心模式程序并执行 323 项回归：282 通过、41 项按平台/可选运行条件跳过；覆盖真实 Tk 窗口、真实 Mihomo、打包程序与中文节点切换。详见 [Windows 验证记录](portable/docs/windows-validation-2026-10-19.md)，不替代 Portal/PS5 真机验收。

## Unreleased — 2026-10-19：跨平台对齐整合

- 在最新 `72b23e4` 基础上整合 Android v3 简洁界面、桌面实时控制及受限状态通道，保留用户新加入的 iOS 页面、移动端仅订阅范围和后台限制说明
- 保留 Windows 测试环境建模、许可证字节保护及 macOS HTTPS 信任根修复；不覆盖 Apple 应用与启动器文件
- 整合后 portable 回归 318 项：296 通过、22 项明确的图形/打包/平台条件跳过，启用真实 Mihomo；涵盖双控制协议、既有隧道保留、组偏好与空闲恢复
- 原生全部包与 race 回归通过，重新生成 Objective-C/Java 绑定；8 项未修改的 iOS 源码守卫通过。Android 168 项 JVM 断言和隐私/结构守卫通过
- 修复外部核心先监听、后进入转发状态的就绪竞态：使用私有目录中固定命令与随机十六进制标记确认 Mihomo post-up 完成，不重放用户请求
- `9c4515f` 的 Windows/macOS/Linux 统一桌面打包与严格来源门禁通过，Android 未签名 APK 构建与审计通过；Linux 318 项测试中 5 项条件跳过，并生成七张真实窗口、离线合成数据截图
- 修正原生可执行文件验收对新状态字段的旧断言：必须同时满足监听器 `listening`、核心 `stopped`、空节点及零外连/唤醒/转发计数；新增五项反例回归，实际 Linux 二进制验证通过。六目标 CI 和 iOS 检查仍待完成，不将已有构建视为真机验收

## Unreleased — 2026-10-19：iOS 共享、节点与设备面板

- iPhone/iPad 新增共享、节点、设备三页，突出监听与实际设备接入状态，支持中英文即时切换。
- 内置适配器池新增显式载入、手动选择、延迟测试和最低延迟自动路由；手动退出自动模式，失败测速不切换选择，后台停止可取消进行中的操作。
- 原生代理按来源 IP 统计设备与连接，记录保留五分钟且停止清空；活动连接改用监听器统计，避免遗漏局域网直连。
- 真实 XCFramework 和 SwiftUI 应用重建；Go 核心通过 race 检查，iOS Simulator 21 项中 20 通过、1 项硬件检查跳过。未宣称真机热点或完整 Clash 规则支持。

## Unreleased — 2026-10-19：设备反馈、节点控制与打包修复整合

- 首页突出启动、等待设备和使用中状态；设备页按来源 IP 去重显示活跃数、连接数及最近五分钟接入记录。
- 独立订阅的外部核心支持逐组手动切换、延迟测试、周期性最低延迟选择；全部失败保留现有选择，手动选择关闭自动策略，休眠时不主动唤醒。
- 关联 Clash 时节点控制禁用，原客户端继续管理节点；内嵌实验模式与移动端保留原能力。
- 整合 `0980a75` 的跨平台发现及 YAML 完整来源、源码和许可审计；修复 Linux sysfs 规范化路径比较，并支持 JSON 转义的国旗节点名称。
- 修复 Windows 测试环境变量大小写建模及许可证 CRLF 改写；补齐搬迁 macOS Python 的系统 CA 回退，保留证书和域名验证及用户证书覆盖。
- 本机完整桌面回归 247 项：238 通过、9 跳过；许可证脚本 9 项通过；公开 HTTPS 下载及精确 YAML 来源校验通过。云端旧打包失败和本轮状态见 `GITHUB-STATUS.md`。

## Unreleased — 2026-10-18：跨平台界面对齐

### 已有功能基线（PR #4，49a8467）

- 简洁中文默认首页，运行中切换中英文及深浅主题；订阅准备入口与局域网接入说明
- 直接导入订阅与复用现有回环 HTTP 代理分离；关联 Clash 时节点仍由原客户端管理
- 展示订阅响应头提供的套餐用量和到期信息；Clash 本地套餐缓存明确标记为只读、非实时
- 保留用户已经完成的 macOS 启动器、桌面设计及 iOS 网络/前台生命周期实现

### 本轮新增（已完成源码及单元验证）

- Windows/Linux 简洁流程可只读识别物理局域网接口、真实掩码及默认路由，生成受限设备名单；VPN、策略路由、歧义及不支持网段转入高级设置
- Windows 当前用户手动 HTTP 代理、Linux 明确配置的本地 HTTP 代理可复用；拒绝带凭据、远端地址和 PAC，不调用原客户端控制器
- 按 Clash Verge 的标准 Windows/Linux 数据目录只读读取当前套餐缓存，不递归搜索或导出订阅地址/令牌

- 桌面保留 Mac 简洁首页，新增实际监听地址、准备/监听/唤醒/转发/错误状态；按来源 IP 去重的活跃设备数与 TCP 连接数分开显示
- 直接订阅支持在线准备、测速、手动节点切换与 `fastest`；健康节点切换须满足延迟差、连续两轮和 30 秒保持期，空闲核心不因定时测速唤醒
- 完整 profile 使用明确选定的自有策略组进行控制，保留原规则；关联已有 Clash 时继续委托原客户端管理节点
- 精确核对 PyYAML wheel、17 个 Python 模块与原生扩展来源；补齐 LibYAML 许可证、SHA 固定源码及归档校验。Windows 原生文件数按来源逐项审计，Linux 独立核对 PyYAML，不降低原有门禁
- 原生许可证采集覆盖 10 个 OS/架构目标，91 个生产依赖均具备许可证；图中非生产测试依赖记录到明确排除清单

- Android v3 采用中文默认深色简洁首页、即时中英文/主题切换、一键准备、套餐信息和真实原生节点控制；保留前台通知、停止及网络丢失清理。订阅输入在单行设置后显式恢复密码掩码

### 本轮验证状态

- 已从 GitHub 的上述精确提交重新建立独立开发分支，不恢复或混入此前遗失的重构快照
- 此环境基线 portable 回归共 202 项，21 项因对应平台、图形环境或外部二进制未启用而跳过，其余通过
- 2026-10-18 独立冻结版 portable 回归共 285 项，20 项因平台/图形/外部产物条件跳过，其余通过；真实 Mihomo 的 2 项回环 fixture 通过，包括实时节点切换保持已有隧道、HTTP/CONNECT 与空闲回收
- Windows/Linux 网络准备的 25 项受控解析测试通过；实际 Windows/Linux 网络接口仍待验收
- 本地 Linux/Python 3.12 冻结构建、YAML/Tcl、源码归档字节校验、启动/重启通过；Windows、Debian 3.13 和 macOS 的精确发行审计及图形 CI 尚待完成
- 原生 Go 全部包通过带 race 检测的回归，覆盖取消/停止、固定节点启动期限、已有流保持、去重设备统计及最大节点列表状态；保留 iOS 原 Status 接口语义
- Android v3 简洁界面、主题/语言、套餐信息及实时控制已通过 168 项 JVM 断言、真实 API36/当前生成绑定的 Java 编译和 aapt2 资源链接；新版 AAR/APK、设备 UI 仍待验收
- 历史 Mac/iOS 验证与真实设备反馈见 `VALIDATION-LOCAL.md`；不能用于替代本轮新代码及独立发行包验证

本轮完成项目和对应平台证据将随实现更新。HTTP/CONNECT 共享不等同于任意 UDP 游戏代理；不更改系统代理、DNS、VPN 或防火墙。

## Unreleased: subscription and node preferences

- Persist auto/preferred/fixed intent independently, with exact-name filters and explicit REJECT sentinel
- Add optional authenticated legacy LuCI controls, root CLI and cache-only node status
- Resolve actual terminal nodes before readiness, with fixed-name equality and no direct terminal
- Explicit bounded/pinned HTTPS subscription fetch replaces automatic HTTP provider; live file reload can change routes
- Mock-only verification; actual OpenWrt/Mihomo/LuCI acceptance and deployment remain separate

## Unreleased

- Keep the listener responsive during core startup with a bounded readiness worker and queued external requests.
- Start the idle budget after readiness; retry failed startup and backend connection attempts without dropping LAN sessions.
- Deny loopback and special-use destinations, validate numeric/IPv6 authorities, and prevent backend DNS resolution from selecting private DIRECT routes.
- Preserve explicit RFC1918/ULA LAN access; document removed CGNAT/link-local compatibility and router-LAN management exposure.
- Add isolated listener, lifecycle, destination, and DNS regression coverage. Real OpenWrt/Mihomo acceptance remains a separate deployment check.

## 0.1.0

- Initial public source release with an explicit, single-client HTTP proxy listener.
- On-demand independent Mihomo core, private-address bypass, external idle shutdown.
- Own-subscription fallback order: Hong Kong, Japan, other regions.
- Interactive setup, staged installation, local private backups, and uninstall.
- English and Simplified Chinese setup guides; offline protocol and lifecycle tests.
