/** Smoke: safe DOM builders escape text content and attributes. */

import { Window } from "happy-dom";

const window = new Window();
globalThis.window = window;
globalThis.document = window.document;
globalThis.Node = window.Node;

const {
    badge,
    el,
    emptyState,
    escapeHtml,
    replaceChildren,
    text,
} = await import("../../static/js/dom-utils.js");

const node = el("button", {
    className: "message-item",
    type: "button",
    dataset: { messageId: "12" },
    title: `<img src=x onerror=alert(1)>`,
}, [
    text(`hello <script>alert(1)</script>`),
    badge("ok", "good"),
]);

if (node.tagName !== "BUTTON") {
    throw new Error("el should create the requested element");
}
if (node.dataset.messageId !== "12") {
    throw new Error("dataset attrs should map to data-*");
}
if (node.getAttribute("title") !== `<img src=x onerror=alert(1)>`) {
    throw new Error("attribute values should be set via DOM APIs, not HTML parsing");
}
if (node.textContent.includes("<script>") === false || node.querySelector("script")) {
    throw new Error("text children must not create script elements");
}
if (node.querySelector(".badge.good")?.textContent !== "ok") {
    throw new Error("badge helper should render class and text");
}

const host = document.createElement("div");
replaceChildren(host, emptyState("空状态 <b>x</b>"));
if (host.children.length !== 1 || host.querySelector("b")) {
    throw new Error("emptyState / replaceChildren should not parse HTML markup");
}
if (host.textContent !== "空状态 <b>x</b>") {
    throw new Error("emptyState should keep literal text");
}
if (escapeHtml("<a>") !== "&lt;a&gt;") {
    throw new Error("escapeHtml should still escape for legacy string callers");
}

console.log("dom-builder helpers ok");
