/** DOM 转义、文本归一化、安全构建与高亮工具。 */

export function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

/** 去掉首尾空白；对应后端 utils.normalize.normalize_text。 */
export function normalizeText(value) {
    if (value == null || value === "") {
        return "";
    }
    return String(value).trim();
}

/** 折叠连续空白；对应后端 utils.normalize.collapse_whitespace。 */
export function normalizeInlineText(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim();
}

const TRUTHY_VALUES = new Set(["1", "true", "yes", "on", "y", "是"]);
const FALSY_VALUES = new Set(["", "0", "false", "no", "off", "n", "否"]);

/** 解析常见真值表达；对应后端 utils.normalize.is_truthy。 */
export function isTruthy(value, defaultValue = false) {
    if (value == null || value === "") {
        return Boolean(defaultValue);
    }
    if (typeof value === "boolean") {
        return value;
    }
    if (typeof value === "number") {
        return value !== 0;
    }
    const textValue = String(value).trim().toLowerCase();
    if (TRUTHY_VALUES.has(textValue)) {
        return true;
    }
    if (FALSY_VALUES.has(textValue)) {
        return false;
    }
    return Boolean(defaultValue);
}

export function formatJson(value) {
    return JSON.stringify(value ?? {}, null, 2);
}

function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function highlightText(value, queries = []) {
    const source = String(value ?? "");
    const tokens = [...new Set(queries.map((query) => normalizeInlineText(query)).filter(Boolean))];
    if (!tokens.length) {
        return escapeHtml(source);
    }
    const pattern = new RegExp(`(${tokens.map(escapeRegExp).join("|")})`, "gi");
    return source.split(pattern).map((segment, index) => (
        index % 2 === 1
            ? `<mark class="log-mark">${escapeHtml(segment)}</mark>`
            : escapeHtml(segment)
    )).join("");
}

const BOOLEAN_TRUE_ATTRS = new Set(["checked", "disabled", "selected", "readonly", "required", "multiple", "hidden"]);

function normalizeChildren(children) {
    if (children == null) {
        return [];
    }
    const list = Array.isArray(children) ? children : [children];
    return list.flat(Infinity).filter((item) => item != null && item !== false);
}

function appendChild(parent, child) {
    if (child == null || child === false) {
        return;
    }
    if (typeof child === "string" || typeof child === "number") {
        parent.appendChild(document.createTextNode(String(child)));
        return;
    }
    if (child instanceof Node) {
        parent.appendChild(child);
    }
}

export function text(value) {
    return document.createTextNode(String(value ?? ""));
}

export function fragment(children = []) {
    const node = document.createDocumentFragment();
    for (const child of normalizeChildren(children)) {
        appendChild(node, child);
    }
    return node;
}

export function el(tag, attrs = null, children = null) {
    const node = document.createElement(tag);
    if (attrs && typeof attrs === "object") {
        for (const [key, value] of Object.entries(attrs)) {
            if (value == null || value === false) {
                continue;
            }
            if (key === "className" || key === "class") {
                node.className = String(value);
                continue;
            }
            if (key === "dataset" && value && typeof value === "object") {
                for (const [dataKey, dataValue] of Object.entries(value)) {
                    if (dataValue == null) {
                        continue;
                    }
                    node.dataset[dataKey] = String(dataValue);
                }
                continue;
            }
            if (key === "text") {
                node.textContent = String(value);
                continue;
            }
            if (key.startsWith("on") && typeof value === "function") {
                node.addEventListener(key.slice(2).toLowerCase(), value);
                continue;
            }
            if (BOOLEAN_TRUE_ATTRS.has(key)) {
                if (value) {
                    node.setAttribute(key, "");
                }
                continue;
            }
            node.setAttribute(key, String(value));
        }
    }
    for (const child of normalizeChildren(children)) {
        appendChild(node, child);
    }
    return node;
}

export function clearChildren(node) {
    if (!node) {
        return;
    }
    while (node.firstChild) {
        node.removeChild(node.firstChild);
    }
}

export function replaceChildren(node, ...children) {
    if (!node) {
        return;
    }
    clearChildren(node);
    for (const child of normalizeChildren(children)) {
        appendChild(node, child);
    }
}

export function badge(label, className = "") {
    const classes = ["badge", className].filter(Boolean).join(" ");
    return el("span", { className: classes }, text(label));
}

export function emptyState(message) {
    return el("div", { className: "empty-state" }, text(message));
}

export function detailMeta(message) {
    return el("div", { className: "detail-meta" }, text(message));
}
