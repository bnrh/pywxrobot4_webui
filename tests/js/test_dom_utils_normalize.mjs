/** Smoke: shared normalize helpers stay aligned with backend semantics. */

const {
    isTruthy,
    normalizeInlineText,
    normalizeText,
} = await import("../../static/js/dom-utils.js");

if (normalizeText("  hello  ") !== "hello") {
    throw new Error("normalizeText should trim edges");
}
if (normalizeInlineText("  hello   world\n") !== "hello world") {
    throw new Error("normalizeInlineText should collapse whitespace");
}
if (!isTruthy("yes") || !isTruthy("是") || isTruthy("no") || isTruthy(null, false) !== false) {
    throw new Error("isTruthy should parse common truthy/falsy forms");
}
if (isTruthy(null, true) !== true) {
    throw new Error("isTruthy should honor default for empty values");
}

console.log("dom-utils normalize helpers ok");
