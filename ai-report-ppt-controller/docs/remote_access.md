# 远程访问说明

Phase 1 默认仅本机访问。

后续局域网模式规则：

- 监听 `0.0.0.0` 前必须设置 `APP_API_TOKEN`。
- 远程请求必须携带 `Authorization: Bearer <token>` 或 `X-API-Token`。
- 不允许远程用户输入任意 shell 命令。
- Chrome debugging port 不直接暴露公网。
- 上传文件限制类型和大小。
- 任务目录按 `task_id` 隔离。

公网访问建议使用 Cloudflare Tunnel、Tailscale、ZeroTier 或 FRP，并保留 token 鉴权。
