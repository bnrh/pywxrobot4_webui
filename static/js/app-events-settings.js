/** 系统设置事件绑定。 */

import { SECRET_SETTINGS_PLACEHOLDER } from "./api.js";

export function registerSettingsEvents(actions) {
    const { elements } = actions;
    const state = () => actions.getState();

elements.settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
        actions.setStatus("正在保存系统设置...");
        const formPayload = actions.readSettingsForm();
        const result = await actions.api.saveSettings(formPayload);
        if (formPayload.api_token && formPayload.api_token !== SECRET_SETTINGS_PLACEHOLDER) {
            actions.setStoredApiToken(formPayload.api_token);
        }
        actions.setOverviewData(result.overview);
        state().settings = result.settings;
        actions.renderOverview();
        actions.renderSettings();
        const suffix = result.restart_required ? `，需要重启字段：${result.restart_required_fields.join(", ")}` : "";
        actions.setStatus(`系统设置已保存${suffix}`, result.restart_required ? "bad" : "good");
    } catch (error) {
        actions.setStatus(`系统设置保存失败：${error.message}`, "bad");
    }
});

elements.refreshSettingsButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新系统设置...");
        await actions.loadSettings();
        actions.setStatus("系统设置已刷新", "good");
    } catch (error) {
        actions.setStatus(`系统设置刷新失败：${error.message}`, "bad");
    }
});
}
