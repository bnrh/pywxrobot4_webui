/** Auto-extracted panel/modal fragment: ai-assistant */

export const html = `                <section class="panel-shell shell-card tab-panel" data-panel="ai-assistant">
                    <div class="panel-toolbar">
                        <div class="panel-actions">
                            <button class="button secondary" id="refreshAiAssistantButton" type="button">刷新智能插件</button>
                            <button class="button secondary compact smart-toolbar-button" id="newAiAssistantConversationButton" type="button">新建对话</button>
                            <button class="button ghost compact smart-toolbar-button" id="openAiAssistantConversationSwitcherButton" type="button">切换对话</button>
                            <button class="button ghost" id="clearAiAssistantConversationButton" type="button">清空对话</button>
                        </div>
                    </div>
                    <div class="smart-assistant-page">
                        <div class="detail-card smart-chat-card">
                            <div class="smart-chat-toolbar">
                                <div class="smart-chat-toolbar-main">
                                    <label class="field-group smart-inline-field">
                                        <span class="field-label">AI 厂商</span>
                                        <select class="smart-toolbar-select smart-toolbar-select-provider" id="aiAssistantProviderSelect"></select>
                                    </label>
                                    <label class="field-group smart-inline-field">
                                        <span class="field-label">模型</span>
                                        <select class="smart-toolbar-select smart-toolbar-select-model" id="aiAssistantModelSelect"></select>
                                    </label>
                                    <label class="field-group smart-inline-field">
                                        <span class="field-label">提示词插件</span>
                                        <select class="smart-toolbar-select smart-toolbar-select-prompt" id="aiAssistantPromptPluginSelect"></select>
                                    </label>
                                </div>
                                <div class="panel-actions smart-chat-toolbar-actions">
                                    <button class="button secondary compact smart-toolbar-button" id="toggleAiAssistantConfigButton" type="button">配置</button>
                                    <button class="button ghost compact smart-toolbar-button" id="toggleAiAssistantToolsButton" type="button">工具列表</button>
                                </div>
                            </div>
                            <div class="settings-alert" id="aiAssistantAlert"></div>
                            <div class="badge-row" id="aiAssistantProviderBadgeRow"></div>
                            <div class="detail-meta" id="aiAssistantConversationMeta">智能插件会优先使用 pywxrobot4 工具完成查询、发送和群管理等操作。</div>
                            <div class="smart-chat-transcript" id="aiAssistantConversation"></div>
                            <form class="settings-form smart-chat-form" id="aiAssistantPromptForm">
                                <label class="field-group field-span-2">
                                    <span class="field-label">指令</span>
                                    <textarea class="config-editor smart-chat-input" id="aiAssistantPromptInput" placeholder="例如：查看当前登录的微信账号，并告诉我每个账号的 wxpid。"></textarea>
                                </label>
                                <div class="field-actions field-span-2">
                                    <button class="button primary" id="sendAiAssistantPromptButton" type="submit">发送给智能插件</button>
                                    <button class="button ghost compact smart-toolbar-button smart-stop-button" id="stopAiAssistantChatButton" type="button">停止对话</button>
                                </div>
                            </form>
                        </div>
                    </div>
                </section>\n`;
