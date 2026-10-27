## 0.4.3 — 各模式实时流量

- 加速器页面显示独立入口的上传、下载、累计流量和实际出口；游戏与星渡读取共享入口。
- 所有模式按目的地址区分局域网与外网。速率按两次页面采样之间的字节差计算，空闲归零；入口重启或状态过期重新采样。
- 页面每两秒刷新，活动方向高亮。只更新展示，无需重启加速器或改动路由配置。

## 0.4.2 — 空闲加速器升级

- 未运行加速会话时，升级不再要求鲜牛账号有效；不操作其他客户端的账户计时。
- 本机正在运行的付费会话仍须停止并确认暂停后才安装。

## 0.4.1 — 官方附件下载兼容

- 在线安装优先使用 GitHub 官方附件 API，同一 CDN 下载，网页下载域名超时可自动回退重试。
- 分别显示检查、下载校验和安装阶段的错误；不启用代理、不引入镜像源。

## 0.4.0 — 路由器订阅、流量与在线更新

- 游戏、星渡页面显示公网/局域网上传下载速度及入口累计流量，统计本身不唤醒核心。
- 显示订阅账户用量、剩余量、到期日期和剩余天数，手动刷新，失败保留上次数据。
- 右上角检查正式路由器版本并一键下载安装，校验配套 IPK 后备份、预检、覆盖升级，保留配置和备注。

## 2026-10-21 — 全平台升级入口与失败恢复（开发候选）

- 保留最新 Android 四页界面及已验证更新功能，修复 universal APK 对不支持的 32 位设备误匹配，以及安装前复检失败后的按钮状态。
- Windows/macOS/Linux 共享用户主动检查与完整包校验下载，独立桌面版本/架构选择；不自动执行、替换程序或覆盖配置。窄窗口保留可滚动更新说明，长保存路径不挤掉操作。
- iOS 设置显示实际版本和官方更新入口，LuCI 增只读更新说明；不虚构 IPA 安装或路由器自动下载。
- 路由器更新先预检/暂存，扩大完整本地备份并在文件写入失败时恢复；失败保持服务停止供人工核查，断电恢复仍有边界。
- 现有测试归档不变，正式更新通道仍需单独签名和发布验收。实际测试及平台限制见本次验证记录。

## 2026-10-21 — Android 界面精简

## 2026-10-21 Android Settings updates

- Settings now checks stable GitHub releases, selects the device APK and downloads with progress.
- Verify digest, size, package, newer version and current signer before opening the Android installer; active connections must stop first.
- Keep CI unsigned and document the signed-release contract; no production key is generated or uploaded.

- 概览、节点、共享、设置四页导航；首页保留状态、订阅、用途、分流和单一连接/停止操作。
- 协议、VPN、后台与排障说明移入帮助；空套餐数据和未启用 VPN 状态默认隐藏，共享地址只在监听就绪后显示。
- 设置保留原网络开关、修复、外观与高级选项；原角色图放入关于，导航不改变订阅或会话。
- README 改为下载、功能、快速开始和文档入口；详细平台/路由器参考独立保留，区分旧归档和当前界面构建。

# Integration test candidate (2026-10-20)

- Combine Android validation and shared desktop workflow updates without changing native Apple work or anime artwork.
- Fix frozen UI selectors, macOS temporary-path compatibility, and exact Windows runtime provenance.
- Wire pinned Windows default Mihomo plus full corresponding dependency source into audited unified builds.
- Run all platform workflows against the exact integration head; retain unsigned/real-device acceptance boundaries.

## 2026-10-20 — Windows 订阅流程与模式约束修复

- 粘贴一次导入并保存，启动共享独立；重复链接去重，显式刷新才下载。失败保留此前订阅，导入不变更网络或自动启动。
- 普通首页默认 Mihomo，不要求选择文件；Windows 包可随附固定版本核心、匹配上游源码及许可证，缺少核心时点击启动自动准备与校验，失败可直接重试。
- 联动已有 Clash 只允许游戏模式，混合/Clash 置灰，配置与启动双重校验；取消联动恢复原订阅与模式，不接管原客户端核心。
- 区分直接订阅统计与 Clash 套餐缓存；就绪后才提供共享地址，保留可见启动入口并适应较小窗口。
- Windows 子进程管道固定 UTF-8，异常/非法输入关闭后回收监听与锁；网络识别不弹出控制台窗口。问题跟踪 #19。

