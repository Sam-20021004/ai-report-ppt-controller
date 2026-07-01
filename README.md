# 联网分析 PPT 生成器

这是一个本地网页应用，可以输入主题、联网搜索公开来源、整理分析结论，并导出 `.pptx` 文件。

## 运行

如果本机有 Node.js：

```powershell
npm start
```

在当前 Codex 环境中，也可以直接使用内置 Node：

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" server.js
```

打开：

```text
http://localhost:5176
```

## 可选密钥

搜索优先级：

- `BRAVE_SEARCH_API_KEY`
- `BING_SEARCH_API_KEY`
- `TAVILY_API_KEY`
- `SERPAPI_KEY` 或 `SERPAPI_API_KEY`
- 未配置时尝试 DuckDuckGo 公开搜索

分析增强：

- `OPENAI_API_KEY`
- `OPENAI_MODEL`

不配置 OpenAI 密钥时，应用会使用本地规则生成大纲和分析。
