/** Shell：导航、刷新、全局 Escape / 搜索下拉关闭。 */

import { closeSearchableSelect } from "./config-search.js";

export function registerShellEvents(actions) {
    const { elements } = actions;

elements.navTabs.forEach((button) => {
    button.addEventListener("click", () => actions.switchTab(button.dataset.tab));
});

elements.tabRefreshButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新当前视图...");
        await actions.loadOverview();
        await actions.refreshCurrentTab();
        actions.setStatus("当前视图已刷新", "good");
    } catch (error) {
        actions.setStatus(`刷新失败：${error.message}`, "bad");
    }
});

elements.reloadConfigButton.addEventListener("click", async () => {
    try {
        await actions.reloadFromConfig();
    } catch (error) {
        actions.setStatus(`重载失败：${error.message}`, "bad");
    }
});


document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
        return;
    }
    const openSearchableSelect = document.querySelector(".config-searchable-select.is-open");
    if (openSearchableSelect) {
        closeSearchableSelect(openSearchableSelect, true);
        return;
    }
    if (elements.pluginExecuteModal.classList.contains("is-visible")) {
        actions.closePluginExecuteModal();
        return;
    }
    if (elements.aiAssistantConversationModal?.classList.contains("is-visible")) {
        actions.closeAiAssistantConversationModal();
        return;
    }
    if (elements.aiAssistantToolsModal?.classList.contains("is-visible")) {
        actions.closeAiAssistantToolsModal();
        return;
    }
    if (elements.aiAssistantConfigModal?.classList.contains("is-visible")) {
        actions.closeAiAssistantConfigModal();
        return;
    }
    if (elements.pluginConfigModal.classList.contains("is-visible")) {
        actions.closePluginConfigModal();
    }
});

document.addEventListener("click", (event) => {
    document.querySelectorAll(".config-searchable-select.is-open").forEach((container) => {
        if (container.contains(event.target)) {
            return;
        }
        closeSearchableSelect(container, true);
    });
});
}
