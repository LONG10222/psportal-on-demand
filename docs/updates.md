# 应用更新

各平台采用相同的“确认来源 → 匹配平台 → 验证完整性 → 保留配置”原则，但安装方式遵守系统限制。Android 支持设置内检查与安装确认；Windows/macOS/Linux 支持检查与校验下载完整包后手动切换；iOS 提供更新指引，opkg 路由器支持页面内升级，不伪装成自动安装。应用包内已随附的核心跟随对应完整包；macOS/Linux 另行配置的外部核心及已有 Clash 不由应用更新器接管。

## 安卓

在 **设置 → 应用更新** 检查正式版本，查看更新内容后下载。页面显示进度；完成校验后点 **安装更新**，由 Android 系统确认覆盖安装。首次使用时，按提示允许星渡安装应用，再返回点安装。更新保留应用配置。连接运行中可以检查和下载，安装前需要停止连接。

从本项目最近 100 个 GitHub Releases 中选择版本号最高的适用正式 APK，跳过草稿和预发布。没有正式发布包时会明确显示“尚未发布正式更新”；网络失败不会显示“已经是最新版”。下载失败可重试；离开页面取消网络任务，已完整验证的下载可在下次检查后复用。首次安装带更新功能的版本仍需手动安装一次。

安装前核对 SHA-256、包名、新版本号、设备最低系统要求及当前签名证书。更换签名的包会被拒绝；不要通过卸载应用来解决签名不匹配，否则会丢失配置。普通应用不能绕过 Android 的安装确认。

## 发布维护

目前仓库 CI 产物仍为 **unsigned**，现有归档为测试预发布，均不进入正式更新通道。发布者需要用固定、备份妥当的私有签名密钥签署 APK；不要上传私钥、口令或 keystore 到源码或 Release。当前本机验证包使用开发签名，不应宣称为正式生产签名。未配置自动签名发布流水线。

每次发行递增 `native/android/app/build.gradle` 的 `versionCode`，同步 APK 审计及版本测试。正式 Release 中上传已经签名的独立 APK，文件名必须为：

```
StarPass-Android-<versionCode>-arm64-v8a.apk
StarPass-Android-<versionCode>-x86_64.apk
StarPass-Android-<versionCode>-universal.apk
```

例如 `StarPass-Android-6-universal.apk`。文件名版本号必须与 APK 内一致。可仅发布通用包，也可发布按架构拆分的包；客户端优先选择设备首选架构，再回退通用包。GitHub API 的附件 `digest` 必须提供 `sha256:` 校验值。下载仅允许 GitHub 官方 HTTPS 发布地址与其附件域名，不引入第三方镜像。Release 正文用简短列表写明本版变化，并附对应源码、依赖许可证和构建来源。

先上传完整附件并验证签名/覆盖安装，再将 Release 从草稿发布为正式版。不要将现有 unsigned ZIP 归档标为正式版，客户端只接收已签名的独立 APK。版本号不会在 Windows 与 Android 间比较。

## Windows / macOS / Linux

进入 **设置 → 应用更新 → 检查更新**。只在用户点击后联网，不启动后台更新定时器。检查最近 100 个 Release 内适用的正式桌面包，按桌面三段版本号选择，Windows、macOS、Linux 及 Android 的发行互不遮蔽。当前没有正式桌面更新包；旧 `c1d2d3a` 测试预发布不进入此通道。网络失败会显示失败，不显示“已经是最新版”。

点击 **下载校验包** 后选择新文件路径，程序验证固定项目 HTTPS 来源、附件长度和 SHA-256；失败清理临时下载，不覆盖现有文件、运行中的程序或用户配置。下载完成仅表示“包已验证”，不等于安装成功。此版本不自动解压、执行或替换程序；不绕过系统安全提示。

1. 正常停止本应用连接并退出，保留旧程序目录及配置备份。
2. 将完整新包解压到不同目录，保留配套源码与许可证，不混用旧版运行库。
3. 使用原来的用户配置位置；若此前显式指定配置路径，继续指定该路径。不要把新包示例配置覆盖到旧配置。
4. 验证新版本启动、配置与基本连接，再决定是否移除旧包。新包无法启动时可恢复旧程序，但若未来版本迁移配置格式，应按该版说明恢复兼容的备份，不能保证任意降级。

