/** 控制台 DOM 事件绑定。 */

import { closeSearchableSelect } from "./config-search.js";
import { SECRET_SETTINGS_PLACEHOLDER } from "./api.js";
import { formatJson } from "./dom-utils.js";
import { hasStructuredPluginConfig, readStructuredPluginConfig, validateStructuredPluginConfig, handleStructuredConfigAction } from "./plugin-config-form.js";
import { isDirectExecutePlugin } from "./plugin-helpers.js";
import { normalizeManualPluginExecution } from "./plugin-helpers.js";
import { normalizeInlineText } from "./dom-utils.js";

export function registerAppEvents(actions) {
    const { elements } = actions;
    const state = () => actions.getState();

elements.navTabs.forEach((button) => {
    button.addEventListener("click", () => actions.switchTab(button.dataset.tab));
});

elements.tabRefreshButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新当前视图...");
        await actions.loadOverview();
        await actions.refreshCurrentTab();
        actions.setStatus("当前视图已刷新", "good");
    } catch (error) {
        actions.setStatus(`刷新失败：${error.message}`, "bad");
    }
});

elements.reloadConfigButton.addEventListener("click", async () => {
    try {
        await actions.reloadFromConfig();
    } catch (error) {
        actions.setStatus(`重载失败：${error.message}`, "bad");
    }
});

elements.refreshMessagesButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新消息...");
        await actions.loadMessages();
        actions.setStatus("消息已刷新", "good");
    } catch (error) {
        actions.setStatus(`消息刷新失败：${error.message}`, "bad");
    }
});

elements.refreshUsersButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新用户...");
        await actions.loadUsers();
        actions.setStatus("用户信息已刷新", "good");
    } catch (error) {
        actions.setStatus(`用户刷新失败：${error.message}`, "bad");
    }
});

elements.aiAssistantSettingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!elements.aiAssistantSettingsForm.reportValidity()) {
        actions.setStatus("请先修正智能插件配置中的输入项", "bad");
        return;
    }
    try {
        actions.setStatus("正在保存智能插件设置...");
        actions.applyAiAssistantPayload(await actions.api.saveAiAssistantSettings(actions.readAiAssistantSettingsForm()), true);
        actions.renderAiAssistant();
        actions.renderAiAssistantConversationList();
        actions.closeAiAssistantConfigModal();
        actions.setStatus("智能插件设置已保存", "good");
    } catch (error) {
        actions.setStatus(`智能插件设置保存失败：${error.message}`, "bad");
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
        actions.appendAiAssistantPromptPluginRow();
        actions.syncAiAssistantPromptPluginTableState();
        return;
    }

    if (action === "remove-prompt-plugin") {
        actionTarget.closest("[data-ai-prompt-plugin-row]")?.remove();
        actions.syncAiAssistantPromptPluginTableState();
        return;
    }

    if (action === "add-row") {
        actions.appendAiAssistantConfigRow();
        actions.syncAiAssistantConfigTableState();
        return;
    }

    if (action === "remove-row") {
        actionTarget.closest("[data-ai-config-row]")?.remove();
        actions.syncAiAssistantConfigTableState();
    }
});

elements.aiAssistantSettingsForm.addEventListener("input", (event) => {
    if (!(event.target instanceof Element)) {
        return;
    }
    const promptPluginCard = event.target.closest("[data-ai-prompt-plugin-row]");
    if (promptPluginCard) {
        actions.syncAiAssistantPromptPluginCardState(promptPluginCard);
        return;
    }
    const row = event.target.closest("[data-ai-config-row]");
    if (row) {
        actions.syncAiAssistantConfigRowState(row);
    }
});

elements.aiAssistantSettingsForm.addEventListener("change", (event) => {
    if (!(event.target instanceof Element)) {
        return;
    }
    const promptPluginCard = event.target.closest("[data-ai-prompt-plugin-row]");
    if (promptPluginCard) {
        actions.syncAiAssistantPromptPluginCardState(promptPluginCard);
        actions.syncAiAssistantPromptPluginTableState();
        return;
    }
    const row = event.target.closest("[data-ai-config-row]");
    if (row) {
        actions.syncAiAssistantConfigRowState(row);
        actions.syncAiAssistantConfigTableState();
    }
});

elements.refreshAiAssistantButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新智能插件配置...");
        await actions.loadAiAssistant();
        actions.setStatus("智能插件配置已刷新", "good");
    } catch (error) {
        actions.setStatus(`智能插件刷新失败：${error.message}`, "bad");
    }
});

