#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def transform_plugins() -> None:
    path = ROOT / "static" / "js" / "app-events-plugins.js"
    text = path.read_text(encoding="utf-8")
    if "dom-bind" not in text:
        text = text.replace(
            'from "./dom-utils.js";\n',
            'from "./dom-utils.js";\nimport { bindOnce } from "./dom-bind.js";\n',
        )
    text = text.replace(
        """[elements.pluginGrid, elements.featurePluginGrid].forEach((grid) => {
    grid.addEventListener("click", (event) => {
        handlePluginGridAction(event).catch((error) => {
            actions.setStatus(`插件操作失败：${error.message}`, "bad");
        });
    });
});""",
        """[elements.pluginGrid, elements.featurePluginGrid].forEach((grid, index) => {
    bindOnce(grid, `plugins.gridClick.${index}`, "click", (event) => {
        handlePluginGridAction(event).catch((error) => {
            actions.setStatus(`插件操作失败：${error.message}`, "bad");
        });
    });
});""",
    )
    replacements = [
        ('elements.pluginLogList.addEventListener("click",', 'bindOnce(elements.pluginLogList, "plugins.logList", "click",'),
        ('elements.pluginLogFilter.addEventListener("change",', 'bindOnce(elements.pluginLogFilter, "plugins.logFilter", "change",'),
        ('elements.pluginLogLevelFilter.addEventListener("change",', 'bindOnce(elements.pluginLogLevelFilter, "plugins.logLevel", "change",'),
        ('elements.pluginLogKeywordFilter.addEventListener("input",', 'bindOnce(elements.pluginLogKeywordFilter, "plugins.logKeywordInput", "input",'),
        ('elements.pluginLogKeywordFilter.addEventListener("search",', 'bindOnce(elements.pluginLogKeywordFilter, "plugins.logKeywordSearch", "search",'),
        ('elements.refreshPluginLogsButton.addEventListener("click",', 'bindOnce(elements.refreshPluginLogsButton, "plugins.refreshLogs", "click",'),
        ('elements.closePluginConfigButton.addEventListener("click", actions.closePluginConfigModal);',
         'bindOnce(elements.closePluginConfigButton, "plugins.closeConfig", "click", actions.closePluginConfigModal);'),
        ('elements.cancelPluginConfigButton.addEventListener("click", actions.closePluginConfigModal);',
         'bindOnce(elements.cancelPluginConfigButton, "plugins.cancelConfig", "click", actions.closePluginConfigModal);'),
        ('elements.closePluginExecuteButton.addEventListener("click", actions.closePluginExecuteModal);',
         'bindOnce(elements.closePluginExecuteButton, "plugins.closeExecute", "click", actions.closePluginExecuteModal);'),
        ('elements.cancelPluginExecuteButton.addEventListener("click", actions.closePluginExecuteModal);',
         'bindOnce(elements.cancelPluginExecuteButton, "plugins.cancelExecute", "click", actions.closePluginExecuteModal);'),
        ('elements.pluginConfigModal.addEventListener("click",', 'bindOnce(elements.pluginConfigModal, "plugins.configBackdrop", "click",'),
        ('elements.pluginExecuteModal.addEventListener("click",', 'bindOnce(elements.pluginExecuteModal, "plugins.executeBackdrop", "click",'),
        ('elements.pluginConfigForm.addEventListener("click",', 'bindOnce(elements.pluginConfigForm, "plugins.configFormClick", "click",'),
        ('elements.savePluginConfigButton.addEventListener("click",', 'bindOnce(elements.savePluginConfigButton, "plugins.saveConfig", "click",'),
        ('elements.executePluginButton.addEventListener("click",', 'bindOnce(elements.executePluginButton, "plugins.execute", "click",'),
        ('elements.refreshPluginsButton.addEventListener("click",', 'bindOnce(elements.refreshPluginsButton, "plugins.refreshPlugins", "click",'),
        ('elements.refreshFeaturePluginsButton.addEventListener("click",', 'bindOnce(elements.refreshFeaturePluginsButton, "plugins.refreshFeatures", "click",'),
    ]
    for old, new in replacements:
        if old not in text:
            raise SystemExit(f"missing pattern: {old[:60]}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8", newline="\n")
    print("plugins ok")


