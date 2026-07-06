/** DOM 转义与文本高亮工具。 */

export function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

export function normalizeInlineText(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim();
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
