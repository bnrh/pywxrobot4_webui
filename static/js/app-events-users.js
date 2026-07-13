/** 用户管理事件绑定。 */

import { bindOnce } from "./dom-bind.js";

export function registerUsersEvents(actions) {
    const { elements } = actions;

    bindOnce(elements.refreshUsersButton, "users.refresh", "click", async () => {
        try {
            actions.setStatus("正在刷新用户...");
            await actions.loadUsers();
            actions.setStatus("用户信息已刷新", "good");
        } catch (error) {
            actions.setStatus(`用户刷新失败：${error.message}`, "bad");
        }
    });
}
