/** 插件结构化配置表单渲染与动态选项加载。 */

import { escapeHtml, normalizeInlineText } from "./dom-utils.js";
import {
    initializeSearchableChoiceFilters,
    syncScopeFieldVisibility,
} from "./config-search.js";
import {
    readStructuredPluginConfig,
    renderPluginConfigFields,
} from "./plugin-config-form.js";
import {
    findPluginDynamicModelField,
    getPluginDynamicOptionPayloads,
    getPluginScopeTargets,
    hasStructuredPluginConfig,
    isMessageSummaryPlugin,
    mergeOptionsWithCurrentValues,
    normalizeRoomMsgSummaryRenderConfig,
    parseStructuredFieldValue,
    WXPID_OPTION_ALL,
    WXPID_OPTION_DEFAULT,
    buildRoomMsgSummaryTimeWindow,
} from "./plugin-helpers.js";

export function getPluginModuleNameForForm(formElement, elements, moduleState) {
    if (formElement === elements.pluginConfigForm) {
        return moduleState.pluginConfigModule;
    }
    if (formElement === elements.pluginExecuteForm) {
        return moduleState.pluginExecuteModule;
    }
    return "";
}

export function buildStructuredPluginConfigPayload(formElement, plugin) {
    const nextConfig = readStructuredPluginConfig(formElement, plugin);
    const mergedConfig = { ...(plugin.config || {}) };
    for (const field of Array.isArray(plugin.config_schema) ? plugin.config_schema : []) {
        delete mergedConfig[field.key];
        for (const alias of Array.isArray(field.aliases) ? field.aliases : []) {
            delete mergedConfig[alias];
        }
    }
    return {
        ...mergedConfig,
        ...nextConfig,
    };
}

export async function loadPluginDynamicOptionPayloads(plugin, config, apiClient) {
    const payloads = { ...getPluginDynamicOptionPayloads(plugin) };
    const modelField = findPluginDynamicModelField(plugin);
    if (!plugin?.module || !modelField) {
        return payloads;
    }

    if (modelField.manual_fetch_options) {
        if (!payloads.model_options) {
            const currentModelKey = normalizeInlineText(modelField.key || "model") || "model";
            payloads.model_options = {
                options: mergeOptionsWithCurrentValues([], config?.[currentModelKey]),
                error: "",
            };
        }
        return payloads;
    }

    try {
        payloads.model_options = await apiClient.getPluginModelOptions(plugin.module, config || {});
    } catch (error) {
        const currentModelKey = normalizeInlineText(modelField.key || "model") || "model";
        const currentModelValue = config?.[currentModelKey];
        payloads.model_options = {
            options: mergeOptionsWithCurrentValues([], currentModelValue),
            error: error.message || String(error),
        };
    }
    return payloads;
}

export function resolveTargetOptionsBySource(optionsSource, currentValues, plugin, pluginTargets) {
    if (optionsSource === "room_options") {
        return mergeOptionsWithCurrentValues(pluginTargets?.room_options || [], currentValues);
    }
    if (optionsSource === "label_options") {
        return Array.isArray(pluginTargets?.label_options) ? [...pluginTargets.label_options] : [];
    }
    if (optionsSource === "wxpid_options") {
        return mergeOptionsWithCurrentValues(pluginTargets?.wxpid_options || [], currentValues);
    }
    if (optionsSource === "model_options") {
        const modelOptions = getPluginDynamicOptionPayloads(plugin).model_options;
        return mergeOptionsWithCurrentValues(modelOptions?.options || [], currentValues);
    }
    return [];
}

export function hydrateDynamicFieldOptions(field, configValue, plugin, pluginTargets) {
    if (!field || typeof field !== "object") {
        return field;
    }

    const nextField = { ...field };
    if (field.options_source) {
        nextField.options = resolveTargetOptionsBySource(field.options_source, configValue, plugin, pluginTargets);
    }

    if (field.options_source === "model_options") {
        const modelOptionsPayload = getPluginDynamicOptionPayloads(plugin).model_options;
        if (modelOptionsPayload?.error) {
            nextField.description = [
                field.description,
                `当前模型列表读取失败：${modelOptionsPayload.error}`,
            ].filter(Boolean).join(" ");
        }
    }

    if (Array.isArray(field.columns)) {
        nextField.columns = field.columns.map((column) => {
            if (!column || typeof column !== "object" || !column.options_source) {
                return column;
            }
            const currentValues = Array.isArray(configValue)
                ? configValue.map((row) => row && typeof row === "object" ? row[column.key] : undefined)
                : [];
            return {
                ...column,
                options: resolveTargetOptionsBySource(column.options_source, currentValues, plugin, pluginTargets),
            };
        });
    }

    return nextField;
}

