import { api } from "/static/js/api.js?v=20260511-07";
import {
    handleStructuredConfigAction,
    hasStructuredPluginConfig,
    readStructuredPluginConfig,
    renderPluginConfigFields,
    validateStructuredPluginConfig,
} from "/static/js/plugin-config-form.js?v=20260511-02";

const OVERVIEW_POLL_INTERVAL_MS = 15000;
const MESSAGE_POLL_INTERVAL_MS = 3000;
const OVERVIEW_RENDER_TICK_MS = 1000;
const AI_ASSISTANT_JOB_POLL_INTERVAL_MS = 1200;
const AI_ASSISTANT_ACTIVE_JOB_STATUSES = new Set(["queued", "running", "stopping"]);
const AI_ASSISTANT_TERMINAL_JOB_STATUSES = new Set(["completed", "failed", "stopped"]);

const MESSAGE_TYPE_LABELS = {
    0x0: "朋友圈",
    0x1: "文本",
    0x3: "图片",
    0x22: "语音",
    0x25: "好友请求",
    0x2A: "名片",
    0x2B: "视频",
    0x2F: "表情",
    0x30: "位置",
    0x31: "XML消息",
    0x32: "音视频通话",
    0x33: "微信初始化",
    0x34: "通话状态通知",
    0x35: "通话邀请",
    0x3E: "小视频",
    0x42: "微信红包",
    0x2710: "通知消息",
    0x2712: "系统消息",
    0x100000031: "百度视频消息",
    0x200000031: "微信运动消息",
    0x210000031: "小程序消息",
    0x240000031: "BOSS直聘消息",
    0x280000031: "聊天记录消息",
    0x2A0000031: "公众号名片消息",
    0x300000031: "QQ音乐消息",
    0x330000031: "视频号消息",
    0x3900000031: "引用消息",
    0x3F0000031: "视频号卡片消息",
    0x400000031: "哔哩哔哩视频消息",
    0x440000031: "微信游戏消息",
    0x4A00000031: "文件下载完成消息",
    0x500000031: "链接消息",
    0x570000031: "群公告消息",
    0x5E0000031: "商品橱窗消息",
    0x600000031: "文件消息",
    0x650000031: "王者荣耀消息",
    0x7D000000031: "转账消息",
    0x7D300000031: "红包封面消息",
    0x1100000031: "位置共享消息",
    0x1300000031: "合并消息",
    0x1500000031: "微信运动步数消息",
};

const tabMeta = {
    dashboard: {
        label: "仪表盘",
        title: "运行概览",
        description: "集中查看插件服务状态、消息积压和待处理变更。",
    },
    messages: {
        label: "消息中心",
        title: "最新消息",
        description: "查看最近收到的消息以及插件处理结果。",
    },
    users: {
        label: "用户管理",
        title: "登录账号",
        description: "查看心跳检测获取到的登录账号信息与最近一次检测状态。",
    },
    features: {
        label: "功能插件",
        title: "功能插件",
        description: "按需执行功能插件。",
    },
    "ai-assistant": {
        label: "智能插件",
        title: "AI 工具代理",
        description: "配置 AI 厂商并让模型调用 wxrobot_api 工具完成查询与操作。",
    },
    plugins: {
        label: "消息插件",
        title: "消息插件",
        description: "统一管理依赖消息的插件。配置会写入 SQLite，并在支持的范围内立即热重载。",
    },
    "plugin-logs": {
        label: "插件日志",
        title: "插件输出",
        description: "查看所有插件输出的结构化日志，并按插件快速筛选。",
    },
    settings: {
        label: "系统设置",
        title: "全局设置",
        description: "维护服务参数、处理策略与运行时行为。",
    },
    logs: {
        label: "日志中心",
        title: "最新日志",
        description: "查看最近生成的日志文件和最后输出内容。",
    },
};

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

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function formatJson(value) {
    return JSON.stringify(value ?? {}, null, 2);
}

function parseJsonObjectInput(value, label) {
    const rawText = String(value ?? "").trim();
    if (!rawText) {
        return {};
    }
    let parsed;
    try {
        parsed = JSON.parse(rawText);
    } catch {
        throw new Error(`${label} 必须是合法 JSON 对象`);
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(`${label} 必须是 JSON 对象`);
    }
    return parsed;
}

async function copyTextToClipboard(value) {
    const text = String(value ?? "");
    if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "readonly");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
    document.body.append(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
}

function normalizeInlineText(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim();
}

function getPayloadValue(message, ...keys) {
    const payload = message?.payload || {};
    for (const key of keys) {
        const value = payload[key];
        if (value !== undefined && value !== null && value !== "") {
            return value;
        }
    }
    return "";
}

function getStatusTone(status) {
    if (status === "processed") {
        return "good";
    }
    if (status === "failed" || status === "rejected") {
        return "bad";
    }
    return "";
}

function getLogTone(level) {
    const normalized = String(level || "").toUpperCase();
    if (normalized === "ERROR") {
        return "bad";
    }
    if (normalized === "WARNING") {
        return "warn";
    }
    if (normalized === "INFO") {
        return "good";
    }
    return "";
}

function getLogLevelClass(level) {
    const normalized = String(level || "").toUpperCase();
    if (normalized === "CRITICAL") {
        return "level-critical";
    }
    if (normalized === "ERROR") {
        return "level-error";
    }
    if (normalized === "WARNING") {
        return "level-warning";
    }
    if (normalized === "INFO") {
        return "level-info";
    }
    if (normalized === "DEBUG") {
        return "level-debug";
    }
    return "level-raw";
}

function getMessageTypeCode(message) {
    const candidates = [
        message.local_type,
        message.msg_type,
        getPayloadValue(message, "msg_type", "local_type"),
    ];
    for (const value of candidates) {
        if (value === "" || value === null || value === undefined) {
            continue;
        }
        const parsed = Number(value);
        if (!Number.isNaN(parsed)) {
            return parsed;
        }
    }
    return null;
}

function getMessageTypeLabel(message) {
    const typeCode = getMessageTypeCode(message);
    if (typeCode === null) {
        return "未知类型";
    }
    return MESSAGE_TYPE_LABELS[typeCode] || `类型 ${typeCode}`;
}

function formatUnixTimestamp(value) {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue) || numericValue <= 0) {
        return "";
    }

    const timestamp = numericValue > 1e12 ? numericValue : numericValue * 1000;
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) {
        return "";
    }

    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
}

