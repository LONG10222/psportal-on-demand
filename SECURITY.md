# Security and private configuration / 隐私与诊断

Do not attach router backups, subscriptions, provider caches, API headers, or full system logs to a public issue. A subscription URL commonly contains an account token. A provider cache contains working node credentials.

不要在公开 Issue 中上传路由器备份、订阅文件、节点缓存、API 认证头或完整系统日志。订阅 URL 通常包含账号令牌，节点缓存包含可直接使用的认证信息。

Private files / 私有文件：

- `/etc/config/portalproxy`
- `/etc/portalproxy/` including generated configuration, provider cache, and API secret
- `/etc/portalproxy-backups/`
- `/tmp/portalproxy/status.json` can identify local addresses / 可能包含本地地址
- system logs may contain connection details / 系统日志可能包含连接细节

For an ordinary bug report, include firmware version, CPU architecture, Mihomo version, project commit, the redacted error, and whether the offline integration test passes. Replace addresses, hostnames, ports, tokens, node names, and identifiers with consistent placeholders. Do not upload a private file merely because `.gitignore` would ignore a similarly named source file.

普通问题报告只需固件版本、CPU 架构、核心版本、项目提交号、脱敏后的报错和离线测试结果。地址、域名、端口、令牌、节点名称及设备标识应替换成一致的示例。`.gitignore` 不会替你处理手工上传的文件。

The listener allowlist is IP based, without client authentication or MAC enforcement. Keep it on a trusted LAN. Do not add WAN forwarding. The internal API is bound to loopback and uses a generated random secret. Local root administrators can read all runtime credentials. The on-demand policy is not a privacy boundary against the router administrator, network operator, or subscription provider.

监听器依据 IP 放行，不提供客户端身份认证或 MAC 校验。仅在可信局域网使用，不做 WAN 端口转发。内部 API 绑定回环地址，并使用随机密钥。本地 root 管理员仍可读取运行凭据。按需启停不构成对路由器管理员、网络运营方或订阅商的隐私隔离。

For a vulnerability, use the repository's private vulnerability reporting feature if available. Otherwise open an issue containing only a high-level description and ask for a private reporting channel. Do not publish an exploit containing a live subscription or another person's credentials.

安全问题优先通过仓库可用的私有漏洞报告渠道提交。如果没有该入口，公开 Issue 仅描述问题类型并联系私下报告方式，不附带有效订阅或他人凭据。
