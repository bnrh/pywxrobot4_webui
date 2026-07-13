/** 消息/功能插件与插件日志、配置弹窗事件绑定。 */

import {
    handleStructuredConfigAction,
    hasStructuredPluginConfig,
    readStructuredPluginConfig,
    validateStructuredPluginConfig,
} from "./plugin-config-form.js";
import { isDirectExecutePlugin } from "./plugin-helpers.js";
import { normalizeInlineText } from "./dom-utils.js";

export function registerPluginsEvents(actions) {
    const { elements } = actions;
    const state = () => actions.getState();

elements.refreshPluginsButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新消息插件...");
        await actions.loadPlugins();
        actions.setStatus("消息插件已刷新", "good");
    } catch (error) {
        actions.setStatus(`消息插件刷新失败：${error.message}`, "bad");
    }
});

elements.refreshFeaturePluginsButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新功能插件...");
        await actions.loadPlugins();
        actions.setStatus("功能插件已刷新", "good");
    } catch (error) {
        actions.setStatus(`功能插件刷新失败：${error.message}`, "bad");
    }
});

async function handlePluginGridAction(event) {
    const button = event.target.closest("button[data-action]");
    if (!button) {
        return;
    }

    const moduleName = button.dataset.plugin;
    if (button.dataset.action === "open-plugin-config") {
        await actions.openPluginConfigModal(moduleName);
        return;
    }

    button.disabled = true;
    try {
        if (button.dataset.action === "toggle-plugin") {
            actions.setStatus("正在切换插件状态...");
            const result = await actions.api.togglePlugin(moduleName, button.dataset.enabled === "1");
            actions.applyPluginMutationResult(result);
            const suffix = result.restart_required ? `，需要重启字段：${result.restart_required_fields.join(", ")}` : "";
            actions.setStatus(`插件状态已更新${suffix}`, result.restart_required ? "bad" : "good");
        } else if (button.dataset.action === "execute-plugin") {
            const plugin = actions.getPluginByModule(moduleName);
            if (plugin && isDirectExecutePlugin(plugin)) {
                actions.setStatus("正在执行功能插件...");
                await actions.executePluginWithConfig(moduleName, {});
            } else {
                actions.setStatus("正在准备执行范围...");
                if (plugin) {
                    await actions.loadPluginTargetsIfNeeded(plugin);
                }
                await actions.openPluginExecuteModal(moduleName);
            }
        } else if (button.dataset.action === "stop-plugin-execution") {
            actions.setStatus("正在停止功能插件...");
            const result = await actions.api.stopPluginExecution(moduleName);
            actions.applyPluginMutationResult(result);
            const detail = normalizeInlineText(result?.execution?.detail || "");
            actions.setStatus(detail || "正在停止插件...");
        }
    } catch (error) {
        actions.setStatus(`插件操作失败：${error.message}`, "bad");
    } finally {
        button.disabled = false;
    }
}

[elements.pluginGrid, elements.featurePluginGrid].forEach((grid) => {
    grid.addEventListener("click", (event) => {
        handlePluginGridAction(event).catch((error) => {
            actions.setStatus(`插件操作失败：${error.message}`, "bad");
        });
    });
});

elements.pluginLogList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-plugin-log-id]");
    if (!button) {
        return;
    }
    state().selectedPluginLogId = Number(button.dataset.pluginLogId);
    actions.renderPluginLogs();
});

elements.pluginLogFilter.addEventListener("change", async () => {
    try {
        state().selectedPluginLogModule = elements.pluginLogFilter.value;
        state().selectedPluginLogId = null;
        actions.setStatus("正在切换插件日志筛选...");
        await actions.loadPluginLogs(state().selectedPluginLogModule, state().selectedPluginLogLevel, state().selectedPluginLogKeyword);
        actions.setStatus("插件日志已更新", "good");
    } catch (error) {
        actions.setStatus(`插件日志筛选失败：${error.message}`, "bad");
    }
});

elements.pluginLogLevelFilter.addEventListener("change", async () => {
    try {
        state().selectedPluginLogLevel = elements.pluginLogLevelFilter.value;
        state().selectedPluginLogId = null;
        actions.setStatus("正在切换插件日志级别筛选...");
        await actions.loadPluginLogs(state().selectedPluginLogModule, state().selectedPluginLogLevel, state().selectedPluginLogKeyword);
        actions.setStatus("插件日志已更新", "good");
    } catch (error) {
        actions.setStatus(`插件日志级别筛选失败：${error.message}`, "bad");
    }
});