export function getWxpidFieldOptions(currentValue, pluginTargets, users) {
    const seen = new Set();
    const options = [
        { label: "默认第一个微信进程", value: WXPID_OPTION_DEFAULT },
        { label: "所有微信进程", value: WXPID_OPTION_ALL },
    ];
    const targetOptions = Array.isArray(pluginTargets?.wxpid_options) ? pluginTargets.wxpid_options : [];

    for (const option of targetOptions) {
        const numericValue = Number(option?.value);
        if (!Number.isFinite(numericValue)) {
            continue;
        }
        const key = String(numericValue);
        if (seen.has(key)) {
            continue;
        }
        seen.add(key);
        options.push({
            label: normalizeInlineText(option?.label || `微信进程(${numericValue})`) || `微信进程(${numericValue})`,
            search_text: normalizeInlineText(option?.search_text || ""),
            value: numericValue,
        });
    }

    if (!targetOptions.length) {
        const userList = Array.isArray(users?.users) ? users.users : [];
        for (const user of userList) {
            const numericValue = Number(user?.wxpid ?? user?.pid);
            if (!Number.isFinite(numericValue)) {
                continue;
            }
            const key = String(numericValue);
            if (seen.has(key)) {
                continue;
            }
            seen.add(key);
            const nickname = normalizeInlineText(user?.nickname || user?.display_name || "") || "未命名账号";
            const wxid = normalizeInlineText(user?.wxid || "");
            options.push({
                label: wxid ? `${nickname}(${wxid})` : `${nickname}(${numericValue})`,
                value: numericValue,
            });
        }
    }

    const normalizedCurrentValue = String(currentValue ?? "").trim();
    if (
        options.length <= 2
        && normalizedCurrentValue
        && normalizedCurrentValue !== WXPID_OPTION_DEFAULT
        && normalizedCurrentValue !== WXPID_OPTION_ALL
        && !seen.has(normalizedCurrentValue)
    ) {
        const fallbackValue = Number(normalizedCurrentValue);
        options.push({
            label: `当前配置(${normalizedCurrentValue})`,
            value: Number.isFinite(fallbackValue) ? fallbackValue : normalizedCurrentValue,
        });
    }

    return options;
}

export function buildWxpidFieldSchema(field, currentValue, pluginTargets, users, description = "") {
    return {
        ...field,
        type: "select",
        default: Object.prototype.hasOwnProperty.call(field, "default") ? field.default : WXPID_OPTION_DEFAULT,
        options: getWxpidFieldOptions(currentValue, pluginTargets, users),
        description: description || field.description || "默认使用首个登录微信进程；也可选择遍历所有当前登录进程。",
    };
}

export function buildPluginScopeFields(plugin, pluginTargets, modeDefaults = {}) {
    const scopeTargets = getPluginScopeTargets(plugin);
    const config = plugin?.config || {};
    const fields = [];

    if (scopeTargets.includes("rooms")) {
        const roomOptions = mergeOptionsWithCurrentValues(pluginTargets?.room_options || [], config._scope_room_ids || []);
        fields.push({
            key: "_scope_room_mode",
            label: "群聊范围",
            type: "select",
            full_width: false,
            default: modeDefaults._scope_room_mode || "all",
            options: [
                { label: "全部群聊", value: "all" },
                { label: "指定群聊", value: "selected" },
                { label: "不作用于任何群聊", value: "none" },
            ],
            description: "默认作用于全部群聊。选择“指定群聊”后，在下方勾选具体群聊。",
        });
        fields.push({
            key: "_scope_room_ids",
            label: "指定群聊",
            type: "searchable-multi-checkbox",
            options: roomOptions,
            default: [],
            search_placeholder: "搜索群名称或 wxid",
            show_selected_label: "仅显示已勾选群聊",
            empty_text: "没有匹配到群聊。",
            empty_no_options_text: "当前还没有可选群聊。",
            description: roomOptions.length
                ? "仅当上方选择“指定群聊”时生效。支持按群名称或 wxid 搜索筛选。"
                : "当前未读取到群聊列表，可先刷新用户或稍后重试。",
        });
    }

    if (scopeTargets.includes("friend_labels")) {
        const labelOptions = mergeOptionsWithCurrentValues(pluginTargets?.label_options || [], config._scope_friend_labels || []);
        fields.push({
            key: "_scope_friend_mode",
            label: "好友范围",
            type: "select",
            full_width: false,
            default: modeDefaults._scope_friend_mode || "all",
            options: [
                { label: "全部好友", value: "all" },
                { label: "指定好友标签", value: "selected" },
                { label: "不作用于任何好友", value: "none" },
            ],
            description: "好友范围通过标签控制。选择“指定好友标签”后，在下方勾选标签。",
        });
        fields.push({
            key: "_scope_friend_labels",
            label: "指定好友标签",
            type: "searchable-multi-checkbox",
            options: labelOptions,
            default: [],
            search_placeholder: "搜索好友标签",
            show_selected_label: "仅显示已勾选标签",
            empty_text: "没有匹配到好友标签。",
            empty_no_options_text: "当前还没有可选好友标签。",
            description: labelOptions.length
                ? "仅当上方选择“指定好友标签”时生效。支持按标签名搜索筛选。"
                : "当前未读取到标签列表，可先刷新用户或稍后重试。",
        });
    }

    return fields;
}

