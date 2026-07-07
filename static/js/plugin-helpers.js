/** 插件列表、配置与手动执行相关的纯函数工具。 */

import {
    MANUAL_PLUGIN_EXECUTION_ACTIVE_STATUSES,
    MANUAL_PLUGIN_EXECUTION_TERMINAL_STATUSES,
} from "./polling-config.js";
import { normalizeInlineText } from "./dom-utils.js";

export const WXPID_OPTION_DEFAULT = "__default_first__";
export const WXPID_OPTION_ALL = "__all__";

export function normalizeManualPluginExecution(plugin) {
    const execution = plugin?.manual_execution && typeof plugin.manual_execution === "object"
        ? plugin.manual_execution
        : {};
    const status = normalizeInlineText(execution.status || "idle").toLowerCase() || "idle";
    return {
        ...execution,
        status,
        active: MANUAL_PLUGIN_EXECUTION_ACTIVE_STATUSES.has(status),
        terminal: MANUAL_PLUGIN_EXECUTION_TERMINAL_STATUSES.has(status),
        detail: normalizeInlineText(execution.detail || ""),
        error: normalizeInlineText(execution.error || ""),
    };
}

export function isManualPluginExecutionActive(plugin) {
    return normalizeManualPluginExecution(plugin).active;
}

export function handleManualPluginExecutionTransitions(previousPlugins, nextPlugins, setStatus) {
    const previousPluginsByModule = new Map(
        (Array.isArray(previousPlugins) ? previousPlugins : []).map((plugin) => [plugin?.module || "", plugin])
    );
    for (const plugin of Array.isArray(nextPlugins) ? nextPlugins : []) {
        const moduleName = plugin?.module || "";
        if (!moduleName) {
            continue;
        }
        const previousPlugin = previousPluginsByModule.get(moduleName);
        const previousExecution = normalizeManualPluginExecution(previousPlugin);
        const nextExecution = normalizeManualPluginExecution(plugin);
        if (!previousExecution.active || nextExecution.active || !nextExecution.terminal) {
            continue;
        }
        const pluginName = normalizeInlineText(plugin?.name || moduleName) || "插件";
        if (nextExecution.status === "completed") {
            setStatus(
                nextExecution.detail ? `${pluginName} 执行完成：${nextExecution.detail}` : `${pluginName} 执行完成`,
                "good"
            );
            continue;
        }
        if (nextExecution.status === "stopped") {
            setStatus(nextExecution.detail || `${pluginName} 已停止`);
            continue;
        }
        if (nextExecution.status === "failed") {
            setStatus(nextExecution.detail || `${pluginName} 执行失败`, "bad");
        }
    }
}

export function getPluginByModule(plugins, moduleName) {
    return (Array.isArray(plugins) ? plugins : []).find((plugin) => plugin.module === moduleName) || null;
}

export function getPluginDisplayName(plugins, pluginLogs, moduleName, fallback = "未知插件") {
    const plugin = getPluginByModule(plugins, moduleName);
    if (plugin) {
        return plugin.name;
    }
    const pluginOption = pluginLogs?.available_plugins?.find((item) => item.module === moduleName);
    return normalizeInlineText(pluginOption?.name || moduleName || fallback) || fallback;
}

export function hasPluginLogData(dataValue) {
    return !(
        dataValue === undefined
        || dataValue === null
        || dataValue === ""
        || (Array.isArray(dataValue) && !dataValue.length)
        || (typeof dataValue === "object" && !Array.isArray(dataValue) && !Object.keys(dataValue).length)
    );
}

export function getPluginScopeTargets(plugin) {
    const rawTargets = Array.isArray(plugin?.scope_targets) ? plugin.scope_targets : [];
    return [...new Set(rawTargets.map((item) => normalizeInlineText(item).toLowerCase()).filter(Boolean))];
}

export function mergeOptionsWithCurrentValues(options, currentValues) {
    const nextOptions = Array.isArray(options) ? [...options] : [];
    const seen = new Set(nextOptions.map((option) => String(option?.value ?? "").trim()).filter(Boolean));
    const values = Array.isArray(currentValues)
        ? currentValues
        : (currentValues === undefined || currentValues === null || currentValues === "" ? [] : [currentValues]);
    for (const value of values) {
        const normalized = String(value ?? "").trim();
        if (!normalized || seen.has(normalized)) {
            continue;
        }
        seen.add(normalized);
        nextOptions.push({
            label: `当前配置(${normalized})`,
            value: normalized,
        });
    }
    return nextOptions;
}

export function needsPluginTargets(plugin) {
    const scopeTargets = getPluginScopeTargets(plugin);
    if (scopeTargets.includes("rooms") || scopeTargets.includes("friend_labels")) {
        return true;
    }
    const dynamicOptionSources = new Set(["room_options", "label_options", "wxpid_options"]);
    const schema = Array.isArray(plugin?.config_schema) ? plugin.config_schema : [];
    return schema.some((field) => {
        if (!field || typeof field !== "object") {
            return false;
        }
        if (dynamicOptionSources.has(field.options_source)) {
            return true;
        }
        return Array.isArray(field.columns)
            && field.columns.some((column) => column && typeof column === "object" && dynamicOptionSources.has(column.options_source));
    });
}

