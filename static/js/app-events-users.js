/** 用户管理事件绑定。 */

export function registerUsersEvents(actions) {
    const { elements } = actions;

elements.refreshUsersButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新用户...");
        await actions.loadUsers();
        actions.setStatus("用户信息已刷新", "good");
    } catch (error) {
        actions.setStatus(`用户刷新失败：${error.message}`, "bad");
    }
});
}
