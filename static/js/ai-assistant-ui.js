/** AI 助手页面渲染、配置表单与 Modal 控制。 */

import { escapeHtml, formatJson } from "./dom-utils.js";
import { formatStandardDateTime } from "./format-utils.js";
import {
    createAiAssistantConfigId,
    createAiAssistantPromptPluginId,
    isAiAssistantJobActive,
    normalizeAiAssistantJobStatus,
} from "./ai-assistant-data.js";

export function renderAiAssistantConversationList(ctx) {
    if (!ctx.elements.aiAssistantConversationList) {
        return;
    }
    const conversations = ctx.getConversations();
    if (!conversations.length) {
        ctx.elements.aiAssistantConversationList.innerHTML = '<div class="empty-state">还没有历史对话。点击“新建对话”后开始提问即可自动保存。</div>';
        return;
    }
    ctx.elements.aiAssistantConversationList.innerHTML = conversations.map((conversation) => `
        <button class="smart-conversation-card ${conversation.is_active ? "is-active" : ""}" type="button" data-ai-conversation-id="${escapeHtml(conversation.id || "")}">
            <div class="smart-conversation-card-head">
                <div>
                    <h6 class="smart-conversation-title">${escapeHtml(conversation.title || "未命名对话")}</h6>
                    <div class="detail-meta">更新时间 ${escapeHtml(formatStandardDateTime(conversation.updated_at) || conversation.updated_at || "未知")}</div>
                </div>
                <div class="badge-row">
                    ${conversation.has_running_message ? '<span class="badge warn">进行中</span>' : ""}
                    ${conversation.is_active ? '<span class="badge good">当前</span>' : ""}
                </div>
            </div>
            <div class="detail-text smart-conversation-preview">${escapeHtml(conversation.last_message_preview || "暂无消息")}</div>
            <div class="detail-meta">共 ${escapeHtml(String(conversation.message_count || 0))} 条消息</div>
        </button>
    `).join("");
}

export function renderAiConversation(ctx) {
    if (!ctx.elements.aiAssistantConversation) {
        return;
    }

    const messages = Array.isArray(ctx.getCurrentConversation()?.messages)
        ? ctx.getCurrentConversation().messages
        : [];
    if (!messages.length) {
        ctx.elements.aiAssistantConversation.innerHTML = '<div class="empty-state">还没有对话。点击“新建对话”开始新的会话，或直接在当前会话中输入问题。</div>';
        return;
    }

    ctx.elements.aiAssistantConversation.innerHTML = messages.map((message) => {
        const role = message.role === "assistant" ? "assistant" : "user";
        const roleLabel = role === "assistant" ? "智能插件" : "用户";
        const toolTraces = Array.isArray(message.tool_traces) ? message.tool_traces : [];
        const reasoningContent = String(message.reasoning_content || "").trim();
        const status = String(message.status || (message.error ? "failed" : "completed")).trim().toLowerCase();
        const statusTone = message.error || status === "failed"
            ? "bad"
            : (status === "running" || status === "stopped")
                ? "warn"
                : (role === "assistant" ? "good" : "");
        const statusLabel = status === "running"
            ? "处理中"
            : status === "stopped"
                ? "已停止"
            : status === "failed"
                ? "失败"
                : (role === "assistant" ? "已完成" : "已发送");
        const showReasoning = Boolean(reasoningContent);
        const messageBody = message.content || ((status === "running" || status === "stopped")
            ? (message.progress_message || (status === "running" ? "正在处理中..." : "本次对话已手动停止。"))
            : "无内容");
        return `
            <article class="smart-chat-message ${role === "assistant" ? "is-assistant" : "is-user"} ${message.error || status === "failed" ? "is-error" : ""}">
                <div class="smart-chat-message-head">
                    <div class="badge-row">
                        <span class="badge ${statusTone}">${escapeHtml(roleLabel)}</span>
                        <span class="badge ${statusTone}">${escapeHtml(statusLabel)}</span>
                        ${message.provider_label ? `<span class="badge">${escapeHtml(message.provider_label)}</span>` : ""}
                        ${message.prompt_plugin_name ? `<span class="badge">${escapeHtml(message.prompt_plugin_name)}</span>` : ""}
                        ${message.model ? `<span class="badge">${escapeHtml(message.model)}</span>` : ""}
                    </div>
                    <div class="detail-meta">${escapeHtml(formatStandardDateTime(message.updated_at) || message.updated_at || "")}</div>
                </div>
                ${message.progress_message ? `<div class="smart-chat-progress">${escapeHtml(message.progress_message)}</div>` : ""}
                ${showReasoning ? `
                    <section class="smart-reasoning-block">
                        <div class="detail-meta">思考过程</div>
                        <pre class="code-block smart-reasoning-content">${escapeHtml(reasoningContent)}</pre>
                    </section>
                ` : ""}
                ${toolTraces.length ? `
                    <div class="smart-tool-trace-list">
                        ${toolTraces.map((trace) => {
                            const traceStatus = String(trace.status || "ok").toLowerCase();
                            const traceTone = traceStatus === "running" ? "warn" : (traceStatus === "ok" ? "good" : "bad");
                            const traceLabel = traceStatus === "running" ? "工具运行中" : (traceStatus === "ok" ? "工具成功" : "工具失败");
                            return `
                                <section class="smart-tool-trace-item ${traceStatus === "running" ? "is-running" : ""}">
                                    <div class="smart-tool-trace-head">
                                        <div class="badge-row">
                                            <span class="badge ${traceTone}">${escapeHtml(traceLabel)}</span>
                                            <span class="badge">${escapeHtml(trace.name || "unknown_tool")}</span>
                                        </div>
                                    </div>
                                    <div class="detail-meta">参数</div>
                                    <pre class="code-block">${escapeHtml(formatJson(trace.arguments || {}))}</pre>
                                    ${trace.error ? `<div class="detail-text">${escapeHtml(trace.error)}</div>` : ""}
                                </section>
                            `;
                        }).join("")}
                    </div>
                ` : ""}
                <div class="detail-text smart-chat-message-body">${escapeHtml(messageBody)}</div>
            </article>
        `;
    }).join("");

    ctx.elements.aiAssistantConversation.scrollTop = ctx.elements.aiAssistantConversation.scrollHeight;
}