export function getPluginDynamicOptionPayloads(plugin) {
    return plugin?.dynamic_option_payloads && typeof plugin.dynamic_option_payloads === "object"
        ? plugin.dynamic_option_payloads
        : {};
}

export function findPluginDynamicModelField(plugin, fieldKey = "", parentFieldKey = "") {
    const normalizedFieldKey = normalizeInlineText(fieldKey).toLowerCase();
    const normalizedParentFieldKey = normalizeInlineText(parentFieldKey).toLowerCase();
    const schema = Array.isArray(plugin?.config_schema) ? plugin.config_schema : [];
    for (const field of schema) {
        if (!field || typeof field !== "object") {
            continue;
        }
        const normalizedFieldOptionsSource = normalizeInlineText(field.options_source).toLowerCase();
        const normalizedCurrentFieldKey = normalizeInlineText(field.key).toLowerCase();
        if (
            normalizedFieldOptionsSource === "model_options"
            && (!normalizedFieldKey || normalizedCurrentFieldKey === normalizedFieldKey)
            && (!normalizedParentFieldKey || normalizedCurrentFieldKey === normalizedParentFieldKey)
        ) {
            return field;
        }
        for (const column of Array.isArray(field.columns) ? field.columns : []) {
            if (!column || typeof column !== "object") {
                continue;
            }
            const normalizedColumnOptionsSource = normalizeInlineText(column.options_source).toLowerCase();
            const normalizedColumnKey = normalizeInlineText(column.key).toLowerCase();
            if (normalizedColumnOptionsSource !== "model_options") {
                continue;
            }
            if (normalizedFieldKey && normalizedColumnKey !== normalizedFieldKey) {
                continue;
            }
            if (normalizedParentFieldKey && normalizedCurrentFieldKey !== normalizedParentFieldKey) {
                continue;
            }
            return {
                ...column,
                __parent_field_key: field.key,
            };
        }
    }
    return null;
}

export function isMessageSummaryPlugin(plugin) {
    return Boolean(plugin?.message_summary);
}

export function isDirectExecutePlugin(plugin) {
    return Boolean(plugin?.direct_execute);
}

export function getRoomMsgSummaryLookbackSeconds(rangeKey) {
    const rangeMap = {
        "2h": 2 * 60 * 60,
        "6h": 6 * 60 * 60,
        "12h": 12 * 60 * 60,
        "1d": 24 * 60 * 60,
        "3d": 3 * 24 * 60 * 60,
        "1y": 365 * 24 * 60 * 60,
    };
    return rangeMap[normalizeInlineText(rangeKey).toLowerCase()] || rangeMap["2h"];
}

export function parseStructuredFieldValue(rawValue) {
    const normalized = normalizeInlineText(rawValue);
    if (!normalized) {
        return "";
    }
    try {
        return JSON.parse(normalized);
    } catch {
        return normalized;
    }
}

export function formatLocalDateTime(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
        return "";
    }
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
}

export function buildRoomMsgSummaryTimeWindow(rangeKey) {
    const endDate = new Date();
    const startDate = new Date(endDate.getTime() - getRoomMsgSummaryLookbackSeconds(rangeKey) * 1000);
    return {
        startTime: formatLocalDateTime(startDate),
        endTime: formatLocalDateTime(endDate),
    };
}

export function normalizeRoomMsgSummaryRenderConfig(plugin) {
    const nextConfig = { ...(plugin?.config || {}) };
    const exportDirField = Array.isArray(plugin?.config_schema)
        ? plugin.config_schema.find((field) => field?.key === "export_dir")
        : null;
    const normalizedFileType = normalizeInlineText(nextConfig.file_type || nextConfig.output_format).toLowerCase();
    if (!normalizedFileType || normalizedFileType === "txt") {
        nextConfig.file_type = "jsonl";
    }
    if (!normalizeInlineText(nextConfig.export_dir) && !normalizeInlineText(nextConfig.save_path) && normalizeInlineText(exportDirField?.default)) {
        nextConfig.export_dir = String(exportDirField.default);
    }
    const currentTimeRange = normalizeInlineText(nextConfig.time_range).toLowerCase() || "2h";
    const { startTime, endTime } = buildRoomMsgSummaryTimeWindow(currentTimeRange);
    if (!normalizeInlineText(nextConfig.start_time)) {
        nextConfig.start_time = startTime;
    }
    if (!normalizeInlineText(nextConfig.end_time)) {
        nextConfig.end_time = endTime;
    }
    return nextConfig;
}

export function sortPluginsForDisplay(plugins) {
    return [...plugins].sort((left, right) => {
        const enabledDiff = Number(Boolean(right?.enabled)) - Number(Boolean(left?.enabled));
        if (enabledDiff !== 0) {
            return enabledDiff;
        }
        const loadedDiff = Number(Boolean(right?.loaded)) - Number(Boolean(left?.loaded));
        if (loadedDiff !== 0) {
            return loadedDiff;
        }
        const leftLabel = normalizeInlineText(left?.name || left?.module || "");
        const rightLabel = normalizeInlineText(right?.name || right?.module || "");
        return leftLabel.localeCompare(rightLabel, "zh-CN");
    });
}
