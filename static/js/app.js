/** 控制台入口：组装上下文并注册事件 / 运行时。 */

import { createAppContext } from "/static/js/app-context.js?v=20260713-01";
import { registerAppEvents } from "/static/js/app-events.js?v=20260713-01";
import { bootstrapApp, startAppRuntime } from "/static/js/app-runtime.js?v=20260706-15";
import { registerPluginFormEventHandlers } from "/static/js/plugin-form-handlers.js?v=20260706-15";

const { appActions } = createAppContext();

registerAppEvents(appActions);
registerPluginFormEventHandlers(appActions);
startAppRuntime(appActions);
bootstrapApp(appActions);
