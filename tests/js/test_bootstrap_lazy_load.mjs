/** Smoke: bootstrap 仅加载概览 + 当前 Tab（仪表盘跳过二次加载）。 */

import { Window } from "happy-dom";

const window = new Window();
globalThis.window = window;
globalThis.document = window.document;
globalThis.Node = window.Node;
globalThis.HTMLElement = window.HTMLElement;
globalThis.DocumentFragment = window.DocumentFragment;

document.body.innerHTML = `
  <div id="panelGroup"></div>
  <div id="modalRoot"></div>
  <div id="statusPill"></div>
  <div id="activeTabLabel"></div>
  <div id="pageTitle"></div>
  <div id="pageDescription"></div>
  <button class="nav-tab" data-tab="dashboard"></button>
  <button class="nav-tab" data-tab="messages"></button>
  <button id="tabRefreshButton"></button>
  <button id="reloadConfigButton"></button>
`;

const { resetPanelLoaderState } = await import("../../static/js/panel-loader.js");
resetPanelLoaderState();

const { shouldLoadActiveTabOnBootstrap, bootstrapApp } = await import("../../static/js/app-runtime.js");
const { queryAppElements } = await import("../../static/js/app-state.js");

if (shouldLoadActiveTabOnBootstrap("dashboard")) {
    throw new Error("dashboard bootstrap should not reload the active tab");
}
if (!shouldLoadActiveTabOnBootstrap("messages")) {
    throw new Error("non-dashboard tabs should lazy-load on bootstrap");
}

const calls = [];
const elements = queryAppElements();
const actions = {
    elements,
    getState: () => ({ activeTab: "dashboard", messages: [] }),
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

await bootstrapApp(actions);

const names = calls.map((item) => item[0]);
if (!names.includes("loadOverview") || !names.includes("syncMessageTypeLabels")) {
    throw new Error("bootstrap should load overview and message type labels");
}
if (names.includes("refreshCurrentTab")) {
    throw new Error("dashboard bootstrap should not call refreshCurrentTab");
}
if (!document.getElementById("overviewGrid")) {
    throw new Error("bootstrap should inject the dashboard panel");
}

console.log("bootstrap lazy-load ok");
