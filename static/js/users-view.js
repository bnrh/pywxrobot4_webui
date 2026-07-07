/** 用户心跳页渲染。 */

import { escapeHtml, normalizeInlineText } from "./dom-utils.js";

export function renderUsersView(elements, userPayload) {
    if (!userPayload) {
        elements.userGrid.innerHTML = '<div class="empty-state">还没有可展示的用户信息。</div>';
        return;
    }

    const users = Array.isArray(userPayload.users) ? userPayload.users : [];

    if (!userPayload.enabled) {
        elements.userGrid.innerHTML = '<div class="empty-state">心跳检测已关闭，请在系统设置中将心跳间隔设置为大于 0 的秒数。</div>';
        return;
    }

    if (!users.length) {
        elements.userGrid.innerHTML = userPayload.healthy === false
            ? '<div class="empty-state">心跳检测执行失败，暂时无法获取登录账号，请检查主服务连接。</div>'
            : '<div class="empty-state">当前未获取到任何登录账号。</div>';
        return;
    }

    elements.userGrid.innerHTML = users.map((user, index) => {
        const nickname = normalizeInlineText(user.nickname || "");
        const userTitle = `用户${index + 1}`;
        const wechatId = normalizeInlineText(user.wxh || "") || "未设置微信号";
        return `
            <article class="user-card">
                <div class="user-card-head">
                    <div>
                        <h4 class="user-name">${escapeHtml(userTitle)}</h4>
                    </div>
                </div>
                <div class="user-info-list">
                    <div class="user-info-item"><span class="user-info-label">昵称</span><span class="user-info-value">${escapeHtml(nickname || "未提供")}</span></div>
                    <div class="user-info-item"><span class="user-info-label">微信号</span><span class="user-info-value">${escapeHtml(wechatId === "未设置微信号" ? "未提供" : wechatId)}</span></div>
                    <div class="user-info-item"><span class="user-info-label">wxid</span><span class="user-info-value user-info-code">${escapeHtml(normalizeInlineText(user.wxid || "") || "未提供")}</span></div>
                    <div class="user-info-item"><span class="user-info-label">wxpid</span><span class="user-info-value">${escapeHtml(user.wxpid !== undefined && user.wxpid !== null && user.wxpid !== "" ? String(user.wxpid) : "未提供")}</span></div>
                </div>
            </article>
        `;
    }).join("");
}
