import { api, getStoredApiToken, setStoredApiToken, SECRET_SETTINGS_PLACEHOLDER } from "/static/js/api.js?v=20260706-12";
import {
    AI_ASSISTANT_JOB_POLL_INTERVAL_MS,
    MANUAL_PLUGIN_EXECUTION_POLL_INTERVAL_MS,
    OVERVIEW_POLL_INTERVAL_MS,
    OVERVIEW_RENDER_TICK_MS,
} from "/static/js/polling-config.js?v=20260706-12";
import { connectRuntimeEventStream, shouldPollMessages } from "/static/js/runtime-events.js?v=20260706-12";
import {
    formatJson,
    normalizeInlineText,
} from "/static/js/dom-utils.js?v=20260706-12";
import { syncMessageTypeLabels } from "/static/js/message-labels.js?v=20260706-12";
import { tabMeta } from "/static/js/tab-meta.js?v=20260706-12";
import {
    handleStructuredConfigAction,
    hasStructuredPluginConfig,
    readStructuredPluginConfig,
    validateStructuredPluginConfig,
} from "/static/js/plugin-config-form.js?v=20260706-12";
import { copyTextToClipboard, parseJsonObjectInput } from "/static/js/clipboard-utils.js?v=20260706-12";
import { getMessagePollErrorText } from "/static/js/message-poll.js?v=20260706-12";
import {
    applySearchableChoiceFilter,
    applySearchableSelectFilter,
    closeSearchableSelect,
    getSearchableSelectElements,
    handleSearchableSelectInput,
    selectSearchableSelectOption,
    syncScopeFieldVisibility,
} from "/static/js/config-search.js?v=20260706-12";
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
} from "/static/js/plugin-helpers.js?v=20260706-12";
import { renderOverviewGrid } from "/static/js/overview-view.js?v=20260706-12";
import { renderMessagesView } from "/static/js/message-view.js?v=20260706-12";
import { renderUsersView } from "/static/js/users-view.js?v=20260706-12";
import { renderSettingsView } from "/static/js/settings-view.js?v=20260706-12";
import { createAiAssistantController } from "/static/js/ai-assistant-controller.js?v=20260706-12";
import { createTabLoaders } from "/static/js/tab-loaders.js?v=20260706-12";
import { createPluginModalActions } from "/static/js/plugin-modals.js?v=20260706-12";

import { updateHeaderForTab as syncHeaderForTab } from "/static/js/tab-ui.js?v=20260706-12";
import { waitForDuration } from "/static/js/async-utils.js?v=20260706-12";
import { renderServiceLogs, syncLogFiltersFromControls as readLogFiltersFromControls } from "/static/js/log-viewer.js?v=20260706-12";
import { renderPluginLogsView } from "/static/js/plugin-log-viewer.js?v=20260706-12";
import { renderPluginCards } from "/static/js/plugin-cards.js?v=20260706-12";
import {
    applyFetchOptionsSelection,
    buildPluginConfigRenderModel,
    buildPluginExecuteRenderModel,
    buildStructuredPluginConfigPayload,
    getPluginModuleNameForForm,
    handlePluginFetchOptions,
    refreshPluginModelOptionsForm,
    shouldRefreshPluginModelOptions,
    syncRoomMsgSummaryTimeFields,
} from "/static/js/plugin-config-render.js?v=20260706-12";
import {
    decodeAiAssistantModelSelection,
    normalizeAiAssistantJobStatus,
} from "/static/js/ai-assistant-data.js?v=20260706-12";
import {
    appendAiAssistantConfigRow as appendAiAssistantConfigRowView,
    appendAiAssistantPromptPluginRow as appendAiAssistantPromptPluginRowView,
    closeAiAssistantConfigModal as closeAiAssistantConfigModalView,
    closeAiAssistantConversationModal as closeAiAssistantConversationModalView,
    closeAiAssistantToolsModal as closeAiAssistantToolsModalView,
    openAiAssistantConfigModal as openAiAssistantConfigModalView,
    openAiAssistantConversationModal as openAiAssistantConversationModalView,
    openAiAssistantToolsModal as openAiAssistantToolsModalView,
    readAiAssistantSettingsForm as readAiAssistantSettingsFormView,
    renderAiAssistant as renderAiAssistantView,
    renderAiAssistantConversationList as renderAiAssistantConversationListView,
    syncAiAssistantConfigRowState as syncAiAssistantConfigRowStateView,
    syncAiAssistantConfigTableState as syncAiAssistantConfigTableStateView,
    syncAiAssistantPromptPluginCardState as syncAiAssistantPromptPluginCardStateView,
    syncAiAssistantPromptPluginTableState as syncAiAssistantPromptPluginTableStateView,
} from "/static/js/ai-assistant-ui.js?v=20260706-12";

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
let tabLoaders;
let pluginModals;

