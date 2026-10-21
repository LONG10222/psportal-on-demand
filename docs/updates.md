# 应用更新

安卓优先使用设置内更新，Windows 采用下载完整包后退出更新。内核随应用一起更新，不需要用户选择 Mihomo 版本或文件。

## 安卓

在 **设置 → 应用更新** 检查正式版本，查看更新内容后下载。页面显示进度；完成校验后点 **安装更新**，由 Android 系统确认覆盖安装。首次使用时，按提示允许星渡安装应用，再返回点安装。更新保留应用配置。连接运行中可以检查和下载，安装前需要停止连接。

默认只读取本项目 GitHub Releases 的最新正式版本，跳过草稿和预发布。没有正式发布包时会明确显示“尚未发布正式更新”；网络失败不会显示“已经是最新版”。下载失败可重试；离开页面取消网络任务，已完整验证的下载可在下次检查后复用。首次安装带更新功能的版本仍需手动安装一次。

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

先上传完整附件并验证签名/覆盖安装，再将 Release 从草稿发布为正式版。不要将现有 unsigned ZIP 归档标为正式版，否则会影响最新正式版的查询。版本号不会在 Windows 与 Android 间比较。

## Windows 建议

后续设置页采用 **检查更新 → 下载 → 退出并更新 → 重新打开**，按架构自动匹配完整包，保留独立的用户配置目录。更新时先正常停止本应用连接，退出后由独立更新程序替换文件；失败保留旧版本并允许回退。当前 Windows 尚未实现自动替换，仍需解压新包后启动，不能显示“自动更新成功”。

## 验证范围

新增 JVM 测试覆盖版本/架构选择、受限下载域名、哈希/长度校验和取消。编译后清单审计继续严格检查权限，并要求更新 Activity 和单文件 APK provider 均不对外导出；安装包只通过临时只读 URI 授权。应用内没有静默安装、启动检查定时器、密钥生成或用户可配置的更新源。

参考：[Android 安装来源授权](https://developer.android.com/reference/android/content/pm/PackageManager#canRequestPackageInstalls())、[Android 应用签名](https://developer.android.com/studio/publish/app-signing)、[GitHub Release 附件 API](https://docs.github.com/en/rest/releases/assets)。