export function buildPluginConfigRenderModel(plugin, pluginTargets, users) {
    const sourcePlugin = isMessageSummaryPlugin(plugin)
        ? { ...plugin, config: normalizeRoomMsgSummaryRenderConfig(plugin) }
        : plugin;

    if (!sourcePlugin || !Array.isArray(sourcePlugin.config_schema)) {
        return sourcePlugin;
    }

    return {
        ...sourcePlugin,
        config_schema: sourcePlugin.config_schema.map((field) => {
            if (!field || typeof field !== "object") {
                return field;
            }
            const currentValue = sourcePlugin.config?.[field.key];
            let nextField = hydrateDynamicFieldOptions(field, currentValue, sourcePlugin, pluginTargets);
            if (nextField.key === "wxpid") {
                nextField = buildWxpidFieldSchema(nextField, currentValue, pluginTargets, users);
            }
            if (Array.isArray(nextField.columns)) {
                nextField = {
                    ...nextField,
                    columns: nextField.columns.map((column) => {
                        if (!column || typeof column !== "object" || column.key !== "wxpid") {
                            return column;
                        }
                        return buildWxpidFieldSchema(
                            column,
                            undefined,
                            pluginTargets,
                            users,
                            column.description || "默认使用首个登录微信进程；也可选择遍历所有当前登录进程。"
                        );
                    }),
                };
            }
            return nextField;
        }).concat(
            sourcePlugin.message_dependent
                ? buildPluginScopeFields(sourcePlugin, pluginTargets).filter((field) => !sourcePlugin.config_schema.some((item) => item?.key === field.key))
                : []
        ),
    };
}

export function buildPluginExecuteRenderModel(plugin, pluginTargets, users) {
    const scopeTargets = getPluginScopeTargets(plugin);
    const config = { ...(plugin?.config || {}) };
    if (config.wxpid === undefined || config.wxpid === null || config.wxpid === "") {
        config.wxpid = WXPID_OPTION_DEFAULT;
    }
    if (scopeTargets.includes("rooms") && config._scope_room_mode === undefined) {
        config._scope_room_mode = "selected";
    }
    if (scopeTargets.includes("friend_labels") && config._scope_friend_mode === undefined) {
        config._scope_friend_mode = "selected";
    }
    const renderPlugin = buildPluginConfigRenderModel({ ...plugin, config }, pluginTargets, users);
    return {
        ...renderPlugin,
        config,
        config_schema: [
            ...(Array.isArray(renderPlugin.config_schema)
                ? renderPlugin.config_schema
                    .filter((field) => field?.key === "wxpid")
                    .map((field) => ({
                        ...field,
                        description: field.description || "本次执行默认使用首个登录微信进程；这里的选择不会覆盖已保存配置。",
                    }))
                : []),
            ...buildPluginScopeFields({ ...plugin, config }, pluginTargets, config),
        ],
    };
}

