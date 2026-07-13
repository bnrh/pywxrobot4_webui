/** 组装控制台控制器、渲染与 actions 门面。 */

import { api, getStoredApiToken, setStoredApiToken } from "./api.js";
import {
    AI_ASSISTANT_JOB_POLL_INTERVAL_MS,
    MANUAL_PLUGIN_EXECUTION_POLL_INTERVAL_MS,
    OVERVIEW_POLL_INTERVAL_MS,
    OVERVIEW_RENDER_TICK_MS,
} from "./polling-config.js";
import { formatJson, normalizeInlineText } from "./dom-utils.js";
import { syncMessageTypeLabels } from "./message-labels.js";
import { tabMeta } from "./tab-meta.js";
import { copyTextToClipboard } from "./clipboard-utils.js";
import { getMessagePollErrorText } from "./message-poll.js";
import {
    getPluginByModule as findPluginInList,
    getPluginDisplayName as resolvePluginDisplayName,
    handleManualPluginExecutionTransitions,
    hasPluginLogData,
    isDirectExecutePlugin,
    isManualPluginExecutionActive,
    needsPluginTargets,
    normalizeManualPluginExecution,
    sortPluginsForDisplay,
} from "./plugin-helpers.js";
import { renderOverviewGrid } from "./overview-view.js";
import { renderMessagesView } from "./message-view.js";
import { renderUsersView } from "./users-view.js";
import { readSettingsForm, renderSettingsView } from "./settings-view.js";
import { createAiAssistantController } from "./ai-assistant-controller.js";
import { createAiAssistantUiActions } from "./ai-assistant-ui-actions.js";
import { createTabLoaders } from "./tab-loaders.js";
import { createPluginModalActions } from "./plugin-modals.js";
import { updateHeaderForTab as syncHeaderForTab } from "./tab-ui.js";
import { waitForDuration } from "./async-utils.js";
import { createLogFilterActions, renderServiceLogs } from "./log-viewer.js";
import { renderPluginLogsView } from "./plugin-log-viewer.js";
import { renderPluginCards } from "./plugin-cards.js";
import {
    buildPluginConfigRenderModel,
    buildPluginExecuteRenderModel,
    buildStructuredPluginConfigPayload,
    getPluginModuleNameForForm,
} from "./plugin-config-render.js";
import {
    decodeAiAssistantModelSelection,
    normalizeAiAssistantJobStatus,
} from "./ai-assistant-data.js";
import { createAppState, queryAppElements } from "./app-state.js";

