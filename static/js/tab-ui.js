/** Tab 切换时的页眉与导航状态更新。 */

export function updateHeaderForTab(elements, tabMeta, tabName) {
    const meta = tabMeta[tabName];
    if (!meta || !elements) {
        return;
    }
    if (elements.activeTabLabel) {
        elements.activeTabLabel.textContent = meta.label;
    }
    if (elements.pageTitle) {
        elements.pageTitle.textContent = meta.title;
    }
    if (elements.pageDescription) {
        elements.pageDescription.textContent = meta.description;
    }

    (elements.navTabs || []).forEach((button) => {
        button.classList.toggle("is-active", button.dataset.tab === tabName);
    });

    (elements.panels || []).forEach((panel) => {
        panel.classList.toggle("is-active", panel.dataset.panel === tabName);
    });
}
