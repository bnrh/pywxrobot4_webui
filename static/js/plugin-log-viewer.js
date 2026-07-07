/** 插件日志列表与详情渲染。 */

import { escapeHtml, formatJson, normalizeInlineText } from "./dom-utils.js";
import { truncateText } from "./format-utils.js";
import { getLogTone } from "./status-tones.js";

export function renderPluginLogsView({
    elements,
    pluginLogs,
    selection,
    resolvePluginDisplayName,
    hasPluginLogData,
}) {
    if (!pluginLogs) {
        elements.pluginLogMeta.textContent = "尚未加载插件日志。";
        elements.pluginLogList.innerHTML = '<div class="empty-state">还没有插件日志。</div>';
        elements.pluginLogDetail.innerHTML = '<div class="empty-state">请选择左侧日志查看详情。</div>';
        return { selectedPluginLogId: selection.selectedPluginLogId };
    }

    const options = [{ module: "", name: "全部插件" }, ...(pluginLogs.available_plugins || [])];
    const levelOptions = ["", ...(pluginLogs.available_levels || [])];
    elements.pluginLogFilter.innerHTML = options.map((item) => `
        <option value="${escapeHtml(item.module || "")}" ${(item.module || "") === (selection.selectedPluginLogModule || "") ? "selected" : ""}>${escapeHtml(item.name)}</option>
    `).join("");
    elements.pluginLogLevelFilter.innerHTML = levelOptions.map((item) => `
        <option value="${escapeHtml(item || "")}" ${(item || "") === (selection.selectedPluginLogLevel || "") ? "selected" : ""}>${escapeHtml(item || "全部级别")}</option>
    `).join("");
    elements.pluginLogKeywordFilter.value = selection.selectedPluginLogKeyword || "";

    const activePluginName = selection.selectedPluginLogModule
        ? resolvePluginDisplayName(selection.selectedPluginLogModule, selection.selectedPluginLogModule)
        : "全部插件";
    const activeLevel = selection.selectedPluginLogLevel || "全部级别";
    const activeKeyword = selection.selectedPluginLogKeyword || "";
    elements.pluginLogMeta.textContent = `当前筛选：${activePluginName} / ${activeLevel}${activeKeyword ? ` / 关键词 ${activeKeyword}` : ""}，匹配 ${pluginLogs.filtered_total || 0} 条日志，共缓存 ${pluginLogs.total || 0} 条，最新时间 ${pluginLogs.updated_at || "未知"}`;

    if (!pluginLogs.logs?.length) {
        elements.pluginLogList.innerHTML = '<div class="empty-state">当前筛选条件下没有插件日志。</div>';
        elements.pluginLogDetail.innerHTML = '<div class="empty-state">当前筛选条件下没有可展示的日志详情。</div>';
        return { selectedPluginLogId: selection.selectedPluginLogId };
    }

    let selectedPluginLogId = selection.selectedPluginLogId;
    if (
        !selectedPluginLogId
        || !pluginLogs.logs.some((item) => item.internal_id === selectedPluginLogId)
    ) {
        selectedPluginLogId = pluginLogs.logs[0].internal_id;
    }

    elements.pluginLogList.innerHTML = pluginLogs.logs.map((item) => {
        const scope = normalizeInlineText(item.scope || "");
        const preview = truncateText(normalizeInlineText(item.message || "无日志内容"), 92);
        return `
            <button class="plugin-log-item ${item.internal_id === selectedPluginLogId ? "is-active" : ""}" data-plugin-log-id="${item.internal_id}" type="button">
                <div class="plugin-log-item-head">
                    <div class="plugin-log-primary">
                        <h4 class="plugin-log-title">${escapeHtml(resolvePluginDisplayName(item.module, item.plugin || item.module || "未知插件"))}</h4>
                        <div class="detail-meta plugin-log-subline">${escapeHtml(item.recorded_at || "未知时间")}${scope ? ` · ${escapeHtml(scope)}` : ""}${item.module ? ` · ${escapeHtml(item.module)}` : ""}</div>
                    </div>
                    <div class="badge-row">
                        <span class="badge ${getLogTone(item.level)}">${escapeHtml(item.level || "INFO")}</span>
                    </div>
                </div>
                <p class="plugin-log-preview">${escapeHtml(preview)}</p>
            </button>
        `;
    }).join("");

    const selected = pluginLogs.logs.find((item) => item.internal_id === selectedPluginLogId) || null;
    if (!selected) {
        elements.pluginLogDetail.innerHTML = '<div class="empty-state">请选择左侧日志查看详情。</div>';
        return { selectedPluginLogId };
    }

    const selectedScope = normalizeInlineText(selected.scope || "");
    const selectedData = selected.data;
    const hasSelectedData = hasPluginLogData(selectedData);
    elements.pluginLogDetail.innerHTML = `
        <div class="detail-head">
            <div>
                <h4 class="detail-title">${escapeHtml(resolvePluginDisplayName(selected.module, selected.plugin || selected.module || "未知插件"))}</h4>
            </div>
            <div class="badge-row">
                <span class="badge ${getLogTone(selected.level)}">${escapeHtml(selected.level || "INFO")}</span>
                ${selectedScope ? `<span class="badge">${escapeHtml(selectedScope)}</span>` : ""}
            </div>
        </div>
        <div class="detail-section">
            <h5 class="detail-section-title">日志信息</h5>
            <div class="detail-meta">记录时间：${escapeHtml(selected.recorded_at || "未知")}</div>
            <div class="detail-meta">插件模块：${escapeHtml(selected.module || "未知")}</div>
            <div class="detail-meta">插件名称：${escapeHtml(selected.plugin || resolvePluginDisplayName(selected.module))}</div>
            <div class="detail-meta">日志级别：${escapeHtml(selected.level || "INFO")}</div>
            <div class="detail-meta">日志作用域：${escapeHtml(selectedScope || "无")}</div>
        </div>
        <div class="detail-section">
            <h5 class="detail-section-title">日志消息</h5>
            <div class="detail-text">${escapeHtml(selected.message || "无日志内容")}</div>
        </div>
        <div class="detail-section">
            <h5 class="detail-section-title">结构化数据</h5>
            ${hasSelectedData ? `<pre class="code-block plugin-log-data">${escapeHtml(formatJson(selectedData))}</pre>` : '<div class="empty-state">这条日志没有附加结构化数据。</div>'}
        </div>
    `;

    return { selectedPluginLogId };
}
