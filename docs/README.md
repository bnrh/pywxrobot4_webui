# wxrobot_webui 文档

wxrobot_webui 是面向 pywxrobot4 的 Web 控制台与插件运行时。它负责接收微信消息回调、异步调度 Python 插件、管理插件配置与状态，并提供一个可操作的前端界面来查看消息、执行功能插件、配置 AI 工具代理和排查运行问题。

## 文档导航

- [快速开始](getting-started.md)：环境准备、启动顺序、默认端口、首次接入步骤。
- [控制台说明](console-guide.md)：各个页面的用途、常用操作和相关接口入口。
- [插件系统](plugins.md)：插件运行模型、内置插件目录、配置方式和调度机制。
- [智能插件](ai-assistant.md)：AI 厂商配置、MCP 工具调用、对话与任务模型。
- [开发指南](development.md)：如何编写、调试和验证新的 Python 插件。
- [架构与性能优化](optimizations.md)：消息批量处理、SQLite 写缓冲、统一 HTTP、前端懒加载与插件元数据等近期优化。

## 项目定位

当前项目包含三层核心能力：

1. Web UI 与运行时：由 [main.py](../main.py)、[server](../server) 与 [runtime](../runtime) 提供页面、API、消息队列和插件生命周期管理。
2. Python 插件系统：由 [manager](../manager)（含 `plugin_base`）和 [plugins](../plugins) 目录中的插件模块构成。
3. AI 工具代理：由 [ai_assistant](../ai_assistant) 提供多厂商模型配置、MCP 工具发现与调用、对话持久化与异步任务执行。

## 推荐阅读顺序

1. 初次部署：先看 [快速开始](getting-started.md)。
2. 日常运营：再看 [控制台说明](console-guide.md) 和 [插件系统](plugins.md)。
3. 接入 AI：补看 [智能插件](ai-assistant.md)。
4. 二次开发：看 [开发指南](development.md)。
5. 了解近期性能与工程化改动：看 [架构与性能优化](optimizations.md)。

## 目录速览

- [main.py](../main.py)：服务启动入口。
- [server](../server)：FastAPI 应用壳、中间件、页面资源与 API schema。
- [runtime](../runtime)：消息队列、心跳、插件运行时与 SSE 事件。
- [core](../core)：系统配置、SQLite 连接、wxrobot API 客户端。
- [messaging](../messaging)：消息模型与最近消息持久化。
- [utils/http_client.py](../utils/http_client.py)：统一异步 httpx 客户端。
- [ai_assistant](../ai_assistant)：AI 厂商配置、MCP 工具执行、对话与任务管理。
- [manager](../manager)：插件发现、热重载、调度、周期任务与插件基类。
- [plugins](../plugins)：全部消息插件、功能插件和周期插件实现。
- [plugins/_plugin_sdk.py](../plugins/_plugin_sdk.py)：插件公共 SDK（归一化、HTTP、SQL 行解析等）。
- [frontend/index.html](../frontend/index.html)：控制台页面骨架（Tab / Modal 片段动态加载）。
- [static/js/app.js](../static/js/app.js)：控制台入口与模块组装。
- [static/js/plugin-config-form.js](../static/js/plugin-config-form.js)：结构化插件配置表单渲染。
- [webui.sqlite3](../webui.sqlite3)：系统设置、插件配置、插件状态、AI 对话等本地存储。
