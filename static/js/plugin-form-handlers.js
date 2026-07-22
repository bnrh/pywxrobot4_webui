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
import { bindOnce } from "./dom-bind.js";
import { openFolderPickerDialog } from "./folder-picker.js";

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

export async function handleProjectFolderPick(button, formElement, actions) {
    const targetInput = button.closest(".config-file-picker")?.querySelector("input[data-column-key], input[data-config-key]");
    if (!(targetInput instanceof HTMLInputElement)) {
        return false;
    }

    const initialPath = String(targetInput.value || "").trim();
    const selectedPath = await openFolderPickerDialog({
        title: "选择文件夹",
        initialPath: initialPath || undefined,
    });

    if (selectedPath) {
        targetInput.value = selectedPath;
        targetInput.dispatchEvent(new Event("input", { bubbles: true }));
        targetInput.dispatchEvent(new Event("change", { bubbles: true }));
        actions.setStatus(`已选择文件夹：${selectedPath}`, "good");
    }
    return true;
}

export function registerPluginFormEventHandlers(actions) {
    const { elements } = actions;
    const formElements = [elements.pluginConfigForm, elements.pluginExecuteForm].filter(Boolean);

    formElements.forEach((formElement, index) => {
        bindOnce(formElement, `pluginForm.click.${index}`, "click", async (event) => {
            const pickFileButton = event.target.closest("[data-config-pick-project-file]");
            if (pickFileButton) {
                event.preventDefault();
                await handleProjectFilePick(pickFileButton, formElement, actions);
                return;
            }
            const pickFolderButton = event.target.closest("[data-config-pick-project-folder]");
            if (pickFolderButton) {
                event.preventDefault();
                await handleProjectFolderPick(pickFolderButton, formElement, actions);
                return;
            }
            const textareaPickerButton = event.target.closest("[data-textarea-picker]");
            if (textareaPickerButton) {
                event.preventDefault();
                await handleTextareaPicker(textareaPickerButton, formElement, actions);
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

        bindOnce(formElement, `pluginForm.focusin.${index}`, "focusin", (event) => {
            const searchableInput = event.target.closest("[data-config-searchable-input]");
            if (searchableInput) {
                applySearchableSelectFilter(searchableInput);
            }
        });

        ["input", "change", "search", "keyup", "compositionend"].forEach((eventName) => {
            bindOnce(formElement, `pluginForm.${eventName}.${index}`, eventName, (event) => {
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

async function handleTextareaPicker(button, formElement, actions) {
    const container = button.closest(".textarea-with-pickers");
    const textarea = container?.querySelector("textarea[data-column-key], textarea[data-config-key]");
    if (!(textarea instanceof HTMLTextAreaElement)) {
        return;
    }

    const pickerType = button.getAttribute("data-textarea-picker") || "";
    const accept = button.getAttribute("data-picker-accept") || "";
    const uploadDir = button.getAttribute("data-picker-upload-dir") || "";

    const state = actions.getState();
    const moduleName = formElement === actions.elements.pluginConfigForm
        ? state.pluginConfigModule
        : state.pluginExecuteModule;
    if (!moduleName) {
        actions.setStatus("当前未选中插件，无法上传文件", "bad");
        return;
    }

    if (pickerType === "project-image") {
        const result = await handleProjectImagePickInternal(formElement, actions, moduleName, { accept, uploadDir });
        if (result) {
            textarea.value = result;
            textarea.dispatchEvent(new Event("input", { bubbles: true }));
            textarea.dispatchEvent(new Event("change", { bubbles: true }));
            autoSelectReplyType(button, "image_fixed");
        }
    } else if (pickerType === "project-file") {
        const result = await handleProjectFilePickInternal(formElement, actions, moduleName, { accept });
        if (result) {
            textarea.value = result;
            textarea.dispatchEvent(new Event("input", { bubbles: true }));
            textarea.dispatchEvent(new Event("change", { bubbles: true }));
        }
    } else if (pickerType === "project-folder") {
        const currentValue = String(textarea.value || "").trim();
        const isFilePath = /\.[^/\\]+$/.test(currentValue);
        const selectedPath = await openFolderPickerDialog({
            title: "选择文件夹",
            initialPath: (currentValue && !isFilePath) ? currentValue : undefined,
        });
        if (selectedPath) {
            textarea.value = selectedPath;
            textarea.dispatchEvent(new Event("input", { bubbles: true }));
            textarea.dispatchEvent(new Event("change", { bubbles: true }));
            actions.setStatus(`已选择文件夹：${selectedPath}`, "good");
            autoSelectReplyType(button, "image_random");
        }
    }
}

/** 在 object-list 编辑行中，自动将 reply_type 切换为指定值。 */
function autoSelectReplyType(button, replyTypeValue) {
    const rowEditor = button.closest("[data-config-row-editor]");
    if (!rowEditor) {
        return;
    }
    const replyTypeSelect = rowEditor.querySelector('[data-column-key="reply_type"]');
    if (replyTypeSelect instanceof HTMLSelectElement) {
        // option 的 value 经 optionValueToAttribute 处理（JSON.stringify），需同样编码后匹配
        const targetValue = JSON.stringify(replyTypeValue);
        for (const option of replyTypeSelect.options) {
            if (option.value === targetValue) {
                replyTypeSelect.value = targetValue;
                replyTypeSelect.dispatchEvent(new Event("change", { bubbles: true }));
                return;
            }
        }
    }
}

async function handleProjectImagePickInternal(formElement, actions, moduleName, options = {}) {
    return new Promise((resolve) => {
        const pickerInput = document.createElement("input");
        pickerInput.type = "file";
        pickerInput.accept = options.accept || "image/*";
        pickerInput.multiple = false;
        pickerInput.hidden = true;
        document.body.appendChild(pickerInput);

        pickerInput.addEventListener(
            "change",
            async () => {
                const [file] = [...(pickerInput.files || [])];
                pickerInput.remove();
                if (!file) {
                    resolve(null);
                    return;
                }
                try {
                    const payload = await actions.api.uploadPluginAsset(moduleName, "", file, options.uploadDir);
                    const filePath = payload?.path || "";
                    if (filePath) {
                        actions.setStatus(`图片已上传：${filePath}`, "good");
                        resolve(filePath);
                    } else {
                        actions.setStatus("图片上传失败", "bad");
                        resolve(null);
                    }
                } catch (error) {
                    actions.setStatus(`上传失败：${error.message || error}`, "bad");
                    resolve(null);
                }
            },
            { once: true },
        );

        pickerInput.click();
    });
}

async function handleProjectFilePickInternal(formElement, actions, moduleName, options = {}) {
    return new Promise((resolve) => {
        const pickerInput = document.createElement("input");
        pickerInput.type = "file";
        pickerInput.accept = options.accept || "";
        pickerInput.multiple = false;
        pickerInput.hidden = true;
        document.body.appendChild(pickerInput);

        pickerInput.addEventListener(
            "change",
            async () => {
                const [file] = [...(pickerInput.files || [])];
                pickerInput.remove();
                if (!file) {
                    resolve(null);
                    return;
                }
                try {
                    const payload = await actions.api.uploadPluginAsset(moduleName, "", file, "uploads");
                    const filePath = payload?.path || "";
                    if (filePath) {
                        actions.setStatus(`文件已上传：${filePath}`, "good");
                        resolve(filePath);
                    } else {
                        actions.setStatus("文件上传失败", "bad");
                        resolve(null);
                    }
                } catch (error) {
                    actions.setStatus(`上传失败：${error.message || error}`, "bad");
                    resolve(null);
                }
            },
            { once: true },
        );

        pickerInput.click();
    });
}
