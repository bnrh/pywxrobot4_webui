/** 插件卡片列表渲染。 */

import { escapeHtml } from "./dom-utils.js";
import { normalizeManualPluginExecution } from "./plugin-helpers.js";

export function renderPluginCards(targetElement, plugins, emptyText, pluginKind) {
    if (!targetElement) {
        return;
    }

    if (!plugins.length) {
        targetElement.innerHTML = `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
        return;
    }

    targetElement.innerHTML = plugins.map((plugin) => {
        const configKeys = Object.keys(plugin.config || {});
        const configSummary = configKeys.length ? `当前已配置 ${configKeys.length} 项自定义参数。` : "当前未配置自定义参数。";
        const isFeaturePlugin = pluginKind === "feature";
        const isManualExecutePlugin = isFeaturePlugin && !plugin?.capabilities?.tick_hook;
        const manualExecution = normalizeManualPluginExecution(plugin);
        const primaryButton = isManualExecutePlugin
            ? `<button class="button ${manualExecution.active ? "secondary" : "primary"}" type="button" data-action="${manualExecution.active ? "stop-plugin-execution" : "execute-plugin"}" data-plugin="${escapeHtml(plugin.module)}">${manualExecution.active ? "停止插件" : "执行插件"}</button>`
            : `<button class="button ${plugin.enabled ? "secondary" : "primary"}" type="button" data-action="toggle-plugin" data-plugin="${escapeHtml(plugin.module)}" data-enabled="${plugin.enabled ? "0" : "1"}">${plugin.enabled ? "停止插件" : "启动插件"}</button>`;
        return `
            <article class="plugin-card">
                <div class="plugin-head">
                    <div>
                        <h4 class="plugin-name">${escapeHtml(plugin.name)}</h4>
                        <div class="plugin-module">${escapeHtml(plugin.module)}</div>
                    </div>
                    <div class="badge-row">
                        <span class="badge ${plugin.enabled ? "good" : ""}">${plugin.enabled ? "已启用" : "未启用"}</span>
                        <span class="badge ${plugin.loaded ? "good" : plugin.loadable ? "" : "bad"}">${plugin.loaded ? "已加载" : plugin.loadable ? "可加载" : "加载失败"}</span>
                    </div>
                </div>
                <p class="plugin-copy">${escapeHtml(plugin.description || "该插件未提供额外说明。")}</p>
                ${plugin.error ? `<div class="settings-alert is-visible bad">${escapeHtml(plugin.error)}</div>` : ""}
                <div class="detail-meta">${escapeHtml(configSummary)}</div>
                <div class="field-actions">
                    ${primaryButton}
                    <button class="button ghost" type="button" data-action="open-plugin-config" data-plugin="${escapeHtml(plugin.module)}">修改配置</button>
                </div>
            </article>
        `;
    }).join("");
}
