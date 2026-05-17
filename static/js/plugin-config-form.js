import { api } from "/static/js/api.js?v=20260512-09";

const roomMemberPickerCache = new Map();
const roomMemberPickerPendingRequests = new Map();

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function deepClone(value) {
    if (value === undefined) {
        return undefined;
    }
    return JSON.parse(JSON.stringify(value));
}

function normalizeSchema(plugin) {
    return Array.isArray(plugin?.config_schema)
        ? plugin.config_schema.filter((field) => field && typeof field === "object" && field.key)
        : [];
}

function isMeaningfulValue(value) {
    if (value === undefined || value === null) {
        return false;
    }
    if (typeof value === "string") {
        return value.trim() !== "";
    }
    if (typeof value === "number") {
        return Number.isFinite(value);
    }
    if (typeof value === "boolean") {
        return value;
    }
    if (Array.isArray(value)) {
        return value.length > 0;
    }
    if (typeof value === "object") {
        return Object.keys(value).length > 0;
    }
    return true;
}

function getEmptyValue(field) {
    if (Object.prototype.hasOwnProperty.call(field, "default")) {
        return deepClone(field.default);
    }
    switch (field.type) {
        case "checkbox":
            return false;
        case "number":
            return undefined;
        case "string-list":
        case "multi-checkbox":
        case "object-list":
            return [];
        case "key-value-list":
        case "key-multi-value-list":
        case "grouped-object-list":
            return {};
        default:
            return "";
    }
}

function getFieldValue(field, config) {
    if (config && Object.prototype.hasOwnProperty.call(config, field.key)) {
        return deepClone(config[field.key]);
    }
    for (const alias of Array.isArray(field.aliases) ? field.aliases : []) {
        if (config && Object.prototype.hasOwnProperty.call(config, alias)) {
            return deepClone(config[alias]);
        }
    }
    return getEmptyValue(field);
}

function optionValueToAttribute(value) {
    return escapeHtml(JSON.stringify(value));
}

function parseOptionValue(value) {
    if (value === undefined || value === null || value === "") {
        return "";
    }
    try {
        return JSON.parse(value);
    } catch {
        return value;
    }
}