function formatDuration(totalSeconds) {
    const normalized = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    const hours = Math.floor(normalized / 3600);
    const minutes = Math.floor((normalized % 3600) / 60);
    const seconds = Math.floor(normalized % 60);
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatStandardDateTime(value) {
    const normalized = normalizeInlineText(value);
    if (!normalized) {
        return "";
    }
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(normalized)) {
        return normalized;
    }
    const parsed = new Date(normalized);
    if (Number.isNaN(parsed.getTime())) {
        return normalized;
    }
    return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, "0")}-${String(parsed.getDate()).padStart(2, "0")} ${String(parsed.getHours()).padStart(2, "0")}:${String(parsed.getMinutes()).padStart(2, "0")}:${String(parsed.getSeconds()).padStart(2, "0")}`;
}

function formatHeartbeatInterval(value) {
    const seconds = Math.max(0, Number(value) || 0);
    return seconds > 0 ? `${seconds} 秒一次` : "已关闭";
}

function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlightText(value, queries = []) {
    const source = String(value ?? "");
    const tokens = [...new Set(queries.map((query) => normalizeInlineText(query)).filter(Boolean))];
    if (!tokens.length) {
        return escapeHtml(source);
    }
    const pattern = new RegExp(`(${tokens.map(escapeRegExp).join("|")})`, "gi");
    return source.split(pattern).map((segment, index) => (
        index % 2 === 1
            ? `<mark class="log-mark">${escapeHtml(segment)}</mark>`
            : escapeHtml(segment)
    )).join("");
}

function getConversationLabel(message) {
    return normalizeInlineText(
        message.conversation_display_name
        || message.conversation_wxid
        || getPayloadValue(message, "talker", "sender", "wxid", "conversation_id")
        || "未知会话"
    );
}

function getSenderLabel(message) {
    return normalizeInlineText(
        message.room_sender_display_name
        || message.sender_display_name
        || message.sender_wxid
        || getPayloadValue(message, "room_sender", "from_wxid", "from_user", "sender", "wxid")
        || "未知发送者"
    );
}

function getMessageTimeLabel(message) {
    const rawValue = getPayloadValue(message, "create_time", "timestamp", "ts");
    if (typeof rawValue === "string" && /[-:]/.test(rawValue)) {
        return rawValue;
    }
    return formatUnixTimestamp(rawValue) || message.received_at || "未知时间";
}

function getMessageSummary(message) {
    const candidates = [
        message.text_content,
        message.content,
        getPayloadValue(message, "content", "message_content", "msg", "title", "desc", "brief", "description", "s1", "s3", "s4"),
    ];

    for (const candidate of candidates) {
        const text = normalizeInlineText(candidate);
        if (text) {
            return text;
        }
    }

    const typeLabel = getMessageTypeLabel(message);
    if (typeLabel === "图片") {
        return "收到一条图片消息";
    }
    if (typeLabel === "语音") {
        return "收到一条语音消息";
    }
    if (typeLabel === "视频") {
        return "收到一条视频消息";
    }
    if (typeLabel === "表情") {
        return "收到一条表情消息";
    }
    return `收到一条${typeLabel}`;
}

function getMessageTitle(message) {
    const explicitTitle = normalizeInlineText(message.title_display);
    if (explicitTitle) {
        return explicitTitle;
    }
    const sender = getSenderLabel(message);
    const typeLabel = getMessageTypeLabel(message);
    if (message.is_group_message) {
        return getConversationLabel(message);
    }
    if (sender && sender !== "未知发送者") {
        return sender;
    }
    if (message.msgid) {
        return `${typeLabel} · ${message.msgid}`;
    }
    return `${typeLabel}消息`;
}

function truncateText(value, maxLength = 96) {
    const normalized = normalizeInlineText(value);
    return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized;
}

function getAvatarUrl(message) {
    return normalizeInlineText(
        message.avatar_url
        || message.conversation_avatar_url
        || message.sender_avatar_url
    );
}

function renderAvatar(message) {
    const title = getMessageTitle(message);
    const avatarUrl = getAvatarUrl(message);
    const fallback = escapeHtml((title || "?").slice(0, 1).toUpperCase());
    if (avatarUrl) {
        return `<div class="message-avatar"><img class="message-avatar-img" src="${escapeHtml(avatarUrl)}" alt="${escapeHtml(title)}"></div>`;
    }
    return `<div class="message-avatar message-avatar-fallback">${fallback}</div>`;
}

function setStatus(text, type = "") {
    elements.statusPill.textContent = text;
    elements.statusPill.className = `status-pill ${type}`.trim();
}

function setOverviewData(payload) {
    state.overview = payload;
    state.overviewFetchedAt = Date.now();
}

function applyPluginMutationResult(result) {
    if (result?.overview) {
        setOverviewData(result.overview);
        renderOverview();
    }
    if (Array.isArray(result?.plugins)) {
        state.plugins = result.plugins;
        renderPlugins();
    }
    if (result?.settings) {
        state.settings = result.settings;
        renderSettings();
    }
}

function getPluginByModule(moduleName) {
    return state.plugins.find((plugin) => plugin.module === moduleName) || null;
}

function getPluginDisplayName(moduleName, fallback = "未知插件") {
    const plugin = getPluginByModule(moduleName);
    if (plugin) {
        return plugin.name;
    }
    const pluginOption = state.pluginLogs?.available_plugins?.find((item) => item.module === moduleName);
    return normalizeInlineText(pluginOption?.name || moduleName || fallback) || fallback;
}

function hasPluginLogData(dataValue) {
    return !(
        dataValue === undefined
        || dataValue === null
        || dataValue === ""
        || (Array.isArray(dataValue) && !dataValue.length)
        || (typeof dataValue === "object" && !Array.isArray(dataValue) && !Object.keys(dataValue).length)
    );
}

function getPluginLogById(logId) {
    return state.pluginLogs?.logs?.find((item) => item.internal_id === logId) || null;
}

function buildStructuredPluginConfigPayload(plugin) {
    const nextConfig = readStructuredPluginConfig(elements.pluginConfigForm, plugin);
    const mergedConfig = { ...(plugin.config || {}) };
    for (const field of Array.isArray(plugin.config_schema) ? plugin.config_schema : []) {
        delete mergedConfig[field.key];
        for (const alias of Array.isArray(field.aliases) ? field.aliases : []) {
            delete mergedConfig[alias];
        }
    }
    return {
        ...mergedConfig,
        ...nextConfig,
    };
}

function getPluginScopeTargets(plugin) {
    const rawTargets = Array.isArray(plugin?.scope_targets) ? plugin.scope_targets : [];
    return [...new Set(rawTargets.map((item) => normalizeInlineText(item).toLowerCase()).filter(Boolean))];
}

function mergeOptionsWithCurrentValues(options, currentValues) {
    const nextOptions = Array.isArray(options) ? [...options] : [];
    const seen = new Set(nextOptions.map((option) => String(option?.value ?? "").trim()).filter(Boolean));
    const values = Array.isArray(currentValues)
        ? currentValues
        : (currentValues === undefined || currentValues === null || currentValues === "" ? [] : [currentValues]);
    for (const value of values) {
        const normalized = String(value ?? "").trim();
        if (!normalized || seen.has(normalized)) {
            continue;
        }
        seen.add(normalized);
        nextOptions.push({
            label: `当前配置(${normalized})`,
            value: normalized,
        });
    }
    return nextOptions;
}

function needsPluginTargets(plugin) {
    const scopeTargets = getPluginScopeTargets(plugin);
    if (scopeTargets.includes("rooms") || scopeTargets.includes("friend_labels")) {
        return true;
    }
    const schema = Array.isArray(plugin?.config_schema) ? plugin.config_schema : [];
    return schema.some((field) => {
        if (!field || typeof field !== "object") {
            return false;
        }
        if (field.options_source === "room_options" || field.options_source === "label_options") {
            return true;
        }
        return Array.isArray(field.columns)
            && field.columns.some((column) => column && typeof column === "object" && (column.options_source === "room_options" || column.options_source === "label_options"));
    });
}

function resolveTargetOptionsBySource(optionsSource, currentValues) {
    if (optionsSource === "room_options") {
        return mergeOptionsWithCurrentValues(state.pluginTargets?.room_options || [], currentValues);
    }
    if (optionsSource === "label_options") {
        return Array.isArray(state.pluginTargets?.label_options) ? [...state.pluginTargets.label_options] : [];
    }
    return [];
}

function hydrateDynamicFieldOptions(field, configValue) {
    if (!field || typeof field !== "object") {
        return field;
    }

    const nextField = { ...field };
    if (field.options_source) {
        nextField.options = resolveTargetOptionsBySource(field.options_source, configValue);
    }

    if (Array.isArray(field.columns)) {
        nextField.columns = field.columns.map((column) => {
            if (!column || typeof column !== "object" || !column.options_source) {
                return column;
            }
            const currentValues = Array.isArray(configValue)
                ? configValue.map((row) => row && typeof row === "object" ? row[column.key] : undefined)
                : [];
            return {
                ...column,
                options: resolveTargetOptionsBySource(column.options_source, currentValues),
            };
        });
    }

    return nextField;
}

function buildPluginScopeFields(plugin, modeDefaults = {}) {
    const scopeTargets = getPluginScopeTargets(plugin);
    const config = plugin?.config || {};
    const fields = [];

    if (scopeTargets.includes("rooms")) {
        const roomOptions = mergeOptionsWithCurrentValues(state.pluginTargets?.room_options || [], config._scope_room_ids || []);
        fields.push({
            key: "_scope_room_mode",
            label: "群聊范围",
            type: "select",
            full_width: false,
            default: modeDefaults._scope_room_mode || "all",
            options: [
                { label: "全部群聊", value: "all" },
                { label: "指定群聊", value: "selected" },
                { label: "不作用于任何群聊", value: "none" },
            ],
            description: "默认作用于全部群聊。选择“指定群聊”后，在下方勾选具体群聊。",
        });
        fields.push({
            key: "_scope_room_ids",
            label: "指定群聊",
            type: "searchable-multi-checkbox",
            options: roomOptions,
            default: [],
            search_placeholder: "搜索群名称或 wxid",
            show_selected_label: "仅显示已勾选群聊",
            empty_text: "没有匹配到群聊。",
            empty_no_options_text: "当前还没有可选群聊。",
            description: roomOptions.length
                ? "仅当上方选择“指定群聊”时生效。支持按群名称或 wxid 搜索筛选。"
                : "当前未读取到群聊列表，可先刷新用户或稍后重试。",
        });
    }

    if (scopeTargets.includes("friend_labels")) {
        const labelOptions = mergeOptionsWithCurrentValues(state.pluginTargets?.label_options || [], config._scope_friend_labels || []);
        fields.push({
            key: "_scope_friend_mode",
            label: "好友范围",
            type: "select",
            full_width: false,
            default: modeDefaults._scope_friend_mode || "all",
            options: [
                { label: "全部好友", value: "all" },
                { label: "指定好友标签", value: "selected" },
                { label: "不作用于任何好友", value: "none" },
            ],
            description: "好友范围通过标签控制。选择“指定好友标签”后，在下方勾选标签。",
        });
        fields.push({
            key: "_scope_friend_labels",
            label: "指定好友标签",
            type: "searchable-multi-checkbox",
            options: labelOptions,
            default: [],
            search_placeholder: "搜索好友标签",
            show_selected_label: "仅显示已勾选标签",
            empty_text: "没有匹配到好友标签。",
            empty_no_options_text: "当前还没有可选好友标签。",
            description: labelOptions.length
                ? "仅当上方选择“指定好友标签”时生效。支持按标签名搜索筛选。"
                : "当前未读取到标签列表，可先刷新用户或稍后重试。",
        });
    }

    return fields;
}

function buildPluginExecuteRenderModel(plugin) {
    const scopeTargets = getPluginScopeTargets(plugin);
    const config = { ...(plugin?.config || {}) };
    if (scopeTargets.includes("rooms") && config._scope_room_mode === undefined) {
        config._scope_room_mode = "selected";
    }
    if (scopeTargets.includes("friend_labels") && config._scope_friend_mode === undefined) {
        config._scope_friend_mode = "selected";
    }
    return {
        ...plugin,
        config,
        config_schema: buildPluginScopeFields({ ...plugin, config }, config),
    };
}

async function loadPluginTargets(force = false) {
    if (!force && state.pluginTargets) {
        return state.pluginTargets;
    }
    state.pluginTargets = await api.getPluginTargets();
    return state.pluginTargets;
}

function getWxpidFieldOptions(currentValue) {
    const users = Array.isArray(state.users?.users) ? state.users.users : [];
    const seen = new Set();
    const options = [];

    for (const user of users) {
        const numericValue = Number(user?.wxpid ?? user?.pid);
        if (!Number.isFinite(numericValue)) {
            continue;
        }
        const key = String(numericValue);
        if (seen.has(key)) {
            continue;
        }
        seen.add(key);
        const nickname = normalizeInlineText(user?.nickname || user?.display_name || "") || "未命名账号";
        const wxid = normalizeInlineText(user?.wxid || "");
        options.push({
            label: wxid ? `${nickname}(${wxid})` : `${nickname}(${numericValue})`,
            value: numericValue,
        });
    }

    const normalizedCurrentValue = String(currentValue ?? "").trim();
    if (normalizedCurrentValue && !seen.has(normalizedCurrentValue)) {
        const fallbackValue = Number(normalizedCurrentValue);
        options.push({
            label: `当前配置(${normalizedCurrentValue})`,
            value: Number.isFinite(fallbackValue) ? fallbackValue : normalizedCurrentValue,
        });
    }

    return options;
}

function buildPluginConfigRenderModel(plugin) {
    if (!plugin || !Array.isArray(plugin.config_schema)) {
        return plugin;
    }

    return {
        ...plugin,
        config_schema: plugin.config_schema.map((field) => {
            if (!field || typeof field !== "object") {
                return field;
            }
            const nextField = hydrateDynamicFieldOptions(field, plugin.config?.[field.key]);
            if (nextField.key !== "wxpid") {
                return nextField;
            }
            return {
                ...nextField,
                type: "select",
                options: getWxpidFieldOptions(plugin.config?.[field.key]),
                description: nextField.description || "默认使用首个登录微信进程。",
            };
        }).concat(
            plugin.message_dependent
                ? buildPluginScopeFields(plugin).filter((field) => !plugin.config_schema.some((item) => item?.key === field.key))
                : []
        ),
    };
}

function sortPluginsForDisplay(plugins) {
    return [...plugins].sort((left, right) => {
        const enabledDiff = Number(Boolean(right?.enabled)) - Number(Boolean(left?.enabled));
        if (enabledDiff !== 0) {
            return enabledDiff;
        }
        const loadedDiff = Number(Boolean(right?.loaded)) - Number(Boolean(left?.loaded));
        if (loadedDiff !== 0) {
            return loadedDiff;
        }
        const leftLabel = normalizeInlineText(left?.name || left?.module || "");
        const rightLabel = normalizeInlineText(right?.name || right?.module || "");
        return leftLabel.localeCompare(rightLabel, "zh-CN");
    });
}

async function openPluginConfigModal(moduleName) {
    const plugin = getPluginByModule(moduleName);
    if (!plugin) {
        setStatus("未找到指定插件配置", "bad");
        return;
    }
    if (plugin.message_dependent && needsPluginTargets(plugin)) {
        await loadPluginTargets();
    }
    const renderPlugin = buildPluginConfigRenderModel(plugin);
    state.pluginConfigModule = moduleName;
    elements.pluginConfigModalTitle.textContent = `${plugin.name} 配置`;
    if (hasStructuredPluginConfig(renderPlugin)) {
        elements.pluginConfigMeta.textContent = "插件配置会以结构化表单保存到 SQLite，并在支持的范围内立即热重载。";
        elements.pluginConfigForm.hidden = false;
        elements.pluginConfigEditor.hidden = true;
        renderPluginConfigFields(elements.pluginConfigForm, renderPlugin);
        initializeSearchableChoiceFilters(elements.pluginConfigForm);
        syncScopeFieldVisibility(elements.pluginConfigForm);
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
    const detail = normalizeInlineText(result?.result?.detail || "");
    setStatus(detail ? `插件执行完成：${detail}` : "插件执行完成", result?.result?.handled ? "good" : "");
    return result;
}

async function openPluginExecuteModal(moduleName) {
    const plugin = getPluginByModule(moduleName);
    if (!plugin) {
        setStatus("未找到指定功能插件", "bad");
        return;
    }
    if (needsPluginTargets(plugin)) {
        await loadPluginTargets();
    }
    const renderPlugin = buildPluginExecuteRenderModel(plugin);
    if (!renderPlugin.config_schema.length) {
        setStatus("正在执行功能插件...");
        await executePluginWithConfig(moduleName, {});
        return;
    }
    state.pluginExecuteModule = moduleName;
    elements.pluginExecuteModalTitle.textContent = `${plugin.name} 执行范围`;
    elements.pluginExecuteMeta.textContent = "执行前选择这次运行要作用的群聊、好友标签或公众号。本次选择不会覆盖已保存配置。";
    renderPluginConfigFields(elements.pluginExecuteForm, renderPlugin);
    initializeSearchableChoiceFilters(elements.pluginExecuteForm);
    syncScopeFieldVisibility(elements.pluginExecuteForm);
    elements.pluginExecuteModal.classList.add("is-visible");
}

function isNetworkFetchError(error) {
    const message = normalizeInlineText(error?.message || error);
    return message === "Failed to fetch" || /NetworkError/i.test(message);
}

function getMessagePollErrorText(error, failureCount) {
    if (isNetworkFetchError(error)) {
        return failureCount > 1
            ? `消息服务仍未连通，正在第 ${failureCount} 次重试...`
            : "消息服务暂时不可用，正在自动重连...";
    }
    return `消息自动刷新失败：${error.message}`;
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
    const meta = tabMeta[tabName];
    elements.activeTabLabel.textContent = meta.label;
    elements.pageTitle.textContent = meta.title;
    elements.pageDescription.textContent = meta.description;

    elements.navTabs.forEach((button) => {
        button.classList.toggle("is-active", button.dataset.tab === tabName);
    });

    elements.panels.forEach((panel) => {
        panel.classList.toggle("is-active", panel.dataset.panel === tabName);
    });
}

function renderOverview() {
    if (!state.overview) {
        return;
    }

    const enabledCount = Number(state.overview.enabled_plugin_count || 0);
    const loadedCount = Number(state.overview.loaded_plugin_count || 0);
    const queuedMessages = Number(state.overview.queued_messages || 0);
    const pendingRestartFields = state.overview.pending_restart_fields || [];
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - (state.overviewFetchedAt || Date.now())) / 1000));
    const uptimeSeconds = Math.max(0, Number(state.overview.uptime_seconds || 0) + elapsedSeconds);
    const requiresRestart = pendingRestartFields.length > 0;
    const runtimeStartedAt = formatStandardDateTime(state.overview.runtime_started_at) || "未知";
    const heartbeat = state.overview.heartbeat || {};
    const heartbeatEnabled = Boolean(heartbeat.enabled);
    const heartbeatHealthy = heartbeat.healthy;
    const heartbeatStatus = !heartbeatEnabled
        ? "已关闭"
        : heartbeatHealthy === false
            ? "异常"
            : heartbeatHealthy === true
                ? "正常"
                : "检测中";
    const heartbeatHint = heartbeatEnabled
        ? `${formatHeartbeatInterval(heartbeat.interval_seconds)}${heartbeat.last_checked_at ? ` · 最近 ${formatStandardDateTime(heartbeat.last_checked_at)}` : ""}`
        : "设置为 0 时保持关闭";

    const cards = [
        {
            label: "运行时间",
            value: formatDuration(uptimeSeconds),
            hint: "从 WebUI 服务启动时开始累计，并每秒自动刷新",
            tone: "sky",
        },
        {
            label: "启动时间",
            value: runtimeStartedAt,
            hint: "WebUI 服务启动时间",
            tone: "teal",
            valueClass: "is-compact",
        },
        {
            label: "心跳检测",
            value: heartbeatStatus,
            hint: heartbeatHint,
            tone: heartbeatEnabled && heartbeatHealthy === false ? "amber" : "teal",
        },
        {
            label: "已启用插件",
            value: String(enabledCount),
            hint: "来自当前配置的启用数量",
            tone: "teal",
        },
        {
            label: "成功加载",
            value: String(loadedCount),
            hint: loadedCount === enabledCount ? "运行时插件已全部在线" : "仍有插件未进入运行态",
            tone: loadedCount === enabledCount ? "sky" : "amber",
        },
        {
            label: "待处理消息",
            value: String(queuedMessages),
            hint: queuedMessages > 0 ? "队列中仍有消息等待消费" : "消息流当前没有堆积",
            tone: queuedMessages > 0 ? "amber" : "teal",
        },
        {
            label: "重启变更",
            value: String(pendingRestartFields.length),
            hint: requiresRestart ? "部分设置待重启后生效" : "当前运行态与配置保持同步",
            tone: requiresRestart ? "amber" : "sky",
        },
    ];

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

function renderPluginCards(targetElement, plugins, emptyText, pluginKind) {
    if (!targetElement) {
        return;
    }

    if (!plugins.length) {
        targetElement.innerHTML = `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
        return;
    }

    targetElement.innerHTML = plugins.map((plugin) => {
        const configKeys = Object.keys(plugin.config || {});
        const configSummary = configKeys.length ? `当前已配置 ${configKeys.length} 项自定义参数。` : "当前未配置自定义参数。";
        const isFeaturePlugin = pluginKind === "feature";
        const isManualExecutePlugin = isFeaturePlugin && !plugin?.capabilities?.tick_hook;
        const primaryButton = isManualExecutePlugin
            ? `<button class="button primary" type="button" data-action="execute-plugin" data-plugin="${escapeHtml(plugin.module)}">执行插件</button>`
            : `<button class="button ${plugin.enabled ? "secondary" : "primary"}" type="button" data-action="toggle-plugin" data-plugin="${escapeHtml(plugin.module)}" data-enabled="${plugin.enabled ? "0" : "1"}">${plugin.enabled ? "停止插件" : "启动插件"}</button>`;
        return `
            <article class="plugin-card">
                <div class="plugin-head">
                    <div>
                        <h4 class="plugin-name">${escapeHtml(plugin.name)}</h4>
                        <div class="plugin-module">${escapeHtml(plugin.module)}</div>
                    </div>
                    <div class="badge-row">
                        <span class="badge ${plugin.enabled ? "good" : ""}">${plugin.enabled ? "已启用" : "未启用"}</span>
                        <span class="badge ${plugin.loaded ? "good" : plugin.loadable ? "" : "bad"}">${plugin.loaded ? "已加载" : plugin.loadable ? "可加载" : "加载失败"}</span>
                    </div>
                </div>
                <p class="plugin-copy">${escapeHtml(plugin.description || "该插件未提供额外说明。")}</p>
                ${plugin.error ? `<div class="settings-alert is-visible bad">${escapeHtml(plugin.error)}</div>` : ""}
                <div class="detail-meta">${escapeHtml(configSummary)}</div>
                <div class="field-actions">
                    ${primaryButton}
                    <button class="button ghost" type="button" data-action="open-plugin-config" data-plugin="${escapeHtml(plugin.module)}">修改配置</button>
                </div>
            </article>
        `;
    }).join("");
}