## 2026-10-20 — Anime star-sea navigator (draft)

- Give desktop (Windows/macOS/Linux), Android, iOS and LuCI a visible anime navigator hero using the original approved character, not a replacement app icon.
- Unify restrained blue-violet surfaces with static native/CSS star trails; no downloaded artwork, animation, timers or new permissions.
- Keep setup/start controls readable and separate from decorative artwork; adapt native mobile hero layouts for narrow screens and large text.
- Preserve connection, privacy, networking, Apple lifecycle and game-mode boundaries. Build checks and offline fixture screenshots do not establish real-device or network acceptance.

## 2026-10-20 — Cross-platform visual clarity (draft)

- Extend the shared desktop slate/blue visual language to native Android and iOS without copying desktop controls or changing the approved artwork.
- Prioritize subscription and start actions, separate setup from runtime status, and adapt mode controls/headings/metrics for narrow displays and larger text.
- Add a scoped light/dark LuCI three-step guide, package its read-only template, and preserve the router's explicit apply and OpenClash boundaries.
- Preserve privacy masks, Android screenshot protection, native Apple lifecycle, network permissions, and all existing game-mode capability limits.
- Source checks and CI builds are separate from physical-device testing; listener/connection status does not prove Internet access or game compatibility.

## 2026-10-20 — Desktop visual clarity (draft)

- Refine shared Windows/macOS/Linux desktop colors, spacing and hierarchy with a restrained navy/slate dark theme and a legible light theme.
- Prefer available Chinese-capable UI fonts per host; keep the approved character artwork unchanged.
- Label the private HTTPS subscription field, emphasize the primary start action, and separate optional client/core tools from the main path.
- Give service status and the next action a distinct heading; preserve all preparation, connection, failure and capability messages.
- Theme the scrollbar and verify compact 1040×740 Chinese/light and English/dark windows alongside the existing runtime screenshots.
- No engine, subscription, system proxy, firewall, game UDP, routing or native Apple behavior changes. Screenshots use offline fixture data, not live network measurements.

## 2026-10-20 · 新手引导与统一游戏模式说明

- 桌面首页新增只读“使用前检查”和可信核心选择入口，解释首次订阅/核心缺失；不开网络、不改配置、不下载核心。
- 按启动服务、设备接入、设备侧验证给出下一步，连接数不等同外网或游戏 UDP 成功；退出前提醒移除设备代理。
- Android、iOS 与路由器界面统一可见游戏模式定义，沿用实际权限与接入行为，不重写 Apple 后台代码或加入无效模式。
- 新增前置检查、状态引导、翻译与真实窗口按钮回归。全平台构建结果以本提交 Actions 为准，真机仍待验收。

# Changelog

## Unreleased — 2026-10-20：路由器连接恢复与会话状态修正

- 独立与 OpenClash 联动入口在客户端、LAN 上游和代理上游读写收到 EINTR 时保留缓冲区，等待下一次事件重试，避免临时信号导致连接误断
- 非空缓冲区发送返回零字节时及时关闭两端，避免 LAN 连接长期占据最多 32 个接入槽；真正错误仍关闭，不改变半关闭与流量空闲策略
- OpenClash 首次就绪失败不再误报会话活跃或增加空闲回收计数；重试失败时保留已有会话的空闲清理责任，仍不启停 OpenClash
- 新增 11 个模拟生命周期场景，共 869 项断言；全套路由器回归、9 项安装/打包测试、12 项品牌测试及 43 项资源校验通过。模拟测试不替代真实固件、实体设备或后台权限验收
- 继承全平台人物图标与 Apple 端工作，仅修改路由器运行时、对应测试和说明

## Unreleased — 2026-10-20：人物轮廓图标整包更新