function initAppControllers() {
    aiAssistantCtrl = createAiAssistantController(() => state, {
        api,
        setStatus,
        renderAiAssistant,
        renderAiAssistantConversationList,
        waitForDuration,
        aiJobPollIntervalMs: AI_ASSISTANT_JOB_POLL_INTERVAL_MS,
    });
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


function applyAiAssistantPayload(payload, preserveSelection = true) {
    aiAssistantCtrl.applyPayload(payload, preserveSelection);
}

function getAiAssistantConversations() {
    return aiAssistantCtrl.getConversations();
}

function getAiAssistantCurrentConversation() {
    return aiAssistantCtrl.getCurrentConversation();
}

function getAiAssistantCurrentConversationId() {
    return aiAssistantCtrl.getCurrentConversationId();
}

function getAiAssistantProviders() {
    return aiAssistantCtrl.getProviders();
}

function getAiAssistantSettings() {
    return aiAssistantCtrl.getSettings();
}

function getAiAssistantPromptPlugins() {
    return aiAssistantCtrl.getPromptPlugins();
}

function getAiAssistantPromptPlugin(promptPluginId = state.aiAssistantUi.selectedPromptPluginId) {
    return aiAssistantCtrl.getPromptPlugin(promptPluginId);
}

function getAiAssistantProvider(providerKey = state.aiAssistantUi.selectedProvider) {
    return aiAssistantCtrl.getProvider(providerKey);
}

function getAiAssistantCurrentSelection() {
    return aiAssistantCtrl.getCurrentSelection();
}

function setAiAssistantProviderSelection(providerKey, preferredModel = "", preferredConfigId = "") {
    aiAssistantCtrl.setProviderSelection(providerKey, preferredModel, preferredConfigId);
}

function syncAiAssistantUiFromPayload(preserveSelection = true) {
    aiAssistantCtrl.syncUiFromPayload(preserveSelection);
}

function aiAssistantUiCtx() {
    return aiAssistantCtrl.buildUiCtx(elements);
}

function renderAiAssistantConversationList() {
    renderAiAssistantConversationListView(aiAssistantUiCtx());
}

function renderAiAssistant() {
    renderAiAssistantView(aiAssistantUiCtx());
}

function readAiAssistantSettingsForm() {
    return readAiAssistantSettingsFormView(aiAssistantUiCtx());
}

function openAiAssistantConversationModal() {
    openAiAssistantConversationModalView(aiAssistantUiCtx());
}

function openAiAssistantConfigModal() {
    openAiAssistantConfigModalView(aiAssistantUiCtx());
}

function openAiAssistantToolsModal() {
    openAiAssistantToolsModalView(aiAssistantUiCtx());
}

function closeAiAssistantConfigModal() {
    closeAiAssistantConfigModalView(aiAssistantUiCtx());
}

function closeAiAssistantConversationModal() {
    closeAiAssistantConversationModalView(aiAssistantUiCtx());
}

function closeAiAssistantToolsModal() {
    closeAiAssistantToolsModalView(aiAssistantUiCtx());
}

function appendAiAssistantPromptPluginRow() {
    appendAiAssistantPromptPluginRowView(aiAssistantUiCtx());
}

function syncAiAssistantPromptPluginTableState() {
    syncAiAssistantPromptPluginTableStateView(aiAssistantUiCtx());
}

function syncAiAssistantPromptPluginCardState(card) {
    syncAiAssistantPromptPluginCardStateView(aiAssistantUiCtx(), card);
}

function appendAiAssistantConfigRow(providerKey) {
    appendAiAssistantConfigRowView(aiAssistantUiCtx(), providerKey);
}

function syncAiAssistantConfigTableState() {
    syncAiAssistantConfigTableStateView(aiAssistantUiCtx());
}

function syncAiAssistantConfigRowState(row) {
    syncAiAssistantConfigRowStateView(aiAssistantUiCtx(), row);
}

function renderLogs() {
    renderServiceLogs(elements, state.logs, state.logFilters);
}


async function loadOverview() {
    return tabLoaders.loadOverview();
}

async function loadMessages() {
    return tabLoaders.loadMessages();
}

async function loadUsers() {
    return tabLoaders.loadUsers();
}

async function loadPluginTargetsIfNeeded(plugin) {
    if (!needsPluginTargets(plugin)) {
        return state.pluginTargets;
    }
    return loadPluginTargets();
}


async function refreshMessagesByPoll() {
    return tabLoaders.refreshMessagesByPoll();
}


async function loadPlugins() {
    return tabLoaders.loadPlugins();
}


function schedulePluginLogKeywordRefresh() {
    tabLoaders.schedulePluginLogKeywordRefresh();
}


async function loadSettings() {
    return tabLoaders.loadSettings();
}


async function loadAiAssistant() {
    return aiAssistantCtrl.load();
}

async function createAiAssistantConversation() {
    return aiAssistantCtrl.createConversation();
}

async function activateAiAssistantConversation(conversationId) {
    return aiAssistantCtrl.activateConversation(conversationId);
}

async function clearAiAssistantConversation() {
    return aiAssistantCtrl.clearConversation();
}

async function stopAiAssistantChatJob() {
    return aiAssistantCtrl.stopChatJob();
}

async function pollAiAssistantChatJob(jobId) {
    return aiAssistantCtrl.pollChatJob(jobId);
}


async function loadLogs(fileName = state.selectedLogFile) {
    return tabLoaders.loadLogs(fileName);
}


async function refreshCurrentTab() {
    return tabLoaders.refreshCurrentTab();
}

async function loadPluginTargets(force = false) {
    return tabLoaders.loadPluginTargets(force);
}

async function loadPluginTargetsIfNeeded(plugin) {
    return tabLoaders.loadPluginTargetsIfNeeded(plugin);
}

async function loadPluginLogs(moduleName = state.selectedPluginLogModule, level = state.selectedPluginLogLevel, keyword = state.selectedPluginLogKeyword) {
    return tabLoaders.loadPluginLogs(moduleName, level, keyword);
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
    refreshCurrentTab().catch((error) => {
        setStatus(`加载失败：${error.message}`, "bad");
    });
}

function readSettingsForm() {
    const form = elements.settingsForm;
    return {
        host: form.host.value.trim(),
        port: Number(form.port.value),
        callback_path: form.callback_path.value.trim(),
        api_base_url: form.api_base_url.value.trim(),
        request_timeout: Number(form.request_timeout.value),
        worker_count: Number(form.worker_count.value),
        queue_size: Number(form.queue_size.value),
        queue_enqueue_wait_seconds: Number(form.queue_enqueue_wait_seconds.value),
        heartbeat_interval_seconds: Number(form.heartbeat_interval_seconds.value),
        api_token: form.api_token.value.trim(),
        callback_secret: form.callback_secret.value.trim(),
    };
}

function syncLogFiltersFromControls() {
    state.logFilters = readLogFiltersFromControls(elements);
}

async function applyLogFilters(statusText = "正在应用日志筛选...") {
    syncLogFiltersFromControls();
    setStatus(statusText);
    await loadLogs(state.selectedLogFile);
    if (Number(state.logs?.line_count || 0) > 0) {
        setStatus(`日志筛选已更新，命中 ${state.logs.matched_line_count || 0} 行`, "good");
        return;
    }
    setStatus("当前筛选条件下没有命中日志");
}

function scheduleLogFilterRefresh() {
    syncLogFiltersFromControls();
    if (logFilterTimerId !== null) {
        window.clearTimeout(logFilterTimerId);
    }
    logFilterTimerId = window.setTimeout(() => {
        applyLogFilters().catch((error) => {
            setStatus(`日志筛选失败：${error.message}`, "bad");
        });
    }, 250);
}

elements.navTabs.forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
});

