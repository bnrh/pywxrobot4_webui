/** 控制台入口：组装上下文并注册事件 / 运行时。 */

import { createAppContext } from "./app-context.js";
import { bootstrapApp, startAppRuntime } from "./app-runtime.js";

const { appActions } = createAppContext();

startAppRuntime(appActions);
bootstrapApp(appActions);