function normalizeChoiceSearchText(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

function normalizeScopeModeValue(value) {
    const normalized = String(value ?? "").trim();
    return normalized.replace(/^"|"$/g, "");
}

function applySearchableChoiceFilter(input) {
    const fieldContainer = input?.closest("[data-config-field]");
    if (!fieldContainer) {
        return;
    }
    const query = normalizeChoiceSearchText(input.value);
    const showSelectedInput = fieldContainer.querySelector("[data-config-show-selected]");
    const showSelectedOnly = Boolean(showSelectedInput?.checked);
    const choiceItems = [...fieldContainer.querySelectorAll("[data-config-choice-item]")];
    let visibleCount = 0;
    for (const item of choiceItems) {
        const searchText = normalizeChoiceSearchText(item.dataset.searchText || item.textContent || "");
        const checkedInput = item.querySelector('input[type="checkbox"][data-config-key]');
        const checkedMatched = !showSelectedOnly || Boolean(checkedInput?.checked);
        const matched = (!query || searchText.includes(query)) && checkedMatched;
        item.hidden = !matched;
        item.style.display = matched ? "" : "none";
        if (matched) {
            visibleCount += 1;
        }
    }
    const emptyState = fieldContainer.querySelector("[data-config-search-empty]");
    if (emptyState) {
        emptyState.hidden = visibleCount > 0;
    }
}

function initializeSearchableChoiceFilters(container) {
    if (!container) {
        return;
    }
    container.querySelectorAll("[data-config-search-input]").forEach((input) => {
        applySearchableChoiceFilter(input);
    });
}

function getSearchableSelectElements(container) {
    return {
        input: container?.querySelector("[data-config-searchable-input]"),
        hiddenInput: container?.querySelector("[data-config-searchable-value]"),
        menu: container?.querySelector("[data-config-searchable-menu]"),
        emptyState: container?.querySelector("[data-config-searchable-empty]"),
        options: container ? [...container.querySelectorAll("[data-config-searchable-option]")] : [],
    };
}

function getSearchableSelectOptionLabel(optionButton) {
    return String(
        optionButton?.dataset.optionLabel
        || optionButton?.querySelector(".config-searchable-select-option-title")?.textContent
        || ""
    ).trim();
}

function getSelectedSearchableSelectOption(container) {
    const { hiddenInput, options } = getSearchableSelectElements(container);
    if (!hiddenInput?.value) {
        return null;
    }
    return options.find((option) => option.dataset.optionValue === hiddenInput.value) || null;
}

function syncSearchableSelectSelection(container) {
    const selectedOption = getSelectedSearchableSelectOption(container);
    const { options } = getSearchableSelectElements(container);
    for (const option of options) {
        option.classList.toggle("is-selected", option === selectedOption);
    }
}

function applySearchableSelectFilter(input) {
    const container = input?.closest("[data-config-searchable-select]");
    if (!container) {
        return;
    }
    const { menu, emptyState, options } = getSearchableSelectElements(container);
    const query = normalizeChoiceSearchText(input.value);
    let visibleCount = 0;
    for (const option of options) {
        const searchText = normalizeChoiceSearchText(option.dataset.searchText || option.textContent || "");
        const matched = !query || searchText.includes(query);
        option.hidden = !matched;
        option.style.display = matched ? "" : "none";
        if (matched) {
            visibleCount += 1;
        }
    }
    if (emptyState) {
        emptyState.hidden = visibleCount > 0;
    }
    if (menu) {
        menu.hidden = false;
    }
    container.classList.add("is-open");
}

function closeSearchableSelect(container, restoreDisplay = false) {
    if (!container) {
        return;
    }
    const { input, menu } = getSearchableSelectElements(container);
    const selectedOption = getSelectedSearchableSelectOption(container);
    if (restoreDisplay && input) {
        input.value = selectedOption ? getSearchableSelectOptionLabel(selectedOption) : "";
    }
    if (menu) {
        menu.hidden = true;
    }
    container.classList.remove("is-open");
}

function clearSearchableSelectSelection(container) {
    const { hiddenInput } = getSearchableSelectElements(container);
    if (hiddenInput) {
        hiddenInput.value = "";
    }
    syncSearchableSelectSelection(container);
}

function handleSearchableSelectInput(input) {
    const container = input?.closest("[data-config-searchable-select]");
    if (!container) {
        return;
    }
    const selectedOption = getSelectedSearchableSelectOption(container);
    if (selectedOption) {
        const query = normalizeChoiceSearchText(input.value);
        const selectedLabel = normalizeChoiceSearchText(getSearchableSelectOptionLabel(selectedOption));
        const selectedRawValue = normalizeChoiceSearchText(selectedOption.dataset.optionRawValue || "");
        if (query && query !== selectedLabel && query !== selectedRawValue) {
            clearSearchableSelectSelection(container);
        }
    }
    applySearchableSelectFilter(input);
}

function selectSearchableSelectOption(optionButton) {
    const container = optionButton?.closest("[data-config-searchable-select]");
    if (!container) {
        return;
    }
    const { input, hiddenInput } = getSearchableSelectElements(container);
    if (hiddenInput) {
        hiddenInput.value = optionButton.dataset.optionValue || "";
    }
    if (input) {
        input.value = getSearchableSelectOptionLabel(optionButton);
        input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    syncSearchableSelectSelection(container);
    closeSearchableSelect(container, false);
    hiddenInput?.dispatchEvent(new Event("change", { bubbles: true }));
}

function syncScopeFieldVisibility(container) {
    if (!container) {
        return;
    }

    const rules = [
        ["_scope_room_mode", "_scope_room_ids"],
        ["_scope_friend_mode", "_scope_friend_labels"],
    ];

    for (const [controllerKey, targetKey] of rules) {
        const controller = container.querySelector(`[data-config-key="${controllerKey}"]`);
        const target = container.querySelector(`[data-config-field="${targetKey}"]`);
        if (!controller || !target) {
            continue;
        }
        const shouldShow = normalizeScopeModeValue(controller.value) === "selected";
        target.hidden = !shouldShow;
        target.style.display = shouldShow ? "" : "none";
        if (shouldShow) {
            initializeSearchableChoiceFilters(target);
        }
    }
}

function renderPlugins() {
    const messagePlugins = sortPluginsForDisplay(state.plugins.filter((plugin) => plugin.message_dependent !== false));
    const featurePlugins = sortPluginsForDisplay(state.plugins.filter((plugin) => plugin.message_dependent === false));
    renderPluginCards(elements.pluginGrid, messagePlugins, "当前没有依赖消息的插件。", "message");
    renderPluginCards(elements.featurePluginGrid, featurePlugins, "当前没有不依赖消息的功能插件。", "feature");
}

function renderPluginLogs() {
    if (!state.pluginLogs) {
        elements.pluginLogMeta.textContent = "尚未加载插件日志。";
        elements.pluginLogList.innerHTML = '<div class="empty-state">还没有插件日志。</div>';
        elements.pluginLogDetail.innerHTML = '<div class="empty-state">请选择左侧日志查看详情。</div>';
        return;
    }

    const options = [{ module: "", name: "全部插件" }, ...(state.pluginLogs.available_plugins || [])];
    const levelOptions = ["", ...(state.pluginLogs.available_levels || [])];
    elements.pluginLogFilter.innerHTML = options.map((item) => `
        <option value="${escapeHtml(item.module || "")}" ${(item.module || "") === (state.selectedPluginLogModule || "") ? "selected" : ""}>${escapeHtml(item.name)}</option>
    `).join("");
    elements.pluginLogLevelFilter.innerHTML = levelOptions.map((item) => `
        <option value="${escapeHtml(item || "")}" ${(item || "") === (state.selectedPluginLogLevel || "") ? "selected" : ""}>${escapeHtml(item || "全部级别")}</option>
    `).join("");
    elements.pluginLogKeywordFilter.value = state.selectedPluginLogKeyword || "";

    const activePluginName = state.selectedPluginLogModule
        ? getPluginDisplayName(state.selectedPluginLogModule, state.selectedPluginLogModule)
        : "全部插件";
    const activeLevel = state.selectedPluginLogLevel || "全部级别";
    const activeKeyword = state.selectedPluginLogKeyword || "";
    elements.pluginLogMeta.textContent = `当前筛选：${activePluginName} / ${activeLevel}${activeKeyword ? ` / 关键词 ${activeKeyword}` : ""}，匹配 ${state.pluginLogs.filtered_total || 0} 条日志，共缓存 ${state.pluginLogs.total || 0} 条，最新时间 ${state.pluginLogs.updated_at || "未知"}`;

    if (!state.pluginLogs.logs?.length) {
        elements.pluginLogList.innerHTML = '<div class="empty-state">当前筛选条件下没有插件日志。</div>';
        elements.pluginLogDetail.innerHTML = '<div class="empty-state">当前筛选条件下没有可展示的日志详情。</div>';
        return;
    }

    if (
        !state.selectedPluginLogId
        || !state.pluginLogs.logs.some((item) => item.internal_id === state.selectedPluginLogId)
    ) {
        state.selectedPluginLogId = state.pluginLogs.logs[0].internal_id;
    }

    elements.pluginLogList.innerHTML = state.pluginLogs.logs.map((item) => {
        const scope = normalizeInlineText(item.scope || "");
        const preview = truncateText(normalizeInlineText(item.message || "无日志内容"), 92);
        return `
            <button class="plugin-log-item ${item.internal_id === state.selectedPluginLogId ? "is-active" : ""}" data-plugin-log-id="${item.internal_id}" type="button">
                <div class="plugin-log-item-head">
                    <div class="plugin-log-primary">
                        <h4 class="plugin-log-title">${escapeHtml(getPluginDisplayName(item.module, item.plugin || item.module || "未知插件"))}</h4>
                        <div class="detail-meta plugin-log-subline">${escapeHtml(item.recorded_at || "未知时间")}${scope ? ` · ${escapeHtml(scope)}` : ""}${item.module ? ` · ${escapeHtml(item.module)}` : ""}</div>
                    </div>
                    <div class="badge-row">
                        <span class="badge ${getLogTone(item.level)}">${escapeHtml(item.level || "INFO")}</span>
                    </div>
                </div>
                <p class="plugin-log-preview">${escapeHtml(preview)}</p>
            </button>
        `;
    }).join("");

    const selected = getPluginLogById(state.selectedPluginLogId);
    if (!selected) {
        elements.pluginLogDetail.innerHTML = '<div class="empty-state">请选择左侧日志查看详情。</div>';
        return;
    }

    const selectedScope = normalizeInlineText(selected.scope || "");
    const selectedData = selected.data;
    const hasSelectedData = hasPluginLogData(selectedData);
    elements.pluginLogDetail.innerHTML = `
        <div class="detail-head">
            <div>
                <h4 class="detail-title">${escapeHtml(getPluginDisplayName(selected.module, selected.plugin || selected.module || "未知插件"))}</h4>
            </div>
            <div class="badge-row">
                <span class="badge ${getLogTone(selected.level)}">${escapeHtml(selected.level || "INFO")}</span>
                ${selectedScope ? `<span class="badge">${escapeHtml(selectedScope)}</span>` : ""}
            </div>
        </div>
        <div class="detail-section">
            <h5 class="detail-section-title">日志信息</h5>
            <div class="detail-meta">记录时间：${escapeHtml(selected.recorded_at || "未知")}</div>
            <div class="detail-meta">插件模块：${escapeHtml(selected.module || "未知")}</div>
            <div class="detail-meta">插件名称：${escapeHtml(selected.plugin || getPluginDisplayName(selected.module))}</div>
            <div class="detail-meta">日志级别：${escapeHtml(selected.level || "INFO")}</div>
            <div class="detail-meta">日志作用域：${escapeHtml(selectedScope || "无")}</div>
        </div>
        <div class="detail-section">
            <h5 class="detail-section-title">日志消息</h5>
            <div class="detail-text">${escapeHtml(selected.message || "无日志内容")}</div>
        </div>
        <div class="detail-section">
            <h5 class="detail-section-title">结构化数据</h5>
            ${hasSelectedData ? `<pre class="code-block plugin-log-data">${escapeHtml(formatJson(selectedData))}</pre>` : '<div class="empty-state">这条日志没有附加结构化数据。</div>'}
        </div>
    `;
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
    } else {
        elements.settingsAlert.className = "settings-alert is-visible good";
        elements.settingsAlert.textContent = "当前 SQLite 配置与运行时配置一致。保存后可热重载的字段会立即生效。";
    }
}

function waitForDuration(ms) {
    return new Promise((resolve) => {
        window.setTimeout(resolve, ms);
    });
}

function getAiAssistantConversations() {
    return Array.isArray(state.aiAssistant?.conversations) ? state.aiAssistant.conversations : [];
}

function getAiAssistantCurrentConversation() {
    return state.aiAssistant?.current_conversation || null;
}

function getAiAssistantCurrentConversationId() {
    return String(state.aiAssistant?.active_conversation_id || getAiAssistantCurrentConversation()?.id || "");
}

function normalizeAiAssistantJobStatus(status) {
    return String(status || "").trim().toLowerCase();
}

function isAiAssistantJobActive(job) {
    return AI_ASSISTANT_ACTIVE_JOB_STATUSES.has(normalizeAiAssistantJobStatus(job?.status));
}

function isAiAssistantJobTerminal(job) {
    return AI_ASSISTANT_TERMINAL_JOB_STATUSES.has(normalizeAiAssistantJobStatus(job?.status));
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

function getAiAssistantProviders() {
    return Array.isArray(state.aiAssistant?.providers) ? state.aiAssistant.providers : [];
}

function getAiAssistantSettings() {
    return state.aiAssistant?.settings || {};
}

function getAiAssistantProvider(providerKey = state.aiAssistantUi.selectedProvider) {
    return getAiAssistantProviders().find((provider) => provider.key === providerKey) || null;
}

function getAiAssistantProviderSettings(providerKey = state.aiAssistantUi.selectedProvider) {
    return getAiAssistantSettings().providers?.[providerKey] || {};
}

function getAiAssistantProviderConfigs(providerKey = state.aiAssistantUi.selectedProvider) {
    const providerSettings = getAiAssistantProviderSettings(providerKey);
    return Array.isArray(providerSettings.configs) ? providerSettings.configs : [];
}

function getAiAssistantProviderConfigMeta(providerKey = state.aiAssistantUi.selectedProvider, configId = state.aiAssistantUi.selectedProviderConfigId) {
    const provider = getAiAssistantProvider(providerKey);
    return Array.isArray(provider?.configs)
        ? (provider.configs.find((config) => config.id === String(configId || "").trim()) || null)
        : null;
}

function getAiAssistantProviderConfig(providerKey = state.aiAssistantUi.selectedProvider, configId = state.aiAssistantUi.selectedProviderConfigId) {
    const configs = getAiAssistantProviderConfigs(providerKey);
    const normalizedConfigId = String(configId || "").trim();
    return configs.find((config) => config.id === normalizedConfigId)
        || configs.find((config) => config.enabled && config.api_key)
        || configs.find((config) => config.api_key)
        || configs[0]
        || null;
}

function encodeAiAssistantModelSelection(configId = "", model = "") {
    return `${encodeURIComponent(String(configId || "").trim())}::${encodeURIComponent(String(model || "").trim())}`;
}

function decodeAiAssistantModelSelection(value) {
    const [rawConfigId = "", rawModel = ""] = String(value || "").split("::");
    return {
        configId: decodeURIComponent(rawConfigId || ""),
        model: decodeURIComponent(rawModel || ""),
    };
}

function normalizeAiAssistantModelOptions(provider) {
    const normalizedOptions = [];
    const seenSelections = new Set();
    const pushOption = (value, label = value, configId = "", configName = "") => {
        const normalizedValue = String(value || "").trim();
        const normalizedLabel = String(label || normalizedValue).trim() || normalizedValue;
        const normalizedConfigId = String(configId || "").trim();
        const selectionValue = encodeAiAssistantModelSelection(normalizedConfigId, normalizedValue);
        if (!normalizedValue || seenSelections.has(selectionValue)) {
            return;
        }
        seenSelections.add(selectionValue);
        normalizedOptions.push({
            label: normalizedLabel,
            value: normalizedValue,
            configId: normalizedConfigId,
            configName: String(configName || "").trim(),
            selectionValue,
        });
    };

    const rawOptions = Array.isArray(provider?.model_options) ? provider.model_options : [];
    for (const option of rawOptions) {
        if (option && typeof option === "object") {
            pushOption(
                option.value ?? option.label,
                option.label ?? option.value,
                option.config_id ?? "",
                option.config_name ?? ""
            );
        } else {
            pushOption(option);
        }
    }

    const providerConfigs = Array.isArray(provider?.configs) ? provider.configs : [];
    for (const providerConfig of providerConfigs) {
        if (!providerConfig?.configured) {
            continue;
        }
        const fallbackModel = String(provider?.default_model || "").trim();
        if (fallbackModel) {
            pushOption(
                fallbackModel,
                `${providerConfig.name || "未命名配置"} / ${fallbackModel}`,
                providerConfig.id || "",
                providerConfig.name || ""
            );
        }
    }

    return normalizedOptions;
}

function getAiAssistantCurrentSelection() {
    const provider = getAiAssistantProvider() || getAiAssistantProviders()[0] || null;
    if (!provider) {
        return {
            provider: null,
            providerSettings: {},
            modelOptions: [],
            selectedConfig: null,
            selectedConfigMeta: null,
            selectedModel: "",
            selectionValue: "",
        };
    }

    const providerSettings = getAiAssistantProviderSettings(provider.key);
    const modelOptions = normalizeAiAssistantModelOptions(provider);
    const preferredConfigId = state.aiAssistantUi.selectedProviderConfigId;
    const preferredModel = state.aiAssistantUi.selectedModel;
    let matchedOption = modelOptions.find((option) => option.configId === preferredConfigId && option.value === preferredModel);
    if (!matchedOption && preferredConfigId) {
        matchedOption = modelOptions.find((option) => option.configId === preferredConfigId);
    }
    if (!matchedOption && preferredModel) {
        matchedOption = modelOptions.find((option) => option.value === preferredModel);
    }

    const preferredConfig = getAiAssistantProviderConfig(provider.key, preferredConfigId);
    if (!matchedOption && preferredConfig) {
        matchedOption = modelOptions.find((option) => option.configId === preferredConfig.id) || null;
    }
    if (!matchedOption) {
        matchedOption = modelOptions[0] || null;
    }

    const selectedConfigId = matchedOption?.configId || preferredConfig?.id || "";
    const selectedConfig = getAiAssistantProviderConfig(provider.key, selectedConfigId);
    const selectedConfigMeta = getAiAssistantProviderConfigMeta(provider.key, selectedConfigId);
    const selectedModel = matchedOption?.value || preferredModel || provider.default_model || "";

    return {
        provider,
        providerSettings,
        modelOptions,
        selectedConfig,
        selectedConfigMeta,
        selectedModel,
        selectionValue: matchedOption?.selectionValue || encodeAiAssistantModelSelection(selectedConfig?.id || "", selectedModel),
    };
}

function setAiAssistantProviderSelection(providerKey, preferredModel = "", preferredConfigId = "") {
    const providers = getAiAssistantProviders();
    if (!providers.length) {
        state.aiAssistantUi.selectedProvider = "";
        state.aiAssistantUi.selectedProviderConfigId = "";
        state.aiAssistantUi.selectedModel = "";
        return;
    }

    const selectedProvider = providers.find((provider) => provider.key === providerKey) || providers[0];
    const modelOptions = normalizeAiAssistantModelOptions(selectedProvider);
    const normalizedPreferredModel = String(preferredModel || "").trim();
    const normalizedPreferredConfigId = String(preferredConfigId || "").trim();
    let matchedOption = modelOptions.find(
        (option) => option.configId === normalizedPreferredConfigId && option.value === normalizedPreferredModel
    );
    if (!matchedOption && normalizedPreferredConfigId) {
        matchedOption = modelOptions.find((option) => option.configId === normalizedPreferredConfigId);
    }
    if (!matchedOption && normalizedPreferredModel) {
        matchedOption = modelOptions.find((option) => option.value === normalizedPreferredModel);
    }

    const fallbackConfig = getAiAssistantProviderConfig(selectedProvider.key, normalizedPreferredConfigId);
    if (!matchedOption && fallbackConfig) {
        matchedOption = modelOptions.find((option) => option.configId === fallbackConfig.id) || null;
    }
    if (!matchedOption) {
        matchedOption = modelOptions[0] || null;
    }

    state.aiAssistantUi.selectedProvider = selectedProvider.key;
    state.aiAssistantUi.selectedProviderConfigId = matchedOption?.configId || fallbackConfig?.id || "";
    state.aiAssistantUi.selectedModel = matchedOption?.value || normalizedPreferredModel || selectedProvider.default_model || "";
}

function syncAiAssistantUiFromPayload(preserveSelection = true) {
    const settings = getAiAssistantSettings();
    const providers = getAiAssistantProviders();
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

function createAiAssistantConfigId(providerKey = "provider") {
    return `${String(providerKey || "provider").trim()}-config-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
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
            <label class="field-group">
                <span class="field-label">工具调用轮数上限</span>
                <input name="max_tool_rounds" type="number" min="1" max="8" step="1" value="${escapeHtml(String(settings.max_tool_rounds ?? 6))}">
            </label>
            <label class="field-group field-span-2">
                <span class="field-label">系统提示词</span>
                <textarea class="config-editor" name="system_prompt">${escapeHtml(settings.system_prompt || "")}</textarea>
            </label>
            <label class="field-group field-span-2">
                <span class="field-label">温度 temperature</span>
                <input name="temperature" type="number" min="0" max="1.5" step="0.1" value="${escapeHtml(String(settings.temperature ?? 0.2))}">
            </label>
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
        `;
        elements.aiAssistantSettingsForm.querySelectorAll("[data-ai-config-row]").forEach((row) => {
            syncAiAssistantConfigRowState(row);
        });
    }

    if (elements.aiAssistantAlert) {
        const selectedLabel = selectedProvider?.label || "未选择厂商";
        if (selectedConfig?.enabled && selectedConfig?.api_key) {
            elements.aiAssistantAlert.className = `settings-alert is-visible ${selectedConfigMeta?.model_fetch_error ? "bad" : "good"}`;
            elements.aiAssistantAlert.textContent = selectedConfigMeta?.model_fetch_error
                ? `${selectedLabel} · ${selectedConfig.name || "未命名配置"} 已启用，但模型列表自动获取失败，当前会回退到 ${selectedModel}。`
                : `${selectedLabel} · ${selectedConfig.name || "未命名配置"} 已配置并启用，当前对话模型为 ${selectedModel}。配置会保存在本地 SQLite。`;
        } else if (selectedConfig?.api_key) {
            elements.aiAssistantAlert.className = "settings-alert is-visible bad";
            elements.aiAssistantAlert.textContent = `${selectedLabel} · ${selectedConfig.name || "未命名配置"} 已填写 API Key，但当前未启用。发送前请先在配置中启用。`;
        } else if (selectedConfig) {
            elements.aiAssistantAlert.className = "settings-alert is-visible bad";
            elements.aiAssistantAlert.textContent = `${selectedLabel} · ${selectedConfig.name || "未命名配置"} 尚未填写 API Key。点击上方配置按钮后保存，才能开始对话。`;
        } else {
            elements.aiAssistantAlert.className = "settings-alert is-visible bad";
            elements.aiAssistantAlert.textContent = `${selectedLabel} 还没有任何配置。点击上方配置按钮新增一行并保存后，才能开始对话。`;
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
                <span class="badge good">${escapeHtml(selectedProvider.label)}</span>
                <span class="badge">${escapeHtml(selectedConfig?.name || "未命名配置")}</span>
                <span class="badge">${escapeHtml(selectedModel || selectedProvider.default_model || "")}</span>
                <span class="badge ${selectedConfig?.api_key ? "good" : "bad"}">${escapeHtml(selectedConfig?.api_key ? "已配置 API Key" : "未配置 API Key")}</span>
                <span class="badge ${selectedConfig?.enabled ? "good" : "warn"}">${escapeHtml(selectedConfig?.enabled ? "已启用" : "未启用")}</span>
            `
            : '<span class="badge bad">未配置 AI 厂商</span>';
    }

    if (elements.aiAssistantConversationMeta) {
        elements.aiAssistantConversationMeta.textContent = selectedProvider
            ? `${currentConversationTitle} · ${selectedProvider.label}${selectedConfig?.name ? ` / ${selectedConfig.name}` : ""} 当前会话模型：${selectedModel || selectedProvider.default_model || "未设置"}。${currentConversationJobActive ? `当前任务：${currentJob.progress_message || "处理中..."}` : (selectedConfigMeta?.model_fetch_error ? "模型列表自动获取失败，已回退到默认模型。" : `当前共可选 ${modelOptions.length} 个模型选项。`)}`
            : "请先配置并启用一个 AI 厂商。";
    }

    if (elements.sendAiAssistantPromptButton) {
        elements.sendAiAssistantPromptButton.disabled = state.aiRequestInFlight || !(selectedConfig?.enabled && selectedConfig?.api_key);
    }

    renderAiAssistantConversationList();
    renderAiConversation();
}

function renderLogs() {
    if (!state.logs) {
        elements.logMeta.textContent = "尚未加载日志。";
        elements.logViewer.innerHTML = "";
        return;
    }

    elements.logTimeRange.value = state.logFilters.timeRange;
    elements.logLevelFilter.value = state.logFilters.level;
    elements.logModuleFilter.value = state.logFilters.moduleQuery;
    elements.logKeywordFilter.value = state.logFilters.keyword;
    elements.logFileSelect.innerHTML = (state.logs.files || []).map((fileName) => `
        <option value="${escapeHtml(fileName)}" ${fileName === state.logs.active_file ? "selected" : ""}>${escapeHtml(fileName)}</option>
    `).join("");
    const filters = state.logs.filters || {};
    const timeRangeLabels = {
        "1h": "最近一小时",
        "6h": "最近6小时",
        "1d": "最近一天",
        all: "全部",
    };
    const filterChips = [];
    if (filters.time_range && filters.time_range !== "all") {
        filterChips.push(`时间 ${timeRangeLabels[filters.time_range] || filters.time_range}`);
    }
    if (filters.level) {
        filterChips.push(`级别 ${filters.level}`);
    }
    if (filters.module_query) {
        filterChips.push(`模块/函数 ${filters.module_query}`);
    }
    if (filters.keyword) {
        filterChips.push(`关键词 ${filters.keyword}`);
    }

    elements.logMeta.innerHTML = `
        <div class="log-meta-row">
            <span class="log-meta-chip">文件 ${escapeHtml(state.logs.active_file || "无")}</span>
            <span class="log-meta-chip">总行数 ${escapeHtml(String(state.logs.total_line_count || 0))}</span>
            <span class="log-meta-chip">命中 ${escapeHtml(String(state.logs.matched_line_count || 0))}</span>
            <span class="log-meta-chip">展示 ${escapeHtml(String(state.logs.line_count || 0))}</span>
            <span class="log-meta-chip">可解析 ${escapeHtml(String(state.logs.parsed_line_count || 0))}</span>
        </div>
        <div class="log-meta-row">
            <span class="log-meta-chip is-muted">更新时间 ${escapeHtml(formatStandardDateTime(state.logs.updated_at) || state.logs.updated_at || "未知")}</span>
            ${filterChips.length ? filterChips.map((item) => `<span class="log-meta-chip is-filter">${escapeHtml(item)}</span>`).join("") : '<span class="log-meta-chip is-muted">未启用筛选</span>'}
        </div>
    `;

    const entries = Array.isArray(state.logs.entries)
        ? state.logs.entries
        : (state.logs.lines || []).map((raw, index) => ({
            line_number: index + 1,
            raw,
            parsed: false,
            timestamp: "",
            level: "RAW",
            module: "",
            function: "",
            source_line: null,
            message: raw,
        }));

    if (!entries.length) {
        elements.logViewer.innerHTML = '<div class="empty-state">当前筛选条件下没有日志输出。</div>';
        return;
    }

    const rawHighlightQueries = [filters.keyword, filters.module_query].filter(Boolean);
    elements.logViewer.innerHTML = entries.map((entry) => {
        const levelText = entry.parsed ? (entry.level || "INFO") : "RAW";
        const sourceText = entry.parsed
            ? `${entry.module || "unknown"}:${entry.function || "unknown"}`
            : "原始日志片段";
        const timeText = entry.timestamp || `文件行 ${entry.line_number}`;
        const lineText = entry.source_line ? `L${entry.source_line}` : `#${entry.line_number}`;
        const messageText = entry.parsed ? (entry.message || entry.raw || "") : (entry.raw || "");
        const showRawLine = Boolean(entry.parsed && rawHighlightQueries.length);
        return `
            <article class="log-entry ${entry.parsed ? "" : "is-raw"}">
                <div class="log-entry-head">
                    <div class="log-entry-main">
                        <span class="log-level-pill ${getLogLevelClass(levelText)}">${escapeHtml(levelText)}</span>
                        <span class="log-entry-source">${highlightText(sourceText, [filters.module_query])}</span>
                    </div>
                    <div class="log-entry-side">
                        <span class="log-entry-time">${escapeHtml(timeText)}</span>
                        <span class="log-entry-line">${escapeHtml(lineText)}</span>
                    </div>
                </div>
                <div class="log-entry-message">${highlightText(messageText, [filters.keyword])}</div>
                ${showRawLine ? `<div class="log-entry-raw">${highlightText(entry.raw || "", rawHighlightQueries)}</div>` : ""}
            </article>
        `;
    }).join("");
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
    try {
        await loadMessages();
        handleMessagePollSuccess();
    } catch (error) {
        handleMessagePollFailure(error);
    }
}

async function loadPlugins() {
    const payload = await api.getPlugins();
    state.plugins = payload.plugins || [];
    renderPlugins();
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
        heartbeat_interval_seconds: Number(form.heartbeat_interval_seconds.value),
    };
}

function readAiAssistantSettingsForm() {
    const form = elements.aiAssistantSettingsForm;
    const providers = getAiAssistantProviders();
    const normalizedProviders = Object.fromEntries(providers.map((provider) => [provider.key, { configs: [] }]));
    const payload = {
        active_provider: state.aiAssistantUi.selectedProvider || state.aiAssistant?.settings?.active_provider || "zhipu",
        system_prompt: form.querySelector('[name="system_prompt"]')?.value.trim() || "",
        temperature: Number(form.querySelector('[name="temperature"]')?.value || 0.2),
        max_tool_rounds: Number(form.querySelector('[name="max_tool_rounds"]')?.value || 6),
        providers: normalizedProviders,
    };

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
    state.logFilters = {
        timeRange: elements.logTimeRange.value,
        level: elements.logLevelFilter.value,
        moduleQuery: elements.logModuleFilter.value.trim(),
        keyword: elements.logKeywordFilter.value.trim(),
    };
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
    const row = event.target.closest("[data-ai-config-row]");
    if (row) {
        syncAiAssistantConfigRowState(row);
    }
});

