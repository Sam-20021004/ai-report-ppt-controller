# 安全说明

已纳入 Phase 1 的安全约束：

- Codex/Hermes 检测使用固定命令白名单。
- `subprocess` 不使用 shell。
- 上传文件限制扩展名和大小。
- 下载路径限制在 `backend/storage` 内。
- 日志会进行基础敏感字段脱敏。
- 远程访问默认关闭。

禁止项：

- 远程用户直接输入 shell 命令。
- 读取任意本地路径。
- 日志显示 API Key、Cookie、Token。
- 直接暴露 Chrome debugging port 到公网。
