# 使用说明

1. 启动 Phase 1 服务。
2. 打开 `http://127.0.0.1:7860`。
3. 在左侧填写任务标题、PPT/Word 配置、检索边界和 Agent 配置。
4. 点击“连接检测”检查 Codex、Hermes 和 Chrome CDP。
5. 点击“创建任务”保存任务 JSON。
6. 点击“运行 Phase 1 工作流”写入流程日志。

输出文件和日志默认位于：

```text
D:\codex-project\APP\outputs\ai-report-ppt-controller-runtime\tasks\{task_id}
```

如需改变位置，设置 `APP_STORAGE_DIR`。