elements.aiAssistantSettingsForm.addEventListener("change", (event) => {
    if (!(event.target instanceof Element)) {
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

    const { provider: selectedProvider, selectedConfig, selectedModel } = getAiAssistantCurrentSelection();
    if (!selectedProvider || !selectedConfig?.api_key) {
        setStatus("当前选择的 AI 配置尚未填写 API Key，请先点击配置按钮完成设置", "bad");
        return;
    }
    if (!selectedConfig.enabled) {
        setStatus("当前选择的 AI 配置尚未启用，请先在配置中启用后再发送", "bad");
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
            selectedModel || selectedProvider.default_model || ""
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
            setStatus("正在准备执行范围...");
            const plugin = getPluginByModule(moduleName);
            if (plugin) {
                await loadPluginTargetsIfNeeded(plugin);
            }
            await openPluginExecuteModal(moduleName);
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
    const renderPlugin = buildPluginConfigRenderModel(plugin);
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
            const fieldKey = target?.getAttribute?.("data-config-key") || "";
            if (fieldKey === "_scope_room_mode" || fieldKey === "_scope_friend_mode") {
                syncScopeFieldVisibility(formElement);
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
        const renderPlugin = buildPluginConfigRenderModel(plugin);
        if (hasStructuredPluginConfig(renderPlugin)) {
            const validation = validateStructuredPluginConfig(elements.pluginConfigForm, renderPlugin);
            if (!validation.valid) {
                throw new Error(validation.message || "插件配置校验失败");
            }
        }
        const config = hasStructuredPluginConfig(renderPlugin)
            ? buildStructuredPluginConfigPayload(renderPlugin)
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
        const renderPlugin = buildPluginExecuteRenderModel(plugin);
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
        const result = await api.saveSettings(readSettingsForm());
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
        await loadOverview();
        await Promise.all([loadMessages(), loadUsers(), loadPlugins(), loadPluginLogs(), loadSettings(), loadAiAssistant(), loadLogs()]);
        setStatus("控制台已就绪", "good");
    } catch (error) {
        setStatus(`初始化失败：${error.message}`, "bad");
    }
}

bootstrap();

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
    refreshMessagesByPoll();
}, MESSAGE_POLL_INTERVAL_MS);

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