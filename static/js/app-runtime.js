/** 应用启动、定时刷新与运行时事件订阅。 */

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

export async function bootstrapApp(actions) {
    try {
        actions.setStatus("正在初始化控制台...");
        actions.updateHeaderForTab(actions.getState().activeTab);
        await actions.syncMessageTypeLabels();
        await actions.loadOverview();
        await Promise.all([
            actions.loadMessages(),
            actions.loadUsers(),
            actions.loadPlugins(),
            actions.loadPluginLogs(),
            actions.loadSettings(),
            actions.loadAiAssistant(),
            actions.loadLogs(),
        ]);
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
                actions.refreshMessagesByPoll().catch(() => {});
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
            actions.refreshMessagesByPoll().catch(() => {});
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
        actions.refreshMessagesByPoll();
        refreshSecondaryTabs(actions);
    });
}
