import { api, getStoredApiToken, setStoredApiToken, SECRET_SETTINGS_PLACEHOLDER } from "/static/js/api.js?v=20260706-09";
import {
    AI_ASSISTANT_ACTIVE_JOB_STATUSES,
    AI_ASSISTANT_JOB_POLL_INTERVAL_MS,
    AI_ASSISTANT_TERMINAL_JOB_STATUSES,
    MANUAL_PLUGIN_EXECUTION_POLL_INTERVAL_MS,
    OVERVIEW_POLL_INTERVAL_MS,
    OVERVIEW_RENDER_TICK_MS,
} from "/static/js/polling-config.js?v=20260706-09";
import { connectRuntimeEventStream, shouldPollMessages } from "/static/js/runtime-events.js?v=20260706-09";
import {
    escapeHtml,
    formatJson,
    highlightText,
    normalizeInlineText,
} from "/static/js/dom-utils.js?v=20260706-09";
import {
    formatStandardDateTime,
    formatUnixTimestamp,
    truncateText,
} from "/static/js/format-utils.js?v=20260706-09";
import {
    getMessageTypeLabel,
    getPayloadValue,
    syncMessageTypeLabels,
} from "/static/js/message-labels.js?v=20260706-09";
import { tabMeta } from "/static/js/tab-meta.js?v=20260706-09";
import { getLogLevelClass, getLogTone, getStatusTone } from "/static/js/status-tones.js?v=20260706-09";
import {
    getConversationLabel,
    getMessageSummary,
    getMessageTimeLabel,
    getMessageTitle,
    getSenderLabel,
    renderAvatar,
} from "/static/js/message-presenters.js?v=20260706-09";
import {
    handleStructuredConfigAction,
    hasStructuredPluginConfig,
    readStructuredPluginConfig,
    validateStructuredPluginConfig,
} from "/static/js/plugin-config-form.js?v=20260706-09";
import { copyTextToClipboard, parseJsonObjectInput } from "/static/js/clipboard-utils.js?v=20260706-09";
import { getMessagePollErrorText } from "/static/js/message-poll.js?v=20260706-09";
import {
    applySearchableChoiceFilter,
    applySearchableSelectFilter,
    closeSearchableSelect,
    getSearchableSelectElements,
    handleSearchableSelectInput,
    selectSearchableSelectOption,
    syncScopeFieldVisibility,
} from "/static/js/config-search.js?v=20260706-09";
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
} from "/static/js/plugin-helpers.js?v=20260706-09";
import { buildOverviewCards } from "/static/js/overview-cards.js?v=20260706-09";
import { updateHeaderForTab as syncHeaderForTab } from "/static/js/tab-ui.js?v=20260706-09";
import { waitForDuration } from "/static/js/async-utils.js?v=20260706-09";
import { renderServiceLogs, syncLogFiltersFromControls as readLogFiltersFromControls } from "/static/js/log-viewer.js?v=20260706-09";
import { renderPluginLogsView } from "/static/js/plugin-log-viewer.js?v=20260706-09";
import { renderPluginCards } from "/static/js/plugin-cards.js?v=20260706-09";
import {
    applyFetchOptionsSelection,
    buildPluginConfigRenderModel,
    buildPluginExecuteRenderModel,
    buildStructuredPluginConfigPayload,
    getPluginModuleNameForForm,
    handlePluginFetchOptions,
    preparePluginConfigRenderModel,
    preparePluginExecuteRenderModel,
    refreshPluginModelOptionsForm,
    renderStructuredPluginForm,
    shouldRefreshPluginModelOptions,
    syncRoomMsgSummaryTimeFields,
} from "/static/js/plugin-config-render.js?v=20260706-09";
import {
    createAiAssistantConfigId,
    createAiAssistantPromptPluginId,
    decodeAiAssistantModelSelection,
    encodeAiAssistantModelSelection,
    findAiAssistantProvider,
    findAiAssistantProviderConfigMeta,
    getAiAssistantCurrentConversation as readAiAssistantCurrentConversation,
    getAiAssistantCurrentConversationId as readAiAssistantCurrentConversationId,
    getAiAssistantProviderSettings as readAiAssistantProviderSettings,
    getAiAssistantSettings as readAiAssistantSettings,
    isAiAssistantJobActive,
    isAiAssistantJobTerminal,
    listAiAssistantConversations,
    listAiAssistantPromptPlugins,
    listAiAssistantProviderConfigs,
    listAiAssistantProviders,
    normalizeAiAssistantJobStatus,
    normalizeAiAssistantModelOptions,
    resolveAiAssistantCurrentSelection,
    resolveAiAssistantPromptPlugin,
    resolveAiAssistantProviderConfig,
    resolveAiAssistantProviderSelection,
} from "/static/js/ai-assistant-data.js?v=20260706-09";

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
    const plugin = getPluginByModule(moduleName);
    if (!plugin) {
        setStatus("未找到指定插件配置", "bad");
        return;
    }
    if (needsPluginTargets(plugin)) {
        await loadPluginTargets(true);
    }
    const renderPlugin = await preparePluginConfigRenderModel(plugin, state.pluginTargets, state.users, api);
    state.pluginConfigModule = moduleName;
    elements.pluginConfigModalTitle.textContent = `${plugin.name} 配置`;
    if (hasStructuredPluginConfig(renderPlugin)) {
        elements.pluginConfigMeta.textContent = "插件配置会以结构化表单保存到 SQLite，并在支持的范围内立即热重载。";
        elements.pluginConfigForm.hidden = false;
        elements.pluginConfigEditor.hidden = true;
        renderStructuredPluginForm(elements.pluginConfigForm, renderPlugin, pluginRenderCtx());
    } else {
        elements.pluginConfigMeta.textContent = "当前插件尚未提供结构化配置描述，暂时仍使用 JSON 编辑。";
        elements.pluginConfigForm.hidden = true;
        elements.pluginConfigForm.innerHTML = "";
        elements.pluginConfigEditor.hidden = false;
        elements.pluginConfigEditor.value = formatJson(plugin.config || {});
    }
    elements.pluginConfigModal.classList.add("is-visible");
}

function closePluginConfigModal() {
    state.pluginConfigModule = "";
    elements.pluginConfigForm.innerHTML = "";
    elements.pluginConfigModal.classList.remove("is-visible");
}

function closePluginExecuteModal() {
    state.pluginExecuteModule = "";
    elements.pluginExecuteForm.innerHTML = "";
    elements.pluginExecuteModal.classList.remove("is-visible");
}

async function executePluginWithConfig(moduleName, config = {}) {
    const result = await api.executePlugin(moduleName, config);
    applyPluginMutationResult(result);
    const execution = normalizeManualPluginExecution({ manual_execution: result?.execution || {} });
    const detail = execution.detail || normalizeInlineText(result?.result?.detail || "");
    setStatus(detail ? `插件已开始执行：${detail}` : "插件已开始执行", "good");
    return result;
}

async function openPluginExecuteModal(moduleName) {
    const plugin = getPluginByModule(moduleName);
    if (!plugin) {
        setStatus("未找到指定功能插件", "bad");
        return;
    }
    if (isDirectExecutePlugin(plugin)) {
        setStatus("正在执行功能插件...");
        await executePluginWithConfig(moduleName, {});
        return;
    }
    if (needsPluginTargets(plugin)) {
        await loadPluginTargets(true);
    }
    const renderPlugin = await preparePluginExecuteRenderModel(plugin, state.pluginTargets, state.users, api);
    if (!renderPlugin.config_schema.length) {
        setStatus("正在执行功能插件...");
        await executePluginWithConfig(moduleName, {});
        return;
    }
    state.pluginExecuteModule = moduleName;
    elements.pluginExecuteModalTitle.textContent = `${plugin.name} 执行范围`;
    elements.pluginExecuteMeta.textContent = "执行前选择这次运行要作用的微信进程、群聊、好友标签或公众号。本次选择不会覆盖已保存配置。";
    renderStructuredPluginForm(elements.pluginExecuteForm, renderPlugin, pluginRenderCtx());
    elements.pluginExecuteModal.classList.add("is-visible");
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
    if (!state.overview) {
        return;
    }

    const cards = buildOverviewCards(state.overview, state.overviewFetchedAt);

    elements.overviewGrid.innerHTML = cards.map((item) => `
        <article class="overview-card tone-${escapeHtml(item.tone)}">
            <div class="overview-label">${escapeHtml(item.label)}</div>
            <div class="overview-value${item.valueClass ? ` ${item.valueClass}` : ""}">${escapeHtml(item.value)}</div>
            <div class="overview-hint">${escapeHtml(item.hint)}</div>
            ${item.body || ""}
        </article>
    `).join("");
}