elements.tabRefreshButton.addEventListener("click", async () => {
    try {
        setStatus("正在刷新当前视图...");
        await loadOverview();
        await refreshCurrentTab();
        setStatus("当前视图已刷新", "good");
    } catch (error) {
        setStatus(`刷新失败：${error.message}`, "bad");
    }
});

elements.reloadConfigButton.addEventListener("click", async () => {
    try {
        await reloadFromConfig();
    } catch (error) {
        setStatus(`重载失败：${error.message}`, "bad");
    }
});

elements.refreshMessagesButton.addEventListener("click", async () => {
    try {
        setStatus("正在刷新消息...");
        await loadMessages();
        setStatus("消息已刷新", "good");
    } catch (error) {
        setStatus(`消息刷新失败：${error.message}`, "bad");
    }
});

elements.refreshUsersButton.addEventListener("click", async () => {
    try {
        setStatus("正在刷新用户...");
        await loadUsers();
        setStatus("用户信息已刷新", "good");
    } catch (error) {
        setStatus(`用户刷新失败：${error.message}`, "bad");
    }
});

elements.aiAssistantSettingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!elements.aiAssistantSettingsForm.reportValidity()) {
        setStatus("请先修正智能插件配置中的输入项", "bad");
        return;
    }
    try {
        setStatus("正在保存智能插件设置...");
        applyAiAssistantPayload(await api.saveAiAssistantSettings(readAiAssistantSettingsForm()), true);
        renderAiAssistant();
        renderAiAssistantConversationList();
        closeAiAssistantConfigModal();
        setStatus("智能插件设置已保存", "good");
    } catch (error) {
        setStatus(`智能插件设置保存失败：${error.message}`, "bad");
    }
});

elements.aiAssistantSettingsForm.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) {
        return;
    }
    const actionTarget = event.target.closest("[data-ai-config-action]");
    if (!actionTarget) {
        return;
    }

    const action = actionTarget.dataset.aiConfigAction || "";
    if (action === "add-prompt-plugin") {
        appendAiAssistantPromptPluginRow();
        syncAiAssistantPromptPluginTableState();
        return;
    }

    if (action === "remove-prompt-plugin") {
        actionTarget.closest("[data-ai-prompt-plugin-row]")?.remove();
        syncAiAssistantPromptPluginTableState();
        return;
    }

    if (action === "add-row") {
        appendAiAssistantConfigRow();
        syncAiAssistantConfigTableState();
        return;
    }

    if (action === "remove-row") {
        actionTarget.closest("[data-ai-config-row]")?.remove();
        syncAiAssistantConfigTableState();
    }
});

elements.aiAssistantSettingsForm.addEventListener("input", (event) => {
    if (!(event.target instanceof Element)) {
        return;
    }
    const promptPluginCard = event.target.closest("[data-ai-prompt-plugin-row]");
    if (promptPluginCard) {
        syncAiAssistantPromptPluginCardState(promptPluginCard);
        return;
    }
    const row = event.target.closest("[data-ai-config-row]");
    if (row) {
        syncAiAssistantConfigRowState(row);
    }
});

elements.aiAssistantSettingsForm.addEventListener("change", (event) => {
    if (!(event.target instanceof Element)) {
        return;
    }
    const promptPluginCard = event.target.closest("[data-ai-prompt-plugin-row]");
    if (promptPluginCard) {
        syncAiAssistantPromptPluginCardState(promptPluginCard);
        syncAiAssistantPromptPluginTableState();
        return;
    }
    const row = event.target.closest("[data-ai-config-row]");
    if (row) {
        syncAiAssistantConfigRowState(row);
        syncAiAssistantConfigTableState();
    }
});

