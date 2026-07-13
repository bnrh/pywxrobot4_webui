/** 智能插件事件绑定。 */

export function registerAiAssistantEvents(actions) {
    const { elements } = actions;
    const state = () => actions.getState();

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

elements.closeAiAssistantConfigButton?.addEventListener("click", actions.closeAiAssistantConfigModal);
elements.cancelAiAssistantConfigButton?.addEventListener("click", actions.closeAiAssistantConfigModal);
elements.closeAiAssistantToolsButton?.addEventListener("click", actions.closeAiAssistantToolsModal);
elements.dismissAiAssistantToolsButton?.addEventListener("click", actions.closeAiAssistantToolsModal);
elements.closeAiAssistantConversationModalButton?.addEventListener("click", actions.closeAiAssistantConversationModal);
elements.dismissAiAssistantConversationModalButton?.addEventListener("click", actions.closeAiAssistantConversationModal);

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
}