elements.newAiAssistantConversationButton?.addEventListener("click", async () => {
    try {
        actions.setStatus("正在新建对话...");
        await actions.createAiAssistantConversation();
        actions.closeAiAssistantConversationModal();
        actions.setStatus("已创建新对话", "good");
    } catch (error) {
        actions.setStatus(`新建对话失败：${error.message}`, "bad");
    }
});

elements.openAiAssistantConversationSwitcherButton?.addEventListener("click", () => {
    actions.openAiAssistantConversationModal();
});

elements.clearAiAssistantConversationButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在清空当前对话...");
        await actions.clearAiAssistantConversation();
        actions.setStatus("当前对话已清空", "good");
    } catch (error) {
        actions.setStatus(`清空对话失败：${error.message}`, "bad");
    }
});

elements.stopAiAssistantChatButton?.addEventListener("click", async () => {
    try {
        actions.setStatus("正在停止智能插件对话...");
        await actions.stopAiAssistantChatJob();
        if (!state().aiRequestInFlight && actions.normalizeAiAssistantJobStatus(state().aiActiveChatJob?.status) === "stopped") {
            actions.setStatus("智能插件已停止");
        }
    } catch (error) {
        actions.setStatus(`停止智能插件对话失败：${error.message}`, "bad");
    }
});

elements.aiAssistantProviderSelect?.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLSelectElement)) {
        return;
    }
    actions.setAiAssistantProviderSelection(event.target.value);
    actions.renderAiAssistant();
});

elements.aiAssistantModelSelect?.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLSelectElement)) {
        return;
    }
    const selection = actions.decodeAiAssistantModelSelection(event.target.value);
    state().aiAssistantUi.selectedProviderConfigId = selection.configId;
    state().aiAssistantUi.selectedModel = selection.model;
    actions.renderAiAssistant();
});

elements.aiAssistantPromptPluginSelect?.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLSelectElement)) {
        return;
    }
    state().aiAssistantUi.selectedPromptPluginId = event.target.value;
    actions.renderAiAssistant();
});

elements.toggleAiAssistantConfigButton?.addEventListener("click", () => {
    actions.openAiAssistantConfigModal();
});

elements.toggleAiAssistantToolsButton?.addEventListener("click", () => {
    actions.openAiAssistantToolsModal();
});

elements.closeAiAssistantConfigButton?.addEventListener("click", closeAiAssistantConfigModal);
elements.cancelAiAssistantConfigButton?.addEventListener("click", closeAiAssistantConfigModal);
elements.closeAiAssistantToolsButton?.addEventListener("click", closeAiAssistantToolsModal);
elements.dismissAiAssistantToolsButton?.addEventListener("click", closeAiAssistantToolsModal);
elements.closeAiAssistantConversationModalButton?.addEventListener("click", closeAiAssistantConversationModal);
elements.dismissAiAssistantConversationModalButton?.addEventListener("click", closeAiAssistantConversationModal);

elements.aiAssistantConfigModal?.addEventListener("click", (event) => {
    if (event.target === elements.aiAssistantConfigModal) {
        actions.closeAiAssistantConfigModal();
    }
});

elements.aiAssistantToolsModal?.addEventListener("click", (event) => {
    if (event.target === elements.aiAssistantToolsModal) {
        actions.closeAiAssistantToolsModal();
    }
});

elements.aiAssistantConversationModal?.addEventListener("click", (event) => {
    if (event.target === elements.aiAssistantConversationModal) {
        actions.closeAiAssistantConversationModal();
    }
});

elements.aiAssistantConversationList?.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-ai-conversation-id]");
    if (!target) {
        return;
    }
    try {
        actions.setStatus("正在切换对话...");
        await actions.activateAiAssistantConversation(target.dataset.aiConversationId || "");
        actions.closeAiAssistantConversationModal();
        actions.setStatus("历史对话已切换", "good");
    } catch (error) {
        actions.setStatus(`切换对话失败：${error.message}`, "bad");
    }
});

