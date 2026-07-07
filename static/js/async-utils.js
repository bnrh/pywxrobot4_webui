/** 通用异步工具。 */

export function waitForDuration(ms) {
    return new Promise((resolve) => {
        window.setTimeout(resolve, ms);
    });
}
