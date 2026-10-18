# 订阅与节点偏好：第二阶段

本阶段基于第一阶段修复，仍是 OpenWrt/iStoreOS 的 Lua/procd 实现，不是 Windows、macOS 或手机独立客户端。新增可选 LuCI 旧版 CBI 页面和 root/SSH 命令。测试使用模拟核心/系统接口，没有真实路由器、LuCI 浏览器或 Mihomo 核心验收。

## 三种模式

- `auto`：香港 → 日本 → 其他可用节点
- `preferred`：先尝试保存的精确节点名，再按地区顺序回退；健康恢复后应回到首选
- `fixed`：只允许精确同名节点；消失、改名或不可用时失败，不悄悄换节点或直连

`preferred_node` 独立保存在 UCI；切回 auto 保留名字。控制字符、反引号分隔符和保留名禁止，其他正则字符逐字转义。配置通过多段 filter 实现排序，全部模式保留最终 REJECT 哨兵。固定 select 只有精确名称及 REJECT，避免旧版核心不识别 empty-fallback 时变成 COMPATIBLE。直接出口类型在 provider/group 层过滤；业务就绪检查还会拒绝 Direct/Compatible 等终端。

不是向 fallback API 设置一次 fixed：该临时选择可能在故障、测速后清空。`store-selected=false` 保留，避免核心缓存覆盖项目偏好。源码依据、版本和模拟边界见 [core-selection-evidence.md](core-selection-evidence.md)。发布前必须固定实际核心版本验证排序、恢复回首选和拒绝行为。

## 命令

先完成基本网络配置。没有本地种子时先下载缓存：

```sh
portalproxy subscription-update
portalproxy nodes
portalproxy prefer preferred '日本 A'
portalproxy apply
portalproxy prefer fixed '日本 A'
portalproxy prefer auto
portalproxy nodes-refresh
```

保存偏好不改运行中配置，`apply` 会重启监听器并断开现有连接。`nodes` 只读历史缓存；`nodes-refresh` 只在核心已运行时读取 API，不主动测速、不延长空闲预算。延迟来自最后一次健康检查，不是游戏质量评分。启动时递归解析策略组到真实节点，健康且固定模式名称匹配才放行业务。

`subscription-update` 不启动休眠核心，但运行中的 Mihomo 可能监视文件并立即载入更新，改变线路或中断连接，请避开游戏中操作。节点列表快照可能仍旧；更新后可在核心运行时执行 nodes-refresh。首选被订阅删除或改名时不自动改写用户偏好；固定模式拒绝，首选模式回退。缓存缺失或过期不能证明节点已删除。

## LuCI

安装时检测到 `/usr/lib/lua/luci` 才复制可选页面；现代 LuCI 可能需要 `luci-compat`。登录后从“服务”打开 PS Portal。只在受信任 LAN 使用 HTTPS LuCI，不要公开管理端口。

页面读取只显示缓存，不唤醒或续命。订阅链接是只写隐藏输入，留空保留旧值，不回填完整链接。保存、应用已保存设置、更新订阅为独立动作；应用/运行时更新可能中断连接。核心控制口仍仅监听 127.0.0.1，以 root 受限 secret 文件鉴权，浏览器不直连核心。

## 下载与隐私边界

订阅只作为节点集合，不能覆盖本地监听、管理 API 和路由配置。链接/凭据只存本机受限文件，不出现在错误日志或进程参数。节点显示名仍可能暴露地点/服务商，分享诊断时请核对。

需要 curl 和系统 CA。只支持 HTTPS 公网 IPv4目标：IPv4 DNS 查询结果全部检查后固定到本次 TLS 连接，禁止代理环境变量/重定向，大小最多 5 MiB且有独立 DNS/传输超时。局域网、IPv6-only、必须重定向的订阅暂不支持。

传输/TLS/大小失败保留旧缓存；成功 HTTP 200 的内容仍可能是 HTML 或错误 YAML，当前不做核心语义验证，可能替换原文件后导致核心拒绝订阅。不可称为“所有无效更新都保留最后可用版本”。Mihomo 负责解析，使用可信来源；不要导入不可信种子。

安全下载写入 file provider，取消原自动定时 HTTP provider 下载；更新需明确操作。健康检查仍仅在核心运行期间执行。

## 未执行的部署前验收

记录实际 mihomo 版本、散列及 OpenWrt/LuCI 版本，固定测试目标：

1. 首选正常、失败回退、恢复回首选；重启/休眠后偏好恢复
2. 固定节点故障、改名、删除、空订阅均拒绝业务，绝不直连
3. 中文/emoji/正则特殊字符精确匹配，反引号和控制字符拒绝
4. TLS 错误、跳转、DNS 私网/混合地址、超时、超大流式响应拒绝
5. 运行中替换 provider、全被排除、格式错误、重复名称、Direct 类型等输入不绕过 REJECT
6. 嵌套/循环/无节点组或失败健康检查不能提前放行业务
7. LuCI 未登录/非 root/缺 CSRF token 无法修改；链接不在页面源码/日志/参数中
8. 重复点击、会话过期、前进后退不意外重做；页面不唤醒或续命

实际部署需要另行授权。本地模拟通过不等于实机验收通过。