elements.refreshAiAssistantButton.addEventListener("click", async () => {
    try {
        setStatus("正在刷新智能插件配置...");
        await loadAiAssistant();
        setStatus("智能插件配置已刷新", "good");
    } catch (error) {
        setStatus(`智能插件刷新失败：${error.message}`, "bad");
    }
});

elements.newAiAssistantConversationButton?.addEventListener("click", async () => {
    try {
        setStatus("正在新建对话...");
        await createAiAssistantConversation();
        closeAiAssistantConversationModal();
        setStatus("已创建新对话", "good");
    } catch (error) {
        setStatus(`新建对话失败：${error.message}`, "bad");
    }
});

elements.openAiAssistantConversationSwitcherButton?.addEventListener("click", () => {
    openAiAssistantConversationModal();
});

elements.clearAiAssistantConversationButton.addEventListener("click", async () => {
    try {
        setStatus("正在清空当前对话...");
        await clearAiAssistantConversation();
        setStatus("当前对话已清空", "good");
    } catch (error) {
        setStatus(`清空对话失败：${error.message}`, "bad");
    }
});

elements.stopAiAssistantChatButton?.addEventListener("click", async () => {
    try {
        setStatus("正在停止智能插件对话...");
        await stopAiAssistantChatJob();
        if (!state.aiRequestInFlight && normalizeAiAssistantJobStatus(state.aiActiveChatJob?.status) === "stopped") {
            setStatus("智能插件已停止");
        }
    } catch (error) {
        setStatus(`停止智能插件对话失败：${error.message}`, "bad");
    }
});

elements.aiAssistantProviderSelect?.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLSelectElement)) {
        return;
    }
    setAiAssistantProviderSelection(event.target.value);
    renderAiAssistant();
});

elements.aiAssistantModelSelect?.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLSelectElement)) {
        return;
    }
    const selection = decodeAiAssistantModelSelection(event.target.value);
    state.aiAssistantUi.selectedProviderConfigId = selection.configId;
    state.aiAssistantUi.selectedModel = selection.model;
    renderAiAssistant();
});

elements.aiAssistantPromptPluginSelect?.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLSelectElement)) {
        return;
    }
    state.aiAssistantUi.selectedPromptPluginId = event.target.value;
    renderAiAssistant();
});

elements.toggleAiAssistantConfigButton?.addEventListener("click", () => {
    openAiAssistantConfigModal();
});

elements.toggleAiAssistantToolsButton?.addEventListener("click", () => {
    openAiAssistantToolsModal();
});

elements.closeAiAssistantConfigButton?.addEventListener("click", closeAiAssistantConfigModal);
elements.cancelAiAssistantConfigButton?.addEventListener("click", closeAiAssistantConfigModal);
elements.closeAiAssistantToolsButton?.addEventListener("click", closeAiAssistantToolsModal);
elements.dismissAiAssistantToolsButton?.addEventListener("click", closeAiAssistantToolsModal);
elements.closeAiAssistantConversationModalButton?.addEventListener("click", closeAiAssistantConversationModal);
elements.dismissAiAssistantConversationModalButton?.addEventListener("click", closeAiAssistantConversationModal);

elements.aiAssistantConfigModal?.addEventListener("click", (event) => {
    if (event.target === elements.aiAssistantConfigModal) {
        closeAiAssistantConfigModal();
    }
});

elements.aiAssistantToolsModal?.addEventListener("click", (event) => {
    if (event.target === elements.aiAssistantToolsModal) {
        closeAiAssistantToolsModal();
    }
});

elements.aiAssistantConversationModal?.addEventListener("click", (event) => {
    if (event.target === elements.aiAssistantConversationModal) {
        closeAiAssistantConversationModal();
    }
});

elements.aiAssistantConversationList?.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-ai-conversation-id]");
    if (!target) {
        return;
    }
    try {
        setStatus("正在切换对话...");
        await activateAiAssistantConversation(target.dataset.aiConversationId || "");
        closeAiAssistantConversationModal();
        setStatus("历史对话已切换", "good");
    } catch (error) {
        setStatus(`切换对话失败：${error.message}`, "bad");
    }
});

elements.aiAssistantPromptForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.aiRequestInFlight) {
        return;
    }

    const { provider: selectedProvider, selectedConfig, selectedModel, selectedPromptPlugin } = getAiAssistantCurrentSelection();
    if (!selectedProvider || !selectedConfig?.api_key) {
        setStatus("当前选择的 AI 配置尚未填写 API Key，请先点击配置按钮完成设置", "bad");
        return;
    }
    if (!selectedConfig.enabled) {
        setStatus("当前选择的 AI 配置尚未启用，请先在配置中启用后再发送", "bad");
        return;
    }
    if (!selectedPromptPlugin?.id) {
        setStatus("当前还没有可用的提示词插件，请先点击配置按钮完成设置", "bad");
        return;
    }

    const prompt = elements.aiAssistantPromptInput.value.trim();
    if (!prompt) {
        setStatus("请先输入要交给智能插件处理的问题", "bad");
        return;
    }

    elements.aiAssistantPromptInput.value = "";
    state.aiRequestInFlight = true;
    renderAiAssistant();

    try {
        let conversationId = getAiAssistantCurrentConversationId();
        if (!conversationId) {
            await createAiAssistantConversation();
            conversationId = getAiAssistantCurrentConversationId();
        }
        setStatus("智能插件正在调用模型与工具...");
        const payload = await api.createAiAssistantChatJob(
            conversationId,
            prompt,
            selectedProvider.key || "",
            selectedConfig.id || "",
            selectedModel || selectedProvider.default_model || "",
            selectedPromptPlugin.id || ""
        );
        applyAiAssistantPayload(payload, true);
        renderAiAssistant();
        if (!payload.job?.id) {
            throw new Error("智能插件任务创建失败，未返回任务 ID");
        }
        await pollAiAssistantChatJob(payload.job.id);
    } catch (error) {
        state.aiRequestInFlight = false;
        state.aiActiveChatJobId = "";
        state.aiActiveChatJob = null;
        setStatus(`智能插件执行失败：${error.message}`, "bad");
    } finally {
        renderAiAssistant();
    }
});

