/** 应用启动、定时刷新与运行时事件订阅。 */

import { registerAppEvents } from "./app-events.js";
import { ensurePanelLoaded, ensureShellFragments } from "./panel-loader.js";
import {
    connectRuntimeEventStream,
    isRuntimeStreamConnected,
    shouldPollMessages,
    shouldPollOverview,
} from "./runtime-events.js";

const MESSAGE_RUNTIME_EVENT_TYPES = new Set(["message_queued", "message_processed", "message_failed"]);

function isPageVisible() {
    return document.visibilityState === "visible";
}

/** 首屏只需概览；非仪表盘时再懒加载当前 Tab。 */
export function shouldLoadActiveTabOnBootstrap(activeTab) {
    const tab = String(activeTab || "").trim();
    return Boolean(tab) && tab !== "dashboard";
}

function shouldRefreshMessages(actions) {
    const state = actions.getState();
    return state.activeTab === "messages" || (Array.isArray(state.messages) && state.messages.length > 0);
}

export async function bootstrapApp(actions) {
    try {
        actions.setStatus("正在初始化控制台...");
        const activeTab = actions.getState().activeTab;
        actions.updateHeaderForTab(activeTab);
        await ensureShellFragments(actions.elements, activeTab);
        registerAppEvents(actions);
        // 消息类型标签体积小，且消息 Tab 懒加载时需要；与概览并行即可。
        await Promise.all([
            actions.syncMessageTypeLabels(),
            actions.loadOverview(),
        ]);
        if (shouldLoadActiveTabOnBootstrap(activeTab)) {
            await actions.refreshCurrentTab();
        }
        actions.setStatus("控制台已就绪", "good");
    } catch (error) {
        actions.setStatus(`初始化失败：${error.message}`, "bad");
    }
}

function refreshOverviewFromRuntimeEvent(actions, payload) {
    const metrics = payload?.payload?.metrics;
    if (metrics && typeof metrics === "object") {
        actions.applyOverviewMetrics(metrics);
        return;
    }
    actions.loadOverview().catch(() => {});
}

function refreshSecondaryTabs(actions) {
    const activeTab = actions.getState().activeTab;
    if (activeTab === "messages" || activeTab === "ai-assistant" || activeTab === "dashboard") {
        return;
    }
    actions.refreshCurrentTab().catch((error) => {
        actions.setStatus(`自动刷新失败：${error.message}`, "bad");
    });
}

export function startAppRuntime(actions) {
    connectRuntimeEventStream({
        onRuntimeEvent(payload) {
            const eventType = String(payload?.type || "");
            if (eventType === "connected") {
                if (!isPageVisible()) {
                    return;
                }
                if (shouldRefreshMessages(actions)) {
                    actions.refreshMessagesByPoll().catch(() => {});
                }
                actions.loadOverview().catch(() => {});
                return;
            }
            if (!MESSAGE_RUNTIME_EVENT_TYPES.has(eventType)) {
                return;
            }
            if (!isPageVisible()) {
                // 不可见时仍增量更新概览指标，回到前台时消息再补拉。
                refreshOverviewFromRuntimeEvent(actions, payload);
                return;
            }
            if (shouldRefreshMessages(actions)) {
                actions.refreshMessagesByPoll().catch(() => {});
            }
            refreshOverviewFromRuntimeEvent(actions, payload);
        },
    });

    window.setInterval(() => {
        if (!isPageVisible() || !actions.getState().overview) {
            return;
        }
        actions.renderOverview();
    }, actions.overviewRenderTickMs);

    window.setInterval(() => {
        if (!isPageVisible()) {
            return;
        }
        if (!shouldPollOverview()) {
            return;
        }
        actions.loadOverview().catch((error) => {
            actions.setStatus(`概览自动刷新失败：${error.message}`, "bad");
        });
        refreshSecondaryTabs(actions);
    }, 1000);

    window.setInterval(() => {
        if (!isPageVisible()) {
            return;
        }
        if (isRuntimeStreamConnected()) {
            // SSE 正常时消息列表只靠事件刷新，跳过轮询。
            return;
        }
        if (!shouldRefreshMessages(actions)) {
            return;
        }
        if (!shouldPollMessages()) {
            return;
        }
        actions.refreshMessagesByPoll();
    }, 1000);

    document.addEventListener("visibilitychange", () => {
        if (!isPageVisible()) {
            return;
        }

        actions.loadOverview().catch((error) => {
            actions.setStatus(`概览刷新失败：${error.message}`, "bad");
        });
        if (shouldRefreshMessages(actions)) {
            actions.refreshMessagesByPoll();
        }
        refreshSecondaryTabs(actions);
    });
}

export { ensurePanelLoaded };