export function buildAiAssistantPromptPluginCardMarkup(ctx, promptPlugin = {}) {
    const pluginId = String(promptPlugin.id || createAiAssistantPromptPluginId()).trim();
    const pluginName = String(promptPlugin.name || "").trim();
    const prompt = String(promptPlugin.prompt || promptPlugin.system_prompt || "").trim();
    const maxToolRounds = String(promptPlugin.max_tool_rounds ?? 20).trim() || "20";
    const temperature = String(promptPlugin.temperature ?? 0.2).trim() || "0.2";
    const hasInput = Boolean(pluginName || prompt || maxToolRounds !== "20" || temperature !== "0.2");
    const validationErrors = [];
    if (hasInput && !prompt) {
        validationErrors.push("提示词不能为空。");
    }

    return `
        <article class="smart-prompt-plugin-card ${validationErrors.length ? "is-invalid" : ""}" data-ai-prompt-plugin-row>
            <input type="hidden" data-field="id" value="${escapeHtml(pluginId)}">
            <div class="smart-prompt-plugin-head">
                <label class="field-group smart-prompt-plugin-name-field">
                    <span class="field-label">插件名称</span>
                    <input data-field="name" type="text" value="${escapeHtml(pluginName)}" placeholder="例如：群聊总结">
                </label>
                <label class="field-group smart-prompt-plugin-number-field">
                    <span class="field-label">工具调用轮数上限</span>
                    <input data-field="max_tool_rounds" type="number" min="1" max="500" step="1" value="${escapeHtml(maxToolRounds)}">
                </label>
                <label class="field-group smart-prompt-plugin-number-field">
                    <span class="field-label">温度 temperature</span>
                    <input data-field="temperature" type="number" min="0" max="1.5" step="any" value="${escapeHtml(temperature)}">
                </label>
                <div class="config-object-table-actions smart-prompt-plugin-actions">
                    <button class="button ghost compact" type="button" data-ai-config-action="remove-prompt-plugin">删除</button>
                </div>
            </div>
            <label class="field-group">
                <span class="field-label">提示词</span>
                <textarea class="config-editor smart-prompt-plugin-editor" data-field="prompt" placeholder="为这个智能插件填写单独的系统提示词">${escapeHtml(prompt)}</textarea>
            </label>
            <div class="detail-meta">该提示词会与内置时间提示、工具路由规则一起注入到模型上下文中。</div>
            <div class="config-object-table-error" data-ai-prompt-plugin-error>${escapeHtml(validationErrors.join(" "))}</div>
        </article>
    `;
}

export function syncAiAssistantPromptPluginTableState(ctx) {
    const list = ctx.elements.aiAssistantSettingsForm?.querySelector("[data-ai-prompt-plugin-list]");
    if (!list) {
        return;
    }
    const rows = list.querySelectorAll("[data-ai-prompt-plugin-row]");
    const emptyState = list.querySelector("[data-ai-prompt-plugin-empty]");
    if (!rows.length) {
        if (!emptyState) {
            list.innerHTML = '<div class="empty-state smart-ai-config-empty" data-ai-prompt-plugin-empty>还没有任何提示词插件。点击右上角“新增提示词插件”后，分别填写名称、提示词和轮数上限。</div>';
        }
        return;
    }
    emptyState?.remove();
}

