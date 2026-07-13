/** 服务日志事件绑定。 */

export function registerLogsEvents(actions) {
    const { elements } = actions;
    const state = () => actions.getState();

elements.logFileSelect.addEventListener("change", async () => {
    try {
        state().selectedLogFile = elements.logFileSelect.value;
        actions.setStatus("正在切换日志文件...");
        await actions.loadLogs(state().selectedLogFile);
        actions.setStatus("日志已切换", "good");
    } catch (error) {
        actions.setStatus(`日志读取失败：${error.message}`, "bad");
    }
});

elements.logTimeRange.addEventListener("change", async () => {
    try {
        await actions.applyLogFilters();
    } catch (error) {
        actions.setStatus(`日志筛选失败：${error.message}`, "bad");
    }
});

elements.logLevelFilter.addEventListener("change", async () => {
    try {
        await actions.applyLogFilters();
    } catch (error) {
        actions.setStatus(`日志筛选失败：${error.message}`, "bad");
    }
});

elements.logModuleFilter.addEventListener("input", () => actions.scheduleLogFilterRefresh());
elements.logKeywordFilter.addEventListener("input", () => actions.scheduleLogFilterRefresh());

elements.refreshLogsButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新日志...");
        await actions.loadLogs(state().selectedLogFile);
        actions.setStatus("日志已刷新", "good");
    } catch (error) {
        actions.setStatus(`日志刷新失败：${error.message}`, "bad");
    }
});
}