function renderUsers() {
    if (!state.users) {
        elements.userGrid.innerHTML = '<div class="empty-state">还没有可展示的用户信息。</div>';
        return;
    }

    const userPayload = state.users;
    const users = Array.isArray(userPayload.users) ? userPayload.users : [];

    if (!userPayload.enabled) {
        elements.userGrid.innerHTML = '<div class="empty-state">心跳检测已关闭，请在系统设置中将心跳间隔设置为大于 0 的秒数。</div>';
        return;
    }

    if (!users.length) {
        elements.userGrid.innerHTML = userPayload.healthy === false
            ? '<div class="empty-state">心跳检测执行失败，暂时无法获取登录账号，请检查主服务连接。</div>'
            : '<div class="empty-state">当前未获取到任何登录账号。</div>';
        return;
    }

    elements.userGrid.innerHTML = users.map((user, index) => {
        const nickname = normalizeInlineText(user.nickname || "");
        const userTitle = `用户${index + 1}`;
        const wechatId = normalizeInlineText(user.wxh || "") || "未设置微信号";
        return `
            <article class="user-card">
                <div class="user-card-head">
                    <div>
                        <h4 class="user-name">${escapeHtml(userTitle)}</h4>
                    </div>
                </div>
                <div class="user-info-list">
                    <div class="user-info-item"><span class="user-info-label">昵称</span><span class="user-info-value">${escapeHtml(nickname || "未提供")}</span></div>
                    <div class="user-info-item"><span class="user-info-label">微信号</span><span class="user-info-value">${escapeHtml(wechatId === "未设置微信号" ? "未提供" : wechatId)}</span></div>
                    <div class="user-info-item"><span class="user-info-label">wxid</span><span class="user-info-value user-info-code">${escapeHtml(normalizeInlineText(user.wxid || "") || "未提供")}</span></div>
                    <div class="user-info-item"><span class="user-info-label">wxpid</span><span class="user-info-value">${escapeHtml(user.wxpid !== undefined && user.wxpid !== null && user.wxpid !== "" ? String(user.wxpid) : "未提供")}</span></div>
                </div>
            </article>
        `;
    }).join("");
}

function renderMessages() {
    if (!state.messages.length) {
        elements.messageList.innerHTML = '<div class="empty-state">还没有收到任何消息。</div>';
        elements.messageDetail.innerHTML = '<div class="empty-state">请选择左侧消息查看详情。</div>';
        return;
    }

    if (
        state.messageAutoFollow
        || !state.selectedMessageId
        || !state.messages.some((item) => item.internal_id === state.selectedMessageId)
    ) {
        state.selectedMessageId = state.messages[0].internal_id;
    }

    elements.messageList.innerHTML = state.messages.map((message) => {
        const preview = truncateText(getMessageSummary(message), 88);
        const typeLabel = getMessageTypeLabel(message);
        const conversationLabel = getConversationLabel(message);
        const senderLabel = getSenderLabel(message);
        const timeLabel = getMessageTimeLabel(message);
        const badges = [
            `<span class="badge ${getStatusTone(message.status)}">${escapeHtml(message.status)}</span>`,
            `<span class="badge">${escapeHtml(typeLabel)}</span>`,
        ].join("");

        return `
            <button class="message-item ${message.internal_id === state.selectedMessageId ? "is-active" : ""}" data-message-id="${message.internal_id}" type="button">
                ${renderAvatar(message)}
                <div class="message-main">
                    <div class="message-item-head">
                        <div class="message-primary">
                            <h4 class="message-title">${escapeHtml(getMessageTitle(message))}</h4>
                            <div class="detail-meta message-subline">${escapeHtml(timeLabel)}${message.is_group_message && senderLabel ? ` · ${escapeHtml(senderLabel)}` : !message.is_group_message && conversationLabel ? ` · ${escapeHtml(conversationLabel)}` : ""}</div>
                        </div>
                        <div class="badge-row message-badges">${badges}</div>
                    </div>
                    <p class="message-copy">${escapeHtml(preview)}</p>
                </div>
            </button>
        `;
    }).join("");

    const selected = state.messages.find((message) => message.internal_id === state.selectedMessageId);
    const selectedConversation = getConversationLabel(selected);
    const selectedSender = getSenderLabel(selected);
    const selectedTypeLabel = getMessageTypeLabel(selected);
    const selectedTextContent = normalizeInlineText(selected.text_content || "");
    const rawPayloadText = formatJson(selected.payload);
    const shouldShowTextContent = getMessageTypeCode(selected) === 1 && Boolean(selectedTextContent);
    const selectedSourceTime = getPayloadValue(selected, "create_time", "timestamp", "ts");
    const sourceTimestamp = typeof selectedSourceTime === "string" && /[-:]/.test(selectedSourceTime)
        ? selectedSourceTime
        : formatUnixTimestamp(selectedSourceTime);
    const results = selected.plugin_results?.length
        ? selected.plugin_results.map((item) => `
            <div class="badge-row">
                <span class="badge ${item.handled ? "good" : ""}">${escapeHtml(item.plugin)}</span>
                <span class="badge ${item.stop_processing ? "good" : ""}">${item.handled ? "已处理" : "跳过"}</span>
            </div>
            <div class="detail-meta">${escapeHtml(item.detail || "无额外说明")}</div>
        `).join("")
        : '<div class="empty-state">插件尚未返回处理结果。</div>';

    elements.messageDetail.innerHTML = `
        <div class="detail-head">
            <div>
                <h4 class="detail-title">${escapeHtml(getMessageTitle(selected))}</h4>
            </div>
            <div class="badge-row">
                <span class="badge ${getStatusTone(selected.status)}">${escapeHtml(selected.status)}</span>
                <span class="badge">${escapeHtml(selectedTypeLabel)}</span>
                <span class="badge">${selected.is_group_message ? "群聊" : "单聊"}</span>
            </div>
        </div>
        <div class="detail-section">
            <h5 class="detail-section-title">消息信息</h5>
            <div class="detail-meta">消息 ID：${escapeHtml(selected.msgid || `内部消息 ${selected.internal_id}`)}</div>
            <div class="detail-meta">会话：${escapeHtml(selectedConversation)}</div>
            <div class="detail-meta">发送者：${escapeHtml(selected.sender_display_name || selectedSender)}</div>
            ${selected.is_group_message ? `<div class="detail-meta">群成员：${escapeHtml(selected.room_sender_display_name || selectedSender)}</div>` : ""}
        </div>
        ${shouldShowTextContent ? `<div class="detail-section"><h5 class="detail-section-title">消息内容</h5><div class="detail-text">${escapeHtml(selectedTextContent)}</div></div>` : ""}
        <div class="detail-section">
            <h5 class="detail-section-title">处理时间</h5>
            <div class="detail-meta">接收时间：${escapeHtml(selected.received_at || "未知")}</div>
            <div class="detail-meta">消息时间：${escapeHtml(sourceTimestamp || "上游未提供")}</div>
            <div class="detail-meta">完成时间：${escapeHtml(selected.processed_at || "处理中")}</div>
        </div>
        <div class="detail-section">
            <h5 class="detail-section-title">插件结果</h5>
            <div>${results}</div>
        </div>
        <div class="detail-section">
            <div class="detail-section-head">
                <h5 class="detail-section-title">原始负载</h5>
                <button class="button ghost compact" type="button" data-action="copy-message-payload">复制原始负载</button>
            </div>
            <pre class="code-block">${escapeHtml(rawPayloadText)}</pre>
        </div>
    `;
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
    if (!state.settings) {
        return;
    }

    const configSettings = state.settings.config;
    const runtimeSettings = state.settings.runtime;
    const form = elements.settingsForm;

    for (const [key, value] of Object.entries(configSettings)) {
        const field = form.elements.namedItem(key);
        if (!field) {
            continue;
        }
        if (field.type === "checkbox") {
            field.checked = Boolean(value);
        } else {
            field.value = value;
        }
    }

    if (state.settings.restart_required) {
        elements.settingsAlert.className = "settings-alert is-visible bad";
        elements.settingsAlert.textContent = `检测到需要重启的字段：${state.settings.restart_required_fields.join(", ")}。当前运行值仍为 ${runtimeSettings.host}:${runtimeSettings.port}。`;
    } else if (state.settings.api_auth_enabled && !getStoredApiToken()) {
        elements.settingsAlert.className = "settings-alert is-visible bad";
        elements.settingsAlert.textContent = "已启用 Web API 访问令牌，但当前浏览器尚未保存令牌。请填写 api_token 并保存系统设置。";
    } else {
        elements.settingsAlert.className = "settings-alert is-visible good";
        const authHints = [];
        if (state.settings.api_auth_enabled) {
            authHints.push("Web API 鉴权已启用");
        }
        if (state.settings.callback_auth_enabled) {
            authHints.push("消息回调密钥已启用");
        }
        const suffix = authHints.length ? ` ${authHints.join("，")}。` : "";
        elements.settingsAlert.textContent = `当前 SQLite 配置与运行时配置一致。保存后可热重载的字段会立即生效。${suffix}`;
    }
}

