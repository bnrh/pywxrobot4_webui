/** 插件配置与执行 Modal 交互。 */

import { formatJson } from "./dom-utils.js";
import { hasStructuredPluginConfig } from "./plugin-config-form.js";
import {
    preparePluginConfigRenderModel,
    preparePluginExecuteRenderModel,
    renderStructuredPluginForm,
} from "./plugin-config-render.js";

export function createPluginModalActions(getState, deps) {
    async function openConfigModal(moduleName) {
        const state = getState();
        const plugin = deps.getPluginByModule(moduleName);
        if (!plugin) {
            deps.setStatus("未找到指定插件配置", "bad");
            return;
        }
        if (deps.needsPluginTargets(plugin)) {
            await deps.loadPluginTargets(true);
        }
        const renderPlugin = await preparePluginConfigRenderModel(plugin, state.pluginTargets, state.users, deps.api);
        state.pluginConfigModule = moduleName;
        deps.elements.pluginConfigModalTitle.textContent = `${plugin.name} 配置`;
        if (hasStructuredPluginConfig(renderPlugin)) {
            deps.elements.pluginConfigMeta.textContent = "插件配置会以结构化表单保存到 SQLite，并在支持的范围内立即热重载。";
            deps.elements.pluginConfigForm.hidden = false;
            deps.elements.pluginConfigEditor.hidden = true;
            renderStructuredPluginForm(deps.elements.pluginConfigForm, renderPlugin, deps.pluginRenderCtx());
        } else {
            deps.elements.pluginConfigMeta.textContent = "当前插件尚未提供结构化配置描述，暂时仍使用 JSON 编辑。";
            deps.elements.pluginConfigForm.hidden = true;
            deps.elements.pluginConfigForm.innerHTML = "";
            deps.elements.pluginConfigEditor.hidden = false;
            deps.elements.pluginConfigEditor.value = formatJson(plugin.config || {});
        }
        deps.elements.pluginConfigModal.classList.add("is-visible");
    }

    function closeConfigModal() {
        const state = getState();
        state.pluginConfigModule = "";
        deps.elements.pluginConfigForm.innerHTML = "";
        deps.elements.pluginConfigModal.classList.remove("is-visible");
    }

    function closeExecuteModal() {
        const state = getState();
        state.pluginExecuteModule = "";
        deps.elements.pluginExecuteForm.innerHTML = "";
        deps.elements.pluginExecuteModal.classList.remove("is-visible");
    }

    async function executeWithConfig(moduleName, config = {}) {
        const result = await deps.api.executePlugin(moduleName, config);
        deps.applyPluginMutationResult(result);
        const execution = deps.normalizeManualPluginExecution({ manual_execution: result?.execution || {} });
        const detail = execution.detail || deps.normalizeInlineText(result?.result?.detail || "");
        deps.setStatus(detail ? `插件已开始执行：${detail}` : "插件已开始执行", "good");
        return result;
    }

    async function openExecuteModal(moduleName) {
        const state = getState();
        const plugin = deps.getPluginByModule(moduleName);
        if (!plugin) {
            deps.setStatus("未找到指定功能插件", "bad");
            return;
        }
        if (deps.isDirectExecutePlugin(plugin)) {
            deps.setStatus("正在执行功能插件...");
            await executeWithConfig(moduleName, {});
            return;
        }
        if (deps.needsPluginTargets(plugin)) {
            await deps.loadPluginTargets(true);
        }
        const renderPlugin = await preparePluginExecuteRenderModel(plugin, state.pluginTargets, state.users, deps.api);
        if (!renderPlugin.config_schema.length) {
            deps.setStatus("正在执行功能插件...");
            await executeWithConfig(moduleName, {});
            return;
        }
        state.pluginExecuteModule = moduleName;
        deps.elements.pluginExecuteModalTitle.textContent = `${plugin.name} 执行范围`;
        deps.elements.pluginExecuteMeta.textContent = "执行前选择这次运行要作用的微信进程、群聊、好友标签或公众号。本次选择不会覆盖已保存配置。";
        renderStructuredPluginForm(deps.elements.pluginExecuteForm, renderPlugin, deps.pluginRenderCtx());
        deps.elements.pluginExecuteModal.classList.add("is-visible");
    }

    return {
        openConfigModal,
        closeConfigModal,
        openExecuteModal,
        closeExecuteModal,
        executeWithConfig,
    };
}