export function syncRoomMsgSummaryTimeFields(formElement, getPluginModuleName, getPluginByModule, { force = false } = {}) {
    const moduleName = getPluginModuleName(formElement);
    const plugin = moduleName ? getPluginByModule(moduleName) : null;
    if (!isMessageSummaryPlugin(plugin)) {
        return;
    }

    const timeRangeInput = formElement.querySelector('[data-config-key="time_range"]');
    const startInput = formElement.querySelector('[data-config-key="start_time"]');
    const endInput = formElement.querySelector('[data-config-key="end_time"]');
    if (!(timeRangeInput instanceof HTMLSelectElement) || !(startInput instanceof HTMLInputElement) || !(endInput instanceof HTMLInputElement)) {
        return;
    }

    const timeRangeValue = parseStructuredFieldValue(timeRangeInput.value) || "2h";
    const { startTime, endTime } = buildRoomMsgSummaryTimeWindow(timeRangeValue);
    if (force || !normalizeInlineText(startInput.value)) {
        startInput.value = startTime;
    }
    if (force || !normalizeInlineText(endInput.value)) {
        endInput.value = endTime;
    }
}

export function renderStructuredPluginForm(formElement, renderPlugin, helpers) {
    renderPluginConfigFields(formElement, renderPlugin);
    syncRoomMsgSummaryTimeFields(formElement, helpers.getPluginModuleName, helpers.getPluginByModule);
    initializeSearchableChoiceFilters(formElement);
    syncScopeFieldVisibility(formElement);
}

export async function preparePluginConfigRenderModel(plugin, pluginTargets, users, apiClient, configOverride = undefined, renderOptions = {}) {
    const sourcePlugin = {
        ...plugin,
        config: configOverride !== undefined ? configOverride : plugin?.config,
    };
    const dynamicOptionPayloads = renderOptions.forceModelOptions
        ? {
            ...getPluginDynamicOptionPayloads(sourcePlugin),
            model_options: await apiClient.getPluginModelOptions(sourcePlugin.module, sourcePlugin.config || {}),
        }
        : await loadPluginDynamicOptionPayloads(sourcePlugin, sourcePlugin.config || {}, apiClient);
    return buildPluginConfigRenderModel({
        ...sourcePlugin,
        dynamic_option_payloads: dynamicOptionPayloads,
    }, pluginTargets, users);
}

export async function preparePluginExecuteRenderModel(plugin, pluginTargets, users, apiClient, configOverride = undefined, renderOptions = {}) {
    const scopeTargets = getPluginScopeTargets(plugin);
    const config = { ...(configOverride !== undefined ? configOverride : (plugin?.config || {})) };
    if (config.wxpid === undefined || config.wxpid === null || config.wxpid === "") {
        config.wxpid = WXPID_OPTION_DEFAULT;
    }
    if (scopeTargets.includes("rooms") && config._scope_room_mode === undefined) {
        config._scope_room_mode = "selected";
    }
    if (scopeTargets.includes("friend_labels") && config._scope_friend_mode === undefined) {
        config._scope_friend_mode = "selected";
    }

    const dynamicOptionPayloads = renderOptions.forceModelOptions
        ? {
            ...getPluginDynamicOptionPayloads(plugin),
            model_options: await apiClient.getPluginModelOptions(plugin.module, config || {}),
        }
        : await loadPluginDynamicOptionPayloads(plugin, config, apiClient);
    return buildPluginExecuteRenderModel({
        ...plugin,
        config,
        dynamic_option_payloads: dynamicOptionPayloads,
    }, pluginTargets, users);
}

export async function refreshPluginModelOptionsForm(formElement, ctx) {
    const moduleName = getPluginModuleNameForForm(formElement, ctx.elements, ctx.moduleState);
    if (!moduleName) {
        return null;
    }

    const plugin = ctx.getPluginByModule(moduleName);
    if (!plugin || !findPluginDynamicModelField(plugin) || !hasStructuredPluginConfig(plugin)) {
        return null;
    }

    const { pluginTargets, users } = ctx;
    const currentRenderPlugin = formElement === ctx.elements.pluginConfigForm
        ? buildPluginConfigRenderModel(plugin, pluginTargets, users)
        : buildPluginExecuteRenderModel(plugin, pluginTargets, users);
    const nextConfig = readStructuredPluginConfig(formElement, currentRenderPlugin);
    const renderPlugin = formElement === ctx.elements.pluginConfigForm
        ? await preparePluginConfigRenderModel(plugin, pluginTargets, users, ctx.api, nextConfig, { forceModelOptions: true })
        : await preparePluginExecuteRenderModel(plugin, pluginTargets, users, ctx.api, nextConfig, { forceModelOptions: true });

    if (moduleName !== getPluginModuleNameForForm(formElement, ctx.elements, ctx.moduleState)) {
        return null;
    }
    renderStructuredPluginForm(formElement, renderPlugin, ctx);
    return renderPlugin;
}

