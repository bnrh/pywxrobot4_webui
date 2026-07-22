/** 本地目录选择对话框：调用后端 /api/folders/browse 浏览目录并选择完整路径。 */

import { api } from "./api.js";
import { escapeHtml } from "./dom-utils.js";

let activeBackdrop = null;
let resolveCurrentPicker = null;

function closeFolderPickerDialog(result = null) {
    if (resolveCurrentPicker) {
        const resolve = resolveCurrentPicker;
        resolveCurrentPicker = null;
        resolve(result);
    }
    if (activeBackdrop) {
        activeBackdrop.remove();
        activeBackdrop = null;
    }
    document.removeEventListener("keydown", handleEscapeKey);
}

function handleEscapeKey(event) {
    if (event.key === "Escape") {
        closeFolderPickerDialog(null);
    }
}

function renderDialogSkeleton(title = "选择文件夹") {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop is-visible folder-picker-backdrop";
    backdrop.innerHTML = `
        <div class="modal-card shell-card folder-picker-card">
            <div class="panel-head modal-head">
                <div>
                    <p class="panel-eyebrow">本地目录</p>
                    <h3 class="panel-title">${escapeHtml(title)}</h3>
                </div>
                <div class="panel-actions">
                    <button class="button ghost" type="button" data-folder-picker-close>关闭</button>
                </div>
            </div>
            <div class="folder-picker-toolbar">
                <button class="button secondary compact" type="button" data-folder-picker-up disabled>返回上级</button>
                <input class="folder-picker-path-input" type="text" placeholder="手动输入路径或点击下方目录进入" autocomplete="off">
                <button class="button secondary compact" type="button" data-folder-picker-go>进入</button>
            </div>
            <div class="folder-picker-current" data-folder-picker-current>正在读取目录...</div>
            <div class="folder-picker-list" data-folder-picker-list></div>
            <div class="modal-actions">
                <button class="button secondary" type="button" data-folder-picker-cancel>取消</button>
                <button class="button primary" type="button" data-folder-picker-confirm disabled>选择此目录</button>
            </div>
        </div>
    `;
    return backdrop;
}

function renderEntries(list, container) {
    if (!list.length) {
        container.innerHTML = `<div class="folder-picker-empty">当前目录下没有子文件夹</div>`;
        return;
    }
    container.innerHTML = list.map((entry) => `
        <button class="folder-picker-item" type="button" data-folder-path="${escapeHtml(entry.path)}">
            <span class="folder-picker-item-icon" aria-hidden="true">📁</span>
            <span class="folder-picker-item-name">${escapeHtml(entry.name)}</span>
        </button>
    `).join("");
}

export async function openFolderPickerDialog({ title = "选择文件夹", initialPath = "" } = {}) {
    if (activeBackdrop) {
        closeFolderPickerDialog(null);
    }

    const backdrop = renderDialogSkeleton(title);
    document.body.appendChild(backdrop);
    activeBackdrop = backdrop;
    document.addEventListener("keydown", handleEscapeKey);

    const listEl = backdrop.querySelector("[data-folder-picker-list]");
    const currentEl = backdrop.querySelector("[data-folder-picker-current]");
    const pathInput = backdrop.querySelector(".folder-picker-path-input");
    const upButton = backdrop.querySelector("[data-folder-picker-up]");
    const goButton = backdrop.querySelector("[data-folder-picker-go]");
    const confirmButton = backdrop.querySelector("[data-folder-picker-confirm]");

    let currentPath = "";

    async function loadDirectory(targetPath = "") {
        listEl.innerHTML = `<div class="folder-picker-empty">正在读取目录...</div>`;
        currentEl.textContent = "";
        confirmButton.disabled = true;
        try {
            const payload = await api.browseFolders(targetPath);
            currentPath = payload.current_path || "";
            pathInput.value = currentPath;
            currentEl.textContent = currentPath || "(空)";
            confirmButton.disabled = !currentPath;
            if (payload.parent_path) {
                upButton.disabled = false;
                upButton.dataset.path = payload.parent_path;
            } else {
                upButton.disabled = true;
                upButton.dataset.path = "";
            }
            renderEntries(payload.entries || [], listEl);
        } catch (error) {
            listEl.innerHTML = `<div class="folder-picker-empty is-error">读取目录失败：${escapeHtml(error.message || error)}</div>`;
            currentEl.textContent = "";
            confirmButton.disabled = true;
        }
    }

    backdrop.addEventListener("click", async (event) => {
        const target = event.target;
        if (target === backdrop) {
            closeFolderPickerDialog(null);
            return;
        }
        if (target.closest("[data-folder-picker-close], [data-folder-picker-cancel]")) {
            closeFolderPickerDialog(null);
            return;
        }
        if (target.closest("[data-folder-picker-up]")) {
            if (!upButton.disabled) {
                await loadDirectory(upButton.dataset.path || "");
            }
            return;
        }
        if (target.closest("[data-folder-picker-go]")) {
            const manualPath = String(pathInput.value || "").trim();
            if (manualPath) {
                await loadDirectory(manualPath);
            }
            return;
        }
        if (target.closest("[data-folder-picker-confirm]")) {
            if (currentPath) {
                closeFolderPickerDialog(currentPath);
            }
            return;
        }
        const item = target.closest("[data-folder-path]");
        if (item) {
            await loadDirectory(item.dataset.folderPath || "");
        }
    });

    pathInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            const manualPath = String(pathInput.value || "").trim();
            if (manualPath) {
                loadDirectory(manualPath);
            }
        }
    });

    await loadDirectory(initialPath);

    return new Promise((resolve) => {
        resolveCurrentPicker = resolve;
    });
}
