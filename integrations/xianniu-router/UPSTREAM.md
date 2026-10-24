# StarPass HTTP 来源

仓库：https://github.com/LONG10222/psportal-on-demand

固定提交：642905687281f7f34fb9917949ec6c8930e3c7ce

源文件 portable/portalproxy/proxy.py（Git blob 2193aa6af5e4c007a88e45e6c0a55cbcb38d3878）及 policy.py（2331294132ea126d9363fc3fecad4a2d8a809580）。来自本对话上一轮通过 GitHub 连接器取得的固定版本。

proxy.py 增加原生字节流后端和可配置的目标解析器；不向真实目标发送嵌套 CONNECT；普通 HTTP 改用 origin-form。policy.py 未修改。MIT 许可随 IPK 安装于 /usr/share/xianniu-router/LICENSE-StarPass。

http_streams.py 来自本对话 Windows 原型验证过的帧/字节流适配。http_proxy.py 是 N1 的会话、白名单与显式 LAN DNS 适配，不包含 Windows 监督进程或 Job Object。

0.4.0 另外阅读同机星渡已验收源码 5da075302716ec1199bdefcb110d6ae43aff1d46 的 router dashboard.htm、onboarding.htm、render.lua、selection.lua，参考其代理接入、客户端限制与节点选择流程。鲜牛的设备游戏方案、官方会话与本版界面另行实现，没有修改现有星渡或 OpenClash 配置。星渡文档同样明确 HTTP/TCP 接入不覆盖游戏 UDP 或全设备路由。
