/** DOM 转义、文本归一化与高亮工具。 */

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
    const text = String(value).trim().toLowerCase();
    if (TRUTHY_VALUES.has(text)) {
        return true;
    }
    if (FALSY_VALUES.has(text)) {
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
