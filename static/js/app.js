import { api, getStoredApiToken, setStoredApiToken } from "/static/js/api.js?v=20260706-15";
import {
    AI_ASSISTANT_JOB_POLL_INTERVAL_MS,
    MANUAL_PLUGIN_EXECUTION_POLL_INTERVAL_MS,
    OVERVIEW_POLL_INTERVAL_MS,
    OVERVIEW_RENDER_TICK_MS,
} from "/static/js/polling-config.js?v=20260706-15";
import {
    formatJson,
    normalizeInlineText,
} from "/static/js/dom-utils.js?v=20260706-15";
import { syncMessageTypeLabels } from "/static/js/message-labels.js?v=20260706-15";
import { tabMeta } from "/static/js/tab-meta.js?v=20260706-15";
import { copyTextToClipboard } from "/static/js/clipboard-utils.js?v=20260706-15";
import { getMessagePollErrorText } from "/static/js/message-poll.js?v=20260706-15";
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
} from "/static/js/plugin-helpers.js?v=20260706-15";
import { renderOverviewGrid } from "/static/js/overview-view.js?v=20260706-15";
import { renderMessagesView } from "/static/js/message-view.js?v=20260706-15";
import { renderUsersView } from "/static/js/users-view.js?v=20260706-15";
import { readSettingsForm, renderSettingsView } from "/static/js/settings-view.js?v=20260706-15";
import { createAiAssistantController } from "/static/js/ai-assistant-controller.js?v=20260706-15";
import { createAiAssistantUiActions } from "/static/js/ai-assistant-ui-actions.js?v=20260706-15";
import { createTabLoaders } from "/static/js/tab-loaders.js?v=20260706-15";
import { createPluginModalActions } from "/static/js/plugin-modals.js?v=20260706-15";
import { registerAppEvents } from "/static/js/app-events.js?v=20260706-15";
import { bootstrapApp, startAppRuntime } from "/static/js/app-runtime.js?v=20260706-15";
import { registerPluginFormEventHandlers } from "/static/js/plugin-form-handlers.js?v=20260706-15";


import { updateHeaderForTab as syncHeaderForTab } from "/static/js/tab-ui.js?v=20260706-15";
import { waitForDuration } from "/static/js/async-utils.js?v=20260706-15";
import { createLogFilterActions, renderServiceLogs } from "/static/js/log-viewer.js?v=20260706-15";
import { renderPluginLogsView } from "/static/js/plugin-log-viewer.js?v=20260706-15";
import { renderPluginCards } from "/static/js/plugin-cards.js?v=20260706-15";
import {
    buildPluginConfigRenderModel,
    buildPluginExecuteRenderModel,
    buildStructuredPluginConfigPayload,
    getPluginModuleNameForForm,
} from "/static/js/plugin-config-render.js?v=20260706-15";
import {
    decodeAiAssistantModelSelection,
    normalizeAiAssistantJobStatus,
} from "/static/js/ai-assistant-data.js?v=20260706-15";

const state = {
    activeTab: "dashboard",
    overview: null,
    overviewFetchedAt: 0,
    messages: [],
    users: null,
    aiAssistant: null,
    aiConversation: [],
    aiRequestInFlight: false,
    aiActiveChatJobId: "",
    aiActiveChatJob: null,
    aiAssistantUi: {
        selectedProvider: "",
        selectedProviderConfigId: "",
        selectedModel: "",
        selectedPromptPluginId: "",
    },
    selectedMessageId: null,
    messageAutoFollow: true,
    messagePollFailureCount: 0,
    plugins: [],
    pluginTargets: null,
    pluginLogs: null,
    selectedPluginLogModule: "",
    selectedPluginLogLevel: "",
    selectedPluginLogKeyword: "",
    selectedPluginLogId: null,
    pluginConfigModule: "",
    pluginExecuteModule: "",
    settings: null,
    logs: null,
    selectedLogFile: "",
    logFilters: {
        timeRange: "all",
        level: "",
        moduleQuery: "",
        keyword: "",
    },
};

