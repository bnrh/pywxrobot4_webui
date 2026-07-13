/** Auto-extracted panel/modal fragment: plugin-logs */

export const html = `                <section class="panel-shell shell-card tab-panel" data-panel="plugin-logs">
                    <div class="panel-toolbar">
                        <div class="panel-actions log-actions">
                            <select id="pluginLogFilter"></select>
                            <select id="pluginLogLevelFilter"></select>
                            <input class="plugin-log-keyword-input" id="pluginLogKeywordFilter" type="search" placeholder="输入关键词筛选插件日志">
                            <button class="button secondary" id="refreshPluginLogsButton" type="button">刷新插件日志</button>
                        </div>
                    </div>
                    <div class="log-meta" id="pluginLogMeta"></div>
                    <div class="split-layout">
                        <div class="message-list plugin-log-list" id="pluginLogList"></div>
                        <div class="detail-card plugin-log-detail" id="pluginLogDetail"></div>
                    </div>
                </section>\n`;