elements.messageList.addEventListener("click", (event) => {
    const target = event.target.closest("[data-message-id]");
    if (!target) {
        return;
    }
    state.selectedMessageId = Number(target.dataset.messageId);
    state.messageAutoFollow = state.selectedMessageId === state.messages[0]?.internal_id;
    renderMessages();
});

elements.messageDetail.addEventListener("click", async (event) => {
    const button = event.target.closest('button[data-action="copy-message-payload"]');
    if (!button) {
        return;
    }

    const selected = state.messages.find((message) => message.internal_id === state.selectedMessageId);
    if (!selected) {
        setStatus("未找到当前消息原始负载", "bad");
        return;
    }

    try {
        await copyTextToClipboard(formatJson(selected.payload));
        setStatus("原始负载已复制", "good");
    } catch (error) {
        setStatus(`复制原始负载失败：${error.message}`, "bad");
    }
});

elements.refreshPluginsButton.addEventListener("click", async () => {
    try {
        setStatus("正在刷新消息插件...");
        await loadPlugins();
        setStatus("消息插件已刷新", "good");
    } catch (error) {
        setStatus(`消息插件刷新失败：${error.message}`, "bad");
    }
});

elements.refreshFeaturePluginsButton.addEventListener("click", async () => {
    try {
        setStatus("正在刷新功能插件...");
        await loadPlugins();
        setStatus("功能插件已刷新", "good");
    } catch (error) {
        setStatus(`功能插件刷新失败：${error.message}`, "bad");
    }
});

async function handlePluginGridAction(event) {
    const button = event.target.closest("button[data-action]");
    if (!button) {
        return;
    }

    const moduleName = button.dataset.plugin;
    if (button.dataset.action === "open-plugin-config") {
        await openPluginConfigModal(moduleName);
        return;
    }

    button.disabled = true;
    try {
        if (button.dataset.action === "toggle-plugin") {
            setStatus("正在切换插件状态...");
            const result = await api.togglePlugin(moduleName, button.dataset.enabled === "1");
            applyPluginMutationResult(result);
            const suffix = result.restart_required ? `，需要重启字段：${result.restart_required_fields.join(", ")}` : "";
            setStatus(`插件状态已更新${suffix}`, result.restart_required ? "bad" : "good");
        } else if (button.dataset.action === "execute-plugin") {
            const plugin = getPluginByModule(moduleName);
            if (plugin && isDirectExecutePlugin(plugin)) {
                setStatus("正在执行功能插件...");
                await executePluginWithConfig(moduleName, {});
            } else {
                setStatus("正在准备执行范围...");
                if (plugin) {
                    await loadPluginTargetsIfNeeded(plugin);
                }
                await openPluginExecuteModal(moduleName);
            }
        } else if (button.dataset.action === "stop-plugin-execution") {
            setStatus("正在停止功能插件...");
            const result = await api.stopPluginExecution(moduleName);
            applyPluginMutationResult(result);
            const detail = normalizeInlineText(result?.execution?.detail || "");
            setStatus(detail || "正在停止插件...");
        }
    } catch (error) {
        setStatus(`插件操作失败：${error.message}`, "bad");
    } finally {
        button.disabled = false;
    }
}

[elements.pluginGrid, elements.featurePluginGrid].forEach((grid) => {
    grid.addEventListener("click", (event) => {
        handlePluginGridAction(event).catch((error) => {
            setStatus(`插件操作失败：${error.message}`, "bad");
        });
    });
});

elements.pluginLogList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-plugin-log-id]");
    if (!button) {
        return;
    }
    state.selectedPluginLogId = Number(button.dataset.pluginLogId);
    renderPluginLogs();
});

elements.pluginLogFilter.addEventListener("change", async () => {
    try {
        state.selectedPluginLogModule = elements.pluginLogFilter.value;
        state.selectedPluginLogId = null;
        setStatus("正在切换插件日志筛选...");
        await loadPluginLogs(state.selectedPluginLogModule, state.selectedPluginLogLevel, state.selectedPluginLogKeyword);
        setStatus("插件日志已更新", "good");
    } catch (error) {
        setStatus(`插件日志筛选失败：${error.message}`, "bad");
    }
});

elements.pluginLogLevelFilter.addEventListener("change", async () => {
    try {
        state.selectedPluginLogLevel = elements.pluginLogLevelFilter.value;
        state.selectedPluginLogId = null;
        setStatus("正在切换插件日志级别筛选...");
        await loadPluginLogs(state.selectedPluginLogModule, state.selectedPluginLogLevel, state.selectedPluginLogKeyword);
        setStatus("插件日志已更新", "good");
    } catch (error) {
        setStatus(`插件日志级别筛选失败：${error.message}`, "bad");
    }
});