export function shouldRefreshPluginModelOptions(plugin, fieldKey) {
    const modelField = findPluginDynamicModelField(plugin);
    if (!modelField) {
        return false;
    }
    if (modelField.manual_fetch_options) {
        return false;
    }
    const refreshOnFields = Array.isArray(modelField.refresh_on_fields)
        ? modelField.refresh_on_fields.map((item) => normalizeInlineText(item)).filter(Boolean)
        : [];
    if (refreshOnFields.length) {
        return refreshOnFields.includes(normalizeInlineText(fieldKey));
    }
    return ["base_url", "api_key"].includes(normalizeInlineText(fieldKey));
}

export function getFetchOptionsFieldShell(element) {
    return element?.closest(".config-fetch-options-field") || null;
}

export function getFetchOptionsTargetInput(element) {
    const fieldShell = getFetchOptionsFieldShell(element);
    const targetInput = fieldShell?.querySelector("input[data-column-key], input[data-config-key]");
    return targetInput instanceof HTMLInputElement ? targetInput : null;
}

function readFetchOptionsRequestValue(inputElement) {
    if (inputElement instanceof HTMLSelectElement) {
        return parseStructuredFieldValue(inputElement.value);
    }
    if (inputElement instanceof HTMLInputElement && inputElement.type === "checkbox") {
        return Boolean(inputElement.checked);
    }
    if (inputElement instanceof HTMLInputElement && inputElement.type === "number") {
        const text = String(inputElement.value || "").trim();
        if (!text) {
            return undefined;
        }
        const value = Number(text);
        return Number.isFinite(value) ? value : undefined;
    }
    if (inputElement instanceof HTMLInputElement || inputElement instanceof HTMLTextAreaElement) {
        return inputElement.value;
    }
    return "";
}

export function buildFetchOptionsSelectMarkup(fieldKey, options, currentValue) {
    const normalizedCurrentValue = JSON.stringify(currentValue ?? "");
    return `
        <select data-config-fetch-options-select="${escapeHtml(fieldKey)}" style="margin-top:8px;">
            ${options.map((option) => {
                const optionValue = Object.prototype.hasOwnProperty.call(option, "value") ? option.value : option;
                const optionLabel = Object.prototype.hasOwnProperty.call(option, "label") ? option.label : String(optionValue ?? "");
                const encodedValue = escapeHtml(JSON.stringify(optionValue));
                return `<option value="${encodedValue}" ${JSON.stringify(optionValue) === normalizedCurrentValue ? "selected" : ""}>${escapeHtml(optionLabel)}</option>`;
            }).join("")}
        </select>
    `;
}

export function updateFetchOptionsSelect(fieldShell, fieldKey, options, currentValue) {
    if (!fieldShell || !fieldKey) {
        return;
    }
    const mergedOptions = mergeOptionsWithCurrentValues(options, currentValue);
    const existingSelect = fieldShell.querySelector(`[data-config-fetch-options-select="${fieldKey}"]`);
    const nextMarkup = buildFetchOptionsSelectMarkup(fieldKey, mergedOptions, currentValue);
    if (existingSelect) {
        existingSelect.outerHTML = nextMarkup;
    } else {
        fieldShell.insertAdjacentHTML("beforeend", nextMarkup);
    }
    const nextSelect = fieldShell.querySelector(`[data-config-fetch-options-select="${fieldKey}"]`);
    const hasCurrentValue = mergedOptions.some((option) => {
        const optionValue = Object.prototype.hasOwnProperty.call(option, "value") ? option.value : option;
        return JSON.stringify(optionValue) === JSON.stringify(currentValue ?? "");
    });
    if (nextSelect instanceof HTMLSelectElement && !hasCurrentValue) {
        nextSelect.selectedIndex = -1;
    }
}