function normalizeSearchText(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

function getFieldOptionItems(field) {
    return Array.isArray(field.options) ? field.options : [];
}

function getFieldOptionDescriptor(option) {
    const optionValue = Object.prototype.hasOwnProperty.call(option, "value") ? option.value : option;
    const optionLabel = Object.prototype.hasOwnProperty.call(option, "label") ? option.label : String(optionValue);
    const optionSearchText = Object.prototype.hasOwnProperty.call(option, "search_text") ? option.search_text : optionLabel;
    return {
        value: optionValue,
        label: String(optionLabel ?? ""),
        searchText: String(optionSearchText ?? ""),
    };
}

function findFieldOptionByValue(field, value) {
    const normalizedValue = JSON.stringify(value);
    for (const option of getFieldOptionItems(field)) {
        const descriptor = getFieldOptionDescriptor(option);
        if (JSON.stringify(descriptor.value) === normalizedValue) {
            return descriptor;
        }
    }
    return null;
}

function findFieldOptionItemByValue(field, value) {
    const normalizedValue = JSON.stringify(value);
    for (const option of getFieldOptionItems(field)) {
        const descriptor = getFieldOptionDescriptor(option);
        if (JSON.stringify(descriptor.value) === normalizedValue) {
            return option;
        }
    }
    return null;
}

function findSearchableSelectOption(field, rawValue) {
    const normalizedValue = normalizeSearchText(rawValue);
    if (!normalizedValue) {
        return null;
    }
    for (const option of getFieldOptionItems(field)) {
        const descriptor = getFieldOptionDescriptor(option);
        const candidates = [descriptor.label, descriptor.searchText, String(descriptor.value ?? "")]
            .map((item) => normalizeSearchText(item))
            .filter(Boolean);
        if (candidates.includes(normalizedValue)) {
            return descriptor;
        }
    }
    return null;
}

function renderHint(field) {
    const text = String(field.description || field.help || "").trim();
    return text ? `<div class="field-hint">${escapeHtml(text)}</div>` : "";
}

function renderSearchableSelectInput(field, value, datasetKey = "data-config-key") {
    const currentValue = value ?? "";
    const currentOption = findFieldOptionByValue(field, currentValue) || findSearchableSelectOption(field, currentValue);
    const displayValue = currentValue === "" || currentValue === null || currentValue === undefined
        ? ""
        : (currentOption?.label || String(currentValue ?? "").trim());
    const encodedValue = currentValue === "" || currentValue === null || currentValue === undefined
        ? ""
        : optionValueToAttribute(currentOption ? currentOption.value : currentValue);
    const placeholder = String(field.search_placeholder || field.placeholder || "").trim();
    const emptyText = String(field.empty_text || "没有匹配的可选项。")
        .trim();
    const selectedValue = currentOption ? JSON.stringify(currentOption.value) : null;
    const options = getFieldOptionItems(field);

    return `
        <div class="config-searchable-select" data-config-searchable-select>
            <div class="config-searchable-select-shell">
                <input
                    class="config-search-input config-searchable-select-input"
                    type="search"
                    data-config-searchable-input="${escapeHtml(field.key)}"
                    value="${escapeHtml(displayValue)}"
                    placeholder="${escapeHtml(placeholder)}"
                    autocomplete="off"
                >
                <input type="hidden" data-config-searchable-value="${escapeHtml(field.key)}" ${datasetKey}="${escapeHtml(field.key)}" value="${encodedValue}">
                <button class="config-searchable-select-toggle" type="button" data-config-searchable-toggle aria-label="展开${escapeHtml(field.label || field.key || "选项")}"></button>
            </div>
            <div class="config-searchable-select-menu" data-config-searchable-menu hidden>
                <div class="config-searchable-select-options">
                    ${options.map((option) => {
                        const descriptor = getFieldOptionDescriptor(option);
                        const rawValueText = String(descriptor.value ?? "").trim();
                        const isSelected = JSON.stringify(descriptor.value) === selectedValue;
                        const searchText = normalizeSearchText([descriptor.label, descriptor.searchText, rawValueText].join(" "));
                        return `
                            <button
                                class="config-searchable-select-option ${isSelected ? "is-selected" : ""}"
                                type="button"
                                data-config-searchable-option
                                data-option-label="${escapeHtml(descriptor.label)}"
                                data-option-value="${optionValueToAttribute(descriptor.value)}"
                                data-option-raw-value="${escapeHtml(rawValueText)}"
                                data-search-text="${escapeHtml(searchText)}"
                            >
                                <span class="config-searchable-select-option-title">${escapeHtml(descriptor.label)}</span>
                                ${rawValueText && rawValueText !== descriptor.label ? `<span class="config-searchable-select-option-meta">${escapeHtml(rawValueText)}</span>` : ""}
                            </button>
                        `;
                    }).join("")}
                </div>
                <div class="config-searchable-select-empty" data-config-searchable-empty ${options.length ? "hidden" : ""}>${escapeHtml(emptyText)}</div>
            </div>
        </div>
    `;
}

function renderProjectFilePickerInput(field, value, datasetKey = "data-config-key") {
    const currentValue = value ?? "";
    const buttonLabel = String(field.pick_label || field.button_label || "选择文件").trim() || "选择文件";
    return `
        <div class="config-file-picker">
            <input type="text" ${datasetKey}="${escapeHtml(field.key)}" value="${escapeHtml(currentValue)}" placeholder="${escapeHtml(field.placeholder || "")}">
            <button
                class="button secondary compact"
                type="button"
                data-config-pick-project-file
                data-target-key="${escapeHtml(field.key)}"
                data-upload-dir="${escapeHtml(String(field.upload_dir || "uploads").trim())}"
                data-accept="${escapeHtml(String(field.accept || "").trim())}"
            >${escapeHtml(buttonLabel)}</button>
        </div>
    `;
}

function renderFetchOptionsTextInput(field, value, datasetKey = "data-config-key") {
    const currentValue = value ?? "";
    const inputType = escapeHtml(field.input_type || field.type || "text");
    const buttonLabel = String(field.fetch_options_button_label || field.button_label || "获取选项").trim() || "获取选项";
    const selectPlaceholder = String(field.fetch_options_select_placeholder || "从已获取列表中选择").trim() || "从已获取列表中选择";
    const options = getFieldOptionItems(field);
    const normalizedValue = JSON.stringify(currentValue);

    return `
        <div class="config-fetch-options-field">
            <div class="config-file-picker">
                <input type="${inputType}" ${datasetKey}="${escapeHtml(field.key)}" value="${escapeHtml(currentValue)}" placeholder="${escapeHtml(field.placeholder || "")}" autocomplete="off">
                <button
                    class="button secondary compact"
                    type="button"
                    data-config-fetch-options
                    data-target-key="${escapeHtml(field.key)}"
                >${escapeHtml(buttonLabel)}</button>
            </div>
            ${options.length ? `
                <select data-config-fetch-options-select="${escapeHtml(field.key)}" style="margin-top:8px;">
                    <option value="">${escapeHtml(selectPlaceholder)}</option>
                    ${options.map((option) => {
                        const descriptor = getFieldOptionDescriptor(option);
                        const rawValueText = String(descriptor.value ?? "").trim();
                        return `<option value="${optionValueToAttribute(descriptor.value)}" ${JSON.stringify(descriptor.value) === normalizedValue ? "selected" : ""}>${escapeHtml(descriptor.label || rawValueText || String(descriptor.value ?? ""))}</option>`;
                    }).join("")}
                </select>
            ` : ""}
        </div>
    `;
}

function renderPrimitiveInput(field, value, datasetKey = "data-config-key") {
    const currentValue = value ?? "";
    if (field.file_picker === "project-image") {
        return renderProjectFilePickerInput(field, currentValue, datasetKey);
    }
    if (field.fetch_options_button) {
        return renderFetchOptionsTextInput(field, currentValue, datasetKey);
    }
    if (field.type === "textarea") {
        return `<textarea ${datasetKey}="${escapeHtml(field.key)}" rows="${escapeHtml(String(field.rows || 4))}" placeholder="${escapeHtml(field.placeholder || "")}">${escapeHtml(currentValue)}</textarea>`;
    }
    if (field.type === "checkbox") {
        return `
            <label class="config-inline-checkbox">
                <input type="checkbox" ${datasetKey}="${escapeHtml(field.key)}" ${currentValue ? "checked" : ""}>
                <span>${escapeHtml(field.checkbox_label || field.label || "启用")}</span>
            </label>
        `;
    }
    if (field.type === "select") {
        const options = getFieldOptionItems(field);
        if (field.searchable) {
            return renderSearchableSelectInput(field, currentValue, datasetKey);
        }
        const normalizedValue = JSON.stringify(currentValue);
        const emptyOptionLabel = String(field.empty_option_label || field.placeholder || "").trim();
        return `
            <select ${datasetKey}="${escapeHtml(field.key)}">
                ${emptyOptionLabel ? `<option value="" ${currentValue === "" || currentValue === null || currentValue === undefined ? "selected" : ""}>${escapeHtml(emptyOptionLabel)}</option>` : ""}
                ${options.map((option) => {
                    const optionValue = Object.prototype.hasOwnProperty.call(option, "value") ? option.value : option;
                    const optionLabel = Object.prototype.hasOwnProperty.call(option, "label") ? option.label : String(optionValue);
                    return `<option value="${optionValueToAttribute(optionValue)}" ${JSON.stringify(optionValue) === normalizedValue ? "selected" : ""}>${escapeHtml(optionLabel)}</option>`;
                }).join("")}
            </select>
        `;
    }
    const inputType = field.type === "number" ? "number" : (field.input_type || field.type || "text");
    const minAttr = field.min !== undefined ? ` min="${escapeHtml(String(field.min))}"` : "";
    const maxAttr = field.max !== undefined ? ` max="${escapeHtml(String(field.max))}"` : "";
    const stepAttr = field.step !== undefined ? ` step="${escapeHtml(String(field.step))}"` : "";
    return `<input type="${escapeHtml(inputType)}" ${datasetKey}="${escapeHtml(field.key)}" value="${escapeHtml(currentValue)}" placeholder="${escapeHtml(field.placeholder || "")}"${minAttr}${maxAttr}${stepAttr}>`;
}

function renderStringListField(field, value) {
    const lines = Array.isArray(value) ? value : [];
    return `
        <label class="field-group field-span-2 config-field-shell" data-config-field="${escapeHtml(field.key)}" data-config-type="string-list">
            <span class="field-label">${escapeHtml(field.label)}</span>
            <textarea data-config-key="${escapeHtml(field.key)}" rows="${escapeHtml(String(field.rows || 5))}" placeholder="${escapeHtml(field.placeholder || "每行填写一项")}">${escapeHtml(lines.join("\n"))}</textarea>
            ${renderHint(field)}
        </label>
    `;
}

function toNormalizedStringList(value) {
    const items = Array.isArray(value) ? value : String(value ?? "").split(/\r?\n/);
    return items
        .map((item) => String(item ?? "").trim())
        .filter(Boolean);
}

function mergeUniqueStringList(values) {
    const merged = [];
    const seen = new Set();
    for (const value of values) {
        const text = String(value ?? "").trim();
        const key = normalizeSearchText(text);
        if (!text || seen.has(key)) {
            continue;
        }
        seen.add(key);
        merged.push(text);
    }
    return merged;
}

function getRoomMemberPickerCacheKey(roomid, wxpid) {
    return `${String(wxpid ?? "").trim()}::${String(roomid ?? "").trim()}`;
}

async function loadRoomMemberPickerMembers(roomid, wxpid) {
    const cacheKey = getRoomMemberPickerCacheKey(roomid, wxpid);
    if (roomMemberPickerCache.has(cacheKey)) {
        return roomMemberPickerCache.get(cacheKey);
    }
    if (roomMemberPickerPendingRequests.has(cacheKey)) {
        return roomMemberPickerPendingRequests.get(cacheKey);
    }

    const requestPromise = api.getRoomMembers(roomid, wxpid).then((payload) => {
        const members = Array.isArray(payload?.members) ? payload.members : [];
        roomMemberPickerCache.set(cacheKey, members);
        roomMemberPickerPendingRequests.delete(cacheKey);
        return members;
    }).catch((error) => {
        roomMemberPickerPendingRequests.delete(cacheKey);
        throw error;
    });

    roomMemberPickerPendingRequests.set(cacheKey, requestPromise);
    return requestPromise;
}

function isRoomMemberPickerColumn(column) {
    return column?.type === "string-list" && column?.picker === "room-members";
}

function renderRoomMemberPickerColumn(column, value, datasetKey = "data-column-key", fieldKey = "") {
    const lines = Array.isArray(value) ? value : [];
    const buttonLabel = String(column.picker_button_label || "选择群成员").trim() || "选择群成员";
    const helpText = String(column.picker_help || "可手动填写，也可从当前群成员中搜索后填入白名单。选择器会默认填入成员 wxid，更稳定。").trim();
    const searchPlaceholder = String(column.picker_search_placeholder || "搜索群昵称、昵称或 wxid").trim() || "搜索群昵称、昵称或 wxid";
    return `
        <div class="config-string-list-picker" data-config-string-list-picker>
            <div class="config-string-list-picker-toolbar">
                <span class="detail-meta">${escapeHtml(helpText)}</span>
                <button class="button secondary compact" type="button" data-config-form-action="toggle-room-member-picker" data-field="${escapeHtml(fieldKey)}" data-column-key="${escapeHtml(column.key)}">${escapeHtml(buttonLabel)}</button>
            </div>
            <textarea ${datasetKey}="${escapeHtml(column.key)}" rows="${escapeHtml(String(column.rows || 3))}" placeholder="${escapeHtml(column.placeholder || "每行填写一项")}">${escapeHtml(lines.join("\n"))}</textarea>
            <div class="config-room-member-picker" data-config-room-member-picker hidden>
                <div class="config-room-member-picker-toolbar">
                    <input class="config-search-input" type="search" data-config-room-member-search placeholder="${escapeHtml(searchPlaceholder)}">
                    <div class="config-room-member-picker-actions">
                        <button class="button primary compact" type="button" data-config-form-action="apply-room-member-picker" data-field="${escapeHtml(fieldKey)}" data-column-key="${escapeHtml(column.key)}">填入白名单</button>
                        <button class="button ghost compact" type="button" data-config-form-action="close-room-member-picker" data-field="${escapeHtml(fieldKey)}" data-column-key="${escapeHtml(column.key)}">收起</button>
                    </div>
                </div>
                <div class="config-room-member-picker-summary" data-config-room-member-summary>选择后会按成员 wxid 填入白名单，更稳定。</div>
                <div class="config-choice-list config-room-member-picker-list" data-config-room-member-list></div>
                <div class="config-choice-empty" data-config-room-member-empty hidden>没有匹配到群成员。</div>
            </div>
            <div class="config-room-member-status" data-config-room-member-status hidden></div>
        </div>
    `;
}

function renderMultiCheckboxField(field, value, datasetKey = "data-config-key") {
    const selectedValues = new Set(Array.isArray(value) ? value.map((item) => JSON.stringify(item)) : []);
    const options = Array.isArray(field.options) ? field.options : [];
    return `
        <div class="field-group field-span-2 config-field-shell" data-config-field="${escapeHtml(field.key)}" data-config-type="multi-checkbox">
            <span class="field-label">${escapeHtml(field.label)}</span>
            <div class="config-choice-grid">
                ${options.map((option) => {
                    const optionValue = Object.prototype.hasOwnProperty.call(option, "value") ? option.value : option;
                    const optionLabel = Object.prototype.hasOwnProperty.call(option, "label") ? option.label : String(optionValue);
                    const encodedValue = optionValueToAttribute(optionValue);
                    return `
                        <label class="config-choice-item">
                            <input type="checkbox" ${datasetKey}="${escapeHtml(field.key)}" value="${encodedValue}" ${selectedValues.has(JSON.stringify(optionValue)) ? "checked" : ""}>
                            <span>${escapeHtml(optionLabel)}</span>
                        </label>
                    `;
                }).join("")}
            </div>
            ${renderHint(field)}
        </div>
    `;
}

function renderSearchableMultiCheckboxField(field, value, datasetKey = "data-config-key") {
    const selectedValues = new Set(Array.isArray(value) ? value.map((item) => JSON.stringify(item)) : []);
    const options = Array.isArray(field.options) ? field.options : [];
    const searchPlaceholder = String(field.search_placeholder || "搜索群聊名称").trim();
    const showSelectedLabel = String(field.show_selected_label || "仅显示已勾选").trim();
    const emptyStateText = String(field.empty_text || "没有匹配到可选项。").trim();
    const emptyStateNoOptionsText = String(field.empty_no_options_text || "当前还没有可选项。").trim();
    return `
        <div class="field-group field-span-2 config-field-shell" data-config-field="${escapeHtml(field.key)}" data-config-type="searchable-multi-checkbox">
            <div class="config-choice-toolbar" style="display:grid;grid-template-columns:minmax(0,1fr) minmax(340px,540px);gap:12px;align-items:end;">
                <div class="config-choice-toolbar-meta">
                    <span class="field-label">${escapeHtml(field.label)}</span>
                    <span class="detail-meta">共 ${escapeHtml(String(options.length))} 项</span>
                </div>
                <div class="config-choice-toolbar-actions">
                    <input class="config-search-input" type="search" data-config-search-input="${escapeHtml(field.key)}" placeholder="${escapeHtml(searchPlaceholder)}">
                    <label class="config-inline-checkbox config-inline-checkbox-toolbar">
                        <input type="checkbox" data-config-show-selected="${escapeHtml(field.key)}">
                        <span>${escapeHtml(showSelectedLabel)}</span>
                    </label>
                </div>
            </div>
            <div class="config-choice-list" data-config-search-list style="display:flex;flex-direction:column;gap:8px;">
                ${options.map((option) => {
                    const optionValue = Object.prototype.hasOwnProperty.call(option, "value") ? option.value : option;
                    const optionLabel = Object.prototype.hasOwnProperty.call(option, "label") ? option.label : String(optionValue);
                    const encodedValue = optionValueToAttribute(optionValue);
                    const searchText = normalizeSearchText(option.search_text || optionLabel || optionValue);
                    return `
                        <label class="config-choice-item config-choice-item-list" data-config-choice-item data-search-text="${escapeHtml(searchText)}" style="grid-template-columns:16px minmax(0,1fr);align-items:start;column-gap:10px;width:100%;">
                            <input type="checkbox" ${datasetKey}="${escapeHtml(field.key)}" value="${encodedValue}" ${selectedValues.has(JSON.stringify(optionValue)) ? "checked" : ""}>
                            <span>${escapeHtml(optionLabel)}</span>
                        </label>
                    `;
                }).join("")}
                <div class="config-choice-empty" data-config-search-empty ${options.length ? "hidden" : ""}>${options.length ? escapeHtml(emptyStateText) : escapeHtml(emptyStateNoOptionsText)}</div>
            </div>
            ${renderHint(field)}
        </div>
    `;
}

function renderKeyValueRow(field, keyValue = "", valueValue = "") {
    return `
        <div class="config-row" data-config-row>
            <input type="text" data-column-key="__key" value="${escapeHtml(keyValue)}" placeholder="${escapeHtml(field.key_placeholder || "键")}">
            <input type="text" data-column-key="__value" value="${escapeHtml(valueValue)}" placeholder="${escapeHtml(field.value_placeholder || "值")}">
            <button class="button ghost compact config-row-remove" type="button" data-config-form-action="remove-row" data-field="${escapeHtml(field.key)}">删除</button>
        </div>
    `;
}

function renderKeyMultiValueRow(field, keyValue = "", values = []) {
    const selectedValues = new Set((Array.isArray(values) ? values : []).map((item) => JSON.stringify(item)));
    const options = Array.isArray(field.options) ? field.options : [];
    return `
        <div class="config-row config-row-wide" data-config-row>
            <input type="text" data-column-key="__key" value="${escapeHtml(keyValue)}" placeholder="${escapeHtml(field.key_placeholder || "键")}">
            <div class="config-choice-grid is-inline-row">
                ${options.map((option) => {
                    const optionValue = Object.prototype.hasOwnProperty.call(option, "value") ? option.value : option;
                    const optionLabel = Object.prototype.hasOwnProperty.call(option, "label") ? option.label : String(optionValue);
                    const encodedValue = optionValueToAttribute(optionValue);
                    return `
                        <label class="config-choice-item compact">
                            <input type="checkbox" data-column-key="__value" value="${encodedValue}" ${selectedValues.has(JSON.stringify(optionValue)) ? "checked" : ""}>
                            <span>${escapeHtml(optionLabel)}</span>
                        </label>
                    `;
                }).join("")}
            </div>
            <button class="button ghost compact config-row-remove" type="button" data-config-form-action="remove-row" data-field="${escapeHtml(field.key)}">删除</button>
        </div>
    `;
}

function renderRowColumnControl(column, value, fieldKey = "") {
    if (column.type === "string-list") {
        if (isRoomMemberPickerColumn(column)) {
            return renderRoomMemberPickerColumn(column, value, "data-column-key", fieldKey);
        }
        const lines = Array.isArray(value) ? value : [];
        return `<textarea data-column-key="${escapeHtml(column.key)}" rows="${escapeHtml(String(column.rows || 3))}" placeholder="${escapeHtml(column.placeholder || "每行一项")}">${escapeHtml(lines.join("\n"))}</textarea>`;
    }
    if (column.type === "multi-checkbox") {
        return renderMultiCheckboxField(column, value, `data-column-key`).replace('field-group field-span-2 config-field-shell', 'config-column-choice');
    }
    return renderPrimitiveInput(column, value, "data-column-key");
}

function parseStoredRowValue(rawValue) {
    if (!rawValue) {
        return {};
    }
    try {
        const parsed = JSON.parse(String(rawValue));
        return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch {
        return {};
    }
}

function getObjectTableTemplateColumns(field) {
    const templates = (Array.isArray(field.columns) ? field.columns : []).map((column) => {
        if (column.width === "wide") {
            return "minmax(220px, 1.6fr)";
        }
        if (column.width === "compact") {
            return "minmax(108px, 0.68fr)";
        }
        if (column.type === "checkbox") {
            return "minmax(140px, 0.7fr)";
        }
        if (column.type === "number") {
            return "minmax(120px, 0.8fr)";
        }
        return "minmax(160px, 1fr)";
    });
    return `${templates.length ? templates.join(" ") : "minmax(0, 1fr)"} minmax(132px, auto)`;
}

function getObjectTableGridStyle(field) {
    return `style="grid-template-columns:${escapeHtml(getObjectTableTemplateColumns(field))}"`;
}

function getColumnOptionLabel(column, value) {
    const options = getFieldOptionItems(column);
    const normalizedValue = JSON.stringify(value);
    for (const option of options) {
        const descriptor = getFieldOptionDescriptor(option);
        if (JSON.stringify(descriptor.value) === normalizedValue) {
            return descriptor.label;
        }
    }
    return String(value ?? "").trim();
}

function formatObjectTableValue(column, value) {
    if (column.type === "checkbox") {
        return value ? "是" : "否";
    }
    if (column.type === "multi-checkbox") {
        const items = Array.isArray(value) ? value : [];
        return items.length ? items.map((item) => getColumnOptionLabel(column, item)).join("、") : "未填写";
    }
    if (column.type === "string-list") {
        const items = Array.isArray(value) ? value : [];
        return items.length ? items.join("、") : "未填写";
    }
    if (column.type === "select") {
        return getColumnOptionLabel(column, value) || "未填写";
    }
    const text = String(value ?? "").trim();
    return text || "未填写";
}

function renderObjectTableHeader(field) {
    return `
        <div class="config-object-table-header" ${getObjectTableGridStyle(field)}>
            ${(Array.isArray(field.columns) ? field.columns : []).map((column) => `
                <div class="config-object-table-heading">${escapeHtml(column.label)}</div>
            `).join("")}
            <div class="config-object-table-heading is-actions">操作</div>
        </div>
    `;
}

function renderObjectTableRow(field, rowValue = {}) {
    const row = rowValue && typeof rowValue === "object" ? rowValue : {};
    return `
        <div class="config-object-table-row" data-config-row data-row-value="${escapeHtml(JSON.stringify(row))}" ${getObjectTableGridStyle(field)}>
            ${(Array.isArray(field.columns) ? field.columns : []).map((column) => `
                <div class="config-object-table-cell">
                    <div class="config-object-table-value">${escapeHtml(formatObjectTableValue(column, row[column.key]))}</div>
                </div>
            `).join("")}
            <div class="config-object-table-actions">
                <button class="button secondary compact" type="button" data-config-form-action="edit-row" data-field="${escapeHtml(field.key)}">编辑</button>
                <button class="button ghost compact config-row-remove" type="button" data-config-form-action="remove-row" data-field="${escapeHtml(field.key)}">删除</button>
            </div>
        </div>
    `;
}

function getObjectTableEditorCellClass(column) {
    const classNames = ["config-object-table-cell", "config-object-table-editor-cell"];
    if (column?.width === "wide") {
        classNames.push("is-wide");
    }
    return classNames.join(" ");
}

function getObjectTableEditorCellStyle(column) {
    const rawSpan = Number(column?.editor_span);
    const editorSpan = Number.isFinite(rawSpan) ? Math.max(1, Math.min(12, Math.round(rawSpan))) : null;
    return editorSpan ? ` style="--config-editor-span:${escapeHtml(String(editorSpan))}"` : "";
}

function renderObjectTableEditor(field, rowValue = {}, originalRowValue = undefined) {
    const row = rowValue && typeof rowValue === "object" ? rowValue : {};
    const originalValueAttr = originalRowValue === undefined
        ? ""
        : ` data-original-row-value="${escapeHtml(JSON.stringify(originalRowValue && typeof originalRowValue === "object" ? originalRowValue : {}))}"`;
    return `
        <div class="config-object-table-row is-editing" data-config-row-editor${originalValueAttr} ${getObjectTableGridStyle(field)}>
            ${(Array.isArray(field.columns) ? field.columns : []).map((column) => `
                <div class="${escapeHtml(getObjectTableEditorCellClass(column))}"${getObjectTableEditorCellStyle(column)}>
                    <div class="config-row-label">${escapeHtml(column.label)}</div>
                    ${renderRowColumnControl(column, row[column.key], field.key)}
                </div>
            `).join("")}
            <div class="config-object-table-actions">
                <button class="button primary compact" type="button" data-config-form-action="save-row" data-field="${escapeHtml(field.key)}">保存</button>
                <button class="button ghost compact" type="button" data-config-form-action="cancel-row" data-field="${escapeHtml(field.key)}">取消</button>
            </div>
            <div class="config-object-table-error" data-config-row-error hidden></div>
        </div>
    `;
}

function renderObjectTableField(field, value) {
    const rows = Array.isArray(value) ? value : [];
    return `
        <div class="field-group field-span-2 config-field-shell" data-config-field="${escapeHtml(field.key)}" data-config-type="object-list">
            <div class="config-field-head">
                <span class="field-label">${escapeHtml(field.label)}</span>
                <button class="button secondary compact" type="button" data-config-form-action="add-row" data-field="${escapeHtml(field.key)}">新增</button>
            </div>
            <div class="config-object-table-shell">
                ${renderObjectTableHeader(field)}
                <div class="config-rows config-object-table-rows" data-config-rows>${rows.map((row) => renderObjectTableRow(field, row)).join("")}</div>
                <div class="config-choice-empty" data-config-table-empty ${rows.length ? "hidden" : ""}>${escapeHtml(field.empty_text || "暂无规则，点击“新增”后填写并保存。")}</div>
            </div>
            ${renderHint(field)}
        </div>
    `;
}

function renderObjectRow(field, rowValue = {}) {
    const row = rowValue && typeof rowValue === "object" ? rowValue : {};
    return `
        <div class="config-row config-row-table" data-config-row>
            ${field.columns.map((column) => `
                <div class="config-row-cell ${column.width === "wide" ? "is-wide" : ""}">
                    <div class="config-row-label">${escapeHtml(column.label)}</div>
                    ${renderRowColumnControl(column, row[column.key], field.key)}
                </div>
            `).join("")}
            <div class="config-row-actions">
                <button class="button ghost compact config-row-remove" type="button" data-config-form-action="remove-row" data-field="${escapeHtml(field.key)}">删除</button>
            </div>
        </div>
    `;
}

function renderGroupedObjectRows(field, value) {
    const groups = value && typeof value === "object" && !Array.isArray(value) ? value : {};
    const rows = [];
    for (const [groupValue, items] of Object.entries(groups)) {
        for (const item of Array.isArray(items) ? items : []) {
            rows.push({ [field.group_key]: groupValue, ...(item && typeof item === "object" ? item : {}) });
        }
    }
    return rows.length ? rows.map((row) => renderObjectRow(field, row)).join("") : "";
}

function renderKeyValueListField(field, value) {
    const entries = value && typeof value === "object" && !Array.isArray(value) ? Object.entries(value) : [];
    const rows = entries.length ? entries.map(([key, itemValue]) => renderKeyValueRow(field, key, itemValue)).join("") : "";
    return `
        <div class="field-group field-span-2 config-field-shell" data-config-field="${escapeHtml(field.key)}" data-config-type="key-value-list">
            <div class="config-field-head">
                <span class="field-label">${escapeHtml(field.label)}</span>
                <button class="button secondary compact" type="button" data-config-form-action="add-row" data-field="${escapeHtml(field.key)}">新增</button>
            </div>
            <div class="config-rows" data-config-rows>${rows}</div>
            ${renderHint(field)}
        </div>
    `;
}

function renderKeyMultiValueListField(field, value) {
    const entries = value && typeof value === "object" && !Array.isArray(value) ? Object.entries(value) : [];
    const rows = entries.length ? entries.map(([key, values]) => renderKeyMultiValueRow(field, key, values)).join("") : "";
    return `
        <div class="field-group field-span-2 config-field-shell" data-config-field="${escapeHtml(field.key)}" data-config-type="key-multi-value-list">
            <div class="config-field-head">
                <span class="field-label">${escapeHtml(field.label)}</span>
                <button class="button secondary compact" type="button" data-config-form-action="add-row" data-field="${escapeHtml(field.key)}">新增</button>
            </div>
            <div class="config-rows" data-config-rows>${rows}</div>
            ${renderHint(field)}
        </div>
    `;
}

function renderObjectListField(field, value) {
    if (field.display_mode === "table") {
        return renderObjectTableField(field, value);
    }
    const rows = Array.isArray(value) ? value : [];
    return `
        <div class="field-group field-span-2 config-field-shell" data-config-field="${escapeHtml(field.key)}" data-config-type="object-list">
            <div class="config-field-head">
                <span class="field-label">${escapeHtml(field.label)}</span>
                <button class="button secondary compact" type="button" data-config-form-action="add-row" data-field="${escapeHtml(field.key)}">新增</button>
            </div>
            <div class="config-rows" data-config-rows>${rows.map((row) => renderObjectRow(field, row)).join("")}</div>
            ${renderHint(field)}
        </div>
    `;
}

function renderGroupedObjectListField(field, value) {
    return `
        <div class="field-group field-span-2 config-field-shell" data-config-field="${escapeHtml(field.key)}" data-config-type="grouped-object-list">
            <div class="config-field-head">
                <span class="field-label">${escapeHtml(field.label)}</span>
                <button class="button secondary compact" type="button" data-config-form-action="add-row" data-field="${escapeHtml(field.key)}">新增</button>
            </div>
            <div class="config-rows" data-config-rows>${renderGroupedObjectRows(field, value)}</div>
            ${renderHint(field)}
        </div>
    `;
}

function renderSimpleField(field, value) {
    const spanClass = field.full_width === false ? "" : " field-span-2";
    return `
        <label class="field-group${spanClass} config-field-shell" data-config-field="${escapeHtml(field.key)}" data-config-type="${escapeHtml(field.type || "text")}">
            <span class="field-label">${escapeHtml(field.label)}</span>
            ${renderPrimitiveInput(field, value)}
            ${renderHint(field)}
        </label>
    `;
}

function renderField(field, value) {
    switch (field.type) {
        case "string-list":
            return renderStringListField(field, value);
        case "multi-checkbox":
            return renderMultiCheckboxField(field, value);
        case "searchable-multi-checkbox":
            return renderSearchableMultiCheckboxField(field, value);
        case "key-value-list":
            return renderKeyValueListField(field, value);
        case "key-multi-value-list":
            return renderKeyMultiValueListField(field, value);
        case "object-list":
            return renderObjectListField(field, value);
        case "grouped-object-list":
            return renderGroupedObjectListField(field, value);
        default:
            return renderSimpleField(field, value);
    }
}

function readPrimitiveValue(element, field) {
    if (field.type === "checkbox") {
        return Boolean(element.checked);
    }
    if (field.type === "number") {
        const text = String(element.value || "").trim();
        if (!text) {
            return undefined;
        }
        const value = Number(text);
        return Number.isFinite(value) ? value : undefined;
    }
    if (field.type === "select") {
        return parseOptionValue(element.value);
    }
    return element.value;
}

function readStringListValue(fieldContainer) {
    const textarea = fieldContainer.querySelector("[data-config-key]");
    return String(textarea?.value || "")
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);
}

function readMultiCheckboxValue(fieldContainer) {
    return [...fieldContainer.querySelectorAll('input[type="checkbox"][data-config-key]:checked')].map((input) => parseOptionValue(input.value));
}

function rowHasMeaningfulData(rowObject, meaningfulKeys = []) {
    const keys = meaningfulKeys.length ? meaningfulKeys : Object.keys(rowObject);
    return keys.some((key) => isMeaningfulValue(rowObject[key]));
}

function isMissingRequiredValue(value, column) {
    if (column?.type === "checkbox") {
        return value !== true;
    }
    return !isMeaningfulValue(value);
}

function validateObjectRow(field, row) {
    for (const column of Array.isArray(field.columns) ? field.columns : []) {
        if (!column?.required) {
            continue;
        }
        if (isMissingRequiredValue(row?.[column.key], column)) {
            return column.required_message || `${column.label || column.key}不能为空`;
        }
    }
    if (Array.isArray(field.require_one_of) && field.require_one_of.length) {
        const hasAnyValue = field.require_one_of.some((key) => isMeaningfulValue(row?.[key]));
        if (!hasAnyValue) {
            return field.require_one_of_message || `请至少填写 ${field.require_one_of.join(" / ")}`;
        }
    }
    return "";
}

function validateObjectRowsCollection(field, rows) {
    if (!Array.isArray(field.unique_by) || !field.unique_by.length) {
        return "";
    }

    const seenKeys = new Set();
    for (const row of Array.isArray(rows) ? rows : []) {
        const compositeKey = field.unique_by
            .map((key) => JSON.stringify(row?.[key] ?? ""))
            .join("::");
        if (!compositeKey.replace(/[:"\\]/g, "")) {
            continue;
        }
        if (seenKeys.has(compositeKey)) {
            return field.unique_message || `${field.label || "当前配置"}中存在重复规则`;
        }
        seenKeys.add(compositeKey);
    }
    return "";
}

function clearObjectTableEditorError(editorRow) {
    if (!editorRow) {
        return;
    }
    editorRow.classList.remove("is-invalid");
    const errorElement = editorRow.querySelector("[data-config-row-error]");
    if (errorElement) {
        errorElement.textContent = "";
        errorElement.hidden = true;
    }
}

function showObjectTableEditorError(editorRow, message) {
    if (!editorRow) {
        return;
    }
    editorRow.classList.add("is-invalid");
    const errorElement = editorRow.querySelector("[data-config-row-error]");
    if (errorElement) {
        errorElement.textContent = message;
        errorElement.hidden = !message;
    }
}

function getObjectTableColumn(field, columnKey) {
    return (Array.isArray(field?.columns) ? field.columns : []).find((column) => column?.key === columnKey) || null;
}

function getRoomMemberPickerContext(button, field) {
    const pickerColumn = getObjectTableColumn(field, button.dataset.columnKey || "");
    const pickerContainer = button.closest("[data-config-string-list-picker]");
    const editorRow = button.closest("[data-config-row-editor]");
    const textarea = pickerContainer?.querySelector(`textarea[data-column-key="${pickerColumn?.key || ""}"]`) || null;
    const panel = pickerContainer?.querySelector("[data-config-room-member-picker]") || null;
    const list = pickerContainer?.querySelector("[data-config-room-member-list]") || null;
    const empty = pickerContainer?.querySelector("[data-config-room-member-empty]") || null;
    const summary = pickerContainer?.querySelector("[data-config-room-member-summary]") || null;
    const status = pickerContainer?.querySelector("[data-config-room-member-status]") || null;
    const searchInput = pickerContainer?.querySelector("[data-config-room-member-search]") || null;
    const roomColumn = getObjectTableColumn(field, pickerColumn?.picker_room_field || "roomid");
    const roomInput = roomColumn && editorRow ? editorRow.querySelector(`[data-column-key="${roomColumn.key}"]`) : null;
    const roomid = roomInput && roomColumn ? String(readRowColumnValue(roomInput, roomColumn) || "").trim() : "";
    const roomOption = roomColumn && roomid ? findFieldOptionItemByValue(roomColumn, roomid) : null;
    const roomOptionDescriptor = roomOption ? getFieldOptionDescriptor(roomOption) : null;
    const wxpid = roomOption && Object.prototype.hasOwnProperty.call(roomOption, "wxpid") ? roomOption.wxpid : "";
    return {
        pickerColumn,
        pickerContainer,
        editorRow,
        textarea,
        panel,
        list,
        empty,
        summary,
        status,
        searchInput,
        roomColumn,
        roomid,
        roomOption,
        roomLabel: roomOptionDescriptor?.label || roomid,
        wxpid,
    };
}

function setRoomMemberPickerStatus(statusElement, message = "", tone = "") {
    if (!statusElement) {
        return;
    }
    statusElement.textContent = String(message || "").trim();
    statusElement.hidden = !statusElement.textContent;
    statusElement.classList.toggle("is-error", tone === "error");
    statusElement.classList.toggle("is-good", tone === "good");
}

function doesRoomMemberMatchWhitelist(member, whitelistValues) {
    const normalizedWhitelist = new Set(toNormalizedStringList(whitelistValues).map((item) => normalizeSearchText(item)).filter(Boolean));
    if (!normalizedWhitelist.size) {
        return false;
    }
    const candidates = [member?.wxid, member?.display_name, member?.room_nick_name, member?.nick_name]
        .map((item) => normalizeSearchText(item))
        .filter(Boolean);
    return candidates.some((candidate) => normalizedWhitelist.has(candidate));
}

function renderRoomMemberPickerOptions(members, whitelistValues) {
    return members.map((member) => {
        const displayName = String(member?.display_name || member?.label || member?.wxid || "未命名成员").trim() || "未命名成员";
        const wxid = String(member?.wxid || member?.value || "").trim();
        const nickName = String(member?.nick_name || "").trim();
        const roomNickName = String(member?.room_nick_name || "").trim();
        const metaParts = [
            roomNickName && roomNickName !== displayName ? `群昵称：${roomNickName}` : "",
            nickName && nickName !== displayName && nickName !== roomNickName ? `昵称：${nickName}` : "",
            wxid ? `wxid：${wxid}` : "",
        ].filter(Boolean);
        return `
            <label class="config-choice-item config-choice-item-list config-room-member-choice" data-config-room-member-item data-search-text="${escapeHtml(normalizeSearchText(member?.search_text || [displayName, roomNickName, nickName, wxid].join(" ")))}">
                <input
                    type="checkbox"
                    data-config-room-member-option
                    value="${escapeHtml(wxid)}"
                    data-display-name="${escapeHtml(displayName)}"
                    data-room-nick-name="${escapeHtml(roomNickName)}"
                    data-nick-name="${escapeHtml(nickName)}"
                    ${doesRoomMemberMatchWhitelist(member, whitelistValues) ? "checked" : ""}
                >
                <span class="config-room-member-choice-body">
                    <strong class="config-room-member-choice-title">${escapeHtml(displayName)}</strong>
                    ${metaParts.length ? `<small class="config-room-member-choice-meta">${escapeHtml(metaParts.join(" · "))}</small>` : ""}
                </span>
            </label>
        `;
    }).join("");
}

function applyRoomMemberPickerFilter(searchInput) {
    const pickerContainer = searchInput?.closest("[data-config-string-list-picker]");
    const list = pickerContainer?.querySelector("[data-config-room-member-list]");
    const empty = pickerContainer?.querySelector("[data-config-room-member-empty]");
    if (!list || !empty) {
        return;
    }
    const query = normalizeSearchText(searchInput.value);
    let visibleCount = 0;
    for (const item of list.querySelectorAll("[data-config-room-member-item]")) {
        const searchText = normalizeSearchText(item.getAttribute("data-search-text") || item.textContent || "");
        const matched = !query || searchText.includes(query);
        item.hidden = !matched;
        item.style.display = matched ? "" : "none";
        if (matched) {
            visibleCount += 1;
        }
    }
    empty.hidden = visibleCount > 0;
    if (visibleCount <= 0) {
        empty.textContent = query ? "没有匹配到群成员。" : (list.children.length ? "当前群没有可选成员。" : "请先读取群成员列表。");
    }
}

function initializeRoomMemberPickerSearch(searchInput) {
    if (!(searchInput instanceof HTMLInputElement) || searchInput.dataset.roomMemberPickerBound === "1") {
        return;
    }
    const listener = () => applyRoomMemberPickerFilter(searchInput);
    searchInput.addEventListener("input", listener);
    searchInput.addEventListener("search", listener);
    searchInput.dataset.roomMemberPickerBound = "1";
}

function closeRoomMemberPicker(button, field) {
    const context = getRoomMemberPickerContext(button, field);
    if (!context?.panel) {
        return false;
    }
    context.panel.hidden = true;
    return true;
}

async function openRoomMemberPicker(button, field) {
    const context = getRoomMemberPickerContext(button, field);
    if (!context?.panel || !context.pickerColumn) {
        return false;
    }

    initializeRoomMemberPickerSearch(context.searchInput);
    context.panel.hidden = false;
    if (context.searchInput) {
        context.searchInput.value = "";
    }

    if (context.summary) {
        context.summary.textContent = context.roomLabel
            ? `正在读取 ${context.roomLabel} 的群成员，填入时默认使用成员 wxid。`
            : "选择后会按成员 wxid 填入白名单，更稳定。";
    }

    if (!context.roomid) {
        if (context.list) {
            context.list.innerHTML = "";
        }
        if (context.empty) {
            context.empty.hidden = false;
            context.empty.textContent = "请先选择群聊，再打开成员选择器。";
        }
        setRoomMemberPickerStatus(context.status, "请先选择群聊，再打开成员选择器。", "error");
        const roomSearchInput = context.editorRow?.querySelector(`[data-config-searchable-input="${context.roomColumn?.key || "roomid"}"]`);
        roomSearchInput?.focus?.();
        return true;
    }

    if (context.list) {
        context.list.innerHTML = "";
    }
    if (context.empty) {
        context.empty.hidden = false;
        context.empty.textContent = "正在读取群成员...";
    }
    setRoomMemberPickerStatus(context.status, "正在读取群成员...", "");

    try {
        const members = await loadRoomMemberPickerMembers(context.roomid, context.wxpid);
        if (context.panel) {
            context.panel.dataset.roomid = context.roomid;
            context.panel.dataset.wxpid = String(context.wxpid ?? "");
        }
        if (context.list) {
            context.list.innerHTML = renderRoomMemberPickerOptions(members, toNormalizedStringList(context.textarea?.value || ""));
        }
        if (context.empty) {
            context.empty.hidden = members.length > 0;
            context.empty.textContent = members.length ? "没有匹配到群成员。" : "当前群没有可选成员。";
        }
        if (context.summary) {
            context.summary.textContent = context.roomLabel
                ? `${context.roomLabel} 共 ${members.length} 位群成员，可按群昵称、昵称或 wxid 搜索；填入时默认使用成员 wxid。`
                : `共 ${members.length} 位群成员，可按群昵称、昵称或 wxid 搜索；填入时默认使用成员 wxid。`;
        }
        setRoomMemberPickerStatus(context.status, members.length ? `已加载 ${members.length} 位群成员。` : "当前群没有可选成员。", members.length ? "good" : "");
        if (context.searchInput) {
            applyRoomMemberPickerFilter(context.searchInput);
        }
        return true;
    } catch (error) {
        if (context.list) {
            context.list.innerHTML = "";
        }
        if (context.empty) {
            context.empty.hidden = false;
            context.empty.textContent = "读取群成员失败，请稍后重试。";
        }
        setRoomMemberPickerStatus(context.status, `读取群成员失败：${error.message || error}`, "error");
        return true;
    }
}

function applyRoomMemberPickerSelection(button, field) {
    const context = getRoomMemberPickerContext(button, field);
    if (!context?.panel || !(context.textarea instanceof HTMLTextAreaElement)) {
        return false;
    }

    const currentRoomInput = context.roomColumn && context.editorRow
        ? context.editorRow.querySelector(`[data-column-key="${context.roomColumn.key}"]`)
        : null;
    const currentRoomid = currentRoomInput && context.roomColumn
        ? String(readRowColumnValue(currentRoomInput, context.roomColumn) || "").trim()
        : "";
    if (currentRoomid && context.panel.dataset.roomid && currentRoomid !== context.panel.dataset.roomid) {
        setRoomMemberPickerStatus(context.status, "当前群聊已变化，请重新打开成员选择器后再填入。", "error");
        return true;
    }

    const selectedInputs = [...context.panel.querySelectorAll("[data-config-room-member-option]:checked")];
    if (!selectedInputs.length) {
        setRoomMemberPickerStatus(context.status, "请先勾选至少一位群成员。", "error");
        return true;
    }

    const existingValues = toNormalizedStringList(context.textarea.value);
    const existingKeys = new Set(existingValues.map((item) => normalizeSearchText(item)).filter(Boolean));
    const nextValues = [...existingValues];
    let addedCount = 0;

    for (const input of selectedInputs) {
        const memberWxid = String(input.value || "").trim();
        const candidateKeys = [
            memberWxid,
            input.dataset.displayName,
            input.dataset.roomNickName,
            input.dataset.nickName,
        ].map((item) => normalizeSearchText(item)).filter(Boolean);
        if (!memberWxid || candidateKeys.some((candidate) => existingKeys.has(candidate))) {
            continue;
        }
        nextValues.push(memberWxid);
        existingKeys.add(normalizeSearchText(memberWxid));
        addedCount += 1;
    }

    if (addedCount <= 0) {
        setRoomMemberPickerStatus(context.status, "选中的成员已经在白名单中，无需重复填入。", "good");
        context.panel.hidden = true;
        return true;
    }

    context.textarea.value = mergeUniqueStringList(nextValues).join("\n");
    context.textarea.dispatchEvent(new Event("input", { bubbles: true }));
    context.textarea.dispatchEvent(new Event("change", { bubbles: true }));
    context.panel.hidden = true;
    setRoomMemberPickerStatus(context.status, `已填入 ${addedCount} 位群成员到白名单。`, "good");
    return true;
}

function readRowColumnValue(columnElement, column) {
    if (column.type === "checkbox") {
        return Boolean(columnElement.checked);
    }
    if (column.type === "number") {
        const text = String(columnElement.value || "").trim();
        if (!text) {
            return undefined;
        }
        const value = Number(text);
        return Number.isFinite(value) ? value : undefined;
    }
    if (column.type === "select") {
        return parseOptionValue(columnElement.value);
    }
    if (column.type === "string-list") {
        return String(columnElement.value || "")
            .split(/\r?\n/)
            .map((item) => item.trim())
            .filter(Boolean);
    }
    if (column.type === "multi-checkbox") {
        return [...columnElement.querySelectorAll('input[type="checkbox"][data-column-key]:checked')].map((input) => parseOptionValue(input.value));
    }
    return columnElement.value;
}

function readObjectRows(fieldContainer, field) {
    const rows = [];
    for (const rowElement of fieldContainer.querySelectorAll("[data-config-row]")) {
        const row = rowElement.dataset.rowValue
            ? parseStoredRowValue(rowElement.dataset.rowValue)
            : (() => {
                const currentRow = {};
                for (const column of field.columns || []) {
                    if (column.type === "multi-checkbox") {
                        const columnHost = rowElement.querySelector(`.config-column-choice [data-column-key="${column.key}"]`)?.closest(".config-column-choice");
                        const groupElement = rowElement.querySelector(`.config-row-cell [data-column-key="${column.key}"]`)?.closest(".config-row-cell");
                        const checkboxHost = groupElement || columnHost;
                        currentRow[column.key] = checkboxHost
                            ? [...checkboxHost.querySelectorAll(`input[type="checkbox"][data-column-key="${column.key}"]:checked`)].map((input) => parseOptionValue(input.value))
                            : [];
                        continue;
                    }
                    const input = rowElement.querySelector(`[data-column-key="${column.key}"]`);
                    if (!input) {
                        currentRow[column.key] = undefined;
                        continue;
                    }
                    currentRow[column.key] = readRowColumnValue(input, column);
                }
                return currentRow;
            })();
        if (rowHasMeaningfulData(row, field.meaningful_keys || [])) {
            rows.push(row);
        }
    }
    return rows;
}

function syncObjectTableState(fieldContainer) {
    const emptyState = fieldContainer.querySelector("[data-config-table-empty]");
    if (emptyState) {
        emptyState.hidden = fieldContainer.querySelectorAll("[data-config-row]").length > 0;
    }
    const addButton = fieldContainer.querySelector('button[data-config-form-action="add-row"]');
    if (addButton) {
        addButton.disabled = Boolean(fieldContainer.querySelector("[data-config-row-editor]"));
    }
}

function focusObjectTableEditor(editorRow) {
    editorRow?.querySelector("input, textarea, select")?.focus();
}

function beginObjectTableRowEdit(fieldContainer, field, rowValue = {}, originalRowValue = undefined, replaceRowElement = null) {
    if (fieldContainer.querySelector("[data-config-row-editor]")) {
        focusObjectTableEditor(fieldContainer.querySelector("[data-config-row-editor]"));
        return true;
    }

    const rowsContainer = fieldContainer.querySelector("[data-config-rows]");
    if (!rowsContainer) {
        return false;
    }

    const editorMarkup = renderObjectTableEditor(field, rowValue, originalRowValue);
    if (replaceRowElement) {
        replaceRowElement.insertAdjacentHTML("afterend", editorMarkup);
        replaceRowElement.remove();
    } else {
        rowsContainer.insertAdjacentHTML("beforeend", editorMarkup);
    }

    const editorRow = fieldContainer.querySelector("[data-config-row-editor]");
    clearObjectTableEditorError(editorRow);
    syncObjectTableState(fieldContainer);
    focusObjectTableEditor(editorRow);
    return true;
}

function commitObjectTableRow(editorRow, fieldContainer, field) {
    const row = readObjectRows({ querySelectorAll: () => [editorRow] }, field)[0] || {};
    if (!rowHasMeaningfulData(row, field.meaningful_keys || [])) {
        showObjectTableEditorError(editorRow, "请至少填写一项有效内容");
        focusObjectTableEditor(editorRow);
        return true;
    }
    const validationMessage = validateObjectRow(field, row);
    if (validationMessage) {
        showObjectTableEditorError(editorRow, validationMessage);
        focusObjectTableEditor(editorRow);
        return true;
    }
    const collectionValidationMessage = validateObjectRowsCollection(field, [...readObjectRows(fieldContainer, field), row]);
    if (collectionValidationMessage) {
        showObjectTableEditorError(editorRow, collectionValidationMessage);
        focusObjectTableEditor(editorRow);
        return true;
    }
    editorRow.insertAdjacentHTML("afterend", renderObjectTableRow(field, row));
    editorRow.remove();
    syncObjectTableState(fieldContainer);
    return true;
}

function cancelObjectTableRow(editorRow, fieldContainer, field) {
    const originalRowValue = parseStoredRowValue(editorRow.dataset.originalRowValue);
    if (rowHasMeaningfulData(originalRowValue, field.meaningful_keys || [])) {
        editorRow.insertAdjacentHTML("afterend", renderObjectTableRow(field, originalRowValue));
    }
    editorRow.remove();
    syncObjectTableState(fieldContainer);
    return true;
}

function findField(plugin, fieldKey) {
    return normalizeSchema(plugin).find((field) => field.key === fieldKey) || null;
}

export function hasStructuredPluginConfig(plugin) {
    return normalizeSchema(plugin).length > 0;
}

export function renderPluginConfigFields(container, plugin) {
    const schema = normalizeSchema(plugin);
    container.innerHTML = schema.map((field) => renderField(field, getFieldValue(field, plugin.config || {}))).join("");
}

export function readStructuredPluginConfig(container, plugin) {
    const schema = normalizeSchema(plugin);
    const config = {};
    for (const field of schema) {
        const fieldContainer = container.querySelector(`[data-config-field="${field.key}"]`);
        if (!fieldContainer) {
            continue;
        }
        let value;
        switch (field.type) {
            case "string-list":
                value = readStringListValue(fieldContainer);
                break;
            case "multi-checkbox":
            case "searchable-multi-checkbox":
                value = readMultiCheckboxValue(fieldContainer);
                break;
            case "key-value-list": {
                value = {};
                for (const rowElement of fieldContainer.querySelectorAll("[data-config-row]")) {
                    const key = String(rowElement.querySelector('[data-column-key="__key"]')?.value || "").trim();
                    const rowValue = String(rowElement.querySelector('[data-column-key="__value"]')?.value || "").trim();
                    if (key && rowValue) {
                        value[key] = rowValue;
                    }
                }
                break;
            }
            case "key-multi-value-list": {
                value = {};
                for (const rowElement of fieldContainer.querySelectorAll("[data-config-row]")) {
                    const key = String(rowElement.querySelector('[data-column-key="__key"]')?.value || "").trim();
                    const selectedValues = [...rowElement.querySelectorAll('input[type="checkbox"][data-column-key="__value"]:checked')].map((input) => parseOptionValue(input.value));
                    if (key && selectedValues.length) {
                        value[key] = selectedValues;
                    }
                }
                break;
            }
            case "object-list":
                value = readObjectRows(fieldContainer, field);
                break;
            case "grouped-object-list": {
                value = {};
                for (const row of readObjectRows(fieldContainer, field)) {
                    const groupValue = String(row[field.group_key] || "").trim();
                    if (!groupValue) {
                        continue;
                    }
                    const item = { ...row };
                    delete item[field.group_key];
                    if (!rowHasMeaningfulData(item, field.meaningful_keys || [])) {
                        continue;
                    }
                    if (!value[groupValue]) {
                        value[groupValue] = [];
                    }
                    value[groupValue].push(item);
                }
                break;
            }
            default: {
                const input = fieldContainer.querySelector(`[data-config-key="${field.key}"]`);
                if (!input) {
                    continue;
                }
                value = readPrimitiveValue(input, field);
                break;
            }
        }

        if (value === undefined) {
            continue;
        }
        config[field.key] = value;
    }
    return config;
}

export function validateStructuredPluginConfig(container, plugin) {
    const schema = normalizeSchema(plugin);
    for (const field of schema) {
        const fieldContainer = container.querySelector(`[data-config-field="${field.key}"]`);
        if (!fieldContainer) {
            continue;
        }
        if (field.type === "object-list") {
            const rows = readObjectRows(fieldContainer, field);
            for (const row of rows) {
                const validationMessage = validateObjectRow(field, row);
                if (validationMessage) {
                    return {
                        valid: false,
                        message: `${field.label}存在未完成的规则：${validationMessage}`,
                    };
                }
            }
            const collectionValidationMessage = validateObjectRowsCollection(field, rows);
            if (collectionValidationMessage) {
                return {
                    valid: false,
                    message: `${field.label}存在冲突规则：${collectionValidationMessage}`,
                };
            }
        }
    }

    if (container.querySelector("[data-config-row-editor]")) {
        return {
            valid: false,
            message: "存在尚未保存的规则，请先保存或取消当前编辑行",
        };
    }

    return { valid: true, message: "" };
}

export function handleStructuredConfigAction(container, plugin, event) {
    const button = event.target.closest("button[data-config-form-action]");
    if (!button) {
        return false;
    }
    const action = button.dataset.configFormAction;
    const field = findField(plugin, button.dataset.field || "");
    if (!field) {
        return false;
    }
    const fieldContainer = container.querySelector(`[data-config-field="${field.key}"]`);
    const rowsContainer = fieldContainer?.querySelector("[data-config-rows]");
    if (!fieldContainer || !rowsContainer) {
        return false;
    }

    if (field.type === "object-list" && field.display_mode === "table") {
        if (action === "toggle-room-member-picker") {
            void openRoomMemberPicker(button, field);
            return true;
        }
        if (action === "apply-room-member-picker") {
            return applyRoomMemberPickerSelection(button, field);
        }
        if (action === "close-room-member-picker") {
            return closeRoomMemberPicker(button, field);
        }
        if (action === "remove-row") {
            button.closest("[data-config-row]")?.remove();
            syncObjectTableState(fieldContainer);
            return true;
        }
        if (action === "edit-row") {
            const rowElement = button.closest("[data-config-row]");
            if (!rowElement) {
                return false;
            }
            const rowValue = parseStoredRowValue(rowElement.dataset.rowValue);
            return beginObjectTableRowEdit(fieldContainer, field, rowValue, rowValue, rowElement);
        }
        if (action === "save-row") {
            const editorRow = button.closest("[data-config-row-editor]");
            return editorRow ? commitObjectTableRow(editorRow, fieldContainer, field) : false;
        }
        if (action === "cancel-row") {
            const editorRow = button.closest("[data-config-row-editor]");
            return editorRow ? cancelObjectTableRow(editorRow, fieldContainer, field) : false;
        }
        if (action === "add-row") {
            return beginObjectTableRowEdit(fieldContainer, field, {});
        }
        return false;
    }

    if (action === "remove-row") {
        button.closest("[data-config-row]")?.remove();
        return true;
    }

    if (action !== "add-row") {
        return false;
    }

    if (field.type === "key-value-list") {
        rowsContainer.insertAdjacentHTML("beforeend", renderKeyValueRow(field));
        return true;
    }
    if (field.type === "key-multi-value-list") {
        rowsContainer.insertAdjacentHTML("beforeend", renderKeyMultiValueRow(field));
        return true;
    }
    if (field.type === "object-list" || field.type === "grouped-object-list") {
        rowsContainer.insertAdjacentHTML("beforeend", renderObjectRow(field, {}));
        return true;
    }
    return false;
}