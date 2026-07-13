/** 服务日志事件绑定。 */

import { bindOnce } from "./dom-bind.js";

export function registerLogsEvents(actions) {
    const { elements } = actions;
    const state = () => actions.getState();

    bindOnce(elements.logFileSelect, "logs.fileChange", "change", async () => {
        try {
            state().selectedLogFile = elements.logFileSelect.value;
            actions.setStatus("正在切换日志文件...");
            await actions.loadLogs(state().selectedLogFile);
            actions.setStatus("日志已切换", "good");
        } catch (error) {
            actions.setStatus(`日志读取失败：${error.message}`, "bad");
        }
    });

    bindOnce(elements.logTimeRange, "logs.timeRange", "change", async () => {
        try {
            await actions.applyLogFilters();
        } catch (error) {
            actions.setStatus(`日志筛选失败：${error.message}`, "bad");
        }
    });

    bindOnce(elements.logLevelFilter, "logs.level", "change", async () => {
        try {
            await actions.applyLogFilters();
        } catch (error) {
            actions.setStatus(`日志筛选失败：${error.message}`, "bad");
        }
    });

    bindOnce(elements.logModuleFilter, "logs.module", "input", () => actions.scheduleLogFilterRefresh());
    bindOnce(elements.logKeywordFilter, "logs.keyword", "input", () => actions.scheduleLogFilterRefresh());

    bindOnce(elements.refreshLogsButton, "logs.refresh", "click", async () => {
        try {
            actions.setStatus("正在刷新日志...");
            await actions.loadLogs(state().selectedLogFile);
            actions.setStatus("日志已刷新", "good");
        } catch (error) {
            actions.setStatus(`日志刷新失败：${error.message}`, "bad");
        }
    });
}
