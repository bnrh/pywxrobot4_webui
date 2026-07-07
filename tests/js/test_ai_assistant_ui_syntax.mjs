await import("../../static/js/ai-assistant-ui.js");
const { createAiAssistantUiActions } = await import("../../static/js/ai-assistant-ui-actions.js");

const actions = createAiAssistantUiActions(() => ({
    elements: {},
    getProviders: () => [],
    getSettings: () => ({}),
    getPromptPlugins: () => [],
    getPromptPlugin: () => null,
    getProvider: () => null,
    getConversations: () => [],
    getCurrentConversation: () => null,
    aiAssistantUi: {},
}));

if (typeof actions.renderAiAssistant !== "function") {
    throw new Error("createAiAssistantUiActions should expose renderAiAssistant");
}

console.log("ai-assistant-ui syntax ok");
