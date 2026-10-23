# 软路由调试与验收 · 2026-10-23

基于开发分支 `feat/android-settings-updates` 的 `836bb9b`，专用修复分支
`fix/router-install-validation-20261023`。问题记录：[Issue #26](https://github.com/LONG10222/psportal-on-demand/issues/26)。
保留累计功能，不合并旧 main，不改 Android、Windows 或 Apple 客户端。

## 已复现并修复

- **首次唤醒失败**：真实 nixio 的 WNOHANG 未结束结果为 `false`，并非仅为 `0`。保留等待，避免误判退出。
- **节点快照缺失**：真实 nixio poll 超时也返回 `false`；在总时限和步数上限内重试，真正 syscall 错误仍失败。
- **并发时监听器卡死**：LuCI 的 ubus 连接/事件循环缓存不能跨 fork 共用。改为独立 `ubus -t 1` 客户端，仅接收有大小限制的指定服务结果；服务名校验避免 shell 注入。
- **准备即启动**：CLI setup 只保存；LuCI 增加首次网络字段、独立启动/停止与快照刷新。保存不下载、不启停；启用时先校验和生成配置。
- **联动代理认证**：只在进程内存读取已启用的 OpenClash UCI HTTP 认证，核对运行时用户名后发送到固定回环入口。控制器 Bearer 与代理 Basic 分开；不复制到策略、缓存、日志或命令行，不修改 OpenClash。
- **保存影响休眠后的核心**：独立核心路径和 routing mark 读取已经应用的运行策略，不读取之后尚未应用的 UCI 更改。
- **安装与显示**：路由器脚本固定 LF；提供架构无关、无核心的 opkg IPK，包含目录条目、权限与 conffile。源码和 IPK 可重复构建。缺核心允许先安装/配置，独立启动检查并发现已安装的已知路径。
- **状态与界面**：连接数、监听时长及设备/上游实际接收字节；使用 PID 和 Linux starttime 核对活进程，过期状态明确提示。修复 iStoreOS 窄屏标题样式，长说明折叠；联动不展示虚构延迟和选中状态。
- **维护**：升级私有备份、包管理器配置保留、卸载保留与显式清除；源码卸载拒绝符号链接和并发操作。`logs`/`diagnose` 只输出有界、清洗后的本插件信息。

## 功能与验收表

| 功能 | 验证与结果 | 边界 |
| --- | --- | --- |
| 保存、启动、停止、应用分离 | N1 真实 LuCI HTTP 请求；保存后 enabled=0，独立启动后监听就绪 | 浏览器刷新不重复 POST；不把启动当作联网成功 |
| 独立唤醒、回收、再次唤醒 | N1 真实 procd/套接字烟测 | 上游为受控回环 fixture，不是真实订阅 |
| 独立自动、首选、固定 | 隔离 OpenWrt VM + 官方 Mihomo 1.19.32，5 个真实核心场景 | 验证候选排序、中文/emoji/正则精确名称、Direct 排除、缺失固定节点 REJECT；不证明真实节点健康 |
| 核心配置兼容 | N1 现有 Mihomo 1.19.32 执行 `-t` 成功 | 未用该测试启动第二个用户核心 |
| OpenClash 联动 | N1 实际带认证 HTTP 入口；HTTP 200、HTTPS CONNECT 204 | Wikipedia 返回 403，未计作访问成功 |
| 并发与恢复 | N1 4 路并发 HTTPS；监听器 SIGKILL 后 procd 约 5 秒恢复，再请求成功 | 未停止/重启原 OpenClash，未整机重启 N1 |
| 空闲回收与状态 | 10 秒测试预算后自己的会话关闭；再次请求成功；真实字节计数变化 | 使用默认 60 秒作为日常配置；字节包含协议头，时长属于监听器会话 |
| 来源和目标限制 | 非白名单来源拒绝；127.0.0.1、::1、链路本地字面目标返回 403 | 不承诺继承外部核心的全部 DNS/重绑定保护 |
| 节点与订阅 | LuCI 实际按钮读取 60 项代理记录/7 个组；独立下载安全回归保留 | 联动只读，节点切换/测速/订阅更新由 OpenClash 管理；独立延迟来自核心健康检查 |
| 配置、升级、卸载 | N1 实际 opkg 安装与多轮升级；私有备份、配置保留、静态载荷逐字节核对 | opkg 正常保留更改后的 conffile 并留下新默认 `-opkg` 文件；不要覆盖用户配置 |
| 整机启动与清除 | 隔离 OpenWrt 24.10.8 VM 重启后监听器自启、核心仍休眠，UCI 摘要不变；opkg 卸载保留配置/provider/外部核心；显式 purge 删除本插件配置并保留独立备份 | N1 未整机重启；VM 重启清空 /tmp，测试辅助脚本已重新上传后完成清除阶段 |
| Lua 与打包 | 4,618 项计数断言 + LuCI/status/configure/service-status 测试；20 项打包/暂存/故障注入测试 | mock 单列，不作为实机结果 |

N1 环境：iStoreOS 24.10.8（2026081412）、ARM64、Lua 5.1.5、luci-compat、
OpenClash 0.47.156、Mihomo 1.19.32。另使用官方 OpenWrt 24.10.8/opkg 和 25.12.6/apk 的隔离 x86 VM。
不把某个固件的兼容结果推广到全部 OpenWrt/iStoreOS。

## 尚未完成

- 指定实体 PS Portal/Quest 等设备的实际接入、游戏登录与串流体验，需要设备和目标场景。
- 目标 N1 整机重启、长期压力/多日运行、升级异常断电恢复。
- 独立模式真实用户订阅的节点故障/恢复、实际测速质量与所有供应商格式；传输成功仍不保证 YAML 语义有效。
- OpenWrt apk 原生包及签名、iStore 上架。25.12/apk 固件先用源码安装器；不能把 IPK 改名为 APK。
- HTTP/HTTPS CONNECT 只承载 TCP，不提供通用游戏 UDP、透明路由或所有串流协议支持。

## 重跑

```sh
for t in unit access dns ownership lifecycle selection subscription node_api openclash luci status configure service_status; do lua tests/$t.lua || exit; done
python3 tests/packaging.py
sh tests/router-smoke.sh
sh tests/core-config.sh /可信路径/mihomo
# 只在隔离测试系统运行，不能与用户 OpenClash 同时启动第二个核心：
python3 tests/real-core-selection.py /可信路径/mihomo --isolated
```

烟测服务仅使用自己的临时名字和回环端点，结束后清理。历史首次失败曾暴露真实返回值差异、fork 缓存问题；
新增测试夹具的早期 JSON emoji 转义/模块加载顺序问题也已修正。最终通过结果不复用这些失败运行。
私有备份与认证/订阅均不进入仓库、CI 产物或公开问题记录。
