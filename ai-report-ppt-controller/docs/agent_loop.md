# Agent Loop 设计

标准流程：

1. Task Parser 解析任务。
2. Hermes 生成检索式和检索计划。
3. Chrome CLI 执行联网搜索。
4. Hermes 整理检索结果。
5. Codex 生成结构化大纲。
6. Hermes 审核大纲专业性。
7. Codex 修改大纲。
8. Codex 生成 PPT / Word 初稿。
9. Hermes 审核内容专业性、逻辑性和引用完整性。
10. Codex 根据审核意见修改文件。
11. Final QA 检查格式、引用和模板一致性。
12. 导出 PPTX / DOCX / Markdown / JSON 日志。

Phase 1 仅保存流程可视化和日志。Phase 2 开始执行真实 Agent 调用。
