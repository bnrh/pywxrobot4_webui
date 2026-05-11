# webui 插件系统

这个目录提供了一个独立的 FastAPI 插件服务，用来接收微信消息推送并把消息分发给自定义插件处理。

## 设计说明

- 消息入口：插件服务默认监听 `POST /messages`
- 对接方式：将主服务配置文件里的 `base.post_api` 指向插件服务的回调地址
- 配置来源：插件服务启动时从项目根目录 `webui.sqlite3` 读取系统设置和插件配置；首次启动会自动从 `config.ini` 的 `[webui]` 段迁移
- 插件模型：只支持 `plugins/*.py` 文件，插件由 Python 运行时直接加载与热重载
- 插件 SDK：插件通过 `context.api`、`context.logger`、`context.state` 和 `context.hot_reload` 使用统一能力
- 处理机制：HTTP 回调只负责入队，真正的插件执行由后台 worker 异步完成，避免阻塞微信消息转发链路
- 管理页面：访问插件服务根路径 `/` 即可打开控制台，包含仪表盘、消息中心、插件管理、插件日志、系统设置、日志中心等视图

## 前端结构

- `frontend/index.html`：控制台页面骨架
- `static/css/app.css`：页面样式
- `static/js/api.js`：前端 API 调用封装
- `static/js/app.js`：页面状态、tab 切换和交互逻辑

## 内置插件

默认启用的插件：

- `plugins.auto_download_image`：收到图片消息时自动调用 `/cdn/image` 下载原图

内置可选插件：

- `plugins.accept_user_request`：自动通过好友请求，支持标签、欢迎语和免打扰
- `plugins.auto_download_resources`：按群聊或单聊配置下载图片、视频和文件
- `plugins.enter_room_tip`：检测成员入群后发送欢迎语或图片
- `plugins.export_room_members`：在启动或热重载时导出指定群成员列表到 CSV
- `plugins.invite_to_toom`：根据好友请求验证词或文本关键词自动拉群
- `plugins.monitor_biz`：监控公众号文章 XML，并支持通知群聊、落盘和接口转发
- `plugins.openclaw_channel`：监听指定群聊文本并转发到外部 Webhook

## 启动方式

先启动主服务：

```powershell
python main.py
```

确认主服务已经启动后，再启动插件服务：

```powershell
python -m webui
```

插件服务启动后会输出一条提示，告诉你当前应该把 `post_api` 设成哪个地址。

管理页面默认地址：

```text
http://127.0.0.1:28080/
```

## 主服务配置

在 `config.ini` 中增加或修改：

```ini
[base]
api_port = 23235
post_api = http://127.0.0.1:28080/messages
```

修改后重启 `main.py`，后续所有收到的微信消息都会被推送到插件服务。

## webui 配置存储

插件服务会将以下内容保存到项目根目录的 `webui.sqlite3`：

- 系统设置：`host`、`port`、`callback_path`、`api_base_url`、`request_timeout`、`worker_count`、`queue_size`
- 插件启停状态
- 插件 JSON 配置

首次升级到当前版本时，会自动把原先 `config.ini` 中 `[webui]` 段的配置迁移到 SQLite。

## 控制台功能

- 消息中心：查看最近推送到插件服务的消息，以及每条消息的插件处理结果
- 插件管理：启动、停止插件，并编辑插件 JSON 配置
- 插件日志：查看插件输出的结构化日志，支持按插件筛选并查看详情
- 系统设置：修改 `api_base_url`、`port`、`callback_path` 等全局设置
- 日志中心：查看 `logs` 目录下最新日志文件的最近输出

## 消息字段

当前插件系统兼容的核心消息字段包括：

- `msgid`：消息 ID
- `msg_type` / `local_type`：消息类型
- `sender`：会话 wxid，群消息时通常是群 ID
- `room_sender`：群消息中的真实发送人 wxid
- `recipient`：当前登录微信账号 wxid
- `wxpid`：微信进程 ID
- `content`：原始消息内容

## 编写插件

在 `plugins` 下新增 Python 文件，例如：

```python
name = "hello_plugin"
description = "收到 ping 时自动回复 pong"
event_filters = ["text"]


async def startup(context):
    context.logger.info("插件启动", {"plugin": context.plugin_name})


async def handle_message(event, context):
    if str(event.normalized_content or "").strip() != "ping":
        return {"handled": False, "detail": "不是 ping"}

    total_replies = context.state.increment("reply_count", 1)
    await context.api.send_text(
        wxid=event.conversation_wxid,
        content="pong",
        wxpid=event.normalized_wxpid,
    )
    context.logger.info("已回复 pong", {"total_replies": total_replies})
    return {"handled": True, "detail": f"已回复 pong ({total_replies})"}


async def on_hot_reload(hot_reload, context):
    context.logger.warning("检测到插件文件变更，已触发热重载", hot_reload)
```

## Python 插件 SDK

- `context.api`：统一 HTTP SDK，内置消息发送、资源下载、好友请求、标签、群成员、SQL 查询等 wxrobot_api 常用接口包装
- `context.logger`：统一结构化日志，支持 `debug`、`info`、`warning`、`error` 和 `scope(name)`
- `context.state`：基于 `webui.sqlite3` 的持久状态存储，支持 `get`、`set`、`delete`、`has`、`keys`、`values`、`entries`、`get_all`、`clear`、`increment`、`namespace`
- `context.hot_reload`：当前消息处理前的热重载状态，包含 `changed`、`reason`、`current_revision`、`previous_revision`
- 可选钩子：`startup(context)`、`shutdown(context)`、`handle_message(event, context)`、`execute(context)`、`tick(context)`、`on_hot_reload(hot_reload, context)`

插件文件发生变更后，无需重启 WebUI 服务，下一次调度该插件时会自动载入新代码，并在实现了 `onHotReload` 时触发热重载钩子。

启用新插件的方式：

```powershell
在管理页面启用插件后重载运行配置即可。
```

## 图片自动下载插件配置

可以在管理页面中为 `plugins.auto_download_image` 写入如下 JSON 配置：

```json
{"flag":3,"wait":true,"timeout":20}
```

字段说明：

- `flag`：1 缩略图，2 压缩图，3 原图
- `wait`：是否等待下载完成后再结束插件调用
- `timeout`：等待下载结果的秒数