- Android、iOS 与桌面图标统一更新为已选定的黑白人物轮廓版本；保留生成原图和角色启发创作的来源说明，不表示官方授权或联名
- 原始 RGB PNG、43 项平台资源、确定性尺寸／格式生成脚本与哈希清单随源码保留；新增资源继续接受像素、容器、源码归档和打包门禁检查
- 本次只调整品牌资源与必要说明，不更改运行时、应用标识或许可；保留 OpenClash 路由器联动及 iOS SDK26 编译门禁。真机启动器外观与安装验收仍需单独验证

## Unreleased — 2026-10-19：iStoreOS / OpenClash 只读联动

- 新增显式 `core_mode=openclash`；保留独立 Mihomo 按需启动/空闲关闭，联动仅管理自己的入口和会话，不启停外部核心
- 只读使用有效 UCI 覆盖层发现 HTTP/mixed/controller 端口；回环认证、运行端口漂移、代理认证豁免和冲突检查有界且不泄露密钥
- OpenClash 模式/任意策略组只读快照，不假设 PORTAL 组，不捏造实际出口或游戏延迟；可选节点列表失败不阻断已验证入口
- 严格解析的公开域名 fake-IP 回答转交原域名；字面假地址、本地域名、危险回答及畸形包仍拒绝
- `--openclash` 无核心安装，配置保留；LuCI/CLI 明确模式、保存/应用与外部管理边界，独立订阅操作在联动时拒绝
- 新增可重复源码包/校验清单和 GitHub Actions 产物；模拟/暂存测试不等于 iStoreOS/OpenWrt 实机、IPK/APK 或游戏 UDP 支持
- 同步主 README 的 Android 面板、iOS 四页/有界后台实验及平台矩阵，不改客户端源码、Apple 工作或图标
- [详细行为、安装与未验证范围](docs/openclash-linked.zh-CN.md)

## Unreleased — 2026-10-19：最新上传构建校验

- 以最新 iOS 四页界面和限时后台实验为基线，保留用户更新
- 修正 Windows 品牌源码 UTF-8 读取测试；增加非 UTF-8 默认编码回归
- macOS 仅增加实际观察到的图标目录链接，并严格核对所有品牌资源文件及哈希
- 品牌检查准确接受有界 processing 实验，继续验证默认关闭与系统授权边界
- 修复依赖下载失败时遗漏 Go JSON stdout 诊断；仅识别明确瞬态错误作最多三次重试，校验／权限错误仍立即失败
- iOS 队列测试使用独立高优先级测试队列及十秒有界回调等待；门闩超时必须失败，不改变运行时生命周期或后台授权
- 增加真实限时后台驱动的 iOS26 SDK 独立编译矩阵，验证 iPhoneOS/Simulator 目标及实现符号；保留旧 SDK 完整 app 流程，不将编译当作真机后台授权
- 人物轮廓图标整包替换另行提交；本次保持现有资源清单一致

## Unreleased — 2026-10-20：iOS 限时后台实验

- 增加 iOS 26+ 真实持续后台任务适配，15/30/60 分钟主动开启；仅实际授权后继续，拒绝和等待仍为前台运行。
- 到期／系统取消停止，无排队、重试、续期或返回前台自启动；默认关闭，意图不落盘，文件保护保留。
- 模拟器与旧 SDK 明确不可用；本地 38 项 XCTest 中 37 通过、1 项硬件检查跳过，源码守卫 8 项通过。模拟驱动测试不代表真实系统授权，真机后台和锁屏联网未验证。

## Unreleased — 2026-10-20：iOS 四页设计

- 整合 StarPass 品牌及 Apple 网络／会话修复，保留项目与签名标识。
- 手机界面改为共享、节点、设备、设置四页；首页突出订阅导入、启停与真实状态，连接指南按三步展开。
- 节点增加本地搜索、可用筛选、延迟排序与明确的选中态；设备空状态提供下一步操作。
- 设置与长说明移出首页；保存／校验结果在设置页反馈，中文／English 和深浅色即时切换。
- 真实 XCFramework 重建；iOS Simulator 33 项中 32 通过、1 项硬件检查跳过；Go engine/mobile race 检查通过。iPhone 13 mini 窄屏和滚动指引已实际检查。
- 本轮不增加后台常驻、完整 iOS VPN 或 UDP 能力；桌面上游 CI 失败单独记录，不将 UI 验证作为发行验收。