function applyAiAssistantPayload(payload, preserveSelection = true) {
    if (!payload || typeof payload !== "object") {
        return;
    }
    state.aiAssistant = {
        ...(state.aiAssistant || {}),
        ...payload,
    };
    const currentConversation = getAiAssistantCurrentConversation();
    state.aiConversation = Array.isArray(currentConversation?.messages) ? currentConversation.messages : [];
    if (payload.job) {
        state.aiActiveChatJob = payload.job;
        state.aiActiveChatJobId = payload.job.id || state.aiActiveChatJobId;
    }
    if (payload.settings || payload.providers) {
        syncAiAssistantUiFromPayload(preserveSelection);
    }
}

function renderAiAssistantConversationList() {
    if (!elements.aiAssistantConversationList) {
        return;
    }
    const conversations = getAiAssistantConversations();
    if (!conversations.length) {
        elements.aiAssistantConversationList.innerHTML = '<div class="empty-state">还没有历史对话。点击“新建对话”后开始提问即可自动保存。</div>';
        return;
    }
    elements.aiAssistantConversationList.innerHTML = conversations.map((conversation) => `
        <button class="smart-conversation-card ${conversation.is_active ? "is-active" : ""}" type="button" data-ai-conversation-id="${escapeHtml(conversation.id || "")}">
            <div class="smart-conversation-card-head">
                <div>
                    <h6 class="smart-conversation-title">${escapeHtml(conversation.title || "未命名对话")}</h6>
                    <div class="detail-meta">更新时间 ${escapeHtml(formatStandardDateTime(conversation.updated_at) || conversation.updated_at || "未知")}</div>
                </div>
                <div class="badge-row">
                    ${conversation.has_running_message ? '<span class="badge warn">进行中</span>' : ""}
                    ${conversation.is_active ? '<span class="badge good">当前</span>' : ""}
                </div>
            </div>
            <div class="detail-text smart-conversation-preview">${escapeHtml(conversation.last_message_preview || "暂无消息")}</div>
            <div class="detail-meta">共 ${escapeHtml(String(conversation.message_count || 0))} 条消息</div>
        </button>
    `).join("");
}

function renderAiConversation() {
    if (!elements.aiAssistantConversation) {
        return;
    }

    const messages = Array.isArray(getAiAssistantCurrentConversation()?.messages)
        ? getAiAssistantCurrentConversation().messages
        : [];
    if (!messages.length) {
        elements.aiAssistantConversation.innerHTML = '<div class="empty-state">还没有对话。点击“新建对话”开始新的会话，或直接在当前会话中输入问题。</div>';
        return;
    }

    elements.aiAssistantConversation.innerHTML = messages.map((message) => {
        const role = message.role === "assistant" ? "assistant" : "user";
        const roleLabel = role === "assistant" ? "智能插件" : "用户";
        const toolTraces = Array.isArray(message.tool_traces) ? message.tool_traces : [];
        const reasoningContent = String(message.reasoning_content || "").trim();
        const status = String(message.status || (message.error ? "failed" : "completed")).trim().toLowerCase();
        const statusTone = message.error || status === "failed"
            ? "bad"
            : (status === "running" || status === "stopped")
                ? "warn"
                : (role === "assistant" ? "good" : "");
        const statusLabel = status === "running"
            ? "处理中"
            : status === "stopped"
                ? "已停止"
            : status === "failed"
                ? "失败"
                : (role === "assistant" ? "已完成" : "已发送");
        const showReasoning = Boolean(reasoningContent);
        const messageBody = message.content || ((status === "running" || status === "stopped")
            ? (message.progress_message || (status === "running" ? "正在处理中..." : "本次对话已手动停止。"))
            : "无内容");
        return `
            <article class="smart-chat-message ${role === "assistant" ? "is-assistant" : "is-user"} ${message.error || status === "failed" ? "is-error" : ""}">
                <div class="smart-chat-message-head">
                    <div class="badge-row">
                        <span class="badge ${statusTone}">${escapeHtml(roleLabel)}</span>
                        <span class="badge ${statusTone}">${escapeHtml(statusLabel)}</span>
                        ${message.provider_label ? `<span class="badge">${escapeHtml(message.provider_label)}</span>` : ""}
                        ${message.prompt_plugin_name ? `<span class="badge">${escapeHtml(message.prompt_plugin_name)}</span>` : ""}
                        ${message.model ? `<span class="badge">${escapeHtml(message.model)}</span>` : ""}
                    </div>
                    <div class="detail-meta">${escapeHtml(formatStandardDateTime(message.updated_at) || message.updated_at || "")}</div>
                </div>
                ${message.progress_message ? `<div class="smart-chat-progress">${escapeHtml(message.progress_message)}</div>` : ""}
                ${showReasoning ? `
                    <section class="smart-reasoning-block">
                        <div class="detail-meta">思考过程</div>
                        <pre class="code-block smart-reasoning-content">${escapeHtml(reasoningContent)}</pre>
                    </section>
                ` : ""}
                ${toolTraces.length ? `
                    <div class="smart-tool-trace-list">
                        ${toolTraces.map((trace) => {
                            const traceStatus = String(trace.status || "ok").toLowerCase();
                            const traceTone = traceStatus === "running" ? "warn" : (traceStatus === "ok" ? "good" : "bad");
                            const traceLabel = traceStatus === "running" ? "工具运行中" : (traceStatus === "ok" ? "工具成功" : "工具失败");
                            return `
                                <section class="smart-tool-trace-item ${traceStatus === "running" ? "is-running" : ""}">
                                    <div class="smart-tool-trace-head">
                                        <div class="badge-row">
                                            <span class="badge ${traceTone}">${escapeHtml(traceLabel)}</span>
                                            <span class="badge">${escapeHtml(trace.name || "unknown_tool")}</span>
                                        </div>
                                    </div>
                                    <div class="detail-meta">参数</div>
                                    <pre class="code-block">${escapeHtml(formatJson(trace.arguments || {}))}</pre>
                                    ${trace.error ? `<div class="detail-text">${escapeHtml(trace.error)}</div>` : ""}
                                </section>
                            `;
                        }).join("")}
                    </div>
                ` : ""}
                <div class="detail-text smart-chat-message-body">${escapeHtml(messageBody)}</div>
            </article>
        `;
    }).join("");

    elements.aiAssistantConversation.scrollTop = elements.aiAssistantConversation.scrollHeight;
}

function getAiAssistantConversations() {
    return listAiAssistantConversations(state.aiAssistant);
}

function getAiAssistantCurrentConversation() {
    return readAiAssistantCurrentConversation(state.aiAssistant);
}

function getAiAssistantCurrentConversationId() {
    return readAiAssistantCurrentConversationId(state.aiAssistant);
}

function getAiAssistantProviders() {
    return listAiAssistantProviders(state.aiAssistant);
}

function getAiAssistantSettings() {
    return readAiAssistantSettings(state.aiAssistant);
}

function getAiAssistantPromptPlugins() {
    return listAiAssistantPromptPlugins(getAiAssistantSettings());
}

function getAiAssistantPromptPlugin(promptPluginId = state.aiAssistantUi.selectedPromptPluginId) {
    return resolveAiAssistantPromptPlugin(
        getAiAssistantSettings(),
        getAiAssistantPromptPlugins(),
        promptPluginId
    );
}

function getAiAssistantProvider(providerKey = state.aiAssistantUi.selectedProvider) {
    return findAiAssistantProvider(getAiAssistantProviders(), providerKey);
}