export function syncAiAssistantPromptPluginCardState(ctx, card) {
    if (!card) {
        return;
    }
    const name = card.querySelector('[data-field="name"]')?.value.trim() || "";
    const prompt = card.querySelector('[data-field="prompt"]')?.value.trim() || "";
    const maxToolRounds = card.querySelector('[data-field="max_tool_rounds"]')?.value.trim() || "20";
    const temperature = card.querySelector('[data-field="temperature"]')?.value.trim() || "0.2";
    const hasInput = Boolean(name || prompt || maxToolRounds !== "20" || temperature !== "0.2");
    const validationErrors = [];
    if (hasInput && !prompt) {
        validationErrors.push("提示词不能为空。");
    }
    card.classList.toggle("is-invalid", validationErrors.length > 0);
    const errorNode = card.querySelector("[data-ai-prompt-plugin-error]");
    if (errorNode) {
        errorNode.textContent = validationErrors.join(" ");
    }
}

export function appendAiAssistantPromptPluginRow(ctx) {
    const list = ctx.elements.aiAssistantSettingsForm?.querySelector("[data-ai-prompt-plugin-list]");
    if (!list) {
        return;
    }

    const currentPromptPlugin = ctx.getPromptPlugin();
    syncAiAssistantPromptPluginTableState(ctx);
    list.querySelector("[data-ai-prompt-plugin-empty]")?.remove();
    list.insertAdjacentHTML(
        "beforeend",
        buildAiAssistantPromptPluginCardMarkup(ctx, {
            id: createAiAssistantPromptPluginId(),
            name: "",
            prompt: currentPromptPlugin?.prompt || ctx.getSettings().system_prompt || "",
            max_tool_rounds: currentPromptPlugin?.max_tool_rounds ?? ctx.getSettings().max_tool_rounds ?? 20,
            temperature: currentPromptPlugin?.temperature ?? ctx.getSettings().temperature ?? 0.2,
        })
    );
    syncAiAssistantPromptPluginCardState(ctx, list.lastElementChild);
}

export function buildAiAssistantProviderSelectOptions(ctx, selectedProviderKey = "") {
    return ctx.getProviders().map((provider) => `
        <option value="${escapeHtml(provider.key)}" ${provider.key === selectedProviderKey ? "selected" : ""}>${escapeHtml(provider.label)}</option>
    `).join("");
}

export function buildAiAssistantConfigRowMarkup(ctx, providerKey = "", providerConfig = {}, providerConfigMeta = null) {
    const provider = ctx.getProvider(providerKey) || ctx.getProviders()[0] || null;
    const normalizedProviderKey = provider?.key || providerKey || "zhipu";
    const configId = String(providerConfig.id || createAiAssistantConfigId(normalizedProviderKey)).trim();
    const configName = String(providerConfig.name || "").trim();
    const apiKey = String(providerConfig.api_key || "").trim();
    const enabled = Boolean(providerConfig.enabled);
    const baseUrlEditable = Boolean(provider?.allow_custom_base_url);
    const defaultBaseUrl = String(provider?.default_base_url || "").trim();
    const baseUrl = baseUrlEditable
        ? (String(providerConfig.base_url || "").trim() || defaultBaseUrl)
        : defaultBaseUrl;
    const savedModelOptions = Array.isArray(providerConfigMeta?.model_options) ? providerConfigMeta.model_options.length : 0;
    const statusMessage = providerConfigMeta?.model_fetch_error
        ? `模型列表获取失败：${providerConfigMeta.model_fetch_error}`
        : (apiKey
            ? (savedModelOptions ? `已载入 ${savedModelOptions} 个模型选项` : "保存后会自动刷新模型列表")
            : "填写并保存 API Key 后可自动载入模型列表");
    const validationErrors = [];
    if (enabled && !apiKey) {
        validationErrors.push("启用中的配置必须填写 API Key。")
    }
    if (baseUrlEditable && apiKey && !baseUrl) {
        validationErrors.push("通用 OpenAI 配置必须填写 Base URL。")
    }

    return `
        <div class="config-object-table-row smart-model-config-row ${validationErrors.length ? "is-invalid" : "is-editing"}" data-ai-config-row>
            <input type="hidden" data-field="id" value="${escapeHtml(configId)}">
            <div class="config-object-table-cell config-object-table-editor-cell">
                <select data-field="provider_key">
                    ${buildAiAssistantProviderSelectOptions(ctx, normalizedProviderKey)}
                </select>
                <div class="detail-meta" data-ai-provider-meta>${escapeHtml(provider?.description || "")}</div>
            </div>
            <div class="config-object-table-cell config-object-table-editor-cell">
                <input data-field="name" type="text" value="${escapeHtml(configName)}" placeholder="例如：主账号 / 备用 Key">
            </div>
            <div class="config-object-table-cell config-object-table-editor-cell">
                <input data-field="api_key" type="password" autocomplete="off" value="${escapeHtml(apiKey)}" placeholder="输入 ${escapeHtml(provider?.label || "AI")} API Key">
            </div>
            <div class="config-object-table-cell config-object-table-editor-cell">
                <input data-field="base_url" type="text" value="${escapeHtml(baseUrl)}" ${baseUrlEditable ? "" : "disabled"} placeholder="${escapeHtml(defaultBaseUrl || "https://api.openai.com/v1")}">
                <div class="detail-meta" data-ai-base-url-hint>${escapeHtml(baseUrlEditable ? "仅通用 OpenAI 需要填写 Base URL" : `固定地址：${defaultBaseUrl || "代码内置"}`)}</div>
            </div>
            <div class="config-object-table-cell config-object-table-editor-cell smart-config-switch-cell">
                <label class="switch">
                    <input data-field="enabled" type="checkbox" ${enabled ? "checked" : ""}>
                    <span class="switch-slider"></span>
                </label>
                <div class="detail-meta" data-ai-config-status>${escapeHtml(statusMessage)}</div>
            </div>
            <div class="config-object-table-actions">
                <button class="button ghost compact" type="button" data-ai-config-action="remove-row">删除</button>
            </div>
            <div class="config-object-table-error" data-ai-config-error>${escapeHtml(validationErrors.join(" "))}</div>
        </div>
    `;
}

