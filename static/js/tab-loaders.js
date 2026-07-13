/** 各 Tab 数据加载与刷新。 */

export function createTabLoaders(getState, deps) {
    async function loadPluginTargets(force = false) {
        const state = getState();
        if (!force && state.pluginTargets) {
            return state.pluginTargets;
        }
        state.pluginTargets = await deps.api.getPluginTargets();
        return state.pluginTargets;
    }

    async function loadPluginTargetsIfNeeded(plugin) {
        if (!deps.needsPluginTargets(plugin)) {
            return getState().pluginTargets;
        }
        return loadPluginTargets();
    }

    async function loadOverview() {
        deps.setOverviewData(await deps.api.getOverview());
        deps.renderOverview();
    }

    async function loadMessages() {
        const state = getState();
        const payload = await deps.api.getMessages(50);
        state.messages = payload.messages || [];
        deps.renderMessages();
    }

    async function loadUsers() {
        const state = getState();
        state.users = await deps.api.getUsers();
        state.pluginTargets = null;
        deps.renderUsers();
    }

    async function loadPlugins() {
        const payload = await deps.api.getPlugins();
        deps.setPluginsPayload(payload.plugins || []);
    }

    async function loadPluginLogs(
        moduleName = getState().selectedPluginLogModule,
        level = getState().selectedPluginLogLevel,
        keyword = getState().selectedPluginLogKeyword,
    ) {
        const state = getState();
        const payload = await deps.api.getPluginLogs(moduleName, 240, level, keyword);
        state.pluginLogs = payload;
        state.selectedPluginLogModule = payload.module_name || "";
        state.selectedPluginLogLevel = payload.level || "";
        state.selectedPluginLogKeyword = payload.keyword || "";
        deps.renderPluginLogs();
    }

    function schedulePluginLogKeywordRefresh() {
        if (deps.getPluginLogFilterTimerId() !== null) {
            window.clearTimeout(deps.getPluginLogFilterTimerId());
        }
        deps.setPluginLogFilterTimerId(window.setTimeout(() => {
            deps.setStatus("正在按关键词筛选插件日志...");
            loadPluginLogs(
                getState().selectedPluginLogModule,
                getState().selectedPluginLogLevel,
                getState().selectedPluginLogKeyword,
            )
                .then(() => {
                    deps.setStatus("插件日志已更新", "good");
                })
                .catch((error) => {
                    deps.setStatus(`插件日志关键词筛选失败：${error.message}`, "bad");
                });
        }, 250));
    }

    async function loadSettings() {
        getState().settings = await deps.api.getSettings();
        deps.renderSettings();
    }

    async function loadLogs(fileName = getState().selectedLogFile) {
        const state = getState();
        state.logs = await deps.api.getLogs(fileName, 1000, state.logFilters);
        state.selectedLogFile = state.logs.active_file || "";
        deps.renderLogs();
    }

    async function refreshMessagesByPoll() {
        if (deps.getMessagePollInFlight()) {
            return deps.getMessagePollInFlight();
        }

        const pollPromise = (async () => {
            try {
                await loadMessages();
                deps.handleMessagePollSuccess();
            } catch (error) {
                deps.handleMessagePollFailure(error);
            } finally {
                deps.setMessagePollInFlight(null);
            }
        })();
        deps.setMessagePollInFlight(pollPromise);
        return pollPromise;
    }

    async function refreshCurrentTab() {
        switch (getState().activeTab) {
            case "dashboard":
                await loadOverview();
                break;
            case "messages":
                await loadMessages();
                break;
            case "users":
                await loadUsers();
                break;
            case "features":
                await loadPlugins();
                break;
            case "ai-assistant":
                await deps.loadAiAssistant();
                break;
            case "plugins":
                await loadPlugins();
                break;
            case "plugin-logs":
                await loadPluginLogs();
                break;
            case "settings":
                await loadSettings();
                break;
            case "logs":
                await loadLogs();
                break;
            default:
                break;
        }
    }

    return {
        loadOverview,
        loadMessages,
        loadUsers,
        loadPlugins,
        loadPluginLogs,
        loadSettings,
        loadLogs,
        loadPluginTargets,
        loadPluginTargetsIfNeeded,
        schedulePluginLogKeywordRefresh,
        refreshMessagesByPoll,
        refreshCurrentTab,
    };
}
