# Changelog

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

### 本轮验证状态

- 已从 GitHub 的上述精确提交重新建立独立开发分支，不恢复或混入此前遗失的重构快照
- 此环境基线 portable 回归共 202 项，21 项因对应平台、图形环境或外部二进制未启用而跳过，其余通过
- Windows/Linux 网络准备的 25 项受控解析测试通过，但真实主机网络仍待验收；Android 简洁界面、实时设备/节点控制以及 PyYAML 分发审计正在补齐；尚不代表这些平台已经验收通过
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