elements.pluginLogKeywordFilter.addEventListener("input", () => {
    state.selectedPluginLogKeyword = elements.pluginLogKeywordFilter.value.trim();
    state.selectedPluginLogId = null;
    schedulePluginLogKeywordRefresh();
});

elements.pluginLogKeywordFilter.addEventListener("search", () => {
    state.selectedPluginLogKeyword = elements.pluginLogKeywordFilter.value.trim();
    state.selectedPluginLogId = null;
    schedulePluginLogKeywordRefresh();
});

elements.refreshPluginLogsButton.addEventListener("click", async () => {
    try {
        setStatus("正在刷新插件日志...");
        await loadPluginLogs(state.selectedPluginLogModule, state.selectedPluginLogLevel, state.selectedPluginLogKeyword);
        setStatus("插件日志已刷新", "good");
    } catch (error) {
        setStatus(`插件日志刷新失败：${error.message}`, "bad");
    }
});

elements.closePluginConfigButton.addEventListener("click", closePluginConfigModal);
elements.cancelPluginConfigButton.addEventListener("click", closePluginConfigModal);
elements.closePluginExecuteButton.addEventListener("click", closePluginExecuteModal);
elements.cancelPluginExecuteButton.addEventListener("click", closePluginExecuteModal);

elements.pluginConfigModal.addEventListener("click", (event) => {
    if (event.target === elements.pluginConfigModal) {
        closePluginConfigModal();
    }
});

elements.pluginExecuteModal.addEventListener("click", (event) => {
    if (event.target === elements.pluginExecuteModal) {
        closePluginExecuteModal();
    }
});

elements.pluginConfigForm.addEventListener("click", (event) => {
    if (!state.pluginConfigModule) {
        return;
    }
    const plugin = getPluginByModule(state.pluginConfigModule);
    if (!plugin) {
        return;
    }
    const renderPlugin = buildPluginConfigRenderModelForPlugin(plugin);
    if (handleStructuredConfigAction(elements.pluginConfigForm, renderPlugin, event)) {
        event.preventDefault();
    }
});

async function handleProjectFilePick(button, formElement) {
    const targetInput = button.closest(".config-file-picker")?.querySelector("input[data-column-key], input[data-config-key]");
    if (!(targetInput instanceof HTMLInputElement)) {
        return false;
    }

    const moduleName = formElement === elements.pluginConfigForm ? state.pluginConfigModule : state.pluginExecuteModule;
    if (!moduleName) {
        setStatus("当前未选中插件，无法上传图片", "bad");
        return true;
    }

    const pickerInput = document.createElement("input");
    pickerInput.type = "file";
    pickerInput.accept = String(button.dataset.accept || "").trim();
    pickerInput.hidden = true;
    document.body.appendChild(pickerInput);

    const cleanup = () => {
        pickerInput.remove();
    };

    pickerInput.addEventListener(
        "change",
        async () => {
            const [selectedFile] = [...(pickerInput.files || [])];
            if (!selectedFile) {
                cleanup();
                return;
            }

            const originalText = button.textContent || "选择文件";
            button.disabled = true;
            button.textContent = "上传中...";
            try {
                const payload = await api.uploadPluginAsset(
                    moduleName,
                    button.dataset.targetKey || targetInput.getAttribute("data-column-key") || targetInput.getAttribute("data-config-key") || "",
                    selectedFile,
                    String(button.dataset.uploadDir || "uploads").trim() || "uploads",
                );
                targetInput.value = String(payload.path || "");
                targetInput.dispatchEvent(new Event("input", { bubbles: true }));
                targetInput.dispatchEvent(new Event("change", { bubbles: true }));
                setStatus(`图片已保存到 ${payload.path}`, "good");
            } catch (error) {
                setStatus(`图片上传失败：${error.message}`, "bad");
            } finally {
                button.disabled = false;
                button.textContent = originalText;
                cleanup();
            }
        },
        { once: true },
    );

    pickerInput.click();
    return true;
}

[elements.pluginConfigForm, elements.pluginExecuteForm].forEach((formElement) => {
    formElement.addEventListener("click", async (event) => {
        const pickFileButton = event.target.closest("[data-config-pick-project-file]");
        if (pickFileButton) {
            event.preventDefault();
            await handleProjectFilePick(pickFileButton, formElement);
            return;
        }
        const fetchOptionsButton = event.target.closest("[data-config-fetch-options]");
        if (fetchOptionsButton) {
            event.preventDefault();
            await handlePluginFetchOptions(fetchOptionsButton, formElement, pluginRenderCtx());
            return;
        }
        const optionButton = event.target.closest("[data-config-searchable-option]");
        if (optionButton) {
            event.preventDefault();
            selectSearchableSelectOption(optionButton);
            return;
        }
        const toggleButton = event.target.closest("[data-config-searchable-toggle]");
        if (toggleButton) {
            event.preventDefault();
            const container = toggleButton.closest("[data-config-searchable-select]");
            if (!container) {
                return;
            }
            if (container.classList.contains("is-open")) {
                closeSearchableSelect(container, true);
                return;
            }
            const { input } = getSearchableSelectElements(container);
            if (input) {
                input.focus();
                applySearchableSelectFilter(input);
            }
            return;
        }
        const searchableInput = event.target.closest("[data-config-searchable-input]");
        if (searchableInput) {
            applySearchableSelectFilter(searchableInput);
        }
    });

    formElement.addEventListener("focusin", (event) => {
        const searchableInput = event.target.closest("[data-config-searchable-input]");
        if (searchableInput) {
            applySearchableSelectFilter(searchableInput);
        }
    });
});

