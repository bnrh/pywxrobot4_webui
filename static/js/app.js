/** 控制台入口：组装上下文并注册事件 / 运行时。 */

import "../css/app.css";
import { createAppContext } from "./app-context.js";
import { registerAppEvents } from "./app-events.js";
import { bootstrapApp, startAppRuntime } from "./app-runtime.js";
import { registerPluginFormEventHandlers } from "./plugin-form-handlers.js";

const { appActions } = createAppContext();

registerAppEvents(appActions);
registerPluginFormEventHandlers(appActions);
startAppRuntime(appActions);
bootstrapApp(appActions);