function getAiAssistantProviderSettings(providerKey = state.aiAssistantUi.selectedProvider) {
    return readAiAssistantProviderSettings(getAiAssistantSettings(), providerKey);
}

function getAiAssistantProviderConfigs(providerKey = state.aiAssistantUi.selectedProvider) {
    return listAiAssistantProviderConfigs(getAiAssistantSettings(), providerKey);
}

function getAiAssistantProviderConfigMeta(providerKey = state.aiAssistantUi.selectedProvider, configId = state.aiAssistantUi.selectedProviderConfigId) {
    return findAiAssistantProviderConfigMeta(getAiAssistantProvider(providerKey), configId);
}

function getAiAssistantProviderConfig(providerKey = state.aiAssistantUi.selectedProvider, configId = state.aiAssistantUi.selectedProviderConfigId) {
    return resolveAiAssistantProviderConfig(
        getAiAssistantProviderSettings(providerKey),
        getAiAssistantProvider(providerKey),
        configId
    );
}

function getAiAssistantCurrentSelection() {
    return resolveAiAssistantCurrentSelection(state.aiAssistant, state.aiAssistantUi);
}

function setAiAssistantProviderSelection(providerKey, preferredModel = "", preferredConfigId = "") {
    const nextSelection = resolveAiAssistantProviderSelection(
        getAiAssistantSettings(),
        getAiAssistantProviders(),
        providerKey,
        preferredModel,
        preferredConfigId
    );
    state.aiAssistantUi.selectedProvider = nextSelection.selectedProvider;
    state.aiAssistantUi.selectedProviderConfigId = nextSelection.selectedProviderConfigId;
    state.aiAssistantUi.selectedModel = nextSelection.selectedModel;
}

function syncAiAssistantUiFromPayload(preserveSelection = true) {
    const settings = getAiAssistantSettings();
    const promptPlugins = getAiAssistantPromptPlugins();
    const providers = getAiAssistantProviders();
    if (!promptPlugins.length) {
        state.aiAssistantUi.selectedPromptPluginId = "";
    } else {
        const preferredPromptPluginId = preserveSelection && promptPlugins.some((plugin) => plugin.id === state.aiAssistantUi.selectedPromptPluginId)
            ? state.aiAssistantUi.selectedPromptPluginId
            : (promptPlugins.find((plugin) => plugin.id === settings.active_prompt_plugin_id)?.id || promptPlugins[0].id);
        state.aiAssistantUi.selectedPromptPluginId = preferredPromptPluginId;
    }
    if (!providers.length) {
        state.aiAssistantUi.selectedProvider = "";
        state.aiAssistantUi.selectedProviderConfigId = "";
        state.aiAssistantUi.selectedModel = "";
        return;
    }

    const preferredProvider = preserveSelection && providers.some((provider) => provider.key === state.aiAssistantUi.selectedProvider)
        ? state.aiAssistantUi.selectedProvider
        : (providers.find((provider) => provider.key === settings.active_provider)?.key || providers[0].key);
    const preferredModel = preserveSelection ? state.aiAssistantUi.selectedModel : "";
    const preferredConfigId = preserveSelection ? state.aiAssistantUi.selectedProviderConfigId : "";
    setAiAssistantProviderSelection(preferredProvider, preferredModel, preferredConfigId);
}

function buildAiAssistantPromptPluginCardMarkup(promptPlugin = {}) {
    const pluginId = String(promptPlugin.id || createAiAssistantPromptPluginId()).trim();
    const pluginName = String(promptPlugin.name || "").trim();
    const prompt = String(promptPlugin.prompt || promptPlugin.system_prompt || "").trim();
    const maxToolRounds = String(promptPlugin.max_tool_rounds ?? 20).trim() || "20";
    const temperature = String(promptPlugin.temperature ?? 0.2).trim() || "0.2";
    const hasInput = Boolean(pluginName || prompt || maxToolRounds !== "20" || temperature !== "0.2");
    const validationErrors = [];
    if (hasInput && !prompt) {
        validationErrors.push("提示词不能为空。");
    }

    return `
        <article class="smart-prompt-plugin-card ${validationErrors.length ? "is-invalid" : ""}" data-ai-prompt-plugin-row>
            <input type="hidden" data-field="id" value="${escapeHtml(pluginId)}">
            <div class="smart-prompt-plugin-head">
                <label class="field-group smart-prompt-plugin-name-field">
                    <span class="field-label">插件名称</span>
                    <input data-field="name" type="text" value="${escapeHtml(pluginName)}" placeholder="例如：群聊总结">
                </label>
                <label class="field-group smart-prompt-plugin-number-field">
                    <span class="field-label">工具调用轮数上限</span>
                    <input data-field="max_tool_rounds" type="number" min="1" max="500" step="1" value="${escapeHtml(maxToolRounds)}">
                </label>
                <label class="field-group smart-prompt-plugin-number-field">
                    <span class="field-label">温度 temperature</span>
                    <input data-field="temperature" type="number" min="0" max="1.5" step="any" value="${escapeHtml(temperature)}">
                </label>
                <div class="config-object-table-actions smart-prompt-plugin-actions">
                    <button class="button ghost compact" type="button" data-ai-config-action="remove-prompt-plugin">删除</button>
                </div>
            </div>
            <label class="field-group">
                <span class="field-label">提示词</span>
                <textarea class="config-editor smart-prompt-plugin-editor" data-field="prompt" placeholder="为这个智能插件填写单独的系统提示词">${escapeHtml(prompt)}</textarea>
            </label>
            <div class="detail-meta">该提示词会与内置时间提示、工具路由规则一起注入到模型上下文中。</div>
            <div class="config-object-table-error" data-ai-prompt-plugin-error>${escapeHtml(validationErrors.join(" "))}</div>
        </article>
    `;
}

function syncAiAssistantPromptPluginTableState() {
    const list = elements.aiAssistantSettingsForm?.querySelector("[data-ai-prompt-plugin-list]");
    if (!list) {
        return;
    }
    const rows = list.querySelectorAll("[data-ai-prompt-plugin-row]");
    const emptyState = list.querySelector("[data-ai-prompt-plugin-empty]");
    if (!rows.length) {
        if (!emptyState) {
            list.innerHTML = '<div class="empty-state smart-ai-config-empty" data-ai-prompt-plugin-empty>还没有任何提示词插件。点击右上角“新增提示词插件”后，分别填写名称、提示词和轮数上限。</div>';
        }
        return;
    }
    emptyState?.remove();
}

function syncAiAssistantPromptPluginCardState(card) {
    if (!card) {
        return;
    }
    const name = card.querySelector('[data-field="name"]')?.value.trim() || "";
    const prompt = card.querySelector('[data-field="prompt"]')?.value.trim() || "";
    const maxToolRounds = card.querySelector('[data-field="max_tool_rounds"]')?.value.trim() || "20";
    const temperature = card.querySelector('[data-field="temperature"]')?.value.trim() || "0.2";
    const hasInput = Boolean(name || prompt || maxToolRounds !== "20" || temperature !== "0.2");
    const validationErrors = [];
    if (hasInput && !prompt) {
        validationErrors.push("提示词不能为空。");
    }
    card.classList.toggle("is-invalid", validationErrors.length > 0);
    const errorNode = card.querySelector("[data-ai-prompt-plugin-error]");
    if (errorNode) {
        errorNode.textContent = validationErrors.join(" ");
    }
}

function appendAiAssistantPromptPluginRow() {
    const list = elements.aiAssistantSettingsForm?.querySelector("[data-ai-prompt-plugin-list]");
    if (!list) {
        return;
    }

    const currentPromptPlugin = getAiAssistantPromptPlugin();
    syncAiAssistantPromptPluginTableState();
    list.querySelector("[data-ai-prompt-plugin-empty]")?.remove();
    list.insertAdjacentHTML(
        "beforeend",
        buildAiAssistantPromptPluginCardMarkup({
            id: createAiAssistantPromptPluginId(),
            name: "",
            prompt: currentPromptPlugin?.prompt || getAiAssistantSettings().system_prompt || "",
            max_tool_rounds: currentPromptPlugin?.max_tool_rounds ?? getAiAssistantSettings().max_tool_rounds ?? 20,
            temperature: currentPromptPlugin?.temperature ?? getAiAssistantSettings().temperature ?? 0.2,
        })
    );
    syncAiAssistantPromptPluginCardState(list.lastElementChild);
}

