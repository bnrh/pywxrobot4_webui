/** 控制台 DOM 事件绑定入口：按领域注册。 */

import { registerAiAssistantEvents } from "./app-events-ai.js";
import { registerLogsEvents } from "./app-events-logs.js";
import { registerMessagesEvents } from "./app-events-messages.js";
import { registerPluginsEvents } from "./app-events-plugins.js";
import { registerSettingsEvents } from "./app-events-settings.js";
import { registerShellEvents } from "./app-events-shell.js";
import { registerUsersEvents } from "./app-events-users.js";
import { registerPluginFormEventHandlers } from "./plugin-form-handlers.js";

export function registerAppEvents(actions) {
    registerShellEvents(actions);
    registerMessagesEvents(actions);
    registerUsersEvents(actions);
    registerAiAssistantEvents(actions);
    registerPluginsEvents(actions);
    registerSettingsEvents(actions);
    registerLogsEvents(actions);
    // Modal 片段懒加载后才有配置/执行表单节点。
    registerPluginFormEventHandlers(actions);
}
