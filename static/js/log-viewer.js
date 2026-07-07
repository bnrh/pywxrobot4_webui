/** 服务日志中心渲染。 */

import { escapeHtml, highlightText } from "./dom-utils.js";
import { formatStandardDateTime } from "./format-utils.js";
import { getLogLevelClass } from "./status-tones.js";

export function syncLogFiltersFromControls(elements) {
    return {
        timeRange: elements.logTimeRange.value,
        level: elements.logLevelFilter.value,
        moduleQuery: elements.logModuleFilter.value.trim(),
        keyword: elements.logKeywordFilter.value.trim(),
    };
}

export function createLogFilterActions(getState, actions) {
    function syncLogFiltersFromControlsLocal() {
        getState().logFilters = syncLogFiltersFromControls(actions.elements);
    }

    async function applyLogFilters(statusText = "正在应用日志筛选...") {
        syncLogFiltersFromControlsLocal();
        actions.setStatus(statusText);
        await actions.loadLogs(getState().selectedLogFile);
        const logs = getState().logs;
        if (Number(logs?.line_count || 0) > 0) {
            actions.setStatus(`日志筛选已更新，命中 ${logs.matched_line_count || 0} 行`, "good");
            return;
        }
        actions.setStatus("当前筛选条件下没有命中日志");
    }

    function scheduleLogFilterRefresh(getLogFilterTimerId, setLogFilterTimerId) {
        syncLogFiltersFromControlsLocal();
        if (getLogFilterTimerId() !== null) {
            window.clearTimeout(getLogFilterTimerId());
        }
        setLogFilterTimerId(window.setTimeout(() => {
            applyLogFilters().catch((error) => {
                actions.setStatus(`日志筛选失败：${error.message}`, "bad");
            });
        }, 250));
    }

    return {
        syncLogFiltersFromControls: syncLogFiltersFromControlsLocal,
        applyLogFilters,
        scheduleLogFilterRefresh,
    };
}

export function renderServiceLogs(elements, logs, logFilters) {
    if (!logs) {
        elements.logMeta.textContent = "尚未加载日志。";
        elements.logViewer.innerHTML = "";
        return;
    }

    elements.logTimeRange.value = logFilters.timeRange;
    elements.logLevelFilter.value = logFilters.level;
    elements.logModuleFilter.value = logFilters.moduleQuery;
    elements.logKeywordFilter.value = logFilters.keyword;
    elements.logFileSelect.innerHTML = (logs.files || []).map((fileName) => `
        <option value="${escapeHtml(fileName)}" ${fileName === logs.active_file ? "selected" : ""}>${escapeHtml(fileName)}</option>
    `).join("");

    const filters = logs.filters || {};
    const timeRangeLabels = {
        "1h": "最近一小时",
        "6h": "最近6小时",
        "1d": "最近一天",
        all: "全部",
    };
    const filterChips = [];
    if (filters.time_range && filters.time_range !== "all") {
        filterChips.push(`时间 ${timeRangeLabels[filters.time_range] || filters.time_range}`);
    }
    if (filters.level) {
        filterChips.push(`级别 ${filters.level}`);
    }
    if (filters.module_query) {
        filterChips.push(`模块/函数 ${filters.module_query}`);
    }
    if (filters.keyword) {
        filterChips.push(`关键词 ${filters.keyword}`);
    }

    elements.logMeta.innerHTML = `
        <div class="log-meta-row">
            <span class="log-meta-chip">文件 ${escapeHtml(logs.active_file || "无")}</span>
            <span class="log-meta-chip">总行数 ${escapeHtml(String(logs.total_line_count || 0))}</span>
            <span class="log-meta-chip">命中 ${escapeHtml(String(logs.matched_line_count || 0))}</span>
            <span class="log-meta-chip">展示 ${escapeHtml(String(logs.line_count || 0))}</span>
            <span class="log-meta-chip">可解析 ${escapeHtml(String(logs.parsed_line_count || 0))}</span>
        </div>
        <div class="log-meta-row">
            <span class="log-meta-chip is-muted">更新时间 ${escapeHtml(formatStandardDateTime(logs.updated_at) || logs.updated_at || "未知")}</span>
            ${filterChips.length ? filterChips.map((item) => `<span class="log-meta-chip is-filter">${escapeHtml(item)}</span>`).join("") : '<span class="log-meta-chip is-muted">未启用筛选</span>'}
        </div>
    `;

    const entries = Array.isArray(logs.entries)
        ? logs.entries
        : (logs.lines || []).map((raw, index) => ({
            line_number: index + 1,
            raw,
            parsed: false,
            timestamp: "",
            level: "RAW",
            module: "",
            function: "",
            source_line: null,
            message: raw,
        }));

    if (!entries.length) {
        elements.logViewer.innerHTML = '<div class="empty-state">当前筛选条件下没有日志输出。</div>';
        return;
    }

    const rawHighlightQueries = [filters.keyword, filters.module_query].filter(Boolean);
    elements.logViewer.innerHTML = entries.map((entry) => {
        const levelText = entry.parsed ? (entry.level || "INFO") : "RAW";
        const sourceText = entry.parsed
            ? `${entry.module || "unknown"}:${entry.function || "unknown"}`
            : "原始日志片段";
        const timeText = entry.timestamp || `文件行 ${entry.line_number}`;
        const lineText = entry.source_line ? `L${entry.source_line}` : `#${entry.line_number}`;
        const messageText = entry.parsed ? (entry.message || entry.raw || "") : (entry.raw || "");
        const showRawLine = Boolean(entry.parsed && rawHighlightQueries.length);
        return `
            <article class="log-entry ${entry.parsed ? "" : "is-raw"}">
                <div class="log-entry-head">
                    <div class="log-entry-main">
                        <span class="log-level-pill ${getLogLevelClass(levelText)}">${escapeHtml(levelText)}</span>
                        <span class="log-entry-source">${highlightText(sourceText, [filters.module_query])}</span>
                    </div>
                    <div class="log-entry-side">
                        <span class="log-entry-time">${escapeHtml(timeText)}</span>
                        <span class="log-entry-line">${escapeHtml(lineText)}</span>
                    </div>
                </div>
                <div class="log-entry-message">${highlightText(messageText, [filters.keyword])}</div>
                ${showRawLine ? `<div class="log-entry-raw">${highlightText(entry.raw || "", rawHighlightQueries)}</div>` : ""}
            </article>
        `;
    }).join("");
}