def transform_ai() -> None:
    path = ROOT / "static" / "js" / "app-events-ai.js"
    text = path.read_text(encoding="utf-8")
    if "dom-bind" not in text:
        text = '/** 智能插件事件绑定。 */\n\nimport { bindOnce } from "./dom-bind.js";\n\n' + text.split("\n", 2)[-1]
        # fix - the above is fragile. Better:
    text = Path(path).read_text(encoding="utf-8")
    if "from \"./dom-bind.js\"" not in text:
        text = text.replace(
            "/** 智能插件事件绑定。 */\n\nexport function registerAiAssistantEvents",
            "/** 智能插件事件绑定。 */\n\nimport { bindOnce } from \"./dom-bind.js\";\n\nexport function registerAiAssistantEvents",
        )
    pairs = [
        ('elements.aiAssistantSettingsForm.addEventListener("submit",', 'bindOnce(elements.aiAssistantSettingsForm, "ai.settingsSubmit", "submit",'),
        ('elements.aiAssistantSettingsForm.addEventListener("click",', 'bindOnce(elements.aiAssistantSettingsForm, "ai.settingsClick", "click",'),
        ('elements.aiAssistantSettingsForm.addEventListener("input",', 'bindOnce(elements.aiAssistantSettingsForm, "ai.settingsInput", "input",'),
        ('elements.aiAssistantSettingsForm.addEventListener("change",', 'bindOnce(elements.aiAssistantSettingsForm, "ai.settingsChange", "change",'),
        ('elements.refreshAiAssistantButton.addEventListener("click",', 'bindOnce(elements.refreshAiAssistantButton, "ai.refresh", "click",'),
        ('elements.newAiAssistantConversationButton?.addEventListener("click",', 'bindOnce(elements.newAiAssistantConversationButton, "ai.newConversation", "click",'),
        ('elements.openAiAssistantConversationSwitcherButton?.addEventListener("click",', 'bindOnce(elements.openAiAssistantConversationSwitcherButton, "ai.openSwitcher", "click",'),
        ('elements.clearAiAssistantConversationButton.addEventListener("click",', 'bindOnce(elements.clearAiAssistantConversationButton, "ai.clearConversation", "click",'),
        ('elements.stopAiAssistantChatButton?.addEventListener("click",', 'bindOnce(elements.stopAiAssistantChatButton, "ai.stopChat", "click",'),
        ('elements.aiAssistantProviderSelect?.addEventListener("change",', 'bindOnce(elements.aiAssistantProviderSelect, "ai.providerChange", "change",'),
        ('elements.aiAssistantModelSelect?.addEventListener("change",', 'bindOnce(elements.aiAssistantModelSelect, "ai.modelChange", "change",'),
        ('elements.aiAssistantPromptPluginSelect?.addEventListener("change",', 'bindOnce(elements.aiAssistantPromptPluginSelect, "ai.promptChange", "change",'),
        ('elements.toggleAiAssistantConfigButton?.addEventListener("click",', 'bindOnce(elements.toggleAiAssistantConfigButton, "ai.toggleConfig", "click",'),
        ('elements.toggleAiAssistantToolsButton?.addEventListener("click",', 'bindOnce(elements.toggleAiAssistantToolsButton, "ai.toggleTools", "click",'),
        ('elements.closeAiAssistantConfigButton?.addEventListener("click", actions.closeAiAssistantConfigModal);',
         'bindOnce(elements.closeAiAssistantConfigButton, "ai.closeConfig", "click", actions.closeAiAssistantConfigModal);'),
        ('elements.cancelAiAssistantConfigButton?.addEventListener("click", actions.closeAiAssistantConfigModal);',
         'bindOnce(elements.cancelAiAssistantConfigButton, "ai.cancelConfig", "click", actions.closeAiAssistantConfigModal);'),
        ('elements.closeAiAssistantToolsButton?.addEventListener("click", actions.closeAiAssistantToolsModal);',
         'bindOnce(elements.closeAiAssistantToolsButton, "ai.closeTools", "click", actions.closeAiAssistantToolsModal);'),
        ('elements.dismissAiAssistantToolsButton?.addEventListener("click", actions.closeAiAssistantToolsModal);',
         'bindOnce(elements.dismissAiAssistantToolsButton, "ai.dismissTools", "click", actions.closeAiAssistantToolsModal);'),
        ('elements.closeAiAssistantConversationModalButton?.addEventListener("click", actions.closeAiAssistantConversationModal);',
         'bindOnce(elements.closeAiAssistantConversationModalButton, "ai.closeConversationModal", "click", actions.closeAiAssistantConversationModal);'),
        ('elements.dismissAiAssistantConversationModalButton?.addEventListener("click", actions.closeAiAssistantConversationModal);',
         'bindOnce(elements.dismissAiAssistantConversationModalButton, "ai.dismissConversationModal", "click", actions.closeAiAssistantConversationModal);'),
        ('elements.aiAssistantConfigModal?.addEventListener("click",', 'bindOnce(elements.aiAssistantConfigModal, "ai.configBackdrop", "click",'),
        ('elements.aiAssistantToolsModal?.addEventListener("click",', 'bindOnce(elements.aiAssistantToolsModal, "ai.toolsBackdrop", "click",'),
        ('elements.aiAssistantConversationModal?.addEventListener("click",', 'bindOnce(elements.aiAssistantConversationModal, "ai.conversationBackdrop", "click",'),
        ('elements.aiAssistantConversationList?.addEventListener("click",', 'bindOnce(elements.aiAssistantConversationList, "ai.conversationList", "click",'),
        ('elements.aiAssistantPromptForm.addEventListener("submit",', 'bindOnce(elements.aiAssistantPromptForm, "ai.promptSubmit", "submit",'),
    ]
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"missing AI pattern: {old}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8", newline="\n")
    print("ai ok")


