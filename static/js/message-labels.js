/** 消息类型标签（与服务端 message_types 对齐，启动时可从 API 覆盖）。 */

import { api } from "./api.js";

const MESSAGE_TYPE_LABELS = {
    0x0: "朋友圈",
    0x1: "文本",
    0x3: "图片",
    0x22: "语音",
    0x25: "好友请求",
    0x2A: "名片",
    0x2B: "视频",
    0x2F: "表情",
    0x30: "位置",
    0x31: "XML消息",
    0x32: "音视频通话",
    0x33: "微信初始化",
    0x34: "通话状态通知",
    0x35: "通话邀请",
    0x3E: "小视频",
    0x42: "微信红包",
    0x2710: "通知消息",
    0x2712: "系统消息",
    0x100000031: "百度视频消息",
    0x200000031: "微信运动消息",
    0x210000031: "小程序消息",
    0x240000031: "BOSS直聘消息",
    0x280000031: "聊天记录消息",
    0x2A0000031: "公众号名片消息",
    0x300000031: "QQ音乐消息",
    0x330000031: "视频号消息",
    0x3900000031: "引用消息",
    0x3F0000031: "视频号卡片消息",
    0x400000031: "哔哩哔哩视频消息",
    0x440000031: "微信游戏消息",
    0x4A00000031: "文件下载完成消息",
    0x500000031: "链接消息",
    0x570000031: "群公告消息",
    0x5E0000031: "商品橱窗消息",
    0x600000031: "文件消息",
    0x650000031: "王者荣耀消息",
    0x7D000000031: "转账消息",
    0x7D300000031: "红包封面消息",
    0x1100000031: "位置共享消息",
    0x1300000031: "合并消息",
    0x1500000031: "微信运动步数消息",
};

export async function syncMessageTypeLabels() {
    try {
        const payload = await api.getMessageTypes();
        const labels = payload?.labels;
        if (!labels || typeof labels !== "object") {
            return;
        }
        for (const [typeCode, label] of Object.entries(labels)) {
            const numericCode = Number(typeCode);
            if (!Number.isNaN(numericCode) && label) {
                MESSAGE_TYPE_LABELS[numericCode] = String(label);
            }
        }
    } catch {
        // 保留内置标签作为兜底
    }
}

export function getPayloadValue(message, ...keys) {
    const payload = message?.payload || {};
    for (const key of keys) {
        const value = payload[key];
        if (value !== undefined && value !== null && value !== "") {
            return value;
        }
    }
    return "";
}

export function getMessageTypeCode(message) {
    const candidates = [
        message.local_type,
        message.msg_type,
        getPayloadValue(message, "msg_type", "local_type"),
    ];
    for (const value of candidates) {
        if (value === "" || value === null || value === undefined) {
            continue;
        }
        const parsed = Number(value);
        if (!Number.isNaN(parsed)) {
            return parsed;
        }
    }
    return null;
}

export function getMessageTypeLabel(message) {
    const typeCode = getMessageTypeCode(message);
    if (typeCode === null) {
        return "未知类型";
    }
    return MESSAGE_TYPE_LABELS[typeCode] || `类型 ${typeCode}`;
}
