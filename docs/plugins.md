# 插件系统

## 1. 插件运行模型

当前插件系统由 [manager.py](../manager.py)、[plugin_base.py](../plugin_base.py) 和 [plugins](../plugins) 目录共同组成。

核心链路如下：

1. wxrobot_api 将消息回调到 `/messages`。
2. [server.py](../server.py) 将消息写入异步队列。
3. Worker 协程从队列中取出消息。
4. [manager.py](../manager.py) 依次调度已启用插件。
5. 插件通过 `context.api` 调用 wxrobot_api，通过 `context.logger` 记录结构化日志，通过 `context.state` 持久化状态。

## 2. 插件类型

当前仓库里的插件大致分成三类：

### 内置消息插件

依赖消息触发，通常实现 `handle_message(event, context)`。

典型场景：

- 自动下载资源
- 自动通过好友请求
- 入群欢迎
- 群聊禁言
- 收款通知转发

### 功能插件

主要靠手动执行，通常实现 `execute(context)`、`startup(context)` 或导出逻辑。

典型场景：

- 导出联系人
- 导出群成员
- 导出聊天记录
- 群成员去重报表
- 批量标签整理

### 周期插件

依赖 `tick(context)` 和 `schedule` 周期调度执行。

典型场景：

- 微信进程巡检
- 心跳类插件

## 3. 生命周期与能力

当前支持的主要钩子：

- `startup(context)`：插件加载时执行。
- `shutdown(context)`：服务关闭或插件卸载时执行。
- `handle_message(event, context)`：处理消息回调。
- `execute(context)`：手动执行功能插件。
- `tick(context)`：周期任务入口。
- `on_hot_reload(hot_reload, context)`：文件发生变化后的热重载钩子。

`context` 提供的核心能力：

- `context.api`：统一访问 wxrobot_api。
- `context.logger`：输出结构化日志。
- `context.state`：使用 SQLite 持久化插件状态。
- `context.hot_reload`：当前调度前的热重载状态信息。

## 4. 配置模型

前端不再只依赖原始 JSON 文本配置。当前插件推荐使用 `config_schema` 描述结构化表单，交给 [static/js/plugin-config-form.js](../static/js/plugin-config-form.js) 渲染。

常见配置能力：

- 文本、数字、布尔值。
- 搜索型下拉框，如 `room_options`、`label_options`、`wxpid_options`。
- `object-list` 规则表格。
- 多选消息类型。
- 字符串列表。
- 图片上传与相对路径写回。
- 群成员选择器等插件增强能力。

## 5. 作用范围与消息过滤

插件层面目前常用两个机制：

### `event_filters`

用于判断插件是否应该处理某条消息，例如：

- `text`
- `image`
- `video`
- `file`
- `group`
- `notice`
- `sysmsg`
- `friend_request`

### `scope_targets`

用于声明插件配置作用范围，当前常见目标包括：

- `rooms`
- `friend_labels`
- `biz`

## 6. 热重载与状态持久化

插件文件发生变化后，系统会在下一次调度时自动热重载，无需重启整个服务。

需要注意两点：

1. 热重载更适合无状态或轻状态插件。
2. 持久状态应放进 `context.state`，不要依赖模块级临时变量跨重载保存。

`context.state` 的数据会落在 [webui.sqlite3](../webui.sqlite3) 的 `plugin_state` 表。

## 7. 内置插件目录

### 消息插件

| 插件 | 触发方式 | 说明 |
| --- | --- | --- |
| `auto_download_image` | 图片消息 | 自动下载原图 |
| `auto_download_resources` | 视频 / 文件消息 | 按范围自动下载资源 |
| `accept_user_request` | 好友请求 / 通知 | 自动通过好友并支持标签、欢迎语、免打扰 |
| `enter_room_tip` | 通知 / 系统消息 | 新成员入群后发送欢迎语或图片 |
| `invite_to_toom` | 好友请求 / 通知 / 文本 | 根据关键词自动拉群 |
| `openclaw_channel` | 群文本消息 | 转发消息到外部 Webhook |
| `room_message_guard` | 群消息 | 按分组消息类型进行群聊禁言治理 |
| `room_qrcode_guard` | 群图片消息 | 检测群聊图片是否包含二维码，警告后可移出发送成员，依赖 zxing-cpp Python 绑定 |
| `vmq_monitor` | 单聊消息 | 监听指定公众号收款消息并推送到外部服务 |

### 功能与周期插件