elements.aiAssistantPromptForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state().aiRequestInFlight) {
        return;
    }

    const { provider: selectedProvider, selectedConfig, selectedModel, selectedPromptPlugin } = actions.getAiAssistantCurrentSelection();
    if (!selectedProvider || !selectedConfig?.api_key) {
        actions.setStatus("当前选择的 AI 配置尚未填写 API Key，请先点击配置按钮完成设置", "bad");
        return;
    }
    if (!selectedConfig.enabled) {
        actions.setStatus("当前选择的 AI 配置尚未启用，请先在配置中启用后再发送", "bad");
        return;
    }
    if (!selectedPromptPlugin?.id) {
        actions.setStatus("当前还没有可用的提示词插件，请先点击配置按钮完成设置", "bad");
        return;
    }

    const prompt = elements.aiAssistantPromptInput.value.trim();
    if (!prompt) {
        actions.setStatus("请先输入要交给智能插件处理的问题", "bad");
        return;
    }

    elements.aiAssistantPromptInput.value = "";
    state().aiRequestInFlight = true;
    actions.renderAiAssistant();

    try {
        let conversationId = actions.getAiAssistantCurrentConversationId();
        if (!conversationId) {
            await actions.createAiAssistantConversation();
            conversationId = actions.getAiAssistantCurrentConversationId();
        }
        actions.setStatus("智能插件正在调用模型与工具...");
        const payload = await actions.api.createAiAssistantChatJob(
            conversationId,
            prompt,
            selectedProvider.key || "",
            selectedConfig.id || "",
            selectedModel || selectedProvider.default_model || "",
            selectedPromptPlugin.id || ""
        );
        actions.applyAiAssistantPayload(payload, true);
        actions.renderAiAssistant();
        if (!payload.job?.id) {
            throw new Error("智能插件任务创建失败，未返回任务 ID");
        }
        await actions.pollAiAssistantChatJob(payload.job.id);
    } catch (error) {
        state().aiRequestInFlight = false;
        state().aiActiveChatJobId = "";
        state().aiActiveChatJob = null;
        actions.setStatus(`智能插件执行失败：${error.message}`, "bad");
    } finally {
        actions.renderAiAssistant();
    }
});

elements.messageList.addEventListener("click", (event) => {
    const target = event.target.closest("[data-message-id]");
    if (!target) {
        return;
    }
    state().selectedMessageId = Number(target.dataset.messageId);
    state().messageAutoFollow = state().selectedMessageId === state().messages[0]?.internal_id;
    actions.renderMessages();
});

elements.messageDetail.addEventListener("click", async (event) => {
    const button = event.target.closest('button[data-action="copy-message-payload"]');
    if (!button) {
        return;
    }

    const selected = state().messages.find((message) => message.internal_id === state().selectedMessageId);
    if (!selected) {
        actions.setStatus("未找到当前消息原始负载", "bad");
        return;
    }

    try {
        await actions.copyTextToClipboard(actions.formatJson(selected.payload));
        actions.setStatus("原始负载已复制", "good");
    } catch (error) {
        actions.setStatus(`复制原始负载失败：${error.message}`, "bad");
    }
});

elements.refreshPluginsButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新消息插件...");
        await actions.loadPlugins();
        actions.setStatus("消息插件已刷新", "good");
    } catch (error) {
        actions.setStatus(`消息插件刷新失败：${error.message}`, "bad");
    }
});

elements.refreshFeaturePluginsButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新功能插件...");
        await actions.loadPlugins();
        actions.setStatus("功能插件已刷新", "good");
    } catch (error) {
        actions.setStatus(`功能插件刷新失败：${error.message}`, "bad");
    }
});

async function handlePluginGridAction(event) {
    const button = event.target.closest("button[data-action]");
    if (!button) {
        return;
    }

    const moduleName = button.dataset.plugin;
    if (button.dataset.action === "open-plugin-config") {
        await actions.openPluginConfigModal(moduleName);
        return;
    }

    button.disabled = true;
    try {
        if (button.dataset.action === "toggle-plugin") {
            actions.setStatus("正在切换插件状态...");
            const result = await actions.api.togglePlugin(moduleName, button.dataset.enabled === "1");
            actions.applyPluginMutationResult(result);
            const suffix = result.restart_required ? `，需要重启字段：${result.restart_required_fields.join(", ")}` : "";
            actions.setStatus(`插件状态已更新${suffix}`, result.restart_required ? "bad" : "good");
        } else if (button.dataset.action === "execute-plugin") {
            const plugin = actions.getPluginByModule(moduleName);
            if (plugin && isDirectExecutePlugin(plugin)) {
                actions.setStatus("正在执行功能插件...");
                await actions.executePluginWithConfig(moduleName, {});
            } else {
                actions.setStatus("正在准备执行范围...");
                if (plugin) {
                    await actions.loadPluginTargetsIfNeeded(plugin);
                }
                await actions.openPluginExecuteModal(moduleName);
            }
        } else if (button.dataset.action === "stop-plugin-execution") {
            actions.setStatus("正在停止功能插件...");
            const result = await actions.api.stopPluginExecution(moduleName);
            actions.applyPluginMutationResult(result);
            const detail = normalizeInlineText(result?.execution?.detail || "");
            actions.setStatus(detail || "正在停止插件...");
        }
    } catch (error) {
        actions.setStatus(`插件操作失败：${error.message}`, "bad");
    } finally {
        button.disabled = false;
    }
}

