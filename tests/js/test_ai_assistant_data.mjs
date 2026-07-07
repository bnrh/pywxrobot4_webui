import {
    encodeAiAssistantModelSelection,
    isAiAssistantJobActive,
    isAiAssistantJobTerminal,
    normalizeAiAssistantJobStatus,
    resolveAiAssistantCurrentSelection,
} from "../../static/js/ai-assistant-data.js";

if (!isAiAssistantJobActive({ status: "running" })) {
    throw new Error("running job should be active");
}
if (!isAiAssistantJobTerminal({ status: "completed" })) {
    throw new Error("completed job should be terminal");
}
if (normalizeAiAssistantJobStatus(" Running ") !== "running") {
    throw new Error("status normalization failed");
}

const selectionValue = encodeAiAssistantModelSelection("cfg-1", "glm-4");
const selection = resolveAiAssistantCurrentSelection(
    {
        providers: [{
            key: "zhipu",
            label: "智谱",
            configs: [{ id: "meta-1", model_options: [{ model: "glm-4", label: "GLM-4" }] }],
        }],
        settings: {
            providers: {
                zhipu: {
                    configs: [{ id: "cfg-1", name: "主配置", enabled: true, api_key: "x" }],
                },
            },
        },
    },
    {
        selectedProvider: "zhipu",
        selectedProviderConfigId: "cfg-1",
        selectedModel: "glm-4",
        selectedPromptPluginId: "prompt-1",
    },
);

if (selection.selectedModel !== "glm-4") {
    throw new Error(`unexpected selected model: ${selection.selectedModel}`);
}
if (selection.selectionValue !== selectionValue) {
    throw new Error("selection value mismatch");
}

console.log("ai-assistant-data ok");
