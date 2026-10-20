# Windows 工作流修复验证 · 2026-10-20

基于 GitHub 最新界面提交 e28e19775a961ada43b794eb247f3e673bbee1c8，保留当前星海角色、节点控制、模式与配置迁移。

## 本轮修复

- 粘贴一次即导入并保存，不启动、不探测局域网；同一链接重复粘贴不下载。刷新是独立操作，失败保留先前订阅。
- 普通首页不要求选择核心。Windows x64 默认随包 Mihomo v1.19.32；缺少时由点击启动的流程自动发现或下载并校验，成功继续启动、失败可重试。
- 联动现有 Clash 只允许游戏模式，另外两项可见但置灰。配置/启动同时校验；取消联动恢复之前的订阅和模式，不启动或管理原客户端核心。
- 直接订阅统计与原 Clash 套餐缓存分别显示；服务就绪后才可复制共享地址；小窗口始终可见启动按钮。
- 子进程输入输出固定 UTF-8，非法/中断管道安全清理监听及锁。Windows 网络识别不显示额外控制台。

## 验证结果

Windows 本机运行 unittest discover 全套 427 项：384 通过，43 条件跳过，0 失败/错误，耗时 78.766 秒。启用 PSPORTAL_TK_TEST、MIHOMO_BINARY、PSPORTAL_BINARY、PSPORTAL_FROZEN_WINDOW_TEST。

通过范围包含真实 Tk 交互、真实 Mihomo 回环 HTTP/CONNECT、空闲回收/再次唤醒、冻结程序 Unicode 节点控制、异常 UTF-8/父进程关闭后监听与锁清理、粘贴去重、显式刷新、缺少核心时自动准备/重试、联动模式拦截与取消联动恢复。

43 项跳过包括 POSIX/Linux/macOS 特定夹具、仅 X11 截图自动化和未构建的实验性 embedded native 引擎。跳过项目未按通过计入。默认 external Mihomo 已实际运行；不代表实验引擎、真实订阅外网质量或实体 PS Portal 游戏兼容性已验收。

本包为本机构建开发预览，未签名；没有完成仓库正式发布要求的精确 Python 运行库公告审计。未改动系统代理、防火墙或原 Clash 配置。

## 来源与跟踪

默认核心：MetaCubeX/mihomo v1.19.32，官方 Windows amd64-compatible。
核心 SHA-256：04f8d7fc2b314771e1ecbf15951d59f0e1cb7914503c88cfb6972ff6a824e314。
匹配源码提交：88dcbf7f1614a67c3b36b848ee3592dfa92ada36。
包内 licenses/mihomo-v1.19.32/ 保留上游源码 ZIP、许可证和来源记录。

问题跟踪：https://github.com/LONG10222/psportal-on-demand/issues/19 。安卓测试与源码在独立对话/分支中进行，不在本地 Windows 测试数量内。