function buildAiAssistantProviderSelectOptions(selectedProviderKey = "") {
    return getAiAssistantProviders().map((provider) => `
        <option value="${escapeHtml(provider.key)}" ${provider.key === selectedProviderKey ? "selected" : ""}>${escapeHtml(provider.label)}</option>
    `).join("");
}

function buildAiAssistantConfigRowMarkup(providerKey = "", providerConfig = {}, providerConfigMeta = null) {
    const provider = getAiAssistantProvider(providerKey) || getAiAssistantProviders()[0] || null;
    const normalizedProviderKey = provider?.key || providerKey || "zhipu";
    const configId = String(providerConfig.id || createAiAssistantConfigId(normalizedProviderKey)).trim();
    const configName = String(providerConfig.name || "").trim();
    const apiKey = String(providerConfig.api_key || "").trim();
    const enabled = Boolean(providerConfig.enabled);
    const baseUrlEditable = Boolean(provider?.allow_custom_base_url);
    const defaultBaseUrl = String(provider?.default_base_url || "").trim();
    const baseUrl = baseUrlEditable
        ? (String(providerConfig.base_url || "").trim() || defaultBaseUrl)
        : defaultBaseUrl;
    const savedModelOptions = Array.isArray(providerConfigMeta?.model_options) ? providerConfigMeta.model_options.length : 0;
    const statusMessage = providerConfigMeta?.model_fetch_error
        ? `模型列表获取失败：${providerConfigMeta.model_fetch_error}`
        : (apiKey
            ? (savedModelOptions ? `已载入 ${savedModelOptions} 个模型选项` : "保存后会自动刷新模型列表")
            : "填写并保存 API Key 后可自动载入模型列表");
    const validationErrors = [];
    if (enabled && !apiKey) {
        validationErrors.push("启用中的配置必须填写 API Key。")
    }
    if (baseUrlEditable && apiKey && !baseUrl) {
        validationErrors.push("通用 OpenAI 配置必须填写 Base URL。")
    }

    return `
        <div class="config-object-table-row smart-model-config-row ${validationErrors.length ? "is-invalid" : "is-editing"}" data-ai-config-row>
            <input type="hidden" data-field="id" value="${escapeHtml(configId)}">
            <div class="config-object-table-cell config-object-table-editor-cell">
                <select data-field="provider_key">
                    ${buildAiAssistantProviderSelectOptions(normalizedProviderKey)}
                </select>
                <div class="detail-meta" data-ai-provider-meta>${escapeHtml(provider?.description || "")}</div>
            </div>
            <div class="config-object-table-cell config-object-table-editor-cell">
                <input data-field="name" type="text" value="${escapeHtml(configName)}" placeholder="例如：主账号 / 备用 Key">
            </div>
            <div class="config-object-table-cell config-object-table-editor-cell">
                <input data-field="api_key" type="password" autocomplete="off" value="${escapeHtml(apiKey)}" placeholder="输入 ${escapeHtml(provider?.label || "AI")} API Key">
            </div>
            <div class="config-object-table-cell config-object-table-editor-cell">
                <input data-field="base_url" type="text" value="${escapeHtml(baseUrl)}" ${baseUrlEditable ? "" : "disabled"} placeholder="${escapeHtml(defaultBaseUrl || "https://api.openai.com/v1")}">
                <div class="detail-meta" data-ai-base-url-hint>${escapeHtml(baseUrlEditable ? "仅通用 OpenAI 需要填写 Base URL" : `固定地址：${defaultBaseUrl || "代码内置"}`)}</div>
            </div>
            <div class="config-object-table-cell config-object-table-editor-cell smart-config-switch-cell">
                <label class="switch">
                    <input data-field="enabled" type="checkbox" ${enabled ? "checked" : ""}>
                    <span class="switch-slider"></span>
                </label>
                <div class="detail-meta" data-ai-config-status>${escapeHtml(statusMessage)}</div>
            </div>
            <div class="config-object-table-actions">
                <button class="button ghost compact" type="button" data-ai-config-action="remove-row">删除</button>
            </div>
            <div class="config-object-table-error" data-ai-config-error>${escapeHtml(validationErrors.join(" "))}</div>
        </div>
    `;
}

function syncAiAssistantConfigTableState() {
    const tableBody = elements.aiAssistantSettingsForm?.querySelector("[data-ai-config-table-body]");
    if (!tableBody) {
        return;
    }
    const rows = tableBody.querySelectorAll("[data-ai-config-row]");
    const existingEmptyState = tableBody.querySelector("[data-ai-config-empty]");
    if (!rows.length) {
        if (!existingEmptyState) {
            tableBody.innerHTML = '<div class="empty-state smart-ai-config-empty" data-ai-config-empty>还没有任何模型配置。点击右上角“新增配置”后，按行填写厂商、名称和 API Key。</div>';
        }
        return;
    }
    existingEmptyState?.remove();
}

function syncAiAssistantConfigRowState(row) {
    if (!row) {
        return;
    }

    const providerKey = row.querySelector('[data-field="provider_key"]')?.value.trim() || "";
    const provider = getAiAssistantProvider(providerKey) || getAiAssistantProviders()[0] || null;
    const apiKey = row.querySelector('[data-field="api_key"]')?.value.trim() || "";
    const enabled = Boolean(row.querySelector('[data-field="enabled"]')?.checked);
    const baseUrlInput = row.querySelector('[data-field="base_url"]');
    const providerMeta = row.querySelector("[data-ai-provider-meta]");
    const baseUrlHint = row.querySelector("[data-ai-base-url-hint]");
    const statusNode = row.querySelector("[data-ai-config-status]");
    const errorNode = row.querySelector("[data-ai-config-error]");
    const defaultBaseUrl = String(provider?.default_base_url || "").trim();
    const baseUrlEditable = Boolean(provider?.allow_custom_base_url);

    if (providerMeta) {
        providerMeta.textContent = provider?.description || "";
    }

    if (baseUrlInput instanceof HTMLInputElement) {
        baseUrlInput.disabled = !baseUrlEditable;
        if (baseUrlEditable) {
            baseUrlInput.placeholder = defaultBaseUrl || "https://api.openai.com/v1";
            if (!baseUrlInput.value.trim()) {
                baseUrlInput.value = defaultBaseUrl;
            }
        } else {
            baseUrlInput.value = defaultBaseUrl;
        }
    }

    if (baseUrlHint) {
        baseUrlHint.textContent = baseUrlEditable ? "仅通用 OpenAI 需要填写 Base URL" : `固定地址：${defaultBaseUrl || "代码内置"}`;
    }

    if (statusNode) {
        statusNode.textContent = apiKey ? "保存后会自动刷新模型列表" : "填写并保存 API Key 后可自动载入模型列表";
    }

    const validationErrors = [];
    if (enabled && !apiKey) {
        validationErrors.push("启用中的配置必须填写 API Key。")
    }
    if (baseUrlEditable && apiKey && !(baseUrlInput?.value.trim())) {
        validationErrors.push("通用 OpenAI 配置必须填写 Base URL。")
    }
    row.classList.toggle("is-invalid", validationErrors.length > 0);
    row.classList.toggle("is-editing", validationErrors.length === 0);
    if (errorNode) {
        errorNode.textContent = validationErrors.join(" ");
    }
}

function appendAiAssistantConfigRow(providerKey = state.aiAssistantUi.selectedProvider || getAiAssistantProviders()[0]?.key || "zhipu") {
    const tableBody = elements.aiAssistantSettingsForm?.querySelector("[data-ai-config-table-body]");
    if (!tableBody) {
        return;
    }

    syncAiAssistantConfigTableState();
    tableBody.querySelector("[data-ai-config-empty]")?.remove();

    const provider = getAiAssistantProvider(providerKey) || getAiAssistantProviders()[0] || null;
    tableBody.insertAdjacentHTML(
        "beforeend",
        buildAiAssistantConfigRowMarkup(
            provider?.key || providerKey,
            {
                id: createAiAssistantConfigId(provider?.key || providerKey),
                name: "",
                enabled: false,
                api_key: "",
                base_url: provider?.default_base_url || "",
            },
            null,
        )
    );
    syncAiAssistantConfigRowState(tableBody.lastElementChild);
}

function closeAiAssistantConfigModal() {
    elements.aiAssistantConfigModal?.classList.remove("is-visible");
}

