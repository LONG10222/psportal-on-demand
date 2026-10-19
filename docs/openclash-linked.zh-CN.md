# iStoreOS / OpenWrt：星渡与 OpenClash 联动

2026-10-19 开发预览；基于全平台修复提交 `bb68a44bf704be3c1249b8dfbd166dcc5821168a`。
同步包含独立 iOS 26 SDK 编译门禁的全平台源码，门禁通过也不等于真机后台授权。
这是路由器源码安装器，不是 iStore 商店上架包、已签名 IPK/APK 或真机验收报告。

## 保留最初的操作逻辑

只让指定的游戏设备使用显式 HTTP 代理。监听器维持很小的常驻入口；局域网目标直连，
外网请求到来才激活代理会话；无外网数据超过默认 60 秒就收回自己持有的外网连接。
页面查看、节点快照、局域网访问都不会刷新空闲倒计时。

- `standalone`：保留原独立 Mihomo、独立订阅和节点偏好。首次外网请求启动自己的核心，
  健康检查通过后转发；空闲停止自己的核心。OpenClash 不必运行
- `openclash`：复用已经运行的 OpenClash HTTP/mixed 入口；订阅、节点、规则、DNS 与
  全局／规则／直连模式仍由 OpenClash 管理。星渡只激活／关闭自己的会话，绝不启动、
  停止、重启 OpenClash，也不会增加第二个核心或复制其订阅

这里“用途”仍是单设备局域网共享。没有添加无效的路由器“本机 VPN”开关。
入口只承载 HTTP 与 HTTPS CONNECT 的 TCP，不代理任意游戏 UDP、Remote Play UDP、
ICMP 或未使用 HTTP 代理的应用；不能据此承诺游戏延迟改善或全游戏加速。

## 安装与选择

从本草稿 PR 的精确提交或 Actions 的 `starpass-router-source-…` 下载源码包；不要把旧 main
的下载内容当成本次联动版。源码包包含 SHA256SUMS，不含核心和任何运行配置／凭据。
在已具备 Lua 5.1、nixio、luci.jsonc、luci.util、luci.sys、UCI、procd 的路由器上执行：

```sh
sh install.sh --openclash
portalproxy setup
```

向导选择 `openclash`；填入路由器 LAN IPv4、设备的保留 IPv4、可用的 LAN DNS、代理端口
和空闲时间。联动模式不再索要第二份订阅、种子或核心路径。先在 OpenClash 自己的界面
完成订阅及节点配置并启用它，再应用星渡设置。

已有独立安装会先备份并保留配置；`--openclash` 不会偷偷切换既有模式，必须在向导或 LuCI
中明确选择并应用。切换／应用会断开星渡现有连接并清理它以前拥有的独立核心。
保留的旧独立订阅不会上传或导入 OpenClash。

独立模式仍使用 `sh install.sh --core /可信路径/mihomo`。以后切回独立模式须保证自己的
核心和订阅可用。安装、卸载仅操作星渡自己的文件和服务，不更改网络或 OpenClash。

设备连接可互通的可信 LAN，在 Wi-Fi 高级设置里选“HTTP 代理 → 手动”，填写向导显示
的 LAN 地址与端口（默认 10081）。白名单仍只有一个准确来源 IPv4。

## 只读发现与运行前检查

- 从 OpenClash UCI 的有效覆盖层 `@overwrite[0]` 优先读取 `http_port`、`mixed_port`、
  `cn_port`、`dashboard_password`，不存在才读 `config`；显式空值／零不被旧值替代
- 优先 HTTP，禁用／不存在时用 mixed；不把 SOCKS、redir 或 TProxy 端口当作 HTTP
- 所有连接固定到 `127.0.0.1`。首次激活核对带有已配置认证的 `GET /configs` 所报实际端口与
  路由模式，再做有界端口连接检查；不存在、停止、端口漂移或认证不匹配时返回 503
- OpenClash 改了端口后执行 `portalproxy apply` 重新发现。控制器地址、远程转发域名与
  配置路径不会进入请求目标。401 不会回退到匿名访问
- API 密钥仅在本机内存组装请求头，不写入星渡策略、节点缓存、命令行、日志或 LuCI
- HTTP 代理认证与 API 密钥是两件事。本版不复制用户名／密码。如果代理认证已启用，
  必须由用户在 OpenClash 配置有效的 loopback 豁免；当前支持精确形式
  `127.0.0.1/32`、`127.0.0.0/8`、上游文档的 `127.0.0.1/8`，其他形式保守拒绝
- 不改 OpenClash 的监听范围。它自己的控制器可能向 LAN 监听，仍须自行保护认证和访问