elements.pluginLogKeywordFilter.addEventListener("input", () => {
    state().selectedPluginLogKeyword = elements.pluginLogKeywordFilter.value.trim();
    state().selectedPluginLogId = null;
    actions.schedulePluginLogKeywordRefresh();
});

elements.pluginLogKeywordFilter.addEventListener("search", () => {
    state().selectedPluginLogKeyword = elements.pluginLogKeywordFilter.value.trim();
    state().selectedPluginLogId = null;
    actions.schedulePluginLogKeywordRefresh();
});

elements.refreshPluginLogsButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新插件日志...");
        await actions.loadPluginLogs(state().selectedPluginLogModule, state().selectedPluginLogLevel, state().selectedPluginLogKeyword);
        actions.setStatus("插件日志已刷新", "good");
    } catch (error) {
        actions.setStatus(`插件日志刷新失败：${error.message}`, "bad");
    }
});

elements.closePluginConfigButton.addEventListener("click", actions.closePluginConfigModal);
elements.cancelPluginConfigButton.addEventListener("click", actions.closePluginConfigModal);
elements.closePluginExecuteButton.addEventListener("click", actions.closePluginExecuteModal);
elements.cancelPluginExecuteButton.addEventListener("click", actions.closePluginExecuteModal);

elements.pluginConfigModal.addEventListener("click", (event) => {
    if (event.target === elements.pluginConfigModal) {
        actions.closePluginConfigModal();
    }
});

elements.pluginExecuteModal.addEventListener("click", (event) => {
    if (event.target === elements.pluginExecuteModal) {
        actions.closePluginExecuteModal();
    }
});

elements.pluginConfigForm.addEventListener("click", (event) => {
    if (!state().pluginConfigModule) {
        return;
    }
    const plugin = actions.getPluginByModule(state().pluginConfigModule);
    if (!plugin) {
        return;
    }
    const renderPlugin = actions.buildPluginConfigRenderModelForPlugin(plugin);
    if (handleStructuredConfigAction(elements.pluginConfigForm, renderPlugin, event)) {
        event.preventDefault();
    }
});

elements.savePluginConfigButton.addEventListener("click", async () => {
    if (!state().pluginConfigModule) {
        return;
    }

    elements.savePluginConfigButton.disabled = true;
    try {
        const plugin = actions.getPluginByModule(state().pluginConfigModule);
        if (!plugin) {
            throw new Error("未找到指定插件");
        }
        const renderPlugin = actions.buildPluginConfigRenderModelForPlugin(plugin);
        if (hasStructuredPluginConfig(renderPlugin)) {
            const validation = validateStructuredPluginConfig(elements.pluginConfigForm, renderPlugin);
            if (!validation.valid) {
                throw new Error(validation.message || "插件配置校验失败");
            }
        }
        const config = hasStructuredPluginConfig(renderPlugin)
            ? actions.buildStructuredPluginConfigPayload(elements.pluginConfigForm, renderPlugin)
            : (() => {
                const configText = elements.pluginConfigEditor.value.trim() || "{}";
                return configText ? JSON.parse(configText) : {};
            })();
        actions.setStatus("正在保存插件配置...");
        const result = await actions.api.savePluginConfig(state().pluginConfigModule, config);
        actions.applyPluginMutationResult(result);
        actions.closePluginConfigModal();
        const suffix = result.restart_required ? `，需要重启字段：${result.restart_required_fields.join(", ")}` : "";
        actions.setStatus(`插件配置已保存${suffix}`, result.restart_required ? "bad" : "good");
    } catch (error) {
        actions.setStatus(`插件配置保存失败：${error.message}`, "bad");
    } finally {
        elements.savePluginConfigButton.disabled = false;
    }
});

elements.executePluginButton.addEventListener("click", async () => {
    if (!state().pluginExecuteModule) {
        return;
    }

    elements.executePluginButton.disabled = true;
    try {
        const plugin = actions.getPluginByModule(state().pluginExecuteModule);
        if (!plugin) {
            throw new Error("未找到指定功能插件");
        }
        const renderPlugin = actions.buildPluginExecuteRenderModelForPlugin(plugin);
        const config = hasStructuredPluginConfig(renderPlugin)
            ? readStructuredPluginConfig(elements.pluginExecuteForm, renderPlugin)
            : {};
        actions.setStatus("正在执行功能插件...");
        await actions.executePluginWithConfig(state().pluginExecuteModule, config);
        actions.closePluginExecuteModal();
    } catch (error) {
        actions.setStatus(`执行插件失败：${error.message}`, "bad");
    } finally {
        elements.executePluginButton.disabled = false;
    }
});
}