function closeAiAssistantConversationModal() {
    elements.aiAssistantConversationModal?.classList.remove("is-visible");
}

function openAiAssistantConversationModal() {
    closeAiAssistantConfigModal();
    closeAiAssistantToolsModal();
    renderAiAssistantConversationList();
    elements.aiAssistantConversationModal?.classList.add("is-visible");
}

function openAiAssistantConfigModal() {
    closeAiAssistantToolsModal();
    closeAiAssistantConversationModal();
    renderAiAssistant();
    elements.aiAssistantConfigModal?.classList.add("is-visible");
}

function closeAiAssistantToolsModal() {
    elements.aiAssistantToolsModal?.classList.remove("is-visible");
}

function openAiAssistantToolsModal() {
    closeAiAssistantConfigModal();
    closeAiAssistantConversationModal();
    renderAiAssistant();
    elements.aiAssistantToolsModal?.classList.add("is-visible");
}

function renderAiAssistant() {
    if (!state.aiAssistant) {
        return;
    }

    const settings = getAiAssistantSettings();
    const providers = getAiAssistantProviders();
    const promptPlugins = getAiAssistantPromptPlugins();
    const tools = Array.isArray(state.aiAssistant.tools) ? state.aiAssistant.tools : [];
    const currentConversation = getAiAssistantCurrentConversation();
    const currentConversationTitle = currentConversation?.title || "未命名对话";
    const currentJob = state.aiActiveChatJob || {};
    const currentConversationJobActive = isAiAssistantJobActive(currentJob)
        && currentConversation?.id
        && currentJob.conversation_id === currentConversation.id;
    const currentConversationJobStopping = currentConversationJobActive && normalizeAiAssistantJobStatus(currentJob.status) === "stopping";
    const {
        provider: selectedProvider,
        providerSettings: selectedProviderSettings,
        modelOptions,
        selectedConfig,
        selectedConfigMeta,
        selectedModel,
        selectionValue,
        selectedPromptPlugin,
    } = getAiAssistantCurrentSelection();
    const configuredRows = providers.reduce((count, provider) => {
        const providerSettings = settings.providers?.[provider.key] || {};
        const configs = Array.isArray(providerSettings.configs) ? providerSettings.configs : [];
        return count + configs.filter((config) => config.api_key).length;
    }, 0);
    const configRowMarkup = providers.flatMap((provider) => {
        const providerSettings = settings.providers?.[provider.key] || {};
        const providerConfigs = Array.isArray(providerSettings.configs) ? providerSettings.configs : [];
        const providerMetaConfigs = new Map(
            (Array.isArray(provider.configs) ? provider.configs : []).map((config) => [config.id, config])
        );
        return providerConfigs.map((providerConfig) => buildAiAssistantConfigRowMarkup(
            provider.key,
            providerConfig,
            providerMetaConfigs.get(providerConfig.id) || null,
        ));
    }).join("");
    const promptPluginRowMarkup = promptPlugins.map((promptPlugin) => buildAiAssistantPromptPluginCardMarkup(promptPlugin)).join("");

    if (elements.aiAssistantProviderSelect) {
        elements.aiAssistantProviderSelect.innerHTML = providers.map((provider) => `
            <option value="${escapeHtml(provider.key)}" ${provider.key === selectedProvider?.key ? "selected" : ""}>${escapeHtml(provider.label)}</option>
        `).join("");
    }

    if (elements.aiAssistantModelSelect) {
        elements.aiAssistantModelSelect.innerHTML = modelOptions.length
            ? modelOptions.map((option) => `
                <option value="${escapeHtml(option.selectionValue)}" ${option.selectionValue === selectionValue ? "selected" : ""}>${escapeHtml(option.label)}</option>
            `).join("")
            : '<option value="">暂无可用模型</option>';
        elements.aiAssistantModelSelect.disabled = !selectedProvider || (!modelOptions.length && !selectedConfig?.api_key);
    }

    if (elements.aiAssistantPromptPluginSelect) {
        elements.aiAssistantPromptPluginSelect.innerHTML = promptPlugins.length
            ? promptPlugins.map((promptPlugin) => `
                <option value="${escapeHtml(promptPlugin.id || "")}" ${promptPlugin.id === selectedPromptPlugin?.id ? "selected" : ""}>${escapeHtml(promptPlugin.name || "未命名提示词插件")}</option>
            `).join("")
            : '<option value="">暂无提示词插件</option>';
        elements.aiAssistantPromptPluginSelect.disabled = !promptPlugins.length;
    }

    if (elements.toggleAiAssistantConfigButton) {
        elements.toggleAiAssistantConfigButton.textContent = "配置";
    }

    if (elements.toggleAiAssistantToolsButton) {
        elements.toggleAiAssistantToolsButton.textContent = `工具列表 (${tools.length})`;
    }

    if (elements.newAiAssistantConversationButton) {
        elements.newAiAssistantConversationButton.disabled = state.aiRequestInFlight;
    }

    if (elements.openAiAssistantConversationSwitcherButton) {
        elements.openAiAssistantConversationSwitcherButton.disabled = !getAiAssistantConversations().length;
    }

    if (elements.clearAiAssistantConversationButton) {
        elements.clearAiAssistantConversationButton.disabled = state.aiRequestInFlight || !currentConversation?.id;
    }

    if (elements.stopAiAssistantChatButton) {
        elements.stopAiAssistantChatButton.disabled = !currentConversationJobActive || currentConversationJobStopping;
        elements.stopAiAssistantChatButton.textContent = currentConversationJobStopping ? "停止中..." : "停止对话";
    }

    if (elements.aiAssistantSettingsForm) {
        elements.aiAssistantSettingsForm.innerHTML = `
            <section class="config-field-shell field-span-2 smart-prompt-plugin-shell">
                <div class="config-field-head smart-provider-head">
                    <div>
                        <h5 class="detail-section-title">提示词插件配置</h5>
                        <div class="detail-meta">为不同场景维护独立的插件名称、提示词、工具调用轮数上限和温度；聊天页顶部按需切换。</div>
                        <div class="detail-meta">模型 API Key 配置与提示词插件配置解耦，可复用同一套厂商配置。</div>
                    </div>
                    <button class="button secondary compact smart-toolbar-button" type="button" data-ai-config-action="add-prompt-plugin">新增提示词插件</button>
                </div>
                <div class="smart-prompt-plugin-list" data-ai-prompt-plugin-list>
                    ${promptPluginRowMarkup || '<div class="empty-state smart-ai-config-empty" data-ai-prompt-plugin-empty>还没有任何提示词插件。点击右上角“新增提示词插件”后，分别填写名称、提示词和轮数上限。</div>'}
                </div>
            </section>
            <section class="config-field-shell field-span-2 smart-model-config-shell">
                <div class="config-field-head smart-provider-head">
                    <div>
                        <h5 class="detail-section-title">模型配置</h5>
                        <div class="detail-meta">每一行对应一套可选模型配置，固定厂商的网关参数已直接写死；通用 OpenAI 额外填写 Base URL 即可。</div>
                        <div class="detail-meta">当前共保存 ${configuredRows} 条已填写 API Key 的配置，聊天页顶部按“模型名称 / 实际模型”选择。</div>
                    </div>
                    <button class="button secondary compact smart-toolbar-button" type="button" data-ai-config-action="add-row">新增配置</button>
                </div>
                <div class="config-object-table-shell smart-model-config-table">
                    <div class="config-object-table-header smart-model-config-header">
                        <div class="config-object-table-heading">厂商</div>
                        <div class="config-object-table-heading">模型名称</div>
                        <div class="config-object-table-heading">API Key</div>
                        <div class="config-object-table-heading">Base URL</div>
                        <div class="config-object-table-heading">启用</div>
                        <div class="config-object-table-heading is-actions">操作</div>
                    </div>
                    <div class="smart-model-config-body" data-ai-config-table-body>
                        ${configRowMarkup || '<div class="empty-state smart-ai-config-empty" data-ai-config-empty>还没有任何模型配置。点击右上角“新增配置”后，按行填写厂商、名称和 API Key。</div>'}
                    </div>
                </div>
            </section>
            <section class="config-field-shell field-span-2">
                <div class="config-field-head smart-provider-head">
                    <div>
                        <h5 class="detail-section-title">工具权限</h5>
                        <div class="detail-meta">默认仅允许只读查询工具。启用后，模型才可调用发消息、改标签等写操作工具。</div>
                    </div>
                </div>
                <label class="field-group field-span-2">
                    <span class="field-label">允许写操作工具 allow_write_tools</span>
                    <input data-field="allow_write_tools" type="checkbox" ${getAiAssistantSettings().allow_write_tools ? "checked" : ""}>
                </label>
            </section>
        `;
        elements.aiAssistantSettingsForm.querySelectorAll("[data-ai-prompt-plugin-row]").forEach((card) => {
            syncAiAssistantPromptPluginCardState(card);
        });
        elements.aiAssistantSettingsForm.querySelectorAll("[data-ai-config-row]").forEach((row) => {
            syncAiAssistantConfigRowState(row);
        });
    }

    if (elements.aiAssistantAlert) {
        const selectedLabel = selectedProvider?.label || "未选择厂商";
        const selectedPromptPluginLabel = selectedPromptPlugin?.name || "未选择提示词插件";
        if (selectedConfig?.enabled && selectedConfig?.api_key) {
            elements.aiAssistantAlert.className = `settings-alert is-visible ${selectedConfigMeta?.model_fetch_error ? "bad" : "good"}`;
            elements.aiAssistantAlert.textContent = selectedConfigMeta?.model_fetch_error
                ? `${selectedPromptPluginLabel} · ${selectedLabel} · ${selectedConfig.name || "未命名配置"} 已启用，但模型列表自动获取失败，当前会回退到 ${selectedModel}。`
                : `${selectedPromptPluginLabel} · ${selectedLabel} · ${selectedConfig.name || "未命名配置"} 已配置并启用，当前对话模型为 ${selectedModel}。配置会保存在本地 SQLite。`;
        } else if (selectedConfig?.api_key) {
            elements.aiAssistantAlert.className = "settings-alert is-visible bad";
            elements.aiAssistantAlert.textContent = `${selectedPromptPluginLabel} · ${selectedLabel} · ${selectedConfig.name || "未命名配置"} 已填写 API Key，但当前未启用。发送前请先在配置中启用。`;
        } else if (selectedConfig) {
            elements.aiAssistantAlert.className = "settings-alert is-visible bad";
            elements.aiAssistantAlert.textContent = `${selectedPromptPluginLabel} · ${selectedLabel} · ${selectedConfig.name || "未命名配置"} 尚未填写 API Key。点击上方配置按钮后保存，才能开始对话。`;
        } else {
            elements.aiAssistantAlert.className = "settings-alert is-visible bad";
            elements.aiAssistantAlert.textContent = `${selectedPromptPluginLabel} · ${selectedLabel} 还没有任何配置。点击上方配置按钮新增一行并保存后，才能开始对话。`;
        }
    }

    if (elements.aiAssistantToolMeta) {
        const readOnlyCount = tools.filter((tool) => tool.read_only).length;
        elements.aiAssistantToolMeta.textContent = `共 ${tools.length} 个工具，${readOnlyCount} 个只读，${tools.length - readOnlyCount} 个写操作`;
    }

    if (elements.aiAssistantToolGrid) {
        elements.aiAssistantToolGrid.innerHTML = tools.map((tool) => `
            <article class="smart-tool-card">
                <div class="smart-tool-card-head">
                    <h6 class="smart-tool-name">${escapeHtml(tool.name || "unknown")}</h6>
                    <span class="badge ${tool.read_only ? "good" : "warn"}">${escapeHtml(tool.read_only ? "只读" : "写操作")}</span>
                </div>
                <div class="detail-meta">${escapeHtml(tool.description || "")}</div>
            </article>
        `).join("");
    }

    if (elements.aiAssistantProviderBadgeRow) {
        elements.aiAssistantProviderBadgeRow.innerHTML = selectedProvider
            ? `
                <span class="badge">${escapeHtml(selectedPromptPlugin?.name || "未选择提示词插件")}</span>
                <span class="badge good">${escapeHtml(selectedProvider.label)}</span>
                <span class="badge">${escapeHtml(selectedConfig?.name || "未命名配置")}</span>
                <span class="badge">${escapeHtml(selectedModel || selectedProvider.default_model || "")}</span>
                <span class="badge">${escapeHtml(`工具轮数 ${selectedPromptPlugin?.max_tool_rounds ?? settings.max_tool_rounds ?? 20}`)}</span>
                <span class="badge ${selectedConfig?.api_key ? "good" : "bad"}">${escapeHtml(selectedConfig?.api_key ? "已配置 API Key" : "未配置 API Key")}</span>
                <span class="badge ${selectedConfig?.enabled ? "good" : "warn"}">${escapeHtml(selectedConfig?.enabled ? "已启用" : "未启用")}</span>
            `
            : '<span class="badge bad">未配置 AI 厂商</span>';
    }

    if (elements.aiAssistantConversationMeta) {
        elements.aiAssistantConversationMeta.textContent = selectedProvider
            ? `${currentConversationTitle} · ${selectedPromptPlugin?.name || "未选择提示词插件"} · ${selectedProvider.label}${selectedConfig?.name ? ` / ${selectedConfig.name}` : ""} 当前会话模型：${selectedModel || selectedProvider.default_model || "未设置"}。${currentConversationJobActive ? `当前任务：${currentJob.progress_message || "处理中..."}` : (selectedConfigMeta?.model_fetch_error ? "模型列表自动获取失败，已回退到默认模型。" : `当前共可选 ${modelOptions.length} 个模型选项。`)}`
            : "请先配置并启用一个 AI 厂商。";
    }

    if (elements.sendAiAssistantPromptButton) {
        elements.sendAiAssistantPromptButton.disabled = state.aiRequestInFlight || !(selectedConfig?.enabled && selectedConfig?.api_key);
    }

    renderAiAssistantConversationList();
    renderAiConversation();
}