## Unreleased — 2026-10-19：星渡 StarPass 三用途与平台对齐

- 对外名称更新为「星渡 StarPass」，采用简化黑白星形通道图标；保留项目来源、仓库、程序与签名标识。原始图、确定性尺寸生成脚本及平台图标随对应源码分发
- 新增游戏／混合／Clash 三种用途选择，与规则／全局／直连分流模式分开。桌面分别限制为局域网设备、局域网设备与本机手动配置的应用、仅 127.0.0.1；Android 分别映射为 LAN、LAN＋本机 VPN、仅本机 VPN
- 本机 VPN 仍需要 Android 系统授权且默认关闭，不以模式名称代替权限；桌面不自动设置系统代理或 VPN。iOS 明示仅前台解锁的局域网 HTTP/CONNECT 共享，不增加无效的完整 Clash 或混合开关
- Android 完整内联订阅的 select 策略组可读取真实成员并手动切换；自动测速／回退／负载均衡组继续按原订阅工作。原生层再次检查成员资格、活动连接与本机 VPN 状态，操作与弹窗绑定当前会话；选择在本次空闲唤醒后恢复，停止后清空
- 修复后台健康检查与手动策略组选择之间的 Mihomo selector 竞争；保留精确上游源码、补丁及并发回归，不放宽网络准入边界
- 修复桌面 provider 已保存的固定／最快节点策略恢复后，后续测速重新应用旧自动策略的问题；Windows、macOS、Linux 共用该修复。完整 profile 多组偏好保持隔离
- 模式切换保留已验证本地订阅与节点偏好；明确的自动 LAN 来源才随网络更新，旧／手动白名单不按形状猜测并扩大；准备失败、取消和关闭时恢复未成功运行的变更
- Android 显示真实套餐快照获取时间、未测得延迟不显示为 65535 ms，刷新可见网络标签，并将载入与测速按钮语义分清
- 所有实际构建、打包、源码与运行时结果以本提交工作流为准；未使用真实用户订阅、签名密钥或修改主机网络设置。未合并 main，仍需真机热点、Portal、VPN、签名安装和长期后台验收


## Unreleased — 2026-10-19：macOS / iOS 网络与会话修复

- iOS 网络观察使用本次发布的新快照，并由模型持有观察；修复断网／地址变化时读到旧值、遗漏停止的问题。多物理网卡或多个热点接口不再按枚举顺序猜测
- iOS 节点操作与套餐读取绑定当前会话；停止先取消原生请求，再等待已进入的操作退出，避免旧操作跨重启修改新会话。套餐请求共享核心取消上下文，后台／停止可取消正在进行的 HEAD/GET
- 套餐信息明确显示获取时间与“服务器快照 · 非实时”；失败或无字段不伪装为新快照，清除配置同时清除快照；重复停止不重新申请已到期的后台清理时间
- macOS 仅使用确认活跃且唯一的默认路由物理网卡；无路由、VPN、停用网卡、地址歧义转入手动设置。系统代理只解析 scutil 全局字段，避免被嵌套作用域覆盖，并拒绝 PAC/WPAD 歧义
- 桌面一键准备在网络／端口／导入失败时保留原有的关联代理与手动配置，配置确认后再提交变更
- 增补确定性队列、网络快照、取消边界与 macOS 解析／交互回归；保留用户 Apple 页面、启动器、Android 实现及既有修复。实际 Apple 编译、模拟器和打包结果以本提交 CI 为准；未声称真机热点、后台持续共享、签名安装或游戏机验收


## Unreleased — 2026-10-19：重复启动与多策略组恢复修复

