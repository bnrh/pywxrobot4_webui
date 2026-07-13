/** Auto-extracted panel/modal fragment: settings */

export const html = `                <section class="panel-shell shell-card tab-panel" data-panel="settings">
                    <div class="panel-toolbar">
                        <div class="panel-actions">
                            <button class="button secondary" id="refreshSettingsButton" type="button">刷新设置</button>
                        </div>
                    </div>
                    <div class="settings-alert" id="settingsAlert"></div>
                    <form class="settings-form" id="settingsForm">
                        <label class="field-group">
                            <span class="field-label">监听地址 host</span>
                            <input name="host" type="text" required>
                        </label>
                        <label class="field-group">
                            <span class="field-label">监听端口 port</span>
                            <input name="port" type="number" min="1" max="65535" required>
                        </label>
                        <label class="field-group field-span-2">
                            <span class="field-label">消息回调路径 callback_path</span>
                            <input name="callback_path" type="text" required>
                        </label>
                        <label class="field-group field-span-2">
                            <span class="field-label">主服务地址 api_base_url</span>
                            <input name="api_base_url" type="url" required>
                        </label>
                        <label class="field-group">
                            <span class="field-label">请求超时 request_timeout</span>
                            <input name="request_timeout" type="number" min="0.1" step="0.1" required>
                        </label>
                        <label class="field-group">
                            <span class="field-label">Worker 数量 worker_count</span>
                            <input name="worker_count" type="number" min="1" max="32" required>
                        </label>
                        <label class="field-group">
                            <span class="field-label">队列长度 queue_size</span>
                            <input name="queue_size" type="number" min="1" max="100000" required>
                        </label>
                        <label class="field-group">
                            <span class="field-label">队列满等待 queue_enqueue_wait_seconds</span>
                            <input name="queue_enqueue_wait_seconds" type="number" min="0" max="30" step="0.1" required>
                        </label>
                        <label class="field-group">
                            <span class="field-label">心跳间隔 heartbeat_interval_seconds</span>
                            <input name="heartbeat_interval_seconds" type="number" min="0" max="3600" required>
                        </label>
                        <label class="field-group field-span-2">
                            <span class="field-label">Web API 访问令牌 api_token</span>
                            <input name="api_token" type="password" autocomplete="new-password" placeholder="留空表示不启用；已配置时输入新值可覆盖">
                        </label>
                        <label class="field-group field-span-2">
                            <span class="field-label">消息回调密钥 callback_secret</span>
                            <input name="callback_secret" type="password" autocomplete="new-password" placeholder="留空表示不校验；wxrobot_api 需在请求头携带 X-Callback-Secret">
                        </label>
                        <div class="field-actions field-span-2">
                            <button class="button primary" type="submit">保存系统设置</button>
                        </div>
                    </form>
                </section>\n`;