function renderLogs() {
    renderServiceLogs(elements, state.logs, state.logFilters);
}

async function loadOverview() {
    setOverviewData(await api.getOverview());
    renderOverview();
}

async function loadMessages() {
    const payload = await api.getMessages(50);
    state.messages = payload.messages || [];
    renderMessages();
}

async function loadUsers() {
    state.users = await api.getUsers();
    state.pluginTargets = null;
    renderUsers();
}

async function loadPluginTargetsIfNeeded(plugin) {
    if (!needsPluginTargets(plugin)) {
        return state.pluginTargets;
    }
    return loadPluginTargets();
}

async function refreshMessagesByPoll() {
    if (messagePollInFlight) {
        return messagePollInFlight;
    }

    messagePollInFlight = (async () => {
        try {
            await loadMessages();
            handleMessagePollSuccess();
        } catch (error) {
            handleMessagePollFailure(error);
        } finally {
            messagePollInFlight = null;
        }
    })();

    return messagePollInFlight;
}

async function loadPlugins() {
    const payload = await api.getPlugins();
    setPluginsPayload(payload.plugins || []);
}

async function loadPluginLogs(moduleName = state.selectedPluginLogModule, level = state.selectedPluginLogLevel, keyword = state.selectedPluginLogKeyword) {
    const payload = await api.getPluginLogs(moduleName, 240, level, keyword);
    state.pluginLogs = payload;
    state.selectedPluginLogModule = payload.module_name || "";
    state.selectedPluginLogLevel = payload.level || "";
    state.selectedPluginLogKeyword = payload.keyword || "";
    renderPluginLogs();
}

function schedulePluginLogKeywordRefresh() {
    if (pluginLogFilterTimerId !== null) {
        window.clearTimeout(pluginLogFilterTimerId);
    }
    pluginLogFilterTimerId = window.setTimeout(() => {
        setStatus("正在按关键词筛选插件日志...");
        loadPluginLogs(state.selectedPluginLogModule, state.selectedPluginLogLevel, state.selectedPluginLogKeyword)
            .then(() => {
                setStatus("插件日志已更新", "good");
            })
            .catch((error) => {
                setStatus(`插件日志关键词筛选失败：${error.message}`, "bad");
            });
    }, 250);
}

async function loadSettings() {
    state.settings = await api.getSettings();
    renderSettings();
}

async function loadAiAssistant() {
    applyAiAssistantPayload(await api.getAiAssistant(), true);
    renderAiAssistant();
    renderAiAssistantConversationList();
}

async function createAiAssistantConversation() {
    applyAiAssistantPayload(await api.createAiAssistantConversation(), true);
    renderAiAssistant();
    renderAiAssistantConversationList();
}

