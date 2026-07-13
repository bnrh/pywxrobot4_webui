# 架构与性能优化

本文汇总近期落地的运行时、数据库、插件生态与前端工程化优化。实现细节以代码为准；二次开发请同时阅读 [开发指南](development.md) 与 [插件系统](plugins.md)。

## 1. 消息与联系人通路

### 批量 enrichment

消息入库后的联系人 / 群成员补全改为批量预取（`enrich_messages_batch`），避免对每条消息串行打 API。

相关路径：消息仓储与 runtime enrichment 逻辑。

### 插件目标列表

控制台拉取群聊 / 标签等插件目标时：

- 按已登录 `wxpid` **并行**请求；
- 结果带 TTL 缓存（默认约 5 分钟），减少重复全量扫描。

相关路径：[app_builders.py](../app_builders.py)、[contact_directory_cache.py](../contact_directory_cache.py)。

## 2. 统一异步 HTTP

对外 HTTP 统一走 [utils/http_client.py](../utils/http_client.py)（`httpx.AsyncClient`），包括：

- `request` / `get_text` / `get_bytes` / `post_json`
- 进程内共享客户端，服务关闭时 `aclose_shared_http_client`

插件侧请优先使用 [plugins/_plugin_sdk.py](../plugins/_plugin_sdk.py) 封装：

| SDK API | 用途 |
| --- | --- |
| `async_http_get` | GET 文本 |
| `async_http_post` | POST（JSON / form / files） |
| `async_http_get_bytes` | 下载二进制 |
| `async_http_request` | 需要完整 Response（headers / cookies）时 |
| `post_json_request` | 兼容旧名的 JSON POST |

AI 助手、MCP、插件外部推送等均应复用上述链路，避免再引入 `urllib.request` 同步阻塞。

## 3. 数据库与并发

### 线程局部连接 + WAL

[core/db_connection.py](../core/db_connection.py) 为每个线程缓存 SQLite 连接：

- `check_same_thread=False` + `PRAGMA journal_mode=WAL`
- `busy_timeout`、`synchronous=NORMAL`
- 连接已关闭时自动重建

适合当前 FastAPI 异步 + 偶发线程混用的规模。写操作在 SQLite 层仍串行；若消息量继续增大，可再演进为独立写队列或 `aiosqlite`。

### 写锁与批量 commit

高频 Store（最近消息、插件日志、插件状态）通过：

- `sqlite_execute_write`：进程内按库路径加写锁，默认每 N 次写（`DEFAULT_WRITE_FLUSH_EVERY=8`）再 `commit`
- `FLUSH_NOW`：trim / 建表等关键写立即提交
- `sqlite_execute_read` / `flush_sqlite_writes`：读前 flush，保证本进程缓冲写入对读取可见

相关 Store：

- [messaging/store.py](../messaging/store.py)
- [manager/plugin_log_store.py](../manager/plugin_log_store.py)
- [manager/plugin_base.py](../manager/plugin_base.py) 中的 `PluginStateStore`

### 延迟批量裁剪

最近消息与插件日志允许短暂超出 `limit`（软溢出），并按写入次数触发 trim，避免每条写入都 `DELETE`。

可通过 `trim_now()` 在测试或停机前强制裁到 limit。

### 仓储统一读写

消息与插件日志经 repository 层统一读写，业务代码不再直接散落 SQL。

## 4. 前端刷新与首屏

### SSE 优先、轮询兜底

消息与部分指标在 SSE 正常时改为**事件驱动刷新**，减少与轮询的重叠请求；概览等仍保留较长间隔的兜底轮询。

### 首屏与 Tab 懒加载

- 首屏只加载概览与当前 Tab 所需数据；
- 其它 Tab / Modal 片段按需动态加载（[static/js/partials](../static/js/partials)、`panel-loader`）；
- `index.html` 已拆成骨架 + 片段，降低首包解析成本。

### Vite 构建与 DOM 安全构建

- 使用 Vite 打包前端资源，并用 git hash / dist 文件名刷新资源版本戳，避免缓存脏读；
- 提供安全 DOM 构建辅助（如 `el` / `text`），减少手写 `innerHTML`。
- 页面骨架通过 `frontend/index.html` 引用 **`static/dist`** 产物；改前端后务必执行 `npm run build`（会构建并 stamp）。
- 源码调试可直接加载 `/static/js/app.js`（不再 `import` CSS，样式仍由 HTML `<link>` 引入）；生产入口为 `static/js/app.entry.js`。
- Modal / Tab 面板为懒加载：事件绑定必须在片段注入之后执行（`registerAppEvents`），不要在入口过早绑定尚未存在的表单节点。

构建：

```powershell
npm run build
```

## 5. 插件生态

### `_plugin_sdk` 公共能力

大插件（如群聊 AI、近期图片下载）应把可复用逻辑放到 [plugins/_plugin_sdk.py](../plugins/_plugin_sdk.py)，例如：

- 文本 / wxpid / 房间作用域归一化
- `parse_int` / `parse_float` / `parse_datetime_value`
- SQL 行解析：`extract_sql_rows`、`get_mapping_value`
- API 结果：`is_success_ret`、`extract_api_error`
- 路径：`resolve_local_path`、`resolve_downloaded_file_path`
- 统一 HTTP（见第 2 节）

### UI 行为由插件元数据自声明

以下标志写在插件模块顶层，由 [manager](../manager) 读取并下发给控制台，**不必再改** [server/app_config.py](../server/app_config.py) 白名单：

```python
direct_execute = True    # 功能插件一键执行，跳过执行弹窗
message_summary = True   # 消息汇总类配置渲染特判
```

当前已自声明的示例：

| 插件 | `direct_execute` | `message_summary` |
| --- | --- | --- |
| `room_msg_summary` | ✓ | ✓ |
| `user_msg_summary` | ✓ | ✓ |
| `export_contacts` | ✓ |  |
| `download_recent_user_images` | ✓ |  |
| `dont_revoke` | ✓ |  |

新增同类插件时，只需在模块内声明上述布尔字段。

### 遗留模块别名

`invite_to_toom` 已迁为正名 `invite_to_room`；配置与状态会在启动时迁移，发现列表不再展示遗留拼写模块。

## 6. 代码结构整理（便于继续优化）

近期为支撑上述能力，同步做了模块拆分（不改变对外产品能力）：

| 区域 | 变化 |
| --- | --- |
| `manager/` | 插件发现 / 归一化 / Python 插件宿主拆包 |
| `ai_assistant/` | 厂商、MCP、对话任务拆包 |
| `static/js/` | 按领域拆分事件、视图、插件配置渲染；瘦身 `app.js` |
| `utils/normalize.py` | 统一 `normalize_text` / `is_truthy` / `normalize_wxpid` |

## 7. 后续可选方向

在现有规模下上述方案足够；若压力继续上升，可按优先级考虑：

1. SQLite 独立写队列或 `aiosqlite` 全异步化。
2. 消息 / 日志 Store 按业务再拆库文件，降低写锁竞争。
3. 前端关键列表虚拟滚动与更细的 SSE 事件粒度。

## 8. 相关测试入口

```powershell
python -m pytest tests/test_db_connection.py tests/test_message_store_trim.py tests/test_plugin_sdk.py tests/test_app_builders.py tests/test_http_client.py -q
```