[elements.pluginGrid, elements.featurePluginGrid].forEach((grid) => {
    grid.addEventListener("click", (event) => {
        handlePluginGridAction(event).catch((error) => {
            actions.setStatus(`插件操作失败：${error.message}`, "bad");
        });
    });
});

elements.pluginLogList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-plugin-log-id]");
    if (!button) {
        return;
    }
    state().selectedPluginLogId = Number(button.dataset.pluginLogId);
    actions.renderPluginLogs();
});

elements.pluginLogFilter.addEventListener("change", async () => {
    try {
        state().selectedPluginLogModule = elements.pluginLogFilter.value;
        state().selectedPluginLogId = null;
        actions.setStatus("正在切换插件日志筛选...");
        await actions.loadPluginLogs(state().selectedPluginLogModule, state().selectedPluginLogLevel, state().selectedPluginLogKeyword);
        actions.setStatus("插件日志已更新", "good");
    } catch (error) {
        actions.setStatus(`插件日志筛选失败：${error.message}`, "bad");
    }
});

elements.pluginLogLevelFilter.addEventListener("change", async () => {
    try {
        state().selectedPluginLogLevel = elements.pluginLogLevelFilter.value;
        state().selectedPluginLogId = null;
        actions.setStatus("正在切换插件日志级别筛选...");
        await actions.loadPluginLogs(state().selectedPluginLogModule, state().selectedPluginLogLevel, state().selectedPluginLogKeyword);
        actions.setStatus("插件日志已更新", "good");
    } catch (error) {
        actions.setStatus(`插件日志级别筛选失败：${error.message}`, "bad");
    }
});

elements.pluginLogKeywordFilter.addEventListener("input", () => {
    state().selectedPluginLogKeyword = elements.pluginLogKeywordFilter.value.trim();
    state().selectedPluginLogId = null;
    actions.schedulePluginLogKeywordRefresh();
});

elements.pluginLogKeywordFilter.addEventListener("search", () => {
    state().selectedPluginLogKeyword = elements.pluginLogKeywordFilter.value.trim();
    state().selectedPluginLogId = null;
    actions.schedulePluginLogKeywordRefresh();
});

elements.refreshPluginLogsButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新插件日志...");
        await actions.loadPluginLogs(state().selectedPluginLogModule, state().selectedPluginLogLevel, state().selectedPluginLogKeyword);
        actions.setStatus("插件日志已刷新", "good");
    } catch (error) {
        actions.setStatus(`插件日志刷新失败：${error.message}`, "bad");
    }
});

elements.closePluginConfigButton.addEventListener("click", closePluginConfigModal);
elements.cancelPluginConfigButton.addEventListener("click", closePluginConfigModal);
elements.closePluginExecuteButton.addEventListener("click", closePluginExecuteModal);
elements.cancelPluginExecuteButton.addEventListener("click", closePluginExecuteModal);

elements.pluginConfigModal.addEventListener("click", (event) => {
    if (event.target === elements.pluginConfigModal) {
        actions.closePluginConfigModal();
    }
});

elements.pluginExecuteModal.addEventListener("click", (event) => {
    if (event.target === elements.pluginExecuteModal) {
        actions.closePluginExecuteModal();
    }
});

