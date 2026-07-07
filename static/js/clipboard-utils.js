/** 剪贴板与 JSON 输入解析。 */

export function parseJsonObjectInput(value, label) {
    const rawText = String(value ?? "").trim();
    if (!rawText) {
        return {};
    }
    let parsed;
    try {
        parsed = JSON.parse(rawText);
    } catch {
        throw new Error(`${label} 必须是合法 JSON 对象`);
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(`${label} 必须是 JSON 对象`);
    }
    return parsed;
}

export async function copyTextToClipboard(value) {
    const text = String(value ?? "");
    if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "readonly");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
    document.body.append(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
}