### 桌面正式发布契约

发布者递增 `portable/portalproxy/__init__.py` 的 `__version__`，并在独立完整包名称中使用相同版本。当前开发源码仍为 `0.1.0`；提交变化不冒充正式版本递增。附件名为：

- `StarPass-Desktop-<major.minor.patch>-Windows-<x64|arm64>.zip`
- `StarPass-Desktop-<major.minor.patch>-macOS-<x64|arm64|universal>.tar.gz`
- `StarPass-Desktop-<major.minor.patch>-Linux-<x64|arm64>.tar.gz`

仅发布实际构建、测试的架构；名称不能把未验证的 x64 包伪装成 ARM64。macOS universal 包需真实含双架构，否则不要使用此名称。客户端在相同版本优先原生架构，macOS 才允许 universal 回退。GitHub 附件 `digest` 必须为 SHA-256，长度和状态必须有效。附件只接受本项目发布地址及 GitHub 官方附件域名。

这些是未来正式包命名规则，不重命名或覆盖已有历史归档。CI 当前输出仍是开发测试产物，不能仅为让更新器检测到就把 unsigned 归档改成正式版。每个完整包必须带匹配源码、许可证及构建来源；签名、公证和真实升级验收单独完成。SHA-256 是下载完整性校验，不代替系统签名信任。

## iPhone / iPad

设置页 **应用更新** 显示本机实际版本和官方 Releases 入口，明确没有执行在线版本检查。iOS 不运行下载的安装程序，也不会把未签名设备构建或模拟器包称为可安装 IPA。当前仍需通过自己原有、可信的签名安装流程更新；未来如采用商店或 TestFlight，以对应系统渠道为准，不表示本项目已经上架。

更新前停止共享；保留相同应用身份和已有配置，不通过卸载解决安装问题。会话内订阅没有持久化，重启后需要重新导入。不要关闭系统保护或上传签名私钥。

## OpenWrt / iStoreOS

在星渡页面右上角点 **检查更新**，发现新正式版后点 **一键安装更新**。后台从本仓库 GitHub Releases 下载配套 IPK，核对附件 SHA-256、大小、包名、版本及 `all` 架构，预检依赖后备份本地配置并通过 opkg 升级。可以留在当前页面查看结果，不需要 SSH 或手动上传文件。

入口只接受 `starpass-router-vX.Y.Z` 正式发行及独立附件 `luci-app-starpass_X.Y.Z_all.ipk`、`xianniu-router_X.Y.Z_all.ipk`。桌面、Android、测试归档、缺失摘要或不完整的配套附件不进入路由器更新列表。网络失败明确显示失败。不会自动开启代理、定时下载或降级；核心仍通过原 OpenClash 更新。CI 的带提交号包也可升级到更高的正式版本。

保留原订阅、代理地址、端口、MAC 备注、模式和开关。安装前会先停止鲜牛并确认暂停计时；更新后不会自动恢复付费加速。已启用的游戏/星渡服务按保存状态恢复。连接会短暂中断，安装完成刷新页面即可加载新界面。

备份位于 `/etc/portalproxy-backups/update-*`，包含私有配置和旧程序文件。失败时显示错误并保留备份；不把部分安装或断电称为成功，也不承诺自动修复系统包管理器。源码安装和 apk 固件使用原安装流程，页面升级只适用于 opkg 管理的安装。

## 验证范围

新增 JVM 测试覆盖版本/架构选择、受限下载域名、哈希/长度校验和取消。编译后清单审计继续严格检查权限，并要求更新 Activity 和单文件 APK provider 均不对外导出；安装包只通过临时只读 URI 授权。应用内没有静默安装、启动检查定时器、密钥生成或用户可配置的更新源。

参考：[Android 安装来源授权](https://developer.android.com/reference/android/content/pm/PackageManager#canRequestPackageInstalls())、[Android 应用签名](https://developer.android.com/studio/publish/app-signing)、[GitHub Release 附件 API](https://docs.github.com/en/rest/releases/assets)。