const elements = {
    navTabs: [...document.querySelectorAll(".nav-tab")],
    panels: [...document.querySelectorAll(".tab-panel")],
    activeTabLabel: document.getElementById("activeTabLabel"),
    pageTitle: document.getElementById("pageTitle"),
    pageDescription: document.getElementById("pageDescription"),
    statusPill: document.getElementById("statusPill"),
    reloadConfigButton: document.getElementById("reloadConfigButton"),
    tabRefreshButton: document.getElementById("tabRefreshButton"),
    overviewGrid: document.getElementById("overviewGrid"),
    messageList: document.getElementById("messageList"),
    messageDetail: document.getElementById("messageDetail"),
    refreshMessagesButton: document.getElementById("refreshMessagesButton"),
    userGrid: document.getElementById("userGrid"),
    refreshUsersButton: document.getElementById("refreshUsersButton"),
    featurePluginGrid: document.getElementById("featurePluginGrid"),
    refreshFeaturePluginsButton: document.getElementById("refreshFeaturePluginsButton"),
    aiAssistantAlert: document.getElementById("aiAssistantAlert"),
    newAiAssistantConversationButton: document.getElementById("newAiAssistantConversationButton"),
    openAiAssistantConversationSwitcherButton: document.getElementById("openAiAssistantConversationSwitcherButton"),
    aiAssistantProviderSelect: document.getElementById("aiAssistantProviderSelect"),
    aiAssistantModelSelect: document.getElementById("aiAssistantModelSelect"),
    aiAssistantPromptPluginSelect: document.getElementById("aiAssistantPromptPluginSelect"),
    toggleAiAssistantConfigButton: document.getElementById("toggleAiAssistantConfigButton"),
    toggleAiAssistantToolsButton: document.getElementById("toggleAiAssistantToolsButton"),
    aiAssistantConfigModal: document.getElementById("aiAssistantConfigModal"),
    closeAiAssistantConfigButton: document.getElementById("closeAiAssistantConfigButton"),
    cancelAiAssistantConfigButton: document.getElementById("cancelAiAssistantConfigButton"),
    aiAssistantToolsModal: document.getElementById("aiAssistantToolsModal"),
    closeAiAssistantToolsButton: document.getElementById("closeAiAssistantToolsButton"),
    dismissAiAssistantToolsButton: document.getElementById("dismissAiAssistantToolsButton"),
    aiAssistantConversationModal: document.getElementById("aiAssistantConversationModal"),
    closeAiAssistantConversationModalButton: document.getElementById("closeAiAssistantConversationModalButton"),
    dismissAiAssistantConversationModalButton: document.getElementById("dismissAiAssistantConversationModalButton"),
    aiAssistantConversationList: document.getElementById("aiAssistantConversationList"),
    aiAssistantSettingsForm: document.getElementById("aiAssistantSettingsForm"),
    saveAiAssistantSettingsButton: document.getElementById("saveAiAssistantSettingsButton"),
    refreshAiAssistantButton: document.getElementById("refreshAiAssistantButton"),
    clearAiAssistantConversationButton: document.getElementById("clearAiAssistantConversationButton"),
    aiAssistantToolMeta: document.getElementById("aiAssistantToolMeta"),
    aiAssistantToolGrid: document.getElementById("aiAssistantToolGrid"),
    aiAssistantConversation: document.getElementById("aiAssistantConversation"),
    aiAssistantConversationMeta: document.getElementById("aiAssistantConversationMeta"),
    aiAssistantProviderBadgeRow: document.getElementById("aiAssistantProviderBadgeRow"),
    aiAssistantPromptForm: document.getElementById("aiAssistantPromptForm"),
    aiAssistantPromptInput: document.getElementById("aiAssistantPromptInput"),
    sendAiAssistantPromptButton: document.getElementById("sendAiAssistantPromptButton"),
    stopAiAssistantChatButton: document.getElementById("stopAiAssistantChatButton"),
    pluginGrid: document.getElementById("pluginGrid"),
    refreshPluginsButton: document.getElementById("refreshPluginsButton"),
    pluginLogFilter: document.getElementById("pluginLogFilter"),
    pluginLogLevelFilter: document.getElementById("pluginLogLevelFilter"),
    pluginLogKeywordFilter: document.getElementById("pluginLogKeywordFilter"),
    refreshPluginLogsButton: document.getElementById("refreshPluginLogsButton"),
    pluginLogMeta: document.getElementById("pluginLogMeta"),
    pluginLogList: document.getElementById("pluginLogList"),
    pluginLogDetail: document.getElementById("pluginLogDetail"),
    pluginConfigModal: document.getElementById("pluginConfigModal"),
    pluginConfigModalTitle: document.getElementById("pluginConfigModalTitle"),
    pluginConfigMeta: document.getElementById("pluginConfigMeta"),
    pluginConfigForm: document.getElementById("pluginConfigForm"),
    pluginConfigEditor: document.getElementById("pluginConfigEditor"),
    closePluginConfigButton: document.getElementById("closePluginConfigButton"),
    cancelPluginConfigButton: document.getElementById("cancelPluginConfigButton"),
    savePluginConfigButton: document.getElementById("savePluginConfigButton"),
    pluginExecuteModal: document.getElementById("pluginExecuteModal"),
    pluginExecuteModalTitle: document.getElementById("pluginExecuteModalTitle"),
    pluginExecuteMeta: document.getElementById("pluginExecuteMeta"),
    pluginExecuteForm: document.getElementById("pluginExecuteForm"),
    closePluginExecuteButton: document.getElementById("closePluginExecuteButton"),
    cancelPluginExecuteButton: document.getElementById("cancelPluginExecuteButton"),
    executePluginButton: document.getElementById("executePluginButton"),
    settingsForm: document.getElementById("settingsForm"),
    settingsAlert: document.getElementById("settingsAlert"),
    refreshSettingsButton: document.getElementById("refreshSettingsButton"),
    logFileSelect: document.getElementById("logFileSelect"),
    logTimeRange: document.getElementById("logTimeRange"),
    logLevelFilter: document.getElementById("logLevelFilter"),
    logModuleFilter: document.getElementById("logModuleFilter"),
    logKeywordFilter: document.getElementById("logKeywordFilter"),
    refreshLogsButton: document.getElementById("refreshLogsButton"),
    logMeta: document.getElementById("logMeta"),
    logViewer: document.getElementById("logViewer"),
};

let logFilterTimerId = null;
let pluginLogFilterTimerId = null;
let messagePollInFlight = null;
let manualPluginExecutionPollTimerId = null;

let aiAssistantCtrl;
let aiAssistantUi;
let tabLoaders;
let pluginModals;

function initAppControllers() {
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
}


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


let logFilterActions;

function buildAppActions() {
    return {
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
}

initAppControllers();

const appActions = buildAppActions();
logFilterActions = createLogFilterActions(() => state, appActions);
registerAppEvents(appActions);
registerPluginFormEventHandlers(appActions);
startAppRuntime(appActions);

bootstrapApp(appActions);
