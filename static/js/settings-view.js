/** 系统设置页渲染。 */

export function readSettingsForm(elements) {
    const form = elements?.settingsForm;
    if (!form) {
        return {};
    }
    return {
        host: form.host.value.trim(),
        port: Number(form.port.value),
        callback_path: form.callback_path.value.trim(),
        api_base_url: form.api_base_url.value.trim(),
        request_timeout: Number(form.request_timeout.value),
        worker_count: Number(form.worker_count.value),
        queue_size: Number(form.queue_size.value),
        queue_enqueue_wait_seconds: Number(form.queue_enqueue_wait_seconds.value),
        heartbeat_interval_seconds: Number(form.heartbeat_interval_seconds.value),
        api_token: form.api_token.value.trim(),
        callback_secret: form.callback_secret.value.trim(),
    };
}

export function renderSettingsView(elements, settings, getStoredApiToken) {
    if (!settings) {
        return;
    }

    const form = elements?.settingsForm;
    // 设置页为懒加载；插件启停等操作可能带回 settings，但表单尚未挂载。
    if (!form) {
        return;
    }

    const configSettings = settings.config;
    const runtimeSettings = settings.runtime;

    for (const [key, value] of Object.entries(configSettings)) {
        const field = form.elements.namedItem(key);
        if (!field) {
            continue;
        }
        if (field.type === "checkbox") {
            field.checked = Boolean(value);
        } else {
            field.value = value;
        }
    }

    if (!elements.settingsAlert) {
        return;
    }

    if (settings.restart_required) {
        elements.settingsAlert.className = "settings-alert is-visible bad";
        elements.settingsAlert.textContent = `检测到需要重启的字段：${settings.restart_required_fields.join(", ")}。当前运行值仍为 ${runtimeSettings.host}:${runtimeSettings.port}。`;
    } else if (settings.api_auth_enabled && !getStoredApiToken()) {
        elements.settingsAlert.className = "settings-alert is-visible bad";
        elements.settingsAlert.textContent = "已启用 Web API 访问令牌，但当前浏览器尚未保存令牌。请填写 api_token 并保存系统设置。";
    } else {
        elements.settingsAlert.className = "settings-alert is-visible good";
        const authHints = [];
        if (settings.api_auth_enabled) {
            authHints.push("Web API 鉴权已启用");
        }
        if (settings.callback_auth_enabled) {
            authHints.push("消息回调密钥已启用");
        }
        const suffix = authHints.length ? ` ${authHints.join("，")}。` : "";
        elements.settingsAlert.textContent = `当前 SQLite 配置与运行时配置一致。保存后可热重载的字段会立即生效。${suffix}`;
    }
}