export function createAppContext() {
    const state = createAppState();
    const elements = queryAppElements();

    let logFilterTimerId = null;
    let pluginLogFilterTimerId = null;
    let messagePollInFlight = null;
    let manualPluginExecutionPollTimerId = null;
    let logFilterActions = null;

    let aiAssistantCtrl;
    let aiAssistantUi;
    let tabLoaders;
    let pluginModals;

    function setStatus(text, type = "") {
        elements.statusPill.textContent = text;
        elements.statusPill.className = `status-pill ${type}`.trim();
    }

    function setOverviewData(payload) {
        state.overview = payload;
        state.overviewFetchedAt = Date.now();
    }

    function scheduleManualPluginExecutionPoll() {
        if (manualPluginExecutionPollTimerId !== null) {
            window.clearTimeout(manualPluginExecutionPollTimerId);
            manualPluginExecutionPollTimerId = null;
        }
        if (!Array.isArray(state.plugins) || !state.plugins.some(isManualPluginExecutionActive)) {
            return;
        }
        manualPluginExecutionPollTimerId = window.setTimeout(() => {
            api.getPlugins()
                .then((payload) => {
                    if (Array.isArray(payload?.plugins)) {
                        setPluginsPayload(payload.plugins);
                    }
                })
                .catch((error) => {
                    setStatus(`插件执行状态刷新失败：${error.message}`, "bad");
                    if (Array.isArray(state.plugins) && state.plugins.some(isManualPluginExecutionActive)) {
                        scheduleManualPluginExecutionPoll();
                    }
                });
        }, MANUAL_PLUGIN_EXECUTION_POLL_INTERVAL_MS);
    }

    function setPluginsPayload(plugins) {
        const previousPlugins = Array.isArray(state.plugins) ? state.plugins : [];
        state.plugins = Array.isArray(plugins) ? plugins : [];
        renderPlugins();
        handleManualPluginExecutionTransitions(previousPlugins, state.plugins, setStatus);
        scheduleManualPluginExecutionPoll();
    }

    function applyPluginMutationResult(result) {
        if (result?.overview) {
            setOverviewData(result.overview);
            renderOverview();
        }
        if (Array.isArray(result?.plugins)) {
            setPluginsPayload(result.plugins);
        }
        if (result?.settings) {
            state.settings = result.settings;
            renderSettings();
        }
    }

    function getPluginByModule(moduleName) {
        return findPluginInList(state.plugins, moduleName);
    }

    function getPluginDisplayName(moduleName, fallback = "未知插件") {
        return resolvePluginDisplayName(state.plugins, state.pluginLogs, moduleName, fallback);
    }

    function getPluginLogById(logId) {
        return state.pluginLogs?.logs?.find((item) => item.internal_id === logId) || null;
    }

    function pluginRenderCtx() {
        return {
            api,
            elements,
            pluginTargets: state.pluginTargets,
            users: state.users,
            moduleState: {
                pluginConfigModule: state.pluginConfigModule,
                pluginExecuteModule: state.pluginExecuteModule,
            },
            getPluginByModule,
            getPluginModuleName: (formElement) => getPluginModuleNameForForm(formElement, elements, {
                pluginConfigModule: state.pluginConfigModule,
                pluginExecuteModule: state.pluginExecuteModule,
            }),
            setStatus,
        };
    }

    function buildPluginConfigRenderModelForPlugin(plugin) {
        return buildPluginConfigRenderModel(plugin, state.pluginTargets, state.users);
    }

    function buildPluginExecuteRenderModelForPlugin(plugin) {
        return buildPluginExecuteRenderModel(plugin, state.pluginTargets, state.users);
    }

    async function openPluginConfigModal(moduleName) {
        return pluginModals.openConfigModal(moduleName);
    }

    function closePluginConfigModal() {
        pluginModals.closeConfigModal();
    }

    function closePluginExecuteModal() {
        pluginModals.closeExecuteModal();
    }

    async function executePluginWithConfig(moduleName, config = {}) {
        return pluginModals.executeWithConfig(moduleName, config);
    }

    async function openPluginExecuteModal(moduleName) {
        return pluginModals.openExecuteModal(moduleName);
    }

    function handleMessagePollSuccess() {
        if (state.messagePollFailureCount > 0 && state.activeTab === "messages") {
            setStatus("消息自动刷新已恢复", "good");
        }
        state.messagePollFailureCount = 0;
    }

    function handleMessagePollFailure(error) {
        state.messagePollFailureCount += 1;
        if (state.activeTab === "messages") {
            setStatus(getMessagePollErrorText(error, state.messagePollFailureCount), "bad");
        }
    }

    function updateHeaderForTab(tabName) {
        syncHeaderForTab(elements, tabMeta, tabName);
    }

    function renderOverview() {
        renderOverviewGrid(elements, state.overview, state.overviewFetchedAt);
    }

    function renderUsers() {
        renderUsersView(elements, state.users);
    }

    function renderMessages() {
        const result = renderMessagesView(elements, {
            messages: state.messages,
            selectedMessageId: state.selectedMessageId,
            messageAutoFollow: state.messageAutoFollow,
        });
        state.selectedMessageId = result.selectedMessageId;
    }

    function renderPlugins() {
        const messagePlugins = sortPluginsForDisplay(state.plugins.filter((plugin) => plugin.message_dependent !== false));
        const featurePlugins = sortPluginsForDisplay(state.plugins.filter((plugin) => plugin.message_dependent === false));
        renderPluginCards(elements.pluginGrid, messagePlugins, "当前没有依赖消息的插件。", "message");
        renderPluginCards(elements.featurePluginGrid, featurePlugins, "当前没有不依赖消息的功能插件。", "feature");
    }

    function renderPluginLogs() {
        const result = renderPluginLogsView({
            elements,
            pluginLogs: state.pluginLogs,
            selection: {
                selectedPluginLogId: state.selectedPluginLogId,
                selectedPluginLogModule: state.selectedPluginLogModule,
                selectedPluginLogLevel: state.selectedPluginLogLevel,
                selectedPluginLogKeyword: state.selectedPluginLogKeyword,
            },
            resolvePluginDisplayName: (moduleName, fallback) => getPluginDisplayName(moduleName, fallback),
            hasPluginLogData,
        });
        state.selectedPluginLogId = result.selectedPluginLogId;
    }

    function renderSettings() {
        renderSettingsView(elements, state.settings, getStoredApiToken);
    }

    function renderLogs() {
        renderServiceLogs(elements, state.logs, state.logFilters);
    }

    async function reloadFromConfig() {
        setStatus("正在从 SQLite 配置库重载...");
        const result = await api.reloadPlugins();
        applyPluginMutationResult(result);
        const suffix = result.restart_required ? `，需要重启字段：${result.restart_required_fields.join(", ")}` : "";
        setStatus(`重载完成${suffix}`, result.restart_required ? "bad" : "good");
    }

    function switchTab(tabName) {
        state.activeTab = tabName;
        updateHeaderForTab(tabName);
        tabLoaders.refreshCurrentTab().catch((error) => {
            setStatus(`加载失败：${error.message}`, "bad");
        });
    }

    aiAssistantCtrl = createAiAssistantController(() => state, {
        api,
        setStatus,
        renderAiAssistant: () => aiAssistantUi.renderAiAssistant(),
        renderAiAssistantConversationList: () => aiAssistantUi.renderAiAssistantConversationList(),
        waitForDuration,
        aiJobPollIntervalMs: AI_ASSISTANT_JOB_POLL_INTERVAL_MS,
    });
    aiAssistantUi = createAiAssistantUiActions(() => aiAssistantCtrl.buildUiCtx(elements));
    tabLoaders = createTabLoaders(() => state, {
        api,
        setOverviewData,
        renderOverview,
        renderMessages,
        renderUsers,
        renderPlugins,
        renderPluginLogs,
        renderSettings,
        renderLogs,
        setPluginsPayload,
        setStatus,
        needsPluginTargets,
        loadAiAssistant: () => aiAssistantCtrl.load(),
        handleMessagePollSuccess,
        handleMessagePollFailure,
        getMessagePollInFlight: () => messagePollInFlight,
        setMessagePollInFlight: (value) => {
            messagePollInFlight = value;
        },
        getPluginLogFilterTimerId: () => pluginLogFilterTimerId,
        setPluginLogFilterTimerId: (value) => {
            pluginLogFilterTimerId = value;
        },
    });
    pluginModals = createPluginModalActions(() => state, {
        api,
        elements,
        setStatus,
        getPluginByModule,
        needsPluginTargets,
        loadPluginTargets: (force) => tabLoaders.loadPluginTargets(force),
        pluginRenderCtx,
        applyPluginMutationResult,
        normalizeManualPluginExecution,
        normalizeInlineText,
        isDirectExecutePlugin,
    });

    const appActions = {
        getState: () => state,
        elements,
        api,
        setStatus,
        setOverviewData,
        setStoredApiToken,
        switchTab,
        reloadFromConfig,
        updateHeaderForTab,
        syncMessageTypeLabels,
        applyPluginMutationResult,
        loadOverview: () => tabLoaders.loadOverview(),
        loadMessages: () => tabLoaders.loadMessages(),
        loadUsers: () => tabLoaders.loadUsers(),
        loadPlugins: () => tabLoaders.loadPlugins(),
        loadPluginLogs: (...args) => tabLoaders.loadPluginLogs(...args),
        loadPluginTargetsIfNeeded: (plugin) => tabLoaders.loadPluginTargetsIfNeeded(plugin),
        loadSettings: () => tabLoaders.loadSettings(),
        loadLogs: (...args) => tabLoaders.loadLogs(...args),
        loadAiAssistant: () => aiAssistantCtrl.load(),
        refreshCurrentTab: () => tabLoaders.refreshCurrentTab(),
        refreshMessagesByPoll: () => tabLoaders.refreshMessagesByPoll(),
        schedulePluginLogKeywordRefresh: () => tabLoaders.schedulePluginLogKeywordRefresh(),
        renderOverview,
        renderMessages,
        renderPluginLogs,
        renderSettings,
        renderAiAssistant: () => aiAssistantUi.renderAiAssistant(),
        renderAiAssistantConversationList: () => aiAssistantUi.renderAiAssistantConversationList(),
        readAiAssistantSettingsForm: () => aiAssistantUi.readAiAssistantSettingsForm(),
        applyAiAssistantPayload: (payload, preserveSelection = true) => aiAssistantCtrl.applyPayload(payload, preserveSelection),
        createAiAssistantConversation: () => aiAssistantCtrl.createConversation(),
        activateAiAssistantConversation: (conversationId) => aiAssistantCtrl.activateConversation(conversationId),
        clearAiAssistantConversation: () => aiAssistantCtrl.clearConversation(),
        stopAiAssistantChatJob: () => aiAssistantCtrl.stopChatJob(),
        pollAiAssistantChatJob: (jobId) => aiAssistantCtrl.pollChatJob(jobId),
        getAiAssistantCurrentConversationId: () => aiAssistantCtrl.getCurrentConversationId(),
        getAiAssistantCurrentSelection: () => aiAssistantCtrl.getCurrentSelection(),
        setAiAssistantProviderSelection: (...args) => aiAssistantCtrl.setProviderSelection(...args),
        normalizeAiAssistantJobStatus,
        decodeAiAssistantModelSelection,
        openAiAssistantConfigModal: () => aiAssistantUi.openAiAssistantConfigModal(),
        openAiAssistantToolsModal: () => aiAssistantUi.openAiAssistantToolsModal(),
        openAiAssistantConversationModal: () => aiAssistantUi.openAiAssistantConversationModal(),
        closeAiAssistantConfigModal: () => aiAssistantUi.closeAiAssistantConfigModal(),
        closeAiAssistantConversationModal: () => aiAssistantUi.closeAiAssistantConversationModal(),
        closeAiAssistantToolsModal: () => aiAssistantUi.closeAiAssistantToolsModal(),
        appendAiAssistantPromptPluginRow: () => aiAssistantUi.appendAiAssistantPromptPluginRow(),
        syncAiAssistantPromptPluginTableState: () => aiAssistantUi.syncAiAssistantPromptPluginTableState(),
        appendAiAssistantConfigRow: (providerKey) => aiAssistantUi.appendAiAssistantConfigRow(providerKey),
        syncAiAssistantConfigTableState: () => aiAssistantUi.syncAiAssistantConfigTableState(),
        syncAiAssistantPromptPluginCardState: (card) => aiAssistantUi.syncAiAssistantPromptPluginCardState(card),
        syncAiAssistantConfigRowState: (row) => aiAssistantUi.syncAiAssistantConfigRowState(row),
        openPluginConfigModal,
        openPluginExecuteModal,
        closePluginConfigModal,
        closePluginExecuteModal,
        executePluginWithConfig,
        getPluginByModule,
        getPluginDisplayName,
        getPluginLogById,
        buildPluginConfigRenderModelForPlugin,
        buildPluginExecuteRenderModelForPlugin,
        buildStructuredPluginConfigPayload: (form, plugin) => buildStructuredPluginConfigPayload(form, plugin),
        pluginRenderCtx,
        readSettingsForm: () => readSettingsForm(elements),
        applyLogFilters: (...args) => logFilterActions.applyLogFilters(...args),
        scheduleLogFilterRefresh: () => logFilterActions.scheduleLogFilterRefresh(() => logFilterTimerId, (value) => {
            logFilterTimerId = value;
        }),
        copyTextToClipboard,
        formatJson,
        overviewRenderTickMs: OVERVIEW_RENDER_TICK_MS,
        overviewPollIntervalMs: OVERVIEW_POLL_INTERVAL_MS,
    };

    logFilterActions = createLogFilterActions(() => state, appActions);

    return { state, elements, appActions };
}