- 修复 Android 核心仍在异步启动时重复点击启动，会因服务命令编号变化而跳过本机 VPN 启动的问题；以会话代际验证完成回调，停止／重启后的旧回调仍不得启动新 VPN
- 修复桌面恢复多个订阅策略组时，最后一个组的节点偏好污染当前组，后续测速可能将当前组切到错误节点的问题；保持各组偏好与最快节点策略隔离
- 同步 Android 内置简版许可说明与实际 Mihomo 本地补丁来源；构建时刷新，并在 APK 审计中按字节核对，避免发布旧说明
- 保留既有手机 VPN 私有地址边界、macOS/iOS 专用源码与签名限制；本轮不修改系统网络设置，不合并主分支
- 新增回归先复现后修复；本轮本地 JVM 共 243 项断言、17 项编译清单／许可资产测试、17 项源码／许可／补丁测试、6 项仓库打包检查通过。portable 共 322 项测试，293 通过、29 项明确环境条件跳过；真实 Android 服务投递、TUN、安装及设备行为不由这些主机测试证明，实际构建结果以本提交 CI 为准


## Unreleased — Android v4 单应用内核与可选本机代理

- Android 改用独立的完整 Mihomo 路由入口，保留现有桌面与 iOS 入口；不需要关联外部 Clash
- 局域网共享、本机应用 VPN、后台继续运行独立选择；默认保持局域网共享、本机 VPN 关闭，两项网络入口均关闭时禁止启动
- 规则／全局／直连模式作用于所选入口；VPN 使用 Android 系统授权，VPN-only 不开放 LAN 监听
- 订阅经过受限配置验证；完整配置自有策略组与生成节点组明确区分，不承诺全部上游配置特性
- 源码验证通过 229 项 JVM 断言、36 组 Java 到真实 Android Go 配置解析、17 项源码／许可证／上游补丁回归、10 项编译清单解析回归；32 项 Android 核心测试以 race 重复三次，涵盖真实 TCP 模式、SOCKS5 UDP 数据帧、DNS 规则、取消与停止／重启。APK、源码归档及对齐审计以本提交 CI 为准，不能沿用旧版本结果
- 修复实际 race 与停止／重启测试发现的上游并发和嵌入生命周期问题：保留完整 v1.19.32 源码、许可、精确补丁及复现回归；不屏蔽 race 检查
- 原开发签名密钥不可用；不生成替代身份，不宣称已签名安装、升级兼容或真机后台稳定运行

## Unreleased — 2026-10-19：跨平台对齐整合

- 修复 Windows 异步读取在上游 EOF 后仍等到空闲超时的问题：主动取消读取、保留写方向与原设备计数规则；两项确定性回归先复现后通过，六项相关测试重复 100 次、race 重复 20 次及全部 native race 通过。随后 `a0dcf233` 的实际 Windows ARM64 CI 执行已通过

- 在最新 `72b23e4` 基础上整合 Android v3 简洁界面、桌面实时控制及受限状态通道，保留用户新加入的 iOS 页面、移动端仅订阅范围和后台限制说明
- 保留 Windows 测试环境建模、许可证字节保护及 macOS HTTPS 信任根修复；不覆盖 Apple 应用与启动器文件
- 整合后 portable 回归 318 项：296 通过、22 项明确的图形/打包/平台条件跳过，启用真实 Mihomo；涵盖双控制协议、既有隧道保留、组偏好与空闲恢复
- 原生全部包与 race 回归通过，重新生成 Objective-C/Java 绑定；8 项未修改的 iOS 源码守卫通过。Android 168 项 JVM 断言和隐私/结构守卫通过
- 修复外部核心先监听、后进入转发状态的就绪竞态：使用私有目录中固定命令与随机十六进制标记确认 Mihomo post-up 完成，不重放用户请求
- `9c4515f` 的 Windows/macOS/Linux 统一桌面打包与严格来源门禁通过，Android 未签名 APK 构建与审计通过；Linux 318 项测试中 5 项条件跳过，并生成七张真实窗口、离线合成数据截图
- 修正原生可执行文件验收对新状态字段的旧断言：必须同时满足监听器 `listening`、核心 `stopped`、空节点及零外连/唤醒/转发计数；新增五项反例回归，实际 Linux 二进制验证通过。随后 `a0dcf233` 的六项工作流全部通过，包括六目标 native、Android 未签名构建和 iOS 模拟器；不等同真机验收

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
