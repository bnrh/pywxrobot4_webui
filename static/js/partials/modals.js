/** Auto-extracted panel/modal fragment: modals */

export const html = `    <div class="modal-backdrop" id="pluginConfigModal">
        <div class="modal-card shell-card">
            <div class="panel-head modal-head">
                <div>
                    <p class="panel-eyebrow">插件配置</p>
                    <h3 class="panel-title" id="pluginConfigModalTitle">修改插件配置</h3>
                </div>
                <div class="panel-actions">
                    <button class="button ghost" id="closePluginConfigButton" type="button">关闭</button>
                </div>
            </div>
            <div class="detail-meta" id="pluginConfigMeta">插件配置会保存到 SQLite，并在支持的范围内立即热重载。</div>
            <form class="settings-form plugin-config-form" id="pluginConfigForm" hidden></form>
            <textarea class="config-editor modal-editor" id="pluginConfigEditor" hidden></textarea>
            <div class="modal-actions">
                <button class="button secondary" id="cancelPluginConfigButton" type="button">取消</button>
                <button class="button primary" id="savePluginConfigButton" type="button">保存配置</button>
            </div>
        </div>
    </div>

    <div class="modal-backdrop" id="pluginExecuteModal">
        <div class="modal-card shell-card">
            <div class="panel-head modal-head">
                <div>
                    <p class="panel-eyebrow">执行插件</p>
                    <h3 class="panel-title" id="pluginExecuteModalTitle">选择执行范围</h3>
                </div>
                <div class="panel-actions">
                    <button class="button ghost" id="closePluginExecuteButton" type="button">关闭</button>
                </div>
            </div>
            <div class="detail-meta" id="pluginExecuteMeta">执行前选择这次运行要作用的范围，本次选择不会覆盖已保存配置。</div>
            <form class="settings-form plugin-config-form" id="pluginExecuteForm"></form>
            <div class="modal-actions">
                <button class="button secondary" id="cancelPluginExecuteButton" type="button">取消</button>
                <button class="button primary" id="executePluginButton" type="button">执行插件</button>
            </div>
        </div>
    </div>

    <div class="modal-backdrop" id="aiAssistantConfigModal">
        <div class="modal-card shell-card smart-assistant-modal-card">
            <div class="panel-head modal-head">
                <div>
                    <p class="panel-eyebrow">智能插件配置</p>
                    <h3 class="panel-title">智能插件配置</h3>
                </div>
                <div class="panel-actions">
                    <button class="button ghost compact" id="closeAiAssistantConfigButton" type="button">关闭</button>
                </div>
            </div>
            <div class="detail-meta">配置会保存在本地 SQLite，保存后会重新刷新模型列表。</div>
            <form class="settings-form plugin-config-form smart-assistant-form" id="aiAssistantSettingsForm" novalidate></form>
            <div class="modal-actions">
                <button class="button secondary" id="cancelAiAssistantConfigButton" type="button">取消</button>
                <button class="button primary" id="saveAiAssistantSettingsButton" type="submit" form="aiAssistantSettingsForm">保存配置</button>
            </div>
        </div>
    </div>

    <div class="modal-backdrop" id="aiAssistantToolsModal">
        <div class="modal-card shell-card smart-assistant-modal-card smart-assistant-tools-modal-card">
            <div class="panel-head modal-head">
                <div>
                    <p class="panel-eyebrow">MCP 工具</p>
                    <h3 class="panel-title">可用 MCP 工具</h3>
                </div>
                <div class="panel-actions">
                    <button class="button ghost compact" id="closeAiAssistantToolsButton" type="button">关闭</button>
                </div>
            </div>
            <div class="detail-meta" id="aiAssistantToolMeta">尚未加载</div>
            <div class="smart-assistant-modal-body">
                <div class="smart-tool-grid smart-tool-modal-grid" id="aiAssistantToolGrid"></div>
            </div>
            <div class="modal-actions">
                <button class="button secondary" id="dismissAiAssistantToolsButton" type="button">关闭</button>
            </div>
        </div>
    </div>

    <div class="modal-backdrop" id="aiAssistantConversationModal">
        <div class="modal-card shell-card smart-assistant-modal-card">
            <div class="panel-head modal-head">
                <div>
                    <p class="panel-eyebrow">历史对话</p>
                    <h3 class="panel-title">切换对话</h3>
                </div>
                <div class="panel-actions">
                    <button class="button ghost compact" id="closeAiAssistantConversationModalButton" type="button">关闭</button>
                </div>
            </div>
            <div class="detail-meta">历史对话会保存在 SQLite。选择任意一条即可切换回对应会话。</div>
            <div class="smart-assistant-modal-body">
                <div class="smart-conversation-list" id="aiAssistantConversationList"></div>
            </div>
            <div class="modal-actions">
                <button class="button secondary" id="dismissAiAssistantConversationModalButton" type="button">关闭</button>
            </div>
        </div>
    </div>\n`;
