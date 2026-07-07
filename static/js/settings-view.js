/** 系统设置页渲染。 */

export function renderSettingsView(elements, settings, getStoredApiToken) {
    if (!settings) {
        return;
    }

    const configSettings = settings.config;
    const runtimeSettings = settings.runtime;
    const form = elements.settingsForm;

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