def transform_shell() -> None:
    path = ROOT / "static" / "js" / "app-events-shell.js"
    text = path.read_text(encoding="utf-8")
    if "dom-bind" not in text:
        text = text.replace(
            'import { closeSearchableSelect } from "./config-search.js";\n',
            'import { closeSearchableSelect } from "./config-search.js";\nimport { bindOnce } from "./dom-bind.js";\n',
        )
    text = text.replace(
        """elements.navTabs.forEach((button) => {
    button.addEventListener("click", () => actions.switchTab(button.dataset.tab));
});

elements.tabRefreshButton.addEventListener("click", async () => {""",
        """elements.navTabs.forEach((button) => {
    bindOnce(button, `shell.nav.${button.dataset.tab || ""}`, "click", () => {
        actions.switchTab(button.dataset.tab);
    });
});

bindOnce(elements.tabRefreshButton, "shell.refresh", "click", async () => {""",
    )
    text = text.replace(
        """});

elements.reloadConfigButton.addEventListener("click", async () => {""",
        """});

bindOnce(elements.reloadConfigButton, "shell.reload", "click", async () => {""",
    )
    # Escape handler should use optional chaining for modals
    text = text.replace(
        "if (elements.pluginExecuteModal.classList.contains(\"is-visible\"))",
        "if (elements.pluginExecuteModal?.classList.contains(\"is-visible\"))",
    )
    text = text.replace(
        "if (elements.pluginConfigModal.classList.contains(\"is-visible\"))",
        "if (elements.pluginConfigModal?.classList.contains(\"is-visible\"))",
    )
    # document-level listeners - bindOnce on document
    if 'bindOnce(document, "shell.escape"' not in text:
        text = text.replace(
            'document.addEventListener("keydown", (event) => {',
            'bindOnce(document, "shell.escape", "keydown", (event) => {',
        )
        text = text.replace(
            'document.addEventListener("click", (event) => {\n    document.querySelectorAll(".config-searchable-select.is-open")',
            'bindOnce(document, "shell.searchableOutside", "click", (event) => {\n    document.querySelectorAll(".config-searchable-select.is-open")',
        )
    path.write_text(text, encoding="utf-8", newline="\n")
    print("shell ok")


if __name__ == "__main__":
    transform_plugins()
    transform_ai()
    transform_shell()