[elements.pluginConfigForm, elements.pluginExecuteForm].forEach((formElement) => {
    ["input", "change", "search", "keyup", "compositionend"].forEach((eventName) => {
        formElement.addEventListener(eventName, (event) => {
            const target = event.target instanceof Element ? event.target : null;
            const editorRow = target?.closest("[data-config-row-editor]");
            if (editorRow) {
                editorRow.classList.remove("is-invalid");
                const errorElement = editorRow.querySelector("[data-config-row-error]");
                if (errorElement) {
                    errorElement.textContent = "";
                    errorElement.hidden = true;
                }
            }
            const input = target?.closest("[data-config-search-input]");
            if (input) {
                applySearchableChoiceFilter(input);
            }
            const searchableSelectInput = target?.closest("[data-config-searchable-input]");
            if (searchableSelectInput) {
                handleSearchableSelectInput(searchableSelectInput);
            }
            const showSelectedInput = target?.closest("[data-config-show-selected]");
            if (showSelectedInput) {
                const fieldContainer = showSelectedInput.closest("[data-config-field]");
                const searchInput = fieldContainer?.querySelector("[data-config-search-input]");
                if (searchInput) {
                    applySearchableChoiceFilter(searchInput);
                }
            }
            const fetchOptionsSelect = target?.closest?.("[data-config-fetch-options-select]");
            if (fetchOptionsSelect instanceof HTMLSelectElement && event.type === "change") {
                applyFetchOptionsSelection(fetchOptionsSelect);
            }
            const fieldKey = target?.getAttribute?.("data-config-key") || target?.getAttribute?.("data-config-fetch-options-select") || "";
            if (fieldKey === "_scope_room_mode" || fieldKey === "_scope_friend_mode") {
                syncScopeFieldVisibility(formElement);
            }
            if (fieldKey === "time_range") {
                syncRoomMsgSummaryTimeFields(formElement, pluginRenderCtx().getPluginModuleName, getPluginByModule, { force: true });
            }
            if (event.type === "change") {
                const moduleName = pluginRenderCtx().getPluginModuleName(formElement);
                const plugin = moduleName ? getPluginByModule(moduleName) : null;
                if (plugin && shouldRefreshPluginModelOptions(plugin, fieldKey)) {
                    void refreshPluginModelOptionsForm(formElement, pluginRenderCtx());
                }
            }
        });
    });
});

document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
        return;
    }
    const openSearchableSelect = document.querySelector(".config-searchable-select.is-open");
    if (openSearchableSelect) {
        closeSearchableSelect(openSearchableSelect, true);
        return;
    }
    if (elements.pluginExecuteModal.classList.contains("is-visible")) {
        closePluginExecuteModal();
        return;
    }
    if (elements.aiAssistantConversationModal?.classList.contains("is-visible")) {
        closeAiAssistantConversationModal();
        return;
    }
    if (elements.aiAssistantToolsModal?.classList.contains("is-visible")) {
        closeAiAssistantToolsModal();
        return;
    }
    if (elements.aiAssistantConfigModal?.classList.contains("is-visible")) {
        closeAiAssistantConfigModal();
        return;
    }
    if (elements.pluginConfigModal.classList.contains("is-visible")) {
        closePluginConfigModal();
    }
});

document.addEventListener("click", (event) => {
    document.querySelectorAll(".config-searchable-select.is-open").forEach((container) => {
        if (container.contains(event.target)) {
            return;
        }
        closeSearchableSelect(container, true);
    });
});

elements.savePluginConfigButton.addEventListener("click", async () => {
    if (!state.pluginConfigModule) {
        return;
    }

    elements.savePluginConfigButton.disabled = true;
    try {
        const plugin = getPluginByModule(state.pluginConfigModule);
        if (!plugin) {
            throw new Error("未找到指定插件");
        }
        const renderPlugin = buildPluginConfigRenderModelForPlugin(plugin);
        if (hasStructuredPluginConfig(renderPlugin)) {
            const validation = validateStructuredPluginConfig(elements.pluginConfigForm, renderPlugin);
            if (!validation.valid) {
                throw new Error(validation.message || "插件配置校验失败");
            }
        }
        const config = hasStructuredPluginConfig(renderPlugin)
            ? buildStructuredPluginConfigPayload(elements.pluginConfigForm, renderPlugin)
            : (() => {
                const configText = elements.pluginConfigEditor.value.trim() || "{}";
                return configText ? JSON.parse(configText) : {};
            })();
        setStatus("正在保存插件配置...");
        const result = await api.savePluginConfig(state.pluginConfigModule, config);
        applyPluginMutationResult(result);
        closePluginConfigModal();
        const suffix = result.restart_required ? `，需要重启字段：${result.restart_required_fields.join(", ")}` : "";
        setStatus(`插件配置已保存${suffix}`, result.restart_required ? "bad" : "good");
    } catch (error) {
        setStatus(`插件配置保存失败：${error.message}`, "bad");
    } finally {
        elements.savePluginConfigButton.disabled = false;
    }
});

