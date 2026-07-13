/** 控制台共享状态与 DOM 元素查询。 */

export function createAppState() {
    return {
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
}

const ELEMENT_IDS = [
    "activeTabLabel",
    "pageTitle",
    "pageDescription",
    "statusPill",
    "reloadConfigButton",
    "tabRefreshButton",
    "overviewGrid",
    "messageList",
    "messageDetail",
    "refreshMessagesButton",
    "userGrid",
    "refreshUsersButton",
    "featurePluginGrid",
    "refreshFeaturePluginsButton",
    "aiAssistantAlert",
    "newAiAssistantConversationButton",
    "openAiAssistantConversationSwitcherButton",
    "aiAssistantProviderSelect",
    "aiAssistantModelSelect",
    "aiAssistantPromptPluginSelect",
    "toggleAiAssistantConfigButton",
    "toggleAiAssistantToolsButton",
    "aiAssistantConfigModal",
    "closeAiAssistantConfigButton",
    "cancelAiAssistantConfigButton",
    "aiAssistantToolsModal",
    "closeAiAssistantToolsButton",
    "dismissAiAssistantToolsButton",
    "aiAssistantConversationModal",
    "closeAiAssistantConversationModalButton",
    "dismissAiAssistantConversationModalButton",
    "aiAssistantConversationList",
    "aiAssistantSettingsForm",
    "saveAiAssistantSettingsButton",
    "refreshAiAssistantButton",
    "clearAiAssistantConversationButton",
    "aiAssistantToolMeta",
    "aiAssistantToolGrid",
    "aiAssistantConversation",
    "aiAssistantConversationMeta",
    "aiAssistantProviderBadgeRow",
    "aiAssistantPromptForm",
    "aiAssistantPromptInput",
    "sendAiAssistantPromptButton",
    "stopAiAssistantChatButton",
    "pluginGrid",
    "refreshPluginsButton",
    "pluginLogFilter",
    "pluginLogLevelFilter",
    "pluginLogKeywordFilter",
    "refreshPluginLogsButton",
    "pluginLogMeta",
    "pluginLogList",
    "pluginLogDetail",
    "pluginConfigModal",
    "pluginConfigModalTitle",
    "pluginConfigMeta",
    "pluginConfigForm",
    "pluginConfigEditor",
    "closePluginConfigButton",
    "cancelPluginConfigButton",
    "savePluginConfigButton",
    "pluginExecuteModal",
    "pluginExecuteModalTitle",
    "pluginExecuteMeta",
    "pluginExecuteForm",
    "closePluginExecuteButton",
    "cancelPluginExecuteButton",
    "executePluginButton",
    "settingsForm",
    "settingsAlert",
    "refreshSettingsButton",
    "logFileSelect",
    "logTimeRange",
    "logLevelFilter",
    "logModuleFilter",
    "logKeywordFilter",
    "refreshLogsButton",
    "logMeta",
    "logViewer",
];

export function queryAppElements() {
    const elements = {
        panelGroup: document.getElementById("panelGroup"),
        modalRoot: document.getElementById("modalRoot"),
        navTabs: [...document.querySelectorAll(".nav-tab")],
        panels: [...document.querySelectorAll(".tab-panel")],
    };
    for (const id of ELEMENT_IDS) {
        elements[id] = document.getElementById(id);
    }
    return elements;
}

/** 面板懒加载后原地刷新元素引用，保持 actions.elements 同一对象。 */
export function refreshAppElements(elements) {
    if (!elements || typeof elements !== "object") {
        return elements;
    }
    elements.panelGroup = document.getElementById("panelGroup");
    elements.modalRoot = document.getElementById("modalRoot");
    elements.navTabs = [...document.querySelectorAll(".nav-tab")];
    elements.panels = [...document.querySelectorAll(".tab-panel")];
    for (const id of ELEMENT_IDS) {
        elements[id] = document.getElementById(id);
    }
    return elements;
}
