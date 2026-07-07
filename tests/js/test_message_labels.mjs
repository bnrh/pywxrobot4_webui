import {
    getMessageTypeCode,
    getMessageTypeLabel,
    getPayloadValue,
} from "../../static/js/message-labels.js";

const message = {
    local_type: 1,
    payload: {
        create_time: 1710000000,
        text: "hello",
        empty_field: "",
    },
};

if (getMessageTypeCode(message) !== 1) {
    throw new Error("message type code should prefer local_type");
}
if (getMessageTypeLabel(message) !== "文本") {
    throw new Error(`unexpected message type label: ${getMessageTypeLabel(message)}`);
}
if (getPayloadValue(message, "missing", "create_time") !== 1710000000) {
    throw new Error("payload value should fall back to later keys");
}
if (getPayloadValue(message, "empty_field", "text") !== "hello") {
    throw new Error("payload value should skip empty strings");
}

console.log("message-labels ok");