export function syncAiAssistantConfigTableState(ctx) {
    const tableBody = ctx.elements.aiAssistantSettingsForm?.querySelector("[data-ai-config-table-body]");
    if (!tableBody) {
        return;
    }
    const rows = tableBody.querySelectorAll("[data-ai-config-row]");
    const existingEmptyState = tableBody.querySelector("[data-ai-config-empty]");
    if (!rows.length) {
        if (!existingEmptyState) {
            tableBody.innerHTML = '<div class="empty-state smart-ai-config-empty" data-ai-config-empty>还没有任何模型配置。点击右上角“新增配置”后，按行填写厂商、名称和 API Key。</div>';
        }
        return;
    }
    existingEmptyState?.remove();
}

export function syncAiAssistantConfigRowState(ctx, row) {
    if (!row) {
        return;
    }

    const providerKey = row.querySelector('[data-field="provider_key"]')?.value.trim() || "";
    const provider = ctx.getProvider(providerKey) || ctx.getProviders()[0] || null;
    const apiKey = row.querySelector('[data-field="api_key"]')?.value.trim() || "";
    const enabled = Boolean(row.querySelector('[data-field="enabled"]')?.checked);
    const baseUrlInput = row.querySelector('[data-field="base_url"]');
    const providerMeta = row.querySelector("[data-ai-provider-meta]");
    const baseUrlHint = row.querySelector("[data-ai-base-url-hint]");
    const statusNode = row.querySelector("[data-ai-config-status]");
    const errorNode = row.querySelector("[data-ai-config-error]");
    const defaultBaseUrl = String(provider?.default_base_url || "").trim();
    const baseUrlEditable = Boolean(provider?.allow_custom_base_url);

    if (providerMeta) {
        providerMeta.textContent = provider?.description || "";
    }

    if (baseUrlInput instanceof HTMLInputElement) {
        baseUrlInput.disabled = !baseUrlEditable;
        if (baseUrlEditable) {
            baseUrlInput.placeholder = defaultBaseUrl || "https://api.openai.com/v1";
            if (!baseUrlInput.value.trim()) {
                baseUrlInput.value = defaultBaseUrl;
            }
        } else {
            baseUrlInput.value = defaultBaseUrl;
        }
    }

    if (baseUrlHint) {
        baseUrlHint.textContent = baseUrlEditable ? "仅通用 OpenAI 需要填写 Base URL" : `固定地址：${defaultBaseUrl || "代码内置"}`;
    }

    if (statusNode) {
        statusNode.textContent = apiKey ? "保存后会自动刷新模型列表" : "填写并保存 API Key 后可自动载入模型列表";
    }

    const validationErrors = [];
    if (enabled && !apiKey) {
        validationErrors.push("启用中的配置必须填写 API Key。")
    }
    if (baseUrlEditable && apiKey && !(baseUrlInput?.value.trim())) {
        validationErrors.push("通用 OpenAI 配置必须填写 Base URL。")
    }
    row.classList.toggle("is-invalid", validationErrors.length > 0);
    row.classList.toggle("is-editing", validationErrors.length === 0);
    if (errorNode) {
        errorNode.textContent = validationErrors.join(" ");
    }
}

export function appendAiAssistantConfigRow(ctx, providerKey = ctx.aiAssistantUi.selectedProvider || ctx.getProviders()[0]?.key || "zhipu") {
    const tableBody = ctx.elements.aiAssistantSettingsForm?.querySelector("[data-ai-config-table-body]");
    if (!tableBody) {
        return;
    }

    syncAiAssistantConfigTableState(ctx);
    tableBody.querySelector("[data-ai-config-empty]")?.remove();

    const provider = ctx.getProvider(providerKey) || ctx.getProviders()[0] || null;
    tableBody.insertAdjacentHTML(
        "beforeend",
        buildAiAssistantConfigRowMarkup(ctx, 
            provider?.key || providerKey,
            {
                id: createAiAssistantConfigId(provider?.key || providerKey),
                name: "",
                enabled: false,
                api_key: "",
                base_url: provider?.default_base_url || "",
            },
            null,
        )
    );
    syncAiAssistantConfigRowState(ctx, tableBody.lastElementChild);
}

export function closeAiAssistantConfigModal(ctx) {
    ctx.elements.aiAssistantConfigModal?.classList.remove("is-visible");
}

