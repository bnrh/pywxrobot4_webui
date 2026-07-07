/** 插件结构化配置表单交互（文件上传、模型选项、搜索选择器）。 */

import { applyFetchOptionsSelection, handlePluginFetchOptions, refreshPluginModelOptionsForm, shouldRefreshPluginModelOptions, syncRoomMsgSummaryTimeFields } from "./plugin-config-render.js";
import {
    applySearchableChoiceFilter,
    applySearchableSelectFilter,
    closeSearchableSelect,
    getSearchableSelectElements,
    handleSearchableSelectInput,
    selectSearchableSelectOption,
    syncScopeFieldVisibility,
} from "./config-search.js";

export async function handleProjectFilePick(button, formElement, actions) {
    const targetInput = button.closest(".config-file-picker")?.querySelector("input[data-column-key], input[data-config-key]");
    if (!(targetInput instanceof HTMLInputElement)) {
        return false;
    }

    const state = actions.getState();
    const moduleName = formElement === actions.elements.pluginConfigForm
        ? state.pluginConfigModule
        : state.pluginExecuteModule;
    if (!moduleName) {
        actions.setStatus("当前未选中插件，无法上传图片", "bad");
        return true;
    }

    const pickerInput = document.createElement("input");
    pickerInput.type = "file";
    pickerInput.accept = String(button.dataset.accept || "").trim();
    pickerInput.hidden = true;
    document.body.appendChild(pickerInput);

    const cleanup = () => {
        pickerInput.remove();
    };

    pickerInput.addEventListener(
        "change",
        async () => {
            const [selectedFile] = [...(pickerInput.files || [])];
            if (!selectedFile) {
                cleanup();
                return;
            }

            const originalText = button.textContent || "选择文件";
            button.disabled = true;
            button.textContent = "上传中...";
            try {
                const payload = await actions.api.uploadPluginAsset(
                    moduleName,
                    button.dataset.targetKey || targetInput.getAttribute("data-column-key") || targetInput.getAttribute("data-config-key") || "",
                    selectedFile,
                    String(button.dataset.uploadDir || "uploads").trim() || "uploads",
                );
                targetInput.value = String(payload.path || "");
                targetInput.dispatchEvent(new Event("input", { bubbles: true }));
                targetInput.dispatchEvent(new Event("change", { bubbles: true }));
                actions.setStatus(`图片已保存到 ${payload.path}`, "good");
            } catch (error) {
                actions.setStatus(`图片上传失败：${error.message}`, "bad");
            } finally {
                button.disabled = false;
                button.textContent = originalText;
                cleanup();
            }
        },
        { once: true },
    );

    pickerInput.click();
    return true;
}

export function registerPluginFormEventHandlers(actions) {
    const { elements } = actions;

    [elements.pluginConfigForm, elements.pluginExecuteForm].forEach((formElement) => {
        formElement.addEventListener("click", async (event) => {
            const pickFileButton = event.target.closest("[data-config-pick-project-file]");
            if (pickFileButton) {
                event.preventDefault();
                await handleProjectFilePick(pickFileButton, formElement, actions);
                return;
            }
            const fetchOptionsButton = event.target.closest("[data-config-fetch-options]");
            if (fetchOptionsButton) {
                event.preventDefault();
                await handlePluginFetchOptions(fetchOptionsButton, formElement, actions.pluginRenderCtx());
                return;
            }
            const optionButton = event.target.closest("[data-config-searchable-option]");
            if (optionButton) {
                event.preventDefault();
                selectSearchableSelectOption(optionButton);
                return;
            }
            const toggleButton = event.target.closest("[data-config-searchable-toggle]");
            if (toggleButton) {
                event.preventDefault();
                const container = toggleButton.closest("[data-config-searchable-select]");
                if (!container) {
                    return;
                }
                if (container.classList.contains("is-open")) {
                    closeSearchableSelect(container, true);
                    return;
                }
                const { input } = getSearchableSelectElements(container);
                if (input) {
                    input.focus();
                    applySearchableSelectFilter(input);
                }
                return;
            }
            const searchableInput = event.target.closest("[data-config-searchable-input]");
            if (searchableInput) {
                applySearchableSelectFilter(searchableInput);
            }
        });

        formElement.addEventListener("focusin", (event) => {
            const searchableInput = event.target.closest("[data-config-searchable-input]");
            if (searchableInput) {
                applySearchableSelectFilter(searchableInput);
            }
        });
    });

    [elements.pluginConfigForm, elements.pluginExecuteForm].forEach((formElement) => {
        ["input", "change", "search", "keyup", "compositionend"].forEach((eventName) => {
            formElement.addEventListener(eventName, (event) => {
                const target = event.target instanceof Element ? event.target : null;
                const editorRow = target?.closest("[data-config-row-editor]");
                if (editorRow) {
                    editorRow.classList.remove("is-invalid");
                    const errorElement = editorRow.querySelector("[data-config-row-error]");
                    if (errorElement) {
                        errorElement.textContent = "";
                        errorElement.hidden = true;
                    }
                }
                const input = target?.closest("[data-config-search-input]");
                if (input) {
                    applySearchableChoiceFilter(input);
                }
                const searchableSelectInput = target?.closest("[data-config-searchable-input]");
                if (searchableSelectInput) {
                    handleSearchableSelectInput(searchableSelectInput);
                }
                const showSelectedInput = target?.closest("[data-config-show-selected]");
                if (showSelectedInput) {
                    const fieldContainer = showSelectedInput.closest("[data-config-field]");
                    const searchInput = fieldContainer?.querySelector("[data-config-search-input]");
                    if (searchInput) {
                        applySearchableChoiceFilter(searchInput);
                    }
                }
                const fetchOptionsSelect = target?.closest?.("[data-config-fetch-options-select]");
                if (fetchOptionsSelect instanceof HTMLSelectElement && event.type === "change") {
                    applyFetchOptionsSelection(fetchOptionsSelect);
                }
                const fieldKey = target?.getAttribute?.("data-config-key") || target?.getAttribute?.("data-config-fetch-options-select") || "";
                if (fieldKey === "_scope_room_mode" || fieldKey === "_scope_friend_mode") {
                    syncScopeFieldVisibility(formElement);
                }
                if (fieldKey === "time_range") {
                    const renderCtx = actions.pluginRenderCtx();
                    syncRoomMsgSummaryTimeFields(formElement, renderCtx.getPluginModuleName, actions.getPluginByModule, { force: true });
                }
                if (event.type === "change") {
                    const renderCtx = actions.pluginRenderCtx();
                    const moduleName = renderCtx.getPluginModuleName(formElement);
                    const plugin = moduleName ? actions.getPluginByModule(moduleName) : null;
                    if (plugin && shouldRefreshPluginModelOptions(plugin, fieldKey)) {
                        void refreshPluginModelOptionsForm(formElement, renderCtx);
                    }
                }
            });
        });
    });
}