async function activateAiAssistantConversation(conversationId) {
    applyAiAssistantPayload(await api.activateAiAssistantConversation(conversationId), true);
    renderAiAssistant();
    renderAiAssistantConversationList();
}

async function clearAiAssistantConversation() {
    const conversationId = getAiAssistantCurrentConversationId();
    if (!conversationId) {
        throw new Error("当前没有可清空的对话");
    }
    applyAiAssistantPayload(await api.clearAiAssistantConversation(conversationId), true);
    renderAiAssistant();
    renderAiAssistantConversationList();
}

async function stopAiAssistantChatJob() {
    const currentConversation = getAiAssistantCurrentConversation();
    const currentJob = state.aiActiveChatJob || {};
    const jobId = String(currentJob.id || state.aiActiveChatJobId || "").trim();
    if (!jobId || !isAiAssistantJobActive(currentJob)) {
        throw new Error("当前没有可停止的智能插件对话");
    }
    if (currentConversation?.id && currentJob.conversation_id && currentJob.conversation_id !== currentConversation.id) {
        throw new Error("当前对话没有正在运行的智能插件任务");
    }

    const payload = await api.stopAiAssistantChatJob(jobId);
    applyAiAssistantPayload(payload, true);
    if (isAiAssistantJobTerminal(payload.job) && normalizeAiAssistantJobStatus(payload.job?.status) === "stopped") {
        state.aiRequestInFlight = false;
        state.aiActiveChatJobId = "";
        state.aiActiveChatJob = payload.job || null;
    }
    renderAiAssistant();
    renderAiAssistantConversationList();
}

async function pollAiAssistantChatJob(jobId) {
    state.aiActiveChatJobId = jobId;
    while (state.aiActiveChatJobId === jobId) {
        const payload = await api.getAiAssistantChatJob(jobId);
        applyAiAssistantPayload(payload, true);
        renderAiAssistant();
        renderAiAssistantConversationList();
        const job = payload.job || {};
        const jobStatus = normalizeAiAssistantJobStatus(job.status);
        if (jobStatus === "completed") {
            state.aiRequestInFlight = false;
            state.aiActiveChatJobId = "";
            state.aiActiveChatJob = job;
            const messages = Array.isArray(getAiAssistantCurrentConversation()?.messages) ? getAiAssistantCurrentConversation().messages : [];
            const latestAssistantMessage = [...messages].reverse().find((message) => message.role === "assistant");
            setStatus(`智能插件已完成，本次调用了 ${Number(latestAssistantMessage?.tool_traces?.length || 0)} 个工具`, "good");
            renderAiAssistant();
            return;
        }
        if (jobStatus === "stopped") {
            state.aiRequestInFlight = false;
            state.aiActiveChatJobId = "";
            state.aiActiveChatJob = job;
            setStatus("智能插件已停止");
            renderAiAssistant();
            return;
        }
        if (jobStatus === "failed") {
            state.aiRequestInFlight = false;
            state.aiActiveChatJobId = "";
            state.aiActiveChatJob = job;
            setStatus(`智能插件执行失败：${job.error || "未知错误"}`, "bad");
            renderAiAssistant();
            return;
        }
        await waitForDuration(AI_ASSISTANT_JOB_POLL_INTERVAL_MS);
    }
}

async function loadLogs(fileName = state.selectedLogFile) {
    state.logs = await api.getLogs(fileName, 1000, state.logFilters);
    state.selectedLogFile = state.logs.active_file || "";
    renderLogs();
}

async function refreshCurrentTab() {
    switch (state.activeTab) {
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
            await loadAiAssistant();
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

function readAiAssistantSettingsForm() {
    const form = elements.aiAssistantSettingsForm;
    const providers = getAiAssistantProviders();
    const normalizedProviders = Object.fromEntries(providers.map((provider) => [provider.key, { configs: [] }]));
    const payload = {
        active_provider: state.aiAssistantUi.selectedProvider || state.aiAssistant?.settings?.active_provider || "zhipu",
        active_prompt_plugin_id: "",
        system_prompt: "",
        temperature: 0.2,
        max_tool_rounds: 20,
        allow_write_tools: false,
        prompt_plugins: [],
        providers: normalizedProviders,
    };

    const promptPluginRows = Array.from(form.querySelectorAll("[data-ai-prompt-plugin-row]"));
    for (const [index, row] of promptPluginRows.entries()) {
        const rawName = row.querySelector('[data-field="name"]')?.value.trim() || "";
        const rawPrompt = row.querySelector('[data-field="prompt"]')?.value.trim() || "";
        const rawMaxToolRounds = row.querySelector('[data-field="max_tool_rounds"]')?.value.trim() || "20";
        const rawTemperature = row.querySelector('[data-field="temperature"]')?.value.trim() || "0.2";
        const hasInput = Boolean(rawName || rawPrompt || rawMaxToolRounds !== "20" || rawTemperature !== "0.2");
        if (!hasInput) {
            continue;
        }
        if (!rawPrompt) {
            throw new Error(`${rawName || `提示词插件 ${index + 1}`} 的提示词不能为空`);
        }
        payload.prompt_plugins.push({
            id: row.querySelector('[data-field="id"]')?.value.trim() || createAiAssistantPromptPluginId(),
            name: rawName || `提示词插件 ${payload.prompt_plugins.length + 1}`,
            prompt: rawPrompt,
            temperature: Number(rawTemperature || 0.2),
            max_tool_rounds: Number(rawMaxToolRounds || 20),
        });
    }

    if (!payload.prompt_plugins.length) {
        const fallbackPromptPlugin = getAiAssistantPromptPlugin() || {
            id: createAiAssistantPromptPluginId(),
            name: "通用助手",
            prompt: state.aiAssistant?.settings?.system_prompt || "",
            temperature: state.aiAssistant?.settings?.temperature ?? 0.2,
            max_tool_rounds: state.aiAssistant?.settings?.max_tool_rounds ?? 20,
        };
        payload.prompt_plugins.push({
            id: fallbackPromptPlugin.id || createAiAssistantPromptPluginId(),
            name: fallbackPromptPlugin.name || "通用助手",
            prompt: fallbackPromptPlugin.prompt || state.aiAssistant?.settings?.system_prompt || "",
            temperature: Number(fallbackPromptPlugin.temperature ?? 0.2),
            max_tool_rounds: Number(fallbackPromptPlugin.max_tool_rounds ?? 20),
        });
    }

    const selectedPromptPlugin = payload.prompt_plugins.find((plugin) => plugin.id === state.aiAssistantUi.selectedPromptPluginId)
        || payload.prompt_plugins[0];
    payload.active_prompt_plugin_id = selectedPromptPlugin.id;
    payload.system_prompt = selectedPromptPlugin.prompt;
    payload.temperature = Number(selectedPromptPlugin.temperature ?? 0.2);
    payload.max_tool_rounds = Number(selectedPromptPlugin.max_tool_rounds ?? 20);
    payload.allow_write_tools = Boolean(form.querySelector('[data-field="allow_write_tools"]')?.checked);

    const configRows = Array.from(form.querySelectorAll("[data-ai-config-row]"));
    for (const row of configRows) {
        const providerKey = row.querySelector('[data-field="provider_key"]')?.value.trim() || "";
        const provider = getAiAssistantProvider(providerKey);
        if (!provider || !payload.providers[providerKey]) {
            continue;
        }

        const rawName = row.querySelector('[data-field="name"]')?.value.trim() || "";
        const apiKey = row.querySelector('[data-field="api_key"]')?.value.trim() || "";
        const enabled = Boolean(row.querySelector('[data-field="enabled"]')?.checked);
        const rawBaseUrl = row.querySelector('[data-field="base_url"]')?.value.trim() || "";
        const baseUrl = provider.allow_custom_base_url
            ? (rawBaseUrl || provider.default_base_url || "")
            : (provider.default_base_url || "");
        const isBlankRow = !rawName && !apiKey && !enabled && (!provider.allow_custom_base_url || !rawBaseUrl || rawBaseUrl === provider.default_base_url);
        if (isBlankRow) {
            continue;
        }

        payload.providers[providerKey].configs.push({
            id: row.querySelector('[data-field="id"]')?.value.trim() || createAiAssistantConfigId(providerKey),
            name: rawName || `${provider.label} 配置 ${payload.providers[providerKey].configs.length + 1}`,
            enabled,
            api_key: apiKey,
            base_url: baseUrl,
        });
    }

    return payload;
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