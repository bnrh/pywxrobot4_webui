/** 控制台轮询与任务状态刷新间隔（毫秒）。 */

/** SSE 断开时的概览全量轮询间隔。 */
export const OVERVIEW_POLL_INTERVAL_MS = 15000;
/** SSE 正常时的概览全量兜底同步间隔（指标主要由 SSE 增量更新）。 */
export const OVERVIEW_POLL_INTERVAL_SSE_MS = 60000;
/** SSE 断开时的消息列表轮询间隔。 */
export const MESSAGE_POLL_INTERVAL_MS = 3000;
/** SSE 正常时不轮询消息列表（仅事件驱动）；保留常量供兼容/测试引用。 */
export const MESSAGE_POLL_INTERVAL_SSE_MS = 0;
export const OVERVIEW_RENDER_TICK_MS = 1000;
export const AI_ASSISTANT_JOB_POLL_INTERVAL_MS = 1200;
export const AI_ASSISTANT_ACTIVE_JOB_STATUSES = new Set(["queued", "running", "stopping"]);
export const AI_ASSISTANT_TERMINAL_JOB_STATUSES = new Set(["completed", "failed", "stopped"]);
export const MANUAL_PLUGIN_EXECUTION_POLL_INTERVAL_MS = 1200;
export const MANUAL_PLUGIN_EXECUTION_ACTIVE_STATUSES = new Set(["queued", "running", "stopping"]);
export const MANUAL_PLUGIN_EXECUTION_TERMINAL_STATUSES = new Set(["completed", "failed", "stopped"]);
