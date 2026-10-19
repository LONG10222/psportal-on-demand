# GitHub 更新、日志与优化记录

检查日期：2026-10-19。仓库 [LONG10222/psportal-on-demand](https://github.com/LONG10222/psportal-on-demand)，当前工作为基于 PR #4 最新源码的独立草稿 [PR #5](https://github.com/LONG10222/psportal-on-demand/pull/5)，未合并主分支。

## 跨平台整合检查（2026-10-19）

用户新基线 `72b23e4` 已整合到 `9c4515f`，保留 Apple 应用与启动器字节。GitHub PR 合成提交 `9024b931` 与该提交的源码树相同。

- [统一桌面打包](https://github.com/LONG10222/psportal-on-demand/actions/runs/39185011647) 三平台通过：Windows/macOS/Linux 的精确来源、完整许可、匹配源码与归档门禁均通过；此前 Windows 核心就绪竞态已在该检查通过。
- [Portable desktop builds](https://github.com/LONG10222/psportal-on-demand/actions/runs/39185011634)、[Android 未签名构建与审计](https://github.com/LONG10222/psportal-on-demand/actions/runs/39185011567) 及基础 checks 通过。
- Linux 实际窗口生成七张离线合成数据截图，支持可读性检查，不能证明真实订阅、手机或游戏机连接。
- [原生桌面检查](https://github.com/LONG10222/psportal-on-demand/actions/runs/39185011633) 暴露旧验收断言：把正在监听、核心休眠误判为错误。已保留零外连/唤醒门禁并修正双状态断言，实际 Linux 二进制、14 项脚本测试与全部 Go 测试通过，待新提交 CI 验证。
- iOS Simulator 检查尚在运行；未宣称真机后台常驻或热点验收。

下文为历史记录，不能代替最新提交检查。

## 检查到的更新

- `main` 仍为 `5abe7274`；PR #4 远端基线为 `49a8467`，当时没有新增讨论或评审评论。
- `feat/cross-platform-ui-parity` 新增三次提交，最新 `0980a75`：需求与状态文档、Windows/Linux 只读发现、PyYAML/LibYAML 完整来源与打包审计。其轻量 [checks](https://github.com/LONG10222/psportal-on-demand/actions/runs/39144794753) 通过，但该检查只覆盖原路由器与仓库检查，不能证明桌面发行包通过。
- 已在自己的分支整合上述源码，没有修改另一对话的工作目录。整合回归发现并修复 sysfs 非规范化路径比较；补测 JSON 中转义的国旗字符。最新本机结果：247 项中 238 通过、9 跳过。

## 原基线的云端结果

以下对应 `49a8467`，不是本轮整合代码的结果。

| 检查 | 结果与日志 |
| --- | --- |
| 基础 checks | [成功](https://github.com/LONG10222/psportal-on-demand/actions/runs/39131363619) |
| Portable desktop builds | [成功](https://github.com/LONG10222/psportal-on-demand/actions/runs/39131363757) |
| Native Desktop Runtime Tests | [成功](https://github.com/LONG10222/psportal-on-demand/actions/runs/39131363729) |
| Android 构建 | [成功](https://github.com/LONG10222/psportal-on-demand/actions/runs/39131363703) |
| iOS Simulator | [成功](https://github.com/LONG10222/psportal-on-demand/actions/runs/39131363610) |
| Unified desktop packaged runtime | [失败，三个目标均被发行门禁拦截](https://github.com/LONG10222/psportal-on-demand/actions/runs/39131363687) |

统一桌面打包的失败点已读取到具体作业日志：

1. [Linux](https://github.com/LONG10222/psportal-on-demand/actions/runs/39131363687/job/117687050069)：`Unmapped bundled ELF: yaml/_yaml.cpython-313-x86_64-linux-gnu.so`，打包清单未审查新增 YAML 扩展。
2. [Windows](https://github.com/LONG10222/psportal-on-demand/actions/runs/39131363687/job/117687049865)：`Expected exactly 25 verified binary origins`，原有清单未计入并验证 YAML 扩展。
3. [macOS](https://github.com/LONG10222/psportal-on-demand/actions/runs/39131363687/job/117687050079)：`Bundle symlink topology differs from review`，应用包中新增加的 YAML 链接结构未被原清单覆盖。

## 已落实的修复与优化

- 保留发行门禁，使用独立审查的 wheel、完整源归档、PyYAML 和 LibYAML 许可文本，逐文件校验新增 Python 模块与原生扩展来源。
- 三平台分别核对真实二进制清单、导入和符号链接，不以“构建能运行”代替来源证明；源码、许可证及最终归档仍需匹配。
- 用户操作反馈与节点自动选择已加入自己的外部核心路径；节点操作通过继承的进程管道完成，没有额外开放控制端口，关联 Clash 不调用其控制器。
- 客户端 IP 只用于内存中的本地设备面板，不记录目标网站或订阅密钥。查看问题先看启动/核心日志、设备页错误计数及精确提交的 CI 日志。

## 本轮云端验证

整合提交 `326345f` 已实际触发新检查：

- [Portable desktop builds](https://github.com/LONG10222/psportal-on-demand/actions/runs/39147526423)：Linux 和 macOS 作业通过；Windows 在两项新测试处失败，分别是用真实 Windows 环境模拟 Linux 时丢失大小写冲突，以及旧许可证文件被 Git 改成 CRLF。
- [Unified desktop packaged runtime](https://github.com/LONG10222/psportal-on-demand/actions/runs/39147526429)：Linux 的完整归档、来源与许可证审计已通过；其他目标在该检查快照时尚未完成。
- Windows 两项错误已修复：使用独立环境映射建模 Linux；通过 Git 属性保留原始许可证字节，没有放宽校验。另补齐 macOS 搬迁 Python 的系统 CA 回退并实际验证公开 HTTPS 下载，未禁用证书校验。

以上是精确提交的检查快照。后续修复更新会触发新一轮检查，旧结果不会作为最新代码的证明；实时状态见 [PR #4 checks](https://github.com/LONG10222/psportal-on-demand/pull/4/checks)。

后续优化优先级：先确认新的三平台归档门禁，再验收真实手机／游戏机的连接和网络切换，最后扩展移动端实时设备与节点面板。游戏 UDP、iPhone 后台常驻和真实热点仍是独立验收项。
