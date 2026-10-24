# 官方登录与节点资料证据

公开安装文件 XianNiu.exe，SHA256 dc514287f9f8c6c73e07a8935235dd262580e4c1769ad741ea88af5b60273bcb，FileVersion 5.2.8.2。

客户端请求函数 0xa7759c 的静态分支：0xa776a1/0xa776b2 写 mobile/mobile_code；0xa77777 写密码摘要；0xa77787 选择 /client/auth/login；0xa777d0 写第三方 code；0xa777e0 选择 /client/auth/other。0xa77802 后附加 hardware、os_type、client_type、client_version、os_info、os_version、datetime、channel。静态只证明构造，不证明真实登录成功。

官方网页 [登录组件](https://wap.xianniu.com/js/chunk-021162ca.js) 直接使用 MD5 摘要并调用相同的客户端登录接口；[公共组件](https://wap.xianniu.com/js/chunk-common.js) 声明官方服务端时间接口 /open/tools/datetime。原型使用正常服务端时间与本机稳定硬件标识，密码不持久化。

微信标准流程观察：官方 QR 页面 → WeChat 正常扫码确认 → 官方 webapi.xianniu.com/auth/weixinweb/callback → threelogin.xianniu.com/pc/auth2.html，由其 code 进行客户端第三方登录交换。兼容旧 user.xianniu.com/auth2.html。旧 api1 入口与 webapi 回调的 Cookie 域不同；0.3.1 统一入口，但仍未处理新登录落地域名。0.4.0 在该跳转取得 code 时停止请求，避免重复消费回调。官方 [auth2.js](https://threelogin.xianniu.com/pc/js/auth2.js) 从 URL 提取 code 后调用 THREEAUTOLOGIN。是否完成真实登录见本轮验证 JSON，不能从静态分支或扫码确认推断。

官方“记住登录”：0x9ec654/0x9e6950 保存/读取 HKLM SOFTWARE\\xianniu 的 access_token；0xa77655 将保存值放入 token 字段，调用 /client/auth/login_token。本次仅分析公开 EXE 代码，没有读取私有注册表值。旧导入令牌的单次官方恢复尝试返回 400065；新的有效会话恢复仍待实测。

会员接口：/client/member/details 位于 0xa831b0，携带 access_token；/client/member/suspend 位于 0xa82cd4，/client/member/recovery 位于 0xa834a0，携带 access_token 和 sender。暂停调用者 0xa86f62/0xa86ff3 使用 sender=0。本版使用相同请求编码，不绕过会员限制。仅投影套餐、计时状态和官方到期字段；未确认时间字段单位前不自行计算剩余秒数。

节点接口 /client/accelerate/linelist 的请求为 game_id、area_id=0。PS5 港服实机返回 6 行，包含 line_id、line_title、area_ids、line_in/line_out、isp/provider、speed_ip 与三个运营商入口 IP。页面投影这些非凭据字段，不返回线路密钥或加速授权。实际节点分配继续使用正常 /client/accelerate/start。

管理接口采用 OpenWrt [rpcd exec 插件协议](https://openwrt.org/docs/techref/rpcd)。整数参数使用数值宽度声明，按 [rpcd 源码](https://github.com/openwrt/rpcd/blob/master/plugin.c) 的签名解析方式注册。未登录的 HTTP 调用已观察到 JSON-RPC Access denied。