`GET /proxies` 仅用于有界、清洗后的只读节点／组快照；大列表或不支持的返回不会阻止
已通过运行端口检查的入口。不会发送 PUT/PATCH/DELETE、测速、订阅更新或组切换请求。
端口可达不代表 Internet 可达、节点健康或游戏成功；状态不会编造延迟或“实际出口”。

## 操作与状态

```sh
portalproxy status         # 入口、核心归属和自己的会话状态
portalproxy nodes          # 只读本地缓存，不联网、不唤醒
portalproxy nodes-refresh  # 显式读取已经运行的 OpenClash，绝不启动它
portalproxy check          # 配置与发现检查，不启动服务
portalproxy apply          # 重新发现并重启自己的入口，会断开自己的连接
portalproxy stop           # 只停星渡入口及自己拥有的核心／会话
```

LuCI 的“服务 → StarPass / 星渡”可选择核心归属、保存、明确应用，并展示缓存的 OpenClash
模式和策略组。联动时隐藏独立订阅／偏好编辑；CLI 的订阅更新与偏好修改也会拒绝。
节点切换和订阅更新请在“服务 → OpenClash”操作。保存不重启；普通查看不联网。

## DNS 与路由边界

联动模式继承 OpenClash 的最终规则，包括 DIRECT，不自动强制外网走代理。它也继承
外部核心的 DNS／重绑定防护；独立模式自行添加的后端私网拒绝规则不能宣称仍然有效。
OpenClash 看见的来源通常是路由器／回环，而非原游戏设备 IP，按设备来源匹配的规则
未必适用。请在 OpenClash 中明确配置并用真实请求核验所需出口。

监听器仍拒绝回环、链路本地等禁止字面地址，以及本地 DNS 中可检测的禁止回答。
只有联动模式下的公开域名，完整、合法 DNS 回答中的默认 fake-IP 段 `198.18.0.0/15`
才作为“交给外部核心解析”的信号，转发原域名；绝不直接连接该假地址。
用户直接填写 fake-IP 字面地址、`.lan` / `.local` / 单标签名字收到 fake-IP、混入
127.0.0.1 等危险回答、截断或畸形 DNS 包仍被拒绝。自定义 fake-IP 网段没有被放宽。

星渡不修改防火墙、路由、DNS 劫持、VPN 或 TUN。真实路由器若已有透明代理／TUN规则，
需用户确认 LAN DNS 和回环入口的实际行为；不把接口被透明重定向的环境当作已验收。

## 验证与限制

本轮本地通过 4,482 项具名计数断言、LuCI 认证/操作/切换回归及 9 项暂存/源码打包测试；其中生命周期为 783 项断言、36 个模拟场景。

新增纯内存测试覆盖有效 UCI 覆盖、缺省/禁用端口、认证及注入、运行配置漂移、端口冲突、
任意策略组与 DIRECT、秘密字段清洗、只读 API、缓存跨模式失效、认证代理豁免、fake-IP、
LAN 并发、取消／超时／空闲／再次激活及“不管理外部服务”。原独立路由器回归保留。
安装器测试在临时目录进行，验证无核心安装、配置保留、卸载、确定性源码包和校验清单。
GitHub checks 在 Lua 5.1 上重跑；本地 texlua 不替代目标固件验证。

尚未验证：指定版本 iStoreOS/OpenWrt + OpenClash + LuCI 真机、真实用户订阅、实体 Portal、
路由器升级/重启、透明代理和实际出口、热点、长时间空闲、IPv6 上行兼容性。源码包不是
二进制包；运行测试依赖完整仓库中的部分打包夹具。现有独立 smoke 脚本不代表本版联动实机验收。

## 核对过的上游接口

2026-10-19 只读核对，未复制上游实现或修改第三方许可：

- [OpenClash UCI 默认端口](https://github.com/vernesong/OpenClash/blob/master/luci-app-openclash/root/etc/config/openclash)
- [有效覆盖读取](https://github.com/vernesong/OpenClash/blob/master/luci-app-openclash/root/usr/share/openclash/uci.sh)
- [控制器与配置生成](https://github.com/vernesong/OpenClash/blob/master/luci-app-openclash/root/usr/share/openclash/yml_change.sh)
- [OpenClash 服务归属](https://github.com/vernesong/OpenClash/blob/master/luci-app-openclash/root/etc/init.d/openclash)
- [Mihomo 通用认证设置](https://github.com/MetaCubeX/Meta-Docs/blob/main/docs/config/general.en.md)
- [Mihomo 只读配置 API 实现](https://github.com/MetaCubeX/mihomo/blob/Meta/hub/route/configs.go)
