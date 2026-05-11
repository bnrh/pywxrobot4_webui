async function extractErrorDetail(response) {
    let detail = response.statusText;
    try {
        const payload = await response.json();
        detail = payload.detail || JSON.stringify(payload);
    } catch {
        detail = await response.text();
    }
    return detail || `HTTP ${response.status}`;
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, {
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
        ...options,
    });

    if (!response.ok) {
        throw new Error(await extractErrorDetail(response));
    }

    return response.json();
}

async function requestForm(url, formData, options = {}) {
    const response = await fetch(url, {
        ...options,
        body: formData,
    });

    if (!response.ok) {
        throw new Error(await extractErrorDetail(response));
    }

    return response.json();
}

export const api = {
    getOverview() {
        return requestJson("/api/overview");
    },
    getMessages(limit = 40) {
        return requestJson(`/api/messages?limit=${limit}`);
    },
    getUsers() {
        return requestJson("/api/users");
    },
    getAiAssistant() {
        return requestJson("/api/ai-assistant");
    },
    createAiAssistantConversation() {
        return requestJson("/api/ai-assistant/conversations", {
            method: "POST",
        });
    },
    activateAiAssistantConversation(conversationId) {
        return requestJson(`/api/ai-assistant/conversations/${encodeURIComponent(conversationId)}/activate`, {
            method: "POST",
        });
    },
    clearAiAssistantConversation(conversationId) {
        return requestJson(`/api/ai-assistant/conversations/${encodeURIComponent(conversationId)}/clear`, {
            method: "POST",
        });
    },
    saveAiAssistantSettings(settings) {
        return requestJson("/api/ai-assistant/settings", {
            method: "POST",
            body: JSON.stringify({ settings }),
        });
    },
    createAiAssistantChatJob(conversationId, prompt, provider = "", providerConfigId = "", model = "") {
        return requestJson("/api/ai-assistant/chat-jobs", {
            method: "POST",
            body: JSON.stringify({
                conversation_id: conversationId,
                prompt,
                provider: provider || null,
                provider_config_id: providerConfigId || null,
                model: model || null,
            }),
        });
    },
    getAiAssistantChatJob(jobId) {
        return requestJson(`/api/ai-assistant/chat-jobs/${encodeURIComponent(jobId)}`);
    },
    stopAiAssistantChatJob(jobId) {
        return requestJson(`/api/ai-assistant/chat-jobs/${encodeURIComponent(jobId)}/stop`, {
            method: "POST",
        });
    },
    chatWithAiAssistant(messages = [], provider = "", providerConfigId = "", model = "") {
        return requestJson("/api/ai-assistant/chat", {
            method: "POST",
            body: JSON.stringify({
                provider: provider || null,
                provider_config_id: providerConfigId || null,
                model: model || null,
                messages,
            }),
        });
    },
    getPluginTargets() {
        return requestJson("/api/plugin-targets");
    },
    getPlugins() {
        return requestJson("/api/plugins");
    },
    reloadPlugins() {
        return requestJson("/api/plugins/reload", { method: "POST" });
    },
    togglePlugin(moduleName, enabled) {
        return requestJson(`/api/plugins/${encodeURIComponent(moduleName)}/toggle`, {
            method: "POST",
            body: JSON.stringify({ enabled }),
        });
    },
    savePluginConfig(moduleName, config) {
        return requestJson(`/api/plugins/${encodeURIComponent(moduleName)}/config`, {
            method: "POST",
            body: JSON.stringify({ config }),
        });
    },
    uploadPluginAsset(moduleName, fieldKey, file, uploadDir = "uploads") {
        const formData = new FormData();
        formData.append("module_name", moduleName);
        formData.append("field_key", fieldKey || "");
        formData.append("upload_dir", uploadDir || "uploads");
        formData.append("file", file);
        return requestForm("/api/plugin-assets/upload", formData, { method: "POST" });
    },
    executePlugin(moduleName, config = {}) {
        return requestJson(`/api/plugins/${encodeURIComponent(moduleName)}/execute`, {
            method: "POST",
            body: JSON.stringify({ config }),
        });
    },
    getSettings() {
        return requestJson("/api/settings");
    },
    saveSettings(payload) {
        return requestJson("/api/settings", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    getLogs(fileName = "", limit = 200, filters = {}) {
        const params = new URLSearchParams();
        params.set("limit", String(limit));
        if (fileName) {
            params.set("file_name", fileName);
        }
        if (filters.timeRange) {
            params.set("time_range", filters.timeRange);
        }
        if (filters.level) {
            params.set("level", filters.level);
        }
        if (filters.moduleQuery) {
            params.set("module_query", filters.moduleQuery);
        }
        if (filters.keyword) {
            params.set("keyword", filters.keyword);
        }
        return requestJson(`/api/logs?${params.toString()}`);
    },
    getPluginLogs(moduleName = "", limit = 200, level = "", keyword = "") {
        const params = new URLSearchParams();
        params.set("limit", String(limit));
        if (moduleName) {
            params.set("module_name", moduleName);
        }
        if (level) {
            params.set("level", level);
        }
        if (keyword) {
            params.set("keyword", keyword);
        }
        return requestJson(`/api/plugin-logs?${params.toString()}`);
    },
};