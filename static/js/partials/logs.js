/** Auto-extracted panel/modal fragment: logs */

export const html = `                <section class="panel-shell shell-card tab-panel" data-panel="logs">
                    <div class="panel-toolbar">
                        <div class="panel-actions log-actions">
                            <select id="logFileSelect"></select>
                            <button class="button secondary" id="refreshLogsButton" type="button">刷新日志</button>
                        </div>
                    </div>
                    <div class="log-filter-bar">
                        <label class="log-filter-group">
                            <span class="field-label">时间范围</span>
                            <select id="logTimeRange">
                                <option value="1h">最近一小时</option>
                                <option value="6h">最近6小时</option>
                                <option value="1d">最近一天</option>
                                <option value="all" selected>全部</option>
                            </select>
                        </label>
                        <label class="log-filter-group">
                            <span class="field-label">日志级别</span>
                            <select id="logLevelFilter">
                                <option value="">全部级别</option>
                                <option value="DEBUG">DEBUG</option>
                                <option value="INFO">INFO</option>
                                <option value="WARNING">WARNING</option>
                                <option value="ERROR">ERROR</option>
                                <option value="CRITICAL">CRITICAL</option>
                            </select>
                        </label>
                        <label class="log-filter-group">
                            <span class="field-label">模块或函数</span>
                            <input id="logModuleFilter" type="text" placeholder="例如 api.runtime 或 main">
                        </label>
                        <label class="log-filter-group">
                            <span class="field-label">日志关键词</span>
                            <input id="logKeywordFilter" type="text" placeholder="输入关键词筛选日志内容">
                        </label>
                    </div>
                    <div class="log-meta" id="logMeta"></div>
                    <div class="log-viewer" id="logViewer"></div>
                </section>\n`;
