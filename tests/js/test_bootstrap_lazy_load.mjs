/** Smoke: bootstrap 仅加载概览 + 当前 Tab（仪表盘跳过二次加载）。 */

import { shouldLoadActiveTabOnBootstrap } from "../../static/js/app-runtime.js";

if (shouldLoadActiveTabOnBootstrap("dashboard")) {
    throw new Error("dashboard bootstrap should not reload the active tab");
}
if (!shouldLoadActiveTabOnBootstrap("messages")) {
    throw new Error("non-dashboard tabs should lazy-load on bootstrap");
}
if (!shouldLoadActiveTabOnBootstrap("settings")) {
    throw new Error("settings should lazy-load on bootstrap");
}
if (shouldLoadActiveTabOnBootstrap("") || shouldLoadActiveTabOnBootstrap(null)) {
    throw new Error("empty active tab should not trigger tab load");
}

const calls = [];
const actions = {
    getState: () => ({ activeTab: "dashboard" }),
    setStatus: (text) => {
        calls.push(["setStatus", text]);
    },
    updateHeaderForTab: (tab) => {
        calls.push(["updateHeaderForTab", tab]);
    },
    syncMessageTypeLabels: async () => {
        calls.push(["syncMessageTypeLabels"]);
    },
    loadOverview: async () => {
        calls.push(["loadOverview"]);
    },
    refreshCurrentTab: async () => {
        calls.push(["refreshCurrentTab"]);
    },
};

const { bootstrapApp } = await import("../../static/js/app-runtime.js");
await bootstrapApp(actions);

const names = calls.map((item) => item[0]);
if (!names.includes("loadOverview") || !names.includes("syncMessageTypeLabels")) {
    throw new Error("bootstrap should load overview and message type labels");
}
if (names.includes("refreshCurrentTab")) {
    throw new Error("dashboard bootstrap should not call refreshCurrentTab");
}
if (names.includes("loadMessages") || names.includes("loadPlugins")) {
    throw new Error("bootstrap should not eagerly load all tabs");
}

const messageCalls = [];
const messageActions = {
    getState: () => ({ activeTab: "messages" }),
    setStatus: () => {},
    updateHeaderForTab: () => {},
    syncMessageTypeLabels: async () => {},
    loadOverview: async () => {
        messageCalls.push("loadOverview");
    },
    refreshCurrentTab: async () => {
        messageCalls.push("refreshCurrentTab");
    },
};
await bootstrapApp(messageActions);
if (!messageCalls.includes("refreshCurrentTab")) {
    throw new Error("non-dashboard bootstrap should load the active tab");
}

console.log("bootstrap lazy-load ok");
