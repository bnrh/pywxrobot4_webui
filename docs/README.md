# wxrobot_webui 文档

wxrobot_webui 是面向 wxrobot_api 的 Web 控制台与插件运行时。它负责接收微信消息回调、异步调度 Python 插件、管理插件配置与状态，并提供一个可操作的前端界面来查看消息、执行功能插件、配置 AI 工具代理和排查运行问题。

## 文档导航

- [快速开始](getting-started.md)：环境准备、启动顺序、默认端口、首次接入步骤。
- [控制台说明](console-guide.md)：各个页面的用途、常用操作和相关接口入口。
- [插件系统](plugins.md)：插件运行模型、内置插件目录、配置方式和调度机制。
- [智能插件](ai-assistant.md)：AI 厂商配置、MCP 工具调用、对话与任务模型。
- [开发指南](development.md)：如何编写、调试和验证新的 Python 插件。

## 项目定位

当前项目包含三层核心能力：

1. Web UI 与运行时：由 [main.py](../main.py) 和 [server.py](../server.py) 提供页面、API、消息队列和插件生命周期管理。
2. Python 插件系统：由 [manager.py](../manager.py)、[plugin_base.py](../plugin_base.py) 和 [plugins](../plugins) 目录中的插件模块构成。
3. AI 工具代理：由 [ai_assistant.py](../ai_assistant.py) 提供多厂商模型配置、MCP 工具发现与调用、对话持久化与异步任务执行。

## 推荐阅读顺序

1. 初次部署：先看 [快速开始](getting-started.md)。
2. 日常运营：再看 [控制台说明](console-guide.md) 和 [插件系统](plugins.md)。
3. 接入 AI：补看 [智能插件](ai-assistant.md)。
4. 二次开发：最后看 [开发指南](development.md)。

## 目录速览

- [main.py](../main.py)：服务启动入口。
- [server.py](../server.py)：FastAPI 应用、页面接口、插件运行时、消息回调入口。
- [config.py](../config.py)：系统配置、SQLite 存储、兼容旧配置迁移。
- [ai_assistant.py](../ai_assistant.py)：AI 厂商配置、MCP 工具执行、对话与任务管理。
- [manager.py](../manager.py)：插件发现、热重载、调度、周期任务。
- [plugin_base.py](../plugin_base.py)：插件上下文、日志、状态存储抽象。
- [plugins](../plugins)：全部消息插件、功能插件和周期插件实现。
- [frontend/index.html](../frontend/index.html)：控制台页面骨架。
- [static/js/app.js](../static/js/app.js)：控制台交互与页面逻辑。
- [static/js/plugin-config-form.js](../static/js/plugin-config-form.js)：结构化插件配置表单渲染。
- [webui.sqlite3](../webui.sqlite3)：系统设置、插件配置、插件状态、AI 对话等本地存储。
