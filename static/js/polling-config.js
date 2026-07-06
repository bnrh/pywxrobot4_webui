/** 控制台轮询与任务状态刷新间隔（毫秒）。 */

export const OVERVIEW_POLL_INTERVAL_MS = 15000;
export const MESSAGE_POLL_INTERVAL_MS = 3000;
export const MESSAGE_POLL_INTERVAL_SSE_MS = 12000;
export const OVERVIEW_RENDER_TICK_MS = 1000;
export const AI_ASSISTANT_JOB_POLL_INTERVAL_MS = 1200;
export const AI_ASSISTANT_ACTIVE_JOB_STATUSES = new Set(["queued", "running", "stopping"]);
export const AI_ASSISTANT_TERMINAL_JOB_STATUSES = new Set(["completed", "failed", "stopped"]);
export const MANUAL_PLUGIN_EXECUTION_POLL_INTERVAL_MS = 1200;
export const MANUAL_PLUGIN_EXECUTION_ACTIVE_STATUSES = new Set(["queued", "running", "stopping"]);
export const MANUAL_PLUGIN_EXECUTION_TERMINAL_STATUSES = new Set(["completed", "failed", "stopped"]);