export function closeAiAssistantConversationModal(ctx) {
    ctx.elements.aiAssistantConversationModal?.classList.remove("is-visible");
}

export function openAiAssistantConversationModal(ctx) {
    closeAiAssistantConfigModal(ctx);
    closeAiAssistantToolsModal(ctx);
    renderAiAssistantConversationList(ctx);
    ctx.elements.aiAssistantConversationModal?.classList.add("is-visible");
}

export function openAiAssistantConfigModal(ctx) {
    closeAiAssistantToolsModal(ctx);
    closeAiAssistantConversationModal(ctx);
    renderAiAssistant(ctx);
    ctx.elements.aiAssistantConfigModal?.classList.add("is-visible");
}

export function closeAiAssistantToolsModal(ctx) {
    ctx.elements.aiAssistantToolsModal?.classList.remove("is-visible");
}

export function openAiAssistantToolsModal(ctx) {
    closeAiAssistantConfigModal(ctx);
    closeAiAssistantConversationModal(ctx);
    renderAiAssistant(ctx);
    ctx.elements.aiAssistantToolsModal?.classList.add("is-visible");
}

export function renderAiAssistant(ctx) {
    if (!ctx.aiAssistant) {
        return;
    }

    const settings = ctx.getSettings();
    const providers = ctx.getProviders();
    const promptPlugins = ctx.getPromptPlugins();
    const tools = Array.isArray(ctx.aiAssistant.tools) ? ctx.aiAssistant.tools : [];
    const currentConversation = ctx.getCurrentConversation();
    const currentConversationTitle = currentConversation?.title || "未命名对话";
    const currentJob = ctx.aiActiveChatJob || {};
    const currentConversationJobActive = isAiAssistantJobActive(currentJob)
        && currentConversation?.id
        && currentJob.conversation_id === currentConversation.id;
    const currentConversationJobStopping = currentConversationJobActive && normalizeAiAssistantJobStatus(currentJob.status) === "stopping";
    const {
        provider: selectedProvider,
        providerSettings: selectedProviderSettings,
        modelOptions,
        selectedConfig,
        selectedConfigMeta,
        selectedModel,
        selectionValue,
        selectedPromptPlugin,
    } = ctx.getCurrentSelection();
    const configuredRows = providers.reduce((count, provider) => {
        const providerSettings = settings.providers?.[provider.key] || {};
        const configs = Array.isArray(providerSettings.configs) ? providerSettings.configs : [];
        return count + configs.filter((config) => config.api_key).length;
    }, 0);
    const configRowMarkup = providers.flatMap((provider) => {
        const providerSettings = settings.providers?.[provider.key] || {};
        const providerConfigs = Array.isArray(providerSettings.configs) ? providerSettings.configs : [];
        const providerMetaConfigs = new Map(
            (Array.isArray(provider.configs) ? provider.configs : []).map((config) => [config.id, config])
        );
        return providerConfigs.map((providerConfig) => buildAiAssistantConfigRowMarkup(ctx, 
            provider.key,
            providerConfig,
            providerMetaConfigs.get(providerConfig.id) || null,
        ));
    }).join("");
    const promptPluginRowMarkup = promptPlugins.map((promptPlugin) => buildAiAssistantPromptPluginCardMarkup(ctx, promptPlugin)).join("");

    if (ctx.elements.aiAssistantProviderSelect) {
        ctx.elements.aiAssistantProviderSelect.innerHTML = providers.map((provider) => `
            <option value="${escapeHtml(provider.key)}" ${provider.key === selectedProvider?.key ? "selected" : ""}>${escapeHtml(provider.label)}</option>
        `).join("");
    }

    if (ctx.elements.aiAssistantModelSelect) {
        ctx.elements.aiAssistantModelSelect.innerHTML = modelOptions.length
            ? modelOptions.map((option) => `
                <option value="${escapeHtml(option.selectionValue)}" ${option.selectionValue === selectionValue ? "selected" : ""}>${escapeHtml(option.label)}</option>
            `).join("")
            : '<option value="">暂无可用模型</option>';
        ctx.elements.aiAssistantModelSelect.disabled = !selectedProvider || (!modelOptions.length && !selectedConfig?.api_key);
    }

    if (ctx.elements.aiAssistantPromptPluginSelect) {
        ctx.elements.aiAssistantPromptPluginSelect.innerHTML = promptPlugins.length
            ? promptPlugins.map((promptPlugin) => `
                <option value="${escapeHtml(promptPlugin.id || "")}" ${promptPlugin.id === selectedPromptPlugin?.id ? "selected" : ""}>${escapeHtml(promptPlugin.name || "未命名提示词插件")}</option>
            `).join("")
            : '<option value="">暂无提示词插件</option>';
        ctx.elements.aiAssistantPromptPluginSelect.disabled = !promptPlugins.length;
    }

    if (ctx.elements.toggleAiAssistantConfigButton) {
        ctx.elements.toggleAiAssistantConfigButton.textContent = "配置";
    }

    if (ctx.elements.toggleAiAssistantToolsButton) {
        ctx.elements.toggleAiAssistantToolsButton.textContent = `工具列表 (${tools.length})`;
    }

    if (ctx.elements.newAiAssistantConversationButton) {
        ctx.elements.newAiAssistantConversationButton.disabled = ctx.aiRequestInFlight;
    }

    if (ctx.elements.openAiAssistantConversationSwitcherButton) {
        ctx.elements.openAiAssistantConversationSwitcherButton.disabled = !ctx.getConversations().length;
    }

    if (ctx.elements.clearAiAssistantConversationButton) {
        ctx.elements.clearAiAssistantConversationButton.disabled = ctx.aiRequestInFlight || !currentConversation?.id;
    }

    if (ctx.elements.stopAiAssistantChatButton) {
        ctx.elements.stopAiAssistantChatButton.disabled = !currentConversationJobActive || currentConversationJobStopping;
        ctx.elements.stopAiAssistantChatButton.textContent = currentConversationJobStopping ? "停止中..." : "停止对话";
    }

    if (ctx.elements.aiAssistantSettingsForm) {
        ctx.elements.aiAssistantSettingsForm.innerHTML = `
            <section class="config-field-shell field-span-2 smart-prompt-plugin-shell">
                <div class="config-field-head smart-provider-head">
                    <div>
                        <h5 class="detail-section-title">提示词插件配置</h5>
                        <div class="detail-meta">为不同场景维护独立的插件名称、提示词、工具调用轮数上限和温度；聊天页顶部按需切换。</div>
                        <div class="detail-meta">模型 API Key 配置与提示词插件配置解耦，可复用同一套厂商配置。</div>
                    </div>
                    <button class="button secondary compact smart-toolbar-button" type="button" data-ai-config-action="add-prompt-plugin">新增提示词插件</button>
                </div>
                <div class="smart-prompt-plugin-list" data-ai-prompt-plugin-list>
                    ${promptPluginRowMarkup || '<div class="empty-state smart-ai-config-empty" data-ai-prompt-plugin-empty>还没有任何提示词插件。点击右上角“新增提示词插件”后，分别填写名称、提示词和轮数上限。</div>'}
                </div>
            </section>
            <section class="config-field-shell field-span-2 smart-model-config-shell">
                <div class="config-field-head smart-provider-head">
                    <div>
                        <h5 class="detail-section-title">模型配置</h5>
                        <div class="detail-meta">每一行对应一套可选模型配置，固定厂商的网关参数已直接写死；通用 OpenAI 额外填写 Base URL 即可。</div>
                        <div class="detail-meta">当前共保存 ${configuredRows} 条已填写 API Key 的配置，聊天页顶部按“模型名称 / 实际模型”选择。</div>
                    </div>
                    <button class="button secondary compact smart-toolbar-button" type="button" data-ai-config-action="add-row">新增配置</button>
                </div>
                <div class="config-object-table-shell smart-model-config-table">
                    <div class="config-object-table-header smart-model-config-header">
                        <div class="config-object-table-heading">厂商</div>
                        <div class="config-object-table-heading">模型名称</div>
                        <div class="config-object-table-heading">API Key</div>
                        <div class="config-object-table-heading">Base URL</div>
                        <div class="config-object-table-heading">启用</div>
                        <div class="config-object-table-heading is-actions">操作</div>
                    </div>
                    <div class="smart-model-config-body" data-ai-config-table-body>
                        ${configRowMarkup || '<div class="empty-state smart-ai-config-empty" data-ai-config-empty>还没有任何模型配置。点击右上角“新增配置”后，按行填写厂商、名称和 API Key。</div>'}
                    </div>
                </div>
            </section>
            <section class="config-field-shell field-span-2">
                <div class="config-field-head smart-provider-head">
                    <div>
                        <h5 class="detail-section-title">工具权限</h5>
                        <div class="detail-meta">默认仅允许只读查询工具。启用后，模型才可调用发消息、改标签等写操作工具。</div>
                    </div>
                </div>
                <label class="field-group field-span-2">
                    <span class="field-label">允许写操作工具 allow_write_tools</span>
                    <input data-field="allow_write_tools" type="checkbox" ${ctx.getSettings().allow_write_tools ? "checked" : ""}>
                </label>
            </section>
        `;
        ctx.elements.aiAssistantSettingsForm.querySelectorAll("[data-ai-prompt-plugin-row]").forEach((card) => {
            syncAiAssistantPromptPluginCardState(ctx, card);
        });
        ctx.elements.aiAssistantSettingsForm.querySelectorAll("[data-ai-config-row]").forEach((row) => {
            syncAiAssistantConfigRowState(ctx, row);
        });
    }

    if (ctx.elements.aiAssistantAlert) {
        const selectedLabel = selectedProvider?.label || "未选择厂商";
        const selectedPromptPluginLabel = selectedPromptPlugin?.name || "未选择提示词插件";
        if (selectedConfig?.enabled && selectedConfig?.api_key) {
            ctx.elements.aiAssistantAlert.className = `settings-alert is-visible ${selectedConfigMeta?.model_fetch_error ? "bad" : "good"}`;
            ctx.elements.aiAssistantAlert.textContent = selectedConfigMeta?.model_fetch_error
                ? `${selectedPromptPluginLabel} · ${selectedLabel} · ${selectedConfig.name || "未命名配置"} 已启用，但模型列表自动获取失败，当前会回退到 ${selectedModel}。`
                : `${selectedPromptPluginLabel} · ${selectedLabel} · ${selectedConfig.name || "未命名配置"} 已配置并启用，当前对话模型为 ${selectedModel}。配置会保存在本地 SQLite。`;
        } else if (selectedConfig?.api_key) {
            ctx.elements.aiAssistantAlert.className = "settings-alert is-visible bad";
            ctx.elements.aiAssistantAlert.textContent = `${selectedPromptPluginLabel} · ${selectedLabel} · ${selectedConfig.name || "未命名配置"} 已填写 API Key，但当前未启用。发送前请先在配置中启用。`;
        } else if (selectedConfig) {
            ctx.elements.aiAssistantAlert.className = "settings-alert is-visible bad";
            ctx.elements.aiAssistantAlert.textContent = `${selectedPromptPluginLabel} · ${selectedLabel} · ${selectedConfig.name || "未命名配置"} 尚未填写 API Key。点击上方配置按钮后保存，才能开始对话。`;
        } else {
            ctx.elements.aiAssistantAlert.className = "settings-alert is-visible bad";
            ctx.elements.aiAssistantAlert.textContent = `${selectedPromptPluginLabel} · ${selectedLabel} 还没有任何配置。点击上方配置按钮新增一行并保存后，才能开始对话。`;
        }
    }

    if (ctx.elements.aiAssistantToolMeta) {
        const readOnlyCount = tools.filter((tool) => tool.read_only).length;
        ctx.elements.aiAssistantToolMeta.textContent = `共 ${tools.length} 个工具，${readOnlyCount} 个只读，${tools.length - readOnlyCount} 个写操作`;
    }

    if (ctx.elements.aiAssistantToolGrid) {
        ctx.elements.aiAssistantToolGrid.innerHTML = tools.map((tool) => `
            <article class="smart-tool-card">
                <div class="smart-tool-card-head">
                    <h6 class="smart-tool-name">${escapeHtml(tool.name || "unknown")}</h6>
                    <span class="badge ${tool.read_only ? "good" : "warn"}">${escapeHtml(tool.read_only ? "只读" : "写操作")}</span>
                </div>
                <div class="detail-meta">${escapeHtml(tool.description || "")}</div>
            </article>
        `).join("");
    }

    if (ctx.elements.aiAssistantProviderBadgeRow) {
        ctx.elements.aiAssistantProviderBadgeRow.innerHTML = selectedProvider
            ? `
                <span class="badge">${escapeHtml(selectedPromptPlugin?.name || "未选择提示词插件")}</span>
                <span class="badge good">${escapeHtml(selectedProvider.label)}</span>
                <span class="badge">${escapeHtml(selectedConfig?.name || "未命名配置")}</span>
                <span class="badge">${escapeHtml(selectedModel || selectedProvider.default_model || "")}</span>
                <span class="badge">${escapeHtml(`工具轮数 ${selectedPromptPlugin?.max_tool_rounds ?? settings.max_tool_rounds ?? 20}`)}</span>
                <span class="badge ${selectedConfig?.api_key ? "good" : "bad"}">${escapeHtml(selectedConfig?.api_key ? "已配置 API Key" : "未配置 API Key")}</span>
                <span class="badge ${selectedConfig?.enabled ? "good" : "warn"}">${escapeHtml(selectedConfig?.enabled ? "已启用" : "未启用")}</span>
            `
            : '<span class="badge bad">未配置 AI 厂商</span>';
    }

    if (ctx.elements.aiAssistantConversationMeta) {
        ctx.elements.aiAssistantConversationMeta.textContent = selectedProvider
            ? `${currentConversationTitle} · ${selectedPromptPlugin?.name || "未选择提示词插件"} · ${selectedProvider.label}${selectedConfig?.name ? ` / ${selectedConfig.name}` : ""} 当前会话模型：${selectedModel || selectedProvider.default_model || "未设置"}。${currentConversationJobActive ? `当前任务：${currentJob.progress_message || "处理中..."}` : (selectedConfigMeta?.model_fetch_error ? "模型列表自动获取失败，已回退到默认模型。" : `当前共可选 ${modelOptions.length} 个模型选项。`)}`
            : "请先配置并启用一个 AI 厂商。";
    }

    if (ctx.elements.sendAiAssistantPromptButton) {
        ctx.elements.sendAiAssistantPromptButton.disabled = ctx.aiRequestInFlight || !(selectedConfig?.enabled && selectedConfig?.api_key);
    }

    renderAiAssistantConversationList(ctx);
    renderAiConversation(ctx);
}