| 插件 | 类型 | 说明 |
| --- | --- | --- |
| `export_contacts` | 功能插件 | 导出当前好友列表到 CSV |
| `export_room_members` | 功能插件 | 导出指定群成员到 CSV，包含管理员字段 |
| `room_members_deduplication` | 功能插件 | 统计多个群聊组的重复成员并导出 CSV |
| `room_msg_summary` | 功能插件 | 导出指定群聊在时间窗口内的聊天记录 |
| `user_msg_summary` | 功能插件 | 导出指定好友在时间窗口内的聊天记录 |
| `classify_labels` | 功能插件 | 将群成员批量归类到好友标签 |
| `watch_wechat_processes` | 周期插件 | 巡检微信进程与登录账号缓存变化并自动重新 hook |

## 8. 近期能力变化

当前插件系统相对旧 README 已有几个重要变化：

1. 插件配置已普遍迁移到结构化表单模型。
2. 多个导出插件支持更稳定的 wxpid 选择与多进程处理。
3. `room_message_guard` 已支持内置管理员白名单与更细的消息类型分组。
4. AI 助手会优先通过聚合工具处理大群、大好友集场景，减少把全量列表交给模型。
5. 消息插件在未命中路径上已尽量静默，不再输出大量无效“忽略消息”日志。
6. `watch_wechat_processes` 现在会在启动、手动执行和周期巡检时立即读取当前登录账号，与系统缓存账号信息比对；只要发现账号切换或缓存不一致，就会直接重新 hook 并同步账号缓存。

## 9. 特别说明：群聊禁言插件

[room_message_guard.py](../plugins/room_message_guard.py) 现在使用以下消息分组：

1. 文本
2. 图片
3. 语音
4. 视频
5. 表情
6. 名片 / 位置 / 链接 / 文件 / 公众号名片
7. 视频号 / 视频号卡片
8. 小程序
9. 合并消息 / 聊天记录消息
10. 其他类型

同时，它会静默忽略以下消息类型：

- 引用消息
- 添加好友
- 微信初始化
- 通话状态通知
- 通话邀请
- 通知消息
- 系统消息
- 群公告
- 文件下载完成
- 转账

如果开启了移出群成员，插件会在真正调用删除接口前再次检查当前登录账号在该群里的身份；只有当前账号是群主或管理员时才会执行移除，否则只发送提示并记录警告日志。

## 10. 特别说明：群二维码检测插件

[room_qrcode_guard.py](../plugins/room_qrcode_guard.py) 用于检测指定群聊中的图片是否包含二维码。它的处理范围比群聊禁言插件更窄，只会在以下条件同时满足时启动检测：

1. 消息来自群聊。
2. 消息类型是图片。
3. 当前群聊已配置在 `room_ids` 生效列表中。
4. 运行环境已安装 `zxing-cpp`、`Pillow` 和 `numpy`。

当前插件会按下面的顺序执行：

1. 收到图片后先等待 2 秒，再开始后续处理。
2. 读取当前群成员，跳过机器人自己、群主和所有管理员。
3. 调用 `/cdn/image` 下载图片缩略图，当前固定使用 `flag=1`。
4. 用 `zxingcpp.read_barcodes(...)` 检测图片中是否存在二维码。
5. 如果命中二维码，先在群里发送提醒；如果启用了移出开关，再等待 3 到 5 秒，并在确认当前登录账号是该群群主或管理员后才把发送成员移出群聊。

插件当前支持 3 个配置项：

| 配置项 | 说明 |
| --- | --- |
| `kick_after_warning` | 是否在发送提醒后移出群成员 |
| `warning_template` | 提醒文本模版，支持 `@{user_name}`、`{user_name}`、`{room_name}` 占位符 |
| `room_ids` | 生效的群聊列表；如果为空，插件不会生效 |

需要注意的运行边界：

- 它不会处理非群聊消息，也不会处理非图片消息。
- 如果图片下载失败、图片路径不存在、二维码识别依赖缺失，或者识别过程报错，插件会记录日志并静默跳过本次检测。
- 如果图片里没有检测到二维码，插件会直接返回未处理，不产生提醒日志噪音。
- 为避免重复移人，同一成员在短时间内重复违规时，会复用待移出状态，不会重复进入移出队列。
- 如果当前登录账号不是群主或管理员，插件会保留群内提醒，但不会执行移除，并输出警告日志。

## 11. 特别说明：导出与成员类插件

当前与群成员相关的内置插件已经消费了管理员字段：

- `export_room_members`：导出结果包含 `is_admin`。
- `room_members_deduplication`：重复成员统计会排除群主与管理员。
- `room_message_guard`：默认把群主和管理员视为白名单成员。
