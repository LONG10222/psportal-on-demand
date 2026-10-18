# GitHub 更新、日志与优化记录

检查日期：2026-10-19。仓库 [LONG10222/psportal-on-demand](https://github.com/LONG10222/psportal-on-demand)，当前工作使用 [PR #4](https://github.com/LONG10222/psportal-on-demand/pull/4) 的功能分支，未合并主分支。

## 检查到的更新

- `main` 仍为 `5abe7274`；PR #4 远端基线为 `49a8467`，当时没有新增讨论或评审评论。
- `feat/cross-platform-ui-parity` 新增三次提交，最新 `0980a75`：需求与状态文档、Windows/Linux 只读发现、PyYAML/LibYAML 完整来源与打包审计。其轻量 [checks](https://github.com/LONG10222/psportal-on-demand/actions/runs/39144794753) 通过，但该检查只覆盖原路由器与仓库检查，不能证明桌面发行包通过。
- 已在自己的分支整合上述源码，没有修改另一对话的工作目录。整合回归发现并修复 sysfs 非规范化路径比较；补测 JSON 中转义的国旗字符。最新本机结果：244 项中 235 通过、9 跳过。

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

整合版本将在同一功能分支更新后触发新的 PR 检查。旧成功、失败记录不会被当成本轮代码的验证结果；最新状态见 [PR #4 checks](https://github.com/LONG10222/psportal-on-demand/pull/4/checks)。

后续优化优先级：先确认新的三平台归档门禁，再验收真实手机／游戏机的连接和网络切换，最后扩展移动端实时设备与节点面板。游戏 UDP、iPhone 后台常驻和真实热点仍是独立验收项。
