/** AI 助手 UI 动作绑定：将 controller 上下文桥接到视图函数。 */

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
} from "./ai-assistant-ui.js";

export function createAiAssistantUiActions(buildUiCtx) {
    const uiCtx = () => buildUiCtx();

    return {
        renderAiAssistantConversationList: () => renderAiAssistantConversationListView(uiCtx()),
        renderAiAssistant: () => renderAiAssistantView(uiCtx()),
        readAiAssistantSettingsForm: () => readAiAssistantSettingsFormView(uiCtx()),
        openAiAssistantConversationModal: () => openAiAssistantConversationModalView(uiCtx()),
        openAiAssistantConfigModal: () => openAiAssistantConfigModalView(uiCtx()),
        openAiAssistantToolsModal: () => openAiAssistantToolsModalView(uiCtx()),
        closeAiAssistantConfigModal: () => closeAiAssistantConfigModalView(uiCtx()),
        closeAiAssistantConversationModal: () => closeAiAssistantConversationModalView(uiCtx()),
        closeAiAssistantToolsModal: () => closeAiAssistantToolsModalView(uiCtx()),
        appendAiAssistantPromptPluginRow: () => appendAiAssistantPromptPluginRowView(uiCtx()),
        syncAiAssistantPromptPluginTableState: () => syncAiAssistantPromptPluginTableStateView(uiCtx()),
        syncAiAssistantPromptPluginCardState: (card) => syncAiAssistantPromptPluginCardStateView(uiCtx(), card),
        appendAiAssistantConfigRow: (providerKey) => appendAiAssistantConfigRowView(uiCtx(), providerKey),
        syncAiAssistantConfigTableState: () => syncAiAssistantConfigTableStateView(uiCtx()),
        syncAiAssistantConfigRowState: (row) => syncAiAssistantConfigRowStateView(uiCtx(), row),
    };
}
