import { resolveSelectedMessageId } from "../../static/js/message-view.js";

const messages = [
    { internal_id: 10 },
    { internal_id: 20 },
];

if (resolveSelectedMessageId(messages, 20, false) !== 20) {
    throw new Error("existing selection should be preserved when auto-follow is off");
}
if (resolveSelectedMessageId(messages, 99, false) !== 10) {
    throw new Error("invalid selection should fall back to the newest message");
}
if (resolveSelectedMessageId(messages, null, true) !== 10) {
    throw new Error("auto-follow should select the newest message");
}
if (resolveSelectedMessageId([], 5, true) !== 5) {
    throw new Error("empty list should keep the previous selection");
}

console.log("message-view ok");
