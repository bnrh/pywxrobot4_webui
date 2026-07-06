/** 消息/日志状态徽章样式映射。 */

export function getStatusTone(status) {
    if (status === "processed") {
        return "good";
    }
    if (status === "failed" || status === "rejected") {
        return "bad";
    }
    return "";
}

export function getLogTone(level) {
    const normalized = String(level || "").toUpperCase();
    if (normalized === "ERROR") {
        return "bad";
    }
    if (normalized === "WARNING") {
        return "warn";
    }
    if (normalized === "INFO") {
        return "good";
    }
    return "";
}

export function getLogLevelClass(level) {
    const normalized = String(level || "").toUpperCase();
    if (normalized === "CRITICAL") {
        return "level-critical";
    }
    if (normalized === "ERROR") {
        return "level-error";
    }
    if (normalized === "WARNING") {
        return "level-warning";
    }
    if (normalized === "INFO") {
        return "level-info";
    }
    if (normalized === "DEBUG") {
        return "level-debug";
    }
    return "level-raw";
}