export function buildPluginModelOptionsRequestConfig(formElement, plugin, fieldContainer, targetInput, fieldKey, parentFieldKey, ctx) {
    if (!plugin) {
        return {
            __model_field_key: fieldKey,
            __model_parent_field_key: parentFieldKey,
        };
    }

    const { pluginTargets, users, elements } = ctx;
    const renderPlugin = formElement === elements.pluginConfigForm
        ? buildPluginConfigRenderModel(plugin, pluginTargets, users)
        : buildPluginExecuteRenderModel(plugin, pluginTargets, users);
    const currentConfig = readStructuredPluginConfig(formElement, renderPlugin);
    if (!parentFieldKey) {
        return {
            ...currentConfig,
            __model_field_key: fieldKey,
        };
    }

    const modelField = findPluginDynamicModelField(plugin, fieldKey, parentFieldKey);
    const rowContainer = targetInput?.closest("[data-config-row-editor]") || targetInput?.closest("[data-config-row]");
    const rowConfig = {};
    for (const key of [fieldKey, modelField?.base_url_key || "base_url", modelField?.api_key_key || "api_key"]) {
        const normalizedKey = normalizeInlineText(key);
        if (!normalizedKey) {
            continue;
        }
        const rowInput = rowContainer?.querySelector(`[data-column-key="${normalizedKey}"]`);
        if (!rowInput) {
            continue;
        }
        rowConfig[normalizedKey] = readFetchOptionsRequestValue(rowInput);
    }
    return {
        ...rowConfig,
        __model_field_key: fieldKey,
        __model_parent_field_key: parentFieldKey,
    };
}

export function applyFetchOptionsSelection(selectElement) {
    const targetInput = getFetchOptionsTargetInput(selectElement);
    if (!(targetInput instanceof HTMLInputElement)) {
        return;
    }
    const nextValue = parseStructuredFieldValue(selectElement.value);
    targetInput.value = nextValue === undefined || nextValue === null ? "" : String(nextValue);
    targetInput.dispatchEvent(new Event("input", { bubbles: true }));
    targetInput.dispatchEvent(new Event("change", { bubbles: true }));
}

export async function handlePluginFetchOptions(button, formElement, ctx) {
    const moduleName = getPluginModuleNameForForm(formElement, ctx.elements, ctx.moduleState);
    if (!moduleName) {
        ctx.setStatus("当前未选中插件，无法获取模型列表", "bad");
        return true;
    }

    const plugin = ctx.getPluginByModule(moduleName);
    const targetInput = getFetchOptionsTargetInput(button);
    const fieldKey = normalizeInlineText(button?.getAttribute("data-target-key") || targetInput?.getAttribute("data-column-key") || targetInput?.getAttribute("data-config-key") || "");
    const fieldContainer = button?.closest("[data-config-field]");
    const parentFieldKey = fieldContainer?.getAttribute("data-config-type") === "object-list"
        ? normalizeInlineText(fieldContainer?.getAttribute("data-config-field") || "")
        : "";
    if (!plugin || !fieldKey || !(targetInput instanceof HTMLInputElement) || !findPluginDynamicModelField(plugin, fieldKey, parentFieldKey)) {
        ctx.setStatus("当前插件未配置模型列表读取能力", "bad");
        return true;
    }

    const originalText = button.textContent || "获取模型列表";
    button.disabled = true;
    button.textContent = "获取中...";
    try {
        ctx.setStatus("正在获取模型列表...");
        const requestConfig = buildPluginModelOptionsRequestConfig(formElement, plugin, fieldContainer, targetInput, fieldKey, parentFieldKey, ctx);
        const modelOptionsPayload = await ctx.api.getPluginModelOptions(moduleName, requestConfig);
        const nextOptions = Array.isArray(modelOptionsPayload?.options) ? modelOptionsPayload.options : [];
        updateFetchOptionsSelect(getFetchOptionsFieldShell(button), fieldKey, nextOptions, targetInput.value);
        if (modelOptionsPayload?.error) {
            ctx.setStatus(`模型列表读取失败：${modelOptionsPayload.error}`, "bad");
            return true;
        }
        const optionCount = nextOptions.length;
        if (optionCount > 0) {
            ctx.setStatus(`已获取 ${optionCount} 个模型，可继续手动输入或从下拉中选择`, "good");
        } else {
            ctx.setStatus("模型列表为空，请确认上游服务是否返回模型数据", "bad");
        }
    } catch (error) {
        ctx.setStatus(`模型列表读取失败：${error.message}`, "bad");
    } finally {
        button.disabled = false;
        button.textContent = originalText;
    }
    return true;
}