export function readAiAssistantSettingsForm(ctx) {
    const form = ctx.elements.aiAssistantSettingsForm;
    const providers = ctx.getProviders();
    const normalizedProviders = Object.fromEntries(providers.map((provider) => [provider.key, { configs: [] }]));
    const payload = {
        active_provider: ctx.aiAssistantUi.selectedProvider || ctx.aiAssistant?.settings?.active_provider || "zhipu",
        active_prompt_plugin_id: "",
        system_prompt: "",
        temperature: 0.2,
        max_tool_rounds: 20,
        allow_write_tools: false,
        prompt_plugins: [],
        providers: normalizedProviders,
    };

    const promptPluginRows = Array.from(form.querySelectorAll("[data-ai-prompt-plugin-row]"));
    for (const [index, row] of promptPluginRows.entries()) {
        const rawName = row.querySelector('[data-field="name"]')?.value.trim() || "";
        const rawPrompt = row.querySelector('[data-field="prompt"]')?.value.trim() || "";
        const rawMaxToolRounds = row.querySelector('[data-field="max_tool_rounds"]')?.value.trim() || "20";
        const rawTemperature = row.querySelector('[data-field="temperature"]')?.value.trim() || "0.2";
        const hasInput = Boolean(rawName || rawPrompt || rawMaxToolRounds !== "20" || rawTemperature !== "0.2");
        if (!hasInput) {
            continue;
        }
        if (!rawPrompt) {
            throw new Error(`${rawName || `提示词插件 ${index + 1}`} 的提示词不能为空`);
        }
        payload.prompt_plugins.push({
            id: row.querySelector('[data-field="id"]')?.value.trim() || createAiAssistantPromptPluginId(),
            name: rawName || `提示词插件 ${payload.prompt_plugins.length + 1}`,
            prompt: rawPrompt,
            temperature: Number(rawTemperature || 0.2),
            max_tool_rounds: Number(rawMaxToolRounds || 20),
        });
    }

    if (!payload.prompt_plugins.length) {
        const fallbackPromptPlugin = ctx.getPromptPlugin() || {
            id: createAiAssistantPromptPluginId(),
            name: "通用助手",
            prompt: ctx.aiAssistant?.settings?.system_prompt || "",
            temperature: ctx.aiAssistant?.settings?.temperature ?? 0.2,
            max_tool_rounds: ctx.aiAssistant?.settings?.max_tool_rounds ?? 20,
        };
        payload.prompt_plugins.push({
            id: fallbackPromptPlugin.id || createAiAssistantPromptPluginId(),
            name: fallbackPromptPlugin.name || "通用助手",
            prompt: fallbackPromptPlugin.prompt || ctx.aiAssistant?.settings?.system_prompt || "",
            temperature: Number(fallbackPromptPlugin.temperature ?? 0.2),
            max_tool_rounds: Number(fallbackPromptPlugin.max_tool_rounds ?? 20),
        });
    }

    const selectedPromptPlugin = payload.prompt_plugins.find((plugin) => plugin.id === ctx.aiAssistantUi.selectedPromptPluginId)
        || payload.prompt_plugins[0];
    payload.active_prompt_plugin_id = selectedPromptPlugin.id;
    payload.system_prompt = selectedPromptPlugin.prompt;
    payload.temperature = Number(selectedPromptPlugin.temperature ?? 0.2);
    payload.max_tool_rounds = Number(selectedPromptPlugin.max_tool_rounds ?? 20);
    payload.allow_write_tools = Boolean(form.querySelector('[data-field="allow_write_tools"]')?.checked);

    const configRows = Array.from(form.querySelectorAll("[data-ai-config-row]"));
    for (const row of configRows) {
        const providerKey = row.querySelector('[data-field="provider_key"]')?.value.trim() || "";
        const provider = ctx.getProvider(providerKey);
        if (!provider || !payload.providers[providerKey]) {
            continue;
        }

        const rawName = row.querySelector('[data-field="name"]')?.value.trim() || "";
        const apiKey = row.querySelector('[data-field="api_key"]')?.value.trim() || "";
        const enabled = Boolean(row.querySelector('[data-field="enabled"]')?.checked);
        const rawBaseUrl = row.querySelector('[data-field="base_url"]')?.value.trim() || "";
        const baseUrl = provider.allow_custom_base_url
            ? (rawBaseUrl || provider.default_base_url || "")
            : (provider.default_base_url || "");
        const isBlankRow = !rawName && !apiKey && !enabled && (!provider.allow_custom_base_url || !rawBaseUrl || rawBaseUrl === provider.default_base_url);
        if (isBlankRow) {
            continue;
        }

        payload.providers[providerKey].configs.push({
            id: row.querySelector('[data-field="id"]')?.value.trim() || createAiAssistantConfigId(providerKey),
            name: rawName || `${provider.label} 配置 ${payload.providers[providerKey].configs.length + 1}`,
            enabled,
            api_key: apiKey,
            base_url: baseUrl,
        });
    }

    return payload;
}

