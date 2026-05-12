# 开发指南

## 1. 新插件放在哪里

所有 Python 插件都放在 [plugins](../plugins) 目录下，文件名就是模块名。

例如：

- `plugins/room_message_guard.py`
- `plugins/export_room_members.py`
- `plugins/vmq_monitor.py`

## 2. 最小插件结构

一个最小消息插件通常至少包含：

```python
name = "hello_plugin"
description = "收到 ping 时回复 pong"
event_filters = ["text"]


async def handle_message(event, context):
    if str(event.normalized_content or "").strip() != "ping":
        return {"handled": False, "detail": ""}

    await context.api.send_text(
        wxid=event.conversation_wxid,
        content="pong",
        wxpid=event.normalized_wxpid,
    )
    return {"handled": True, "detail": "已回复 pong"}
```

## 3. 常用元数据

### `name`

插件内部标识。

### `description`

插件在控制台展示的说明文字。

### `event_filters`

消息触发范围，例如：

- `text`
- `image`
- `video`
- `file`
- `group`
- `notice`
- `sysmsg`

### `scope_targets`

配置作用范围声明，目前常见值有：

- `rooms`
- `friend_labels`
- `biz`

### `schedule`

周期插件的调度描述，例如指定间隔配置字段与默认周期。

## 4. 可用钩子

当前插件系统支持以下入口：

- `startup(context)`
- `shutdown(context)`
- `handle_message(event, context)`
- `execute(context)`
- `tick(context)`
- `on_hot_reload(hot_reload, context)`

一般建议：

- 消息插件实现 `handle_message`。
- 功能插件实现 `execute`。
- 周期任务实现 `tick` 与 `schedule`。
- 有初始化需求时再加 `startup`。

## 5. `context` 能做什么

### `context.api`

统一调用 wxrobot_api，例如：

- 发送消息
- 获取联系人
- 获取群成员
- 获取聊天记录
- 设置标签
- 删除群成员

### `context.logger`

输出结构化日志，支持 `debug`、`info`、`warning`、`error`。

### `context.state`

持久化插件状态，适合存：

- 计数器
- 去重记录
- 挂起任务信息
- 上次执行结果摘要

### `context.hot_reload`

读取当前热重载信息，例如是否因文件变更而触发重新载入。

## 6. 结构化配置建议

如果插件需要配置，优先写 `config_schema`，而不是要求操作者手写 JSON。

当前仓库已经广泛使用的字段类型包括：

- `text`
- `textarea`
- `number`
- `checkbox`
- `select`
- `multi-checkbox`
- `string-list`
- `object-list`

如果配置项依赖群聊、标签或 wxpid，优先复用已有 `options_source`：

- `room_options`
- `label_options`
- `wxpid_options`

## 7. 编写插件时的几个约定

### 未命中路径尽量静默

如果消息不属于当前插件处理范围，返回：

```python
{"handled": False, "detail": ""}
```

这样可以避免消息中心和插件日志里出现大量无意义噪音。

### 优先做服务端聚合，而不是把大列表交给模型或页面

如果你的需求本质是统计、分页、交集、筛选，优先在服务端完成计算，再把结果返回出去。

### 使用相对路径

涉及导出路径或上传素材时，尽量以项目根目录为基准使用相对路径，避免把个人机器绝对路径写死到配置里。

## 8. 验证建议

修改插件后，优先做最小验证：

```powershell
python -m py_compile plugins/你的插件.py
```

再配合：

- 控制台“消息中心”确认消息是否触发。
- 控制台“插件日志”确认结构化日志是否合理。
- 如有必要，写一个最小脚本直接调用插件内部辅助函数验证分类、解析和配置归一化逻辑。

## 9. 调试建议

排查插件问题时，建议顺序：

1. 看“消息中心”有没有收到消息。
2. 看 `event_filters` 和消息类型是否匹配。
3. 看配置是否命中当前作用范围。
4. 看“插件日志”中的结构化数据。
5. 必要时用 `context.state` 保存最近一次中间结果，便于复盘。

## 10. 一个更完整的插件样例参考

可以优先参考这些现成插件：

- [plugins/accept_user_request.py](../plugins/accept_user_request.py)：消息匹配、规则配置、好友操作。
- [plugins/room_message_guard.py](../plugins/room_message_guard.py)：复杂规则配置、群成员读取、状态去重。
- [plugins/export_room_members.py](../plugins/export_room_members.py)：功能插件、导出文件、热重载执行。
- [plugins/vmq_monitor.py](../plugins/vmq_monitor.py)：消息解析、外部服务推送、周期心跳。
