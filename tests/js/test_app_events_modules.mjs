/** Smoke: app event modules and context assemble without syntax errors. */

await import("../../static/js/app-events.js");
await import("../../static/js/app-events-shell.js");
await import("../../static/js/app-events-messages.js");
await import("../../static/js/app-events-users.js");
await import("../../static/js/app-events-ai.js");
await import("../../static/js/app-events-plugins.js");
await import("../../static/js/app-events-settings.js");
await import("../../static/js/app-events-logs.js");
await import("../../static/js/app-state.js");

const { createAppState, queryAppElements } = await import("../../static/js/app-state.js");
const state = createAppState();
if (state.activeTab !== "dashboard") {
    throw new Error("createAppState should default activeTab to dashboard");
}
if (typeof queryAppElements !== "function") {
    throw new Error("queryAppElements should be exported");
}

const { registerAppEvents } = await import("../../static/js/app-events.js");
if (typeof registerAppEvents !== "function") {
    throw new Error("registerAppEvents should be a function");
}

console.log("app-events modularization ok");
