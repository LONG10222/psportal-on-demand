# Clash 参考记录

用户授权只读查看已安装的 Clash，并获取开源源码。只读取了 Clash Verge 当前首页与已安装版本：2.5.8；没有点击它的开关、菜单、节点或设置，没有调用其控制接口。

已从官方仓库下载 v2.5.8 完整源码，参考副本位于当前工作区 `work/clash-source-complete/clash-verge-rev-2.5.8`，压缩包与校验记录位于 `work/clash-source-reference/SOURCE.json`。保留上游 LICENSE。仅作为参考，没有启动、构建或安装另一份 Clash，后续仅只读解析其标准 profiles.yaml，输出当前订阅名称和套餐统计白名单字段；不导入、展示或写出其订阅 URL、令牌及节点凭据，不写回文件。

- [官方仓库](https://github.com/clash-verge-rev/clash-verge-rev)
- [v2.5.8 软件声明及依赖](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.5.8/package.json)：Tauri、React、Material UI、i18next，项目声明 GPL-3.0-only。
- [主题](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.5.8/src/pages/_theme.tsx)：深浅配色、蓝色强调色。
- [侧栏](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.5.8/src/components/layout/layout-sidebar.tsx)、[代理](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.5.8/src/pages/proxies.tsx)、[订阅](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.5.8/src/pages/profiles.tsx)、[连接](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.5.8/src/pages/connections.tsx)、[规则](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.5.8/src/pages/rules.tsx)：用于比较信息组织和功能职责。

本轮界面以独立 Tk/SwiftUI 代码实现，保留现有代理后端，不复制 Clash 品牌、图标或组件源码。后续如果直接移植 GPL 源码，应保留相应许可、版权和完整对应源码；现有 native Mihomo 组合本来就按 GPL-3.0-only 管理。

目前重点差异是：Clash 管理用户自己的代理客户端环境；本程序首先让其他局域网设备通过 HTTP/CONNECT 接入，并按需管理自己拥有的上游。复用原客户端时，本程序不拥有、也不回收原客户端核心。

iOS 网络识别采用 [Apple NWPathMonitor](https://developer.apple.com/documentation/network/nwpathmonitor)。Apple 的 [NEHotspotNetwork.fetchCurrent](https://developer.apple.com/documentation/networkextension/nehotspotnetwork/fetchcurrent(completionhandler:)) 是受权限约束的当前 Wi-Fi 信息接口，不能据此把蜂窝连接认定为本机个人热点已开启。本版没有为此申请定位、VPN 或 Wi-Fi 信息特权。

桌面已增加只读套餐缓存联动：按上游 `IProfiles.current`、`PrfItem.extra` 与 `updated` 的格式提取统计。代码只返回 upload/download/total/expire、名称和更新时间，明确显示“本地缓存，非实时”；没有调用原客户端的更新订阅动作。
