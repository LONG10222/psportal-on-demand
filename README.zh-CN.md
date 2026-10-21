<div align="center">
  <img src="native/android/app/src/main/res/mipmap-xhdpi/ic_launcher.png" width="72" alt="StarPass" />
  <h1>星渡 StarPass</h1>
  <p>给手机和局域网设备使用的按需代理。</p>
  <p><a href="#下载">下载</a> · <a href="#快速开始">快速开始</a> · <a href="docs/README.en.md">English</a> · <a href="https://github.com/LONG10222/psportal-on-demand/issues">反馈问题</a></p>
</div>

## 下载

- **[已归档测试包](https://github.com/LONG10222/psportal-on-demand/releases)**：Windows、macOS、Linux、Android 与 iOS 模拟器产物。
- **[当前分支构建](https://github.com/LONG10222/psportal-on-demand/actions)**：精简版 Android 界面由当前 PR 构建。旧版 `c1d2d3a` 归档不含这次界面更新。
- [选择版本与安装](docs/downloads.zh-CN.md)。Android CI 原始 APK 未签名；iOS 设备版需要自行签名，模拟器包不能装到手机。

## 功能

- **按需运行**：外部请求唤醒核心，空闲后回收。
- **手机或设备共享**：Android 内置 Mihomo；电脑可独立运行或复用已有 Clash。
- **节点与状态**：查看实际连接、选择支持的节点/策略组并测速。
- **清爽界面**：Android 分为概览、节点、共享、设置，操作说明按需展开。

| 平台 | 入口 | 使用说明 |
| --- | --- | --- |
| Android | 手机代理、局域网共享 | [Android](native/android/README.md) |
| Windows / macOS / Linux | 独立代理、Clash 联动 | [桌面](portable/docs/desktop.md) |
| iPhone / iPad | 前台设备共享 | [iOS](native/ios/README.md) |
| OpenWrt / iStoreOS | 独立运行、OpenClash 联动 | [路由器](docs/router-readme.zh-CN.md) |

## 快速开始

### Android

1. 安装匹配设备的测试 APK，在概览填写 HTTPS 订阅。
2. 选择用途与分流方式，点击 **连接**；本机代理按系统提示申请 VPN 授权。
3. 给其他设备共享时，打开 **共享** 查看地址，在设备 Wi-Fi 中设置手动 HTTP 代理。

**游戏**只共享给局域网设备；**混合**同时代理手机；**Clash**只代理手机。节点操作在“节点”，后台运行与网络修复在“设置”，详细说明在右上角“帮助”。

### 电脑

粘贴一次导入订阅，再点击 **启动共享**。也可直接复用已有 Clash 的代理入口；联动时节点与核心仍由原客户端管理。Windows 默认自动选择 Mihomo，其他系统和实验引擎的准备方式见[桌面指南](portable/docs/desktop.md)。

## 使用须知

局域网共享是 HTTP/HTTPS CONNECT TCP，不能保证任意游戏 UDP 或串流可用。只在可信局域网使用；结束后关闭设备的手动代理。Android 本机代理需要系统 VPN 授权；iOS 默认切后台即停止。更多能力差异见[平台对照](docs/starpass-platform-modes.zh-CN.md)。

## 文档与开发

[Android 构建](native/android/README.md#build) · [桌面源码](portable/README.md) · [原生引擎](native/README.md) · [验证记录](VALIDATION-LOCAL.md) · [安全反馈](SECURITY.md) · [更新日志](CHANGELOG.md)

构建通过、模拟器测试与真机网络验收分别记录，不用旧版测试数字代替当前提交结果。详细能力和历史记录移至[平台参考](docs/platform-reference.zh-CN.md)。

## 开源与致谢

界面信息组织参考 [Clash Meta for Android](https://github.com/MetaCubeX/ClashMetaForAndroid)；文档结构参考 [Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev) 和 [v2rayNG](https://github.com/2dust/v2rayNG)。保留星渡原有角色与图标。

路由器与桌面包装层采用 [MIT](LICENSE)；链接 Mihomo 的原生引擎/Android 应用采用 [GPL-3.0-only](native/LICENSE)。分发时保留匹配源码和依赖许可证。
