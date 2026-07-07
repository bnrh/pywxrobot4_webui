/** AI 助手数据读取、模型选项与任务状态纯函数。 */

import {
    AI_ASSISTANT_ACTIVE_JOB_STATUSES,
    AI_ASSISTANT_TERMINAL_JOB_STATUSES,
} from "./polling-config.js";

export function normalizeAiAssistantJobStatus(status) {
    return String(status || "").trim().toLowerCase();
}

export function isAiAssistantJobActive(job) {
    return AI_ASSISTANT_ACTIVE_JOB_STATUSES.has(normalizeAiAssistantJobStatus(job?.status));
}

export function isAiAssistantJobTerminal(job) {
    return AI_ASSISTANT_TERMINAL_JOB_STATUSES.has(normalizeAiAssistantJobStatus(job?.status));
}

export function listAiAssistantConversations(aiAssistant) {
    return Array.isArray(aiAssistant?.conversations) ? aiAssistant.conversations : [];
}

export function getAiAssistantCurrentConversation(aiAssistant) {
    return aiAssistant?.current_conversation || null;
}

export function getAiAssistantCurrentConversationId(aiAssistant) {
    const currentConversation = getAiAssistantCurrentConversation(aiAssistant);
    return String(aiAssistant?.active_conversation_id || currentConversation?.id || "");
}

export function listAiAssistantProviders(aiAssistant) {
    return Array.isArray(aiAssistant?.providers) ? aiAssistant.providers : [];
}

export function getAiAssistantSettings(aiAssistant) {
    return aiAssistant?.settings || {};
}

export function listAiAssistantPromptPlugins(settings) {
    return Array.isArray(settings.prompt_plugins) ? settings.prompt_plugins : [];
}

export function resolveAiAssistantPromptPlugin(settings, promptPlugins, promptPluginId = "") {
    const normalizedPromptPluginId = String(promptPluginId || "").trim();
    const activePromptPluginId = String(settings.active_prompt_plugin_id || "").trim();
    return promptPlugins.find((plugin) => plugin.id === normalizedPromptPluginId)
        || promptPlugins.find((plugin) => plugin.id === activePromptPluginId)
        || promptPlugins[0]
        || null;
}

export function findAiAssistantProvider(providers, providerKey) {
    return providers.find((provider) => provider.key === providerKey) || null;
}

export function getAiAssistantProviderSettings(settings, providerKey) {
    return settings.providers?.[providerKey] || {};
}

export function listAiAssistantProviderConfigs(settings, providerKey) {
    const providerSettings = getAiAssistantProviderSettings(settings, providerKey);
    return Array.isArray(providerSettings.configs) ? providerSettings.configs : [];
}

export function findAiAssistantProviderConfigMeta(provider, configId) {
    return Array.isArray(provider?.configs)
        ? (provider.configs.find((config) => config.id === String(configId || "").trim()) || null)
        : null;
}

export function resolveAiAssistantProviderConfig(providerSettings, provider, configId) {
    const configs = Array.isArray(providerSettings.configs) ? providerSettings.configs : [];
    const normalizedConfigId = String(configId || "").trim();
    return configs.find((config) => config.id === normalizedConfigId)
        || configs.find((config) => config.enabled && config.api_key)
        || configs.find((config) => config.api_key)
        || configs[0]
        || null;
}

export function encodeAiAssistantModelSelection(configId = "", model = "") {
    return `${encodeURIComponent(String(configId || "").trim())}::${encodeURIComponent(String(model || "").trim())}`;
}

export function decodeAiAssistantModelSelection(value) {
    const [rawConfigId = "", rawModel = ""] = String(value || "").split("::");
    return {
        configId: decodeURIComponent(rawConfigId || ""),
        model: decodeURIComponent(rawModel || ""),
    };
}

export function normalizeAiAssistantModelOptions(provider) {
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

export function resolveAiAssistantCurrentSelection(aiAssistant, aiAssistantUi) {
    const settings = getAiAssistantSettings(aiAssistant);
    const promptPlugins = listAiAssistantPromptPlugins(settings);
    const selectedPromptPlugin = resolveAiAssistantPromptPlugin(
        settings,
        promptPlugins,
        aiAssistantUi.selectedPromptPluginId
    );
    const providers = listAiAssistantProviders(aiAssistant);
    const provider = findAiAssistantProvider(providers, aiAssistantUi.selectedProvider) || providers[0] || null;
    if (!provider) {
        return {
            provider: null,
            providerSettings: {},
            modelOptions: [],
            selectedConfig: null,
            selectedConfigMeta: null,
            selectedModel: "",
            selectionValue: "",
            selectedPromptPlugin,
        };
    }

    const providerSettings = getAiAssistantProviderSettings(settings, provider.key);
    const modelOptions = normalizeAiAssistantModelOptions(provider);
    const preferredConfigId = aiAssistantUi.selectedProviderConfigId;
    const preferredModel = aiAssistantUi.selectedModel;
    let matchedOption = modelOptions.find((option) => option.configId === preferredConfigId && option.value === preferredModel);
    if (!matchedOption && preferredConfigId) {
        matchedOption = modelOptions.find((option) => option.configId === preferredConfigId);
    }
    if (!matchedOption && preferredModel) {
        matchedOption = modelOptions.find((option) => option.value === preferredModel);
    }

    const preferredConfig = resolveAiAssistantProviderConfig(providerSettings, provider, preferredConfigId);
    if (!matchedOption && preferredConfig) {
        matchedOption = modelOptions.find((option) => option.configId === preferredConfig.id) || null;
    }
    if (!matchedOption) {
        matchedOption = modelOptions[0] || null;
    }

    const selectedConfigId = matchedOption?.configId || preferredConfig?.id || "";
    const selectedConfig = resolveAiAssistantProviderConfig(providerSettings, provider, selectedConfigId);
    const selectedConfigMeta = findAiAssistantProviderConfigMeta(provider, selectedConfigId);
    const selectedModel = matchedOption?.value || preferredModel || provider.default_model || "";

    return {
        provider,
        providerSettings,
        modelOptions,
        selectedConfig,
        selectedConfigMeta,
        selectedModel,
        selectionValue: matchedOption?.selectionValue || encodeAiAssistantModelSelection(selectedConfig?.id || "", selectedModel),
        selectedPromptPlugin,
    };
}

export function createAiAssistantConfigId(providerKey = "provider") {
    return `${String(providerKey || "provider").trim()}-config-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function createAiAssistantPromptPluginId() {
    return `prompt-plugin-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function resolveAiAssistantProviderSelection(settings, providers, providerKey, preferredModel = "", preferredConfigId = "") {
    if (!providers.length) {
        return {
            selectedProvider: "",
            selectedProviderConfigId: "",
            selectedModel: "",
        };
    }

    const selectedProvider = findAiAssistantProvider(providers, providerKey) || providers[0];
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

    const fallbackConfig = resolveAiAssistantProviderConfig(
        getAiAssistantProviderSettings(settings, selectedProvider.key),
        selectedProvider,
        normalizedPreferredConfigId
    );
    if (!matchedOption && fallbackConfig) {
        matchedOption = modelOptions.find((option) => option.configId === fallbackConfig.id) || null;
    }
    if (!matchedOption) {
        matchedOption = modelOptions[0] || null;
    }

    return {
        selectedProvider: selectedProvider.key,
        selectedProviderConfigId: matchedOption?.configId || fallbackConfig?.id || "",
        selectedModel: matchedOption?.value || normalizedPreferredModel || selectedProvider.default_model || "",
    };
}
