/** Tab / Modal HTML 片段动态加载。 */

import { refreshAppElements } from "./app-state.js";

const PANEL_LOADERS = {
    dashboard: () => import("./partials/dashboard.js"),
    messages: () => import("./partials/messages.js"),
    users: () => import("./partials/users.js"),
    features: () => import("./partials/features.js"),
    "ai-assistant": () => import("./partials/ai-assistant.js"),
    plugins: () => import("./partials/plugins.js"),
    "plugin-logs": () => import("./partials/plugin-logs.js"),
    settings: () => import("./partials/settings.js"),
    logs: () => import("./partials/logs.js"),
};

const loadedPanels = new Set();
const inflightPanels = new Map();
let modalsLoaded = false;
let modalsInflight = null;

function getPanelGroup() {
    return document.getElementById("panelGroup");
}

function getModalRoot() {
    return document.getElementById("modalRoot");
}

function injectHtml(container, html, { prepend = false } = {}) {
    if (!container) {
        throw new Error("缺少面板/弹窗挂载点");
    }
    const template = document.createElement("template");
    template.innerHTML = String(html || "").trim();
    const fragment = template.content;
    if (prepend && container.firstChild) {
        container.insertBefore(fragment, container.firstChild);
    } else {
        container.appendChild(fragment);
    }
}

export function isPanelLoaded(tabName) {
    return loadedPanels.has(String(tabName || ""));
}

export async function ensureModalsLoaded(elements) {
    if (modalsLoaded) {
        return false;
    }
    if (modalsInflight) {
        await modalsInflight;
        return false;
    }
    modalsInflight = (async () => {
        const mod = await import("./partials/modals.js");
        injectHtml(getModalRoot(), mod.html);
        refreshAppElements(elements);
        modalsLoaded = true;
    })();
    try {
        await modalsInflight;
        return true;
    } finally {
        modalsInflight = null;
    }
}

export async function ensurePanelLoaded(tabName, elements) {
    const name = String(tabName || "").trim();
    const loader = PANEL_LOADERS[name];
    if (!loader) {
        throw new Error(`未知 Tab 面板: ${name}`);
    }
    if (loadedPanels.has(name)) {
        return false;
    }
    if (inflightPanels.has(name)) {
        await inflightPanels.get(name);
        return false;
    }

    const task = (async () => {
        const mod = await loader();
        const existing = document.querySelector(`.tab-panel[data-panel="${name}"]`);
        if (!existing) {
            injectHtml(getPanelGroup(), mod.html);
        }
        loadedPanels.add(name);
        refreshAppElements(elements);
    })();
    inflightPanels.set(name, task);
    try {
        await task;
        return true;
    } finally {
        inflightPanels.delete(name);
    }
}

export async function ensureShellFragments(elements, activeTab = "dashboard") {
    await ensureModalsLoaded(elements);
    await ensurePanelLoaded(activeTab || "dashboard", elements);
}

/** 测试辅助：重置加载状态。 */
export function resetPanelLoaderState() {
    loadedPanels.clear();
    inflightPanels.clear();
    modalsLoaded = false;
    modalsInflight = null;
}

export const PANEL_NAMES = Object.keys(PANEL_LOADERS);
