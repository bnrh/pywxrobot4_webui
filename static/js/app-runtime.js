/** 应用启动、定时刷新与运行时事件订阅。 */

import { connectRuntimeEventStream, shouldPollMessages } from "./runtime-events.js";

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

export function startAppRuntime(actions) {
    connectRuntimeEventStream({
        onRuntimeEvent(payload) {
            const eventType = String(payload?.type || "");
            if (eventType === "message_queued" || eventType === "message_processed" || eventType === "message_failed") {
                actions.refreshMessagesByPoll().catch(() => {});
                actions.loadOverview().catch(() => {});
            }
        },
    });

    window.setInterval(() => {
        if (document.visibilityState === "hidden" || !actions.getState().overview) {
            return;
        }
        actions.renderOverview();
    }, actions.overviewRenderTickMs);

    window.setInterval(() => {
        if (document.visibilityState === "hidden") {
            return;
        }
        actions.loadOverview().catch((error) => {
            actions.setStatus(`概览自动刷新失败：${error.message}`, "bad");
        });
        const activeTab = actions.getState().activeTab;
        if (activeTab !== "messages" && activeTab !== "ai-assistant") {
            actions.refreshCurrentTab().catch((error) => {
                actions.setStatus(`自动刷新失败：${error.message}`, "bad");
            });
        }
    }, actions.overviewPollIntervalMs);

    window.setInterval(() => {
        if (document.visibilityState === "hidden") {
            return;
        }
        if (!shouldPollMessages()) {
            return;
        }
        actions.refreshMessagesByPoll();
    }, 1000);

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState !== "visible") {
            return;
        }

        actions.loadOverview().catch((error) => {
            actions.setStatus(`概览刷新失败：${error.message}`, "bad");
        });
        actions.refreshMessagesByPoll();
        const activeTab = actions.getState().activeTab;
        if (activeTab !== "messages" && activeTab !== "ai-assistant") {
            actions.refreshCurrentTab().catch((error) => {
                actions.setStatus(`自动刷新失败：${error.message}`, "bad");
            });
        }
    });
}