elements.executePluginButton.addEventListener("click", async () => {
    if (!state.pluginExecuteModule) {
        return;
    }

    elements.executePluginButton.disabled = true;
    try {
        const plugin = getPluginByModule(state.pluginExecuteModule);
        if (!plugin) {
            throw new Error("未找到指定功能插件");
        }
        const renderPlugin = buildPluginExecuteRenderModelForPlugin(plugin);
        const config = hasStructuredPluginConfig(renderPlugin)
            ? readStructuredPluginConfig(elements.pluginExecuteForm, renderPlugin)
            : {};
        setStatus("正在执行功能插件...");
        await executePluginWithConfig(state.pluginExecuteModule, config);
        closePluginExecuteModal();
    } catch (error) {
        setStatus(`执行插件失败：${error.message}`, "bad");
    } finally {
        elements.executePluginButton.disabled = false;
    }
});

elements.settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
        setStatus("正在保存系统设置...");
        const formPayload = readSettingsForm();
        const result = await api.saveSettings(formPayload);
        if (formPayload.api_token && formPayload.api_token !== SECRET_SETTINGS_PLACEHOLDER) {
            setStoredApiToken(formPayload.api_token);
        }
        setOverviewData(result.overview);
        state.settings = result.settings;
        renderOverview();
        renderSettings();
        const suffix = result.restart_required ? `，需要重启字段：${result.restart_required_fields.join(", ")}` : "";
        setStatus(`系统设置已保存${suffix}`, result.restart_required ? "bad" : "good");
    } catch (error) {
        setStatus(`系统设置保存失败：${error.message}`, "bad");
    }
});

elements.refreshSettingsButton.addEventListener("click", async () => {
    try {
        setStatus("正在刷新系统设置...");
        await loadSettings();
        setStatus("系统设置已刷新", "good");
    } catch (error) {
        setStatus(`系统设置刷新失败：${error.message}`, "bad");
    }
});

elements.logFileSelect.addEventListener("change", async () => {
    try {
        state.selectedLogFile = elements.logFileSelect.value;
        setStatus("正在切换日志文件...");
        await loadLogs(state.selectedLogFile);
        setStatus("日志已切换", "good");
    } catch (error) {
        setStatus(`日志读取失败：${error.message}`, "bad");
    }
});

elements.logTimeRange.addEventListener("change", async () => {
    try {
        await applyLogFilters();
    } catch (error) {
        setStatus(`日志筛选失败：${error.message}`, "bad");
    }
});

elements.logLevelFilter.addEventListener("change", async () => {
    try {
        await applyLogFilters();
    } catch (error) {
        setStatus(`日志筛选失败：${error.message}`, "bad");
    }
});

elements.logModuleFilter.addEventListener("input", scheduleLogFilterRefresh);
elements.logKeywordFilter.addEventListener("input", scheduleLogFilterRefresh);

elements.refreshLogsButton.addEventListener("click", async () => {
    try {
        setStatus("正在刷新日志...");
        await loadLogs(state.selectedLogFile);
        setStatus("日志已刷新", "good");
    } catch (error) {
        setStatus(`日志刷新失败：${error.message}`, "bad");
    }
});

async function bootstrap() {
    try {
        setStatus("正在初始化控制台...");
        updateHeaderForTab(state.activeTab);
        await syncMessageTypeLabels();
        await loadOverview();
        await Promise.all([loadMessages(), loadUsers(), loadPlugins(), loadPluginLogs(), loadSettings(), loadAiAssistant(), loadLogs()]);
        setStatus("控制台已就绪", "good");
    } catch (error) {
        setStatus(`初始化失败：${error.message}`, "bad");
    }
}

initAppControllers();

bootstrap();

connectRuntimeEventStream({
    onRuntimeEvent(payload) {
        const eventType = String(payload?.type || "");
        if (eventType === "message_queued" || eventType === "message_processed" || eventType === "message_failed") {
            refreshMessagesByPoll().catch(() => {});
            loadOverview().catch(() => {});
        }
    },
});

window.setInterval(() => {
    if (document.visibilityState === "hidden" || !state.overview) {
        return;
    }
    renderOverview();
}, OVERVIEW_RENDER_TICK_MS);

window.setInterval(() => {
    if (document.visibilityState === "hidden") {
        return;
    }
    loadOverview().catch((error) => {
        setStatus(`概览自动刷新失败：${error.message}`, "bad");
    });
    if (state.activeTab !== "messages" && state.activeTab !== "ai-assistant") {
        refreshCurrentTab().catch((error) => {
            setStatus(`自动刷新失败：${error.message}`, "bad");
        });
    }
}, OVERVIEW_POLL_INTERVAL_MS);

window.setInterval(() => {
    if (document.visibilityState === "hidden") {
        return;
    }
    if (!shouldPollMessages()) {
        return;
    }
    refreshMessagesByPoll();
}, 1000);

document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") {
        return;
    }

    loadOverview().catch((error) => {
        setStatus(`概览刷新失败：${error.message}`, "bad");
    });
    refreshMessagesByPoll();
    if (state.activeTab !== "messages" && state.activeTab !== "ai-assistant") {
        refreshCurrentTab().catch((error) => {
            setStatus(`自动刷新失败：${error.message}`, "bad");
        });
    }
});