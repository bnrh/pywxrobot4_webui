/** AI 助手状态访问、载荷同步与异步任务。 */

import {
    findAiAssistantProvider,
    getAiAssistantCurrentConversation as readAiAssistantCurrentConversation,
    getAiAssistantCurrentConversationId as readAiAssistantCurrentConversationId,
    getAiAssistantSettings as readAiAssistantSettings,
    isAiAssistantJobActive,
    isAiAssistantJobTerminal,
    listAiAssistantConversations,
    listAiAssistantPromptPlugins,
    listAiAssistantProviders,
    normalizeAiAssistantJobStatus,
    resolveAiAssistantCurrentSelection,
    resolveAiAssistantPromptPlugin,
    resolveAiAssistantProviderSelection,
} from "./ai-assistant-data.js";

export function createAiAssistantController(getState, deps) {
    const getConversations = () => listAiAssistantConversations(getState().aiAssistant);
    const getCurrentConversation = () => readAiAssistantCurrentConversation(getState().aiAssistant);
    const getCurrentConversationId = () => readAiAssistantCurrentConversationId(getState().aiAssistant);
    const getProviders = () => listAiAssistantProviders(getState().aiAssistant);
    const getSettings = () => readAiAssistantSettings(getState().aiAssistant);
    const getPromptPlugins = () => listAiAssistantPromptPlugins(getSettings());
    const getPromptPlugin = (promptPluginId = getState().aiAssistantUi.selectedPromptPluginId) => resolveAiAssistantPromptPlugin(
        getSettings(),
        getPromptPlugins(),
        promptPluginId,
    );
    const getProvider = (providerKey = getState().aiAssistantUi.selectedProvider) => findAiAssistantProvider(getProviders(), providerKey);
    const getCurrentSelection = () => resolveAiAssistantCurrentSelection(getState().aiAssistant, getState().aiAssistantUi);

    function setProviderSelection(providerKey, preferredModel = "", preferredConfigId = "") {
        const nextSelection = resolveAiAssistantProviderSelection(
            getSettings(),
            getProviders(),
            providerKey,
            preferredModel,
            preferredConfigId,
        );
        const ui = getState().aiAssistantUi;
        ui.selectedProvider = nextSelection.selectedProvider;
        ui.selectedProviderConfigId = nextSelection.selectedProviderConfigId;
        ui.selectedModel = nextSelection.selectedModel;
    }

    function syncUiFromPayload(preserveSelection = true) {
        const state = getState();
        const settings = getSettings();
        const promptPlugins = getPromptPlugins();
        const providers = getProviders();
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
        setProviderSelection(preferredProvider, preferredModel, preferredConfigId);
    }

    function applyPayload(payload, preserveSelection = true) {
        if (!payload || typeof payload !== "object") {
            return;
        }
        const state = getState();
        state.aiAssistant = {
            ...(state.aiAssistant || {}),
            ...payload,
        };
        const currentConversation = getCurrentConversation();
        state.aiConversation = Array.isArray(currentConversation?.messages) ? currentConversation.messages : [];
        if (payload.job) {
            state.aiActiveChatJob = payload.job;
            state.aiActiveChatJobId = payload.job.id || state.aiActiveChatJobId;
        }
        if (payload.settings || payload.providers) {
            syncUiFromPayload(preserveSelection);
        }
    }

    function buildUiCtx(elements) {
        const state = getState();
        return {
            elements,
            get aiAssistant() {
                return state.aiAssistant;
            },
            get aiAssistantUi() {
                return state.aiAssistantUi;
            },
            get aiRequestInFlight() {
                return state.aiRequestInFlight;
            },
            get aiActiveChatJob() {
                return state.aiActiveChatJob;
            },
            getConversations,
            getCurrentConversation,
            getCurrentConversationId,
            getProviders,
            getSettings,
            getPromptPlugins,
            getPromptPlugin,
            getProvider,
            getCurrentSelection,
            setProviderSelection,
        };
    }

    function refreshViews() {
        deps.renderAiAssistant();
        deps.renderAiAssistantConversationList();
    }

    async function load() {
        applyPayload(await deps.api.getAiAssistant(), true);
        refreshViews();
    }

    async function createConversation() {
        applyPayload(await deps.api.createAiAssistantConversation(), true);
        refreshViews();
    }

    async function activateConversation(conversationId) {
        applyPayload(await deps.api.activateAiAssistantConversation(conversationId), true);
        refreshViews();
    }

    async function clearConversation() {
        const conversationId = getCurrentConversationId();
        if (!conversationId) {
            throw new Error("当前没有可清空的对话");
        }
        applyPayload(await deps.api.clearAiAssistantConversation(conversationId), true);
        refreshViews();
    }

    async function stopChatJob() {
        const state = getState();
        const currentConversation = getCurrentConversation();
        const currentJob = state.aiActiveChatJob || {};
        const jobId = String(currentJob.id || state.aiActiveChatJobId || "").trim();
        if (!jobId || !isAiAssistantJobActive(currentJob)) {
            throw new Error("当前没有可停止的智能插件对话");
        }
        if (currentConversation?.id && currentJob.conversation_id && currentJob.conversation_id !== currentConversation.id) {
            throw new Error("当前对话没有正在运行的智能插件任务");
        }

        const payload = await deps.api.stopAiAssistantChatJob(jobId);
        applyPayload(payload, true);
        if (isAiAssistantJobTerminal(payload.job) && normalizeAiAssistantJobStatus(payload.job?.status) === "stopped") {
            state.aiRequestInFlight = false;
            state.aiActiveChatJobId = "";
            state.aiActiveChatJob = payload.job || null;
        }
        refreshViews();
    }

    async function pollChatJob(jobId) {
        const state = getState();
        state.aiActiveChatJobId = jobId;
        while (state.aiActiveChatJobId === jobId) {
            const payload = await deps.api.getAiAssistantChatJob(jobId);
            applyPayload(payload, true);
            refreshViews();
            const job = payload.job || {};
            const jobStatus = normalizeAiAssistantJobStatus(job.status);
            if (jobStatus === "completed") {
                state.aiRequestInFlight = false;
                state.aiActiveChatJobId = "";
                state.aiActiveChatJob = job;
                const messages = Array.isArray(getCurrentConversation()?.messages) ? getCurrentConversation().messages : [];
                const latestAssistantMessage = [...messages].reverse().find((message) => message.role === "assistant");
                deps.setStatus(`智能插件已完成，本次调用了 ${Number(latestAssistantMessage?.tool_traces?.length || 0)} 个工具`, "good");
                deps.renderAiAssistant();
                return;
            }
            if (jobStatus === "stopped") {
                state.aiRequestInFlight = false;
                state.aiActiveChatJobId = "";
                state.aiActiveChatJob = job;
                deps.setStatus("智能插件已停止");
                deps.renderAiAssistant();
                return;
            }
            if (jobStatus === "failed") {
                state.aiRequestInFlight = false;
                state.aiActiveChatJobId = "";
                state.aiActiveChatJob = job;
                deps.setStatus(`智能插件执行失败：${job.error || "未知错误"}`, "bad");
                deps.renderAiAssistant();
                return;
            }
            await deps.waitForDuration(deps.aiJobPollIntervalMs);
        }
    }

    return {
        applyPayload,
        buildUiCtx,
        getConversations,
        getCurrentConversation,
        getCurrentConversationId,
        getProviders,
        getSettings,
        getPromptPlugins,
        getPromptPlugin,
        getProvider,
        getCurrentSelection,
        setProviderSelection,
        syncUiFromPayload,
        load,
        createConversation,
        activateConversation,
        clearConversation,
        stopChatJob,
        pollChatJob,
    };
}