elements.pluginConfigForm.addEventListener("click", (event) => {
    if (!state().pluginConfigModule) {
        return;
    }
    const plugin = actions.getPluginByModule(state().pluginConfigModule);
    if (!plugin) {
        return;
    }
    const renderPlugin = actions.buildPluginConfigRenderModelForPlugin(plugin);
    if (handleStructuredConfigAction(elements.pluginConfigForm, renderPlugin, event)) {
        event.preventDefault();
    }
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
        actions.closePluginExecuteModal();
        return;
    }
    if (elements.aiAssistantConversationModal?.classList.contains("is-visible")) {
        actions.closeAiAssistantConversationModal();
        return;
    }
    if (elements.aiAssistantToolsModal?.classList.contains("is-visible")) {
        actions.closeAiAssistantToolsModal();
        return;
    }
    if (elements.aiAssistantConfigModal?.classList.contains("is-visible")) {
        actions.closeAiAssistantConfigModal();
        return;
    }
    if (elements.pluginConfigModal.classList.contains("is-visible")) {
        actions.closePluginConfigModal();
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
    if (!state().pluginConfigModule) {
        return;
    }

    elements.savePluginConfigButton.disabled = true;
    try {
        const plugin = actions.getPluginByModule(state().pluginConfigModule);
        if (!plugin) {
            throw new Error("未找到指定插件");
        }
        const renderPlugin = actions.buildPluginConfigRenderModelForPlugin(plugin);
        if (hasStructuredPluginConfig(renderPlugin)) {
            const validation = validateStructuredPluginConfig(elements.pluginConfigForm, renderPlugin);
            if (!validation.valid) {
                throw new Error(validation.message || "插件配置校验失败");
            }
        }
        const config = hasStructuredPluginConfig(renderPlugin)
            ? actions.buildStructuredPluginConfigPayload(elements.pluginConfigForm, renderPlugin)
            : (() => {
                const configText = elements.pluginConfigEditor.value.trim() || "{}";
                return configText ? JSON.parse(configText) : {};
            })();
        actions.setStatus("正在保存插件配置...");
        const result = await actions.api.savePluginConfig(state().pluginConfigModule, config);
        actions.applyPluginMutationResult(result);
        actions.closePluginConfigModal();
        const suffix = result.restart_required ? `，需要重启字段：${result.restart_required_fields.join(", ")}` : "";
        actions.setStatus(`插件配置已保存${suffix}`, result.restart_required ? "bad" : "good");
    } catch (error) {
        actions.setStatus(`插件配置保存失败：${error.message}`, "bad");
    } finally {
        elements.savePluginConfigButton.disabled = false;
    }
});

elements.executePluginButton.addEventListener("click", async () => {
    if (!state().pluginExecuteModule) {
        return;
    }

    elements.executePluginButton.disabled = true;
    try {
        const plugin = actions.getPluginByModule(state().pluginExecuteModule);
        if (!plugin) {
            throw new Error("未找到指定功能插件");
        }
        const renderPlugin = actions.buildPluginExecuteRenderModelForPlugin(plugin);
        const config = hasStructuredPluginConfig(renderPlugin)
            ? readStructuredPluginConfig(elements.pluginExecuteForm, renderPlugin)
            : {};
        actions.setStatus("正在执行功能插件...");
        await actions.executePluginWithConfig(state().pluginExecuteModule, config);
        actions.closePluginExecuteModal();
    } catch (error) {
        actions.setStatus(`执行插件失败：${error.message}`, "bad");
    } finally {
        elements.executePluginButton.disabled = false;
    }
});

elements.settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
        actions.setStatus("正在保存系统设置...");
        const formPayload = actions.readSettingsForm();
        const result = await actions.api.saveSettings(formPayload);
        if (formPayload.api_token && formPayload.api_token !== SECRET_SETTINGS_PLACEHOLDER) {
            actions.setStoredApiToken(formPayload.api_token);
        }
        actions.setOverviewData(result.overview);
        state().settings = result.settings;
        actions.renderOverview();
        actions.renderSettings();
        const suffix = result.restart_required ? `，需要重启字段：${result.restart_required_fields.join(", ")}` : "";
        actions.setStatus(`系统设置已保存${suffix}`, result.restart_required ? "bad" : "good");
    } catch (error) {
        actions.setStatus(`系统设置保存失败：${error.message}`, "bad");
    }
});

elements.refreshSettingsButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新系统设置...");
        await actions.loadSettings();
        actions.setStatus("系统设置已刷新", "good");
    } catch (error) {
        actions.setStatus(`系统设置刷新失败：${error.message}`, "bad");
    }
});

elements.logFileSelect.addEventListener("change", async () => {
    try {
        state().selectedLogFile = elements.logFileSelect.value;
        actions.setStatus("正在切换日志文件...");
        await actions.loadLogs(state().selectedLogFile);
        actions.setStatus("日志已切换", "good");
    } catch (error) {
        actions.setStatus(`日志读取失败：${error.message}`, "bad");
    }
});

elements.logTimeRange.addEventListener("change", async () => {
    try {
        await actions.applyLogFilters();
    } catch (error) {
        actions.setStatus(`日志筛选失败：${error.message}`, "bad");
    }
});

elements.logLevelFilter.addEventListener("change", async () => {
    try {
        await actions.applyLogFilters();
    } catch (error) {
        actions.setStatus(`日志筛选失败：${error.message}`, "bad");
    }
});

elements.logModuleFilter.addEventListener("input", () => actions.scheduleLogFilterRefresh());
elements.logKeywordFilter.addEventListener("input", () => actions.scheduleLogFilterRefresh());

elements.refreshLogsButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新日志...");
        await actions.loadLogs(state().selectedLogFile);
        actions.setStatus("日志已刷新", "good");
    } catch (error) {
        actions.setStatus(`日志刷新失败：${error.message}`, "bad");
    }
});


}
