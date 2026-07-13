/** Smoke: panel partials can be dynamically imported and injected. */

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
`;

const {
    ensurePanelLoaded,
    ensureShellFragments,
    isPanelLoaded,
    PANEL_NAMES,
    resetPanelLoaderState,
} = await import("../../static/js/panel-loader.js");
const { queryAppElements, refreshAppElements } = await import("../../static/js/app-state.js");

resetPanelLoaderState();
const elements = queryAppElements();

if (!PANEL_NAMES.includes("messages") || !PANEL_NAMES.includes("dashboard")) {
    throw new Error("PANEL_NAMES should include core tabs");
}

await ensureShellFragments(elements, "dashboard");
if (!isPanelLoaded("dashboard")) {
    throw new Error("dashboard panel should load during shell bootstrap");
}
if (!document.getElementById("overviewGrid")) {
    throw new Error("dashboard fragment should inject overviewGrid");
}
if (!document.getElementById("pluginConfigModal")) {
    throw new Error("shared modals should load during shell bootstrap");
}

const firstMessages = await ensurePanelLoaded("messages", elements);
const secondMessages = await ensurePanelLoaded("messages", elements);
if (!firstMessages || secondMessages) {
    throw new Error("messages panel should load once");
}
if (!document.getElementById("messageList") || !elements.messageList) {
    throw new Error("messages fragment should refresh element refs");
}

refreshAppElements(elements);
if (elements.panels.length < 2) {
    throw new Error("panels list should include loaded tab panels");
}

const { shouldLoadActiveTabOnBootstrap } = await import("../../static/js/app-runtime.js");
if (shouldLoadActiveTabOnBootstrap("dashboard") || !shouldLoadActiveTabOnBootstrap("logs")) {
    throw new Error("bootstrap tab gate should remain correct");
}

console.log("panel-loader ok");
