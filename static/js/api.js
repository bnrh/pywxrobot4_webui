const API_TOKEN_STORAGE_KEY = "wxrobot_webui_api_token";
export const SECRET_SETTINGS_PLACEHOLDER = "******";

export function getStoredApiToken() {
    return String(window.sessionStorage.getItem(API_TOKEN_STORAGE_KEY) || "").trim();
}

export function buildEventStreamUrl() {
    const url = new URL("/api/events/stream", window.location.origin);
    const token = getStoredApiToken();
    if (token) {
        url.searchParams.set("access_token", token);
    }
    return `${url.pathname}${url.search}`;
}

export function setStoredApiToken(token) {
    const normalized = String(token || "").trim();
    if (!normalized) {
        window.sessionStorage.removeItem(API_TOKEN_STORAGE_KEY);
        return;
    }
    window.sessionStorage.setItem(API_TOKEN_STORAGE_KEY, normalized);
}

function buildAuthHeaders(extraHeaders = {}) {
    const headers = { ...extraHeaders };
    const token = getStoredApiToken();
    if (token) {
        headers.Authorization = `Bearer ${token}`;
    }
    return headers;
}

async function extractErrorDetail(response) {
    const fallbackDetail = response.statusText || `HTTP ${response.status}`;
    let detail = fallbackDetail;
    try {
        const rawText = await response.text();
        const trimmedText = rawText.trim();
        const contentType = (response.headers.get("Content-Type") || "").toLowerCase();
        if (!trimmedText) {
            return fallbackDetail;
        }

        if (contentType.includes("text/html") || trimmedText.startsWith("<!DOCTYPE") || trimmedText.startsWith("<html")) {
            return fallbackDetail;
        }

        try {
            const payload = JSON.parse(trimmedText);
            detail = payload.detail || JSON.stringify(payload);
        } catch {
            detail = trimmedText;
        }
    } catch {
        detail = fallbackDetail;
    }
    return detail || fallbackDetail;
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, {
        headers: buildAuthHeaders({
            "Content-Type": "application/json",
            ...(options.headers || {}),
        }),
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
        headers: buildAuthHeaders(options.headers || {}),
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
    getRoomMembers(roomid, wxpid = "") {
        const params = new URLSearchParams();
        if (wxpid !== "" && wxpid !== null && wxpid !== undefined) {
            params.set("wxpid", String(wxpid));
        }
        const query = params.toString();
        return requestJson(`/api/rooms/${encodeURIComponent(roomid)}/members${query ? `?${query}` : ""}`);
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
    createAiAssistantChatJob(conversationId, prompt, provider = "", providerConfigId = "", model = "", promptPluginId = "") {
        return requestJson("/api/ai-assistant/chat-jobs", {
            method: "POST",
            body: JSON.stringify({
                conversation_id: conversationId,
                prompt,
                provider: provider || null,
                provider_config_id: providerConfigId || null,
                model: model || null,
                prompt_plugin_id: promptPluginId || null,
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
    chatWithAiAssistant(messages = [], provider = "", providerConfigId = "", model = "", promptPluginId = "") {
        return requestJson("/api/ai-assistant/chat", {
            method: "POST",
            body: JSON.stringify({
                provider: provider || null,
                provider_config_id: providerConfigId || null,
                model: model || null,
                prompt_plugin_id: promptPluginId || null,
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
    getPluginModelOptions(moduleName, config = {}) {
        return requestJson(`/api/plugins/${encodeURIComponent(moduleName)}/model-options`, {
            method: "POST",
            body: JSON.stringify({ config }),
        });
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
    stopPluginExecution(moduleName) {
        return requestJson(`/api/plugins/${encodeURIComponent(moduleName)}/stop`, {
            method: "POST",
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
    getMessageTypes() {
        return requestJson("/api/message-types");
    },
};