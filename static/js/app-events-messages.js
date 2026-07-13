/** 消息中心事件绑定。 */

export function registerMessagesEvents(actions) {
    const { elements } = actions;
    const state = () => actions.getState();

elements.refreshMessagesButton.addEventListener("click", async () => {
    try {
        actions.setStatus("正在刷新消息...");
        await actions.loadMessages();
        actions.setStatus("消息已刷新", "good");
    } catch (error) {
        actions.setStatus(`消息刷新失败：${error.message}`, "bad");
    }
});

elements.messageList.addEventListener("click", (event) => {
    const target = event.target.closest("[data-message-id]");
    if (!target) {
        return;
    }
    state().selectedMessageId = Number(target.dataset.messageId);
    state().messageAutoFollow = state().selectedMessageId === state().messages[0]?.internal_id;
    actions.renderMessages();
});

elements.messageDetail.addEventListener("click", async (event) => {
    const button = event.target.closest('button[data-action="copy-message-payload"]');
    if (!button) {
        return;
    }

    const selected = state().messages.find((message) => message.internal_id === state().selectedMessageId);
    if (!selected) {
        actions.setStatus("未找到当前消息原始负载", "bad");
        return;
    }

    try {
        await actions.copyTextToClipboard(actions.formatJson(selected.payload));
        actions.setStatus("原始负载已复制", "good");
    } catch (error) {
        actions.setStatus(`复制原始负载失败：${error.message}`, "bad");
    }
});
}
