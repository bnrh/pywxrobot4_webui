/** 控制台侧边栏 Tab 元数据。 */

export const tabMeta = {
    dashboard: {
        label: "仪表盘",
        title: "运行概览",
        description: "集中查看插件服务状态、消息积压和待处理变更。",
    },
    messages: {
        label: "消息中心",
        title: "最新消息",
        description: "查看最近收到的消息以及插件处理结果。",
    },
    users: {
        label: "用户管理",
        title: "登录账号",
        description: "查看心跳检测获取到的登录账号信息与最近一次检测状态。",
    },
    features: {
        label: "功能插件",
        title: "功能插件",
        description: "按需执行功能插件。",
    },
    "ai-assistant": {
        label: "智能插件",
        title: "AI 工具代理",
        description: "配置 AI 厂商并让模型调用 pywxrobot4 工具完成查询与操作。",
    },
    plugins: {
        label: "消息插件",
        title: "消息插件",
        description: "统一管理依赖消息的插件。配置会写入 SQLite，并在支持的范围内立即热重载。",
    },
    "plugin-logs": {
        label: "插件日志",
        title: "插件输出",
        description: "查看所有插件输出的结构化日志，并按插件快速筛选。",
    },
    settings: {
        label: "系统设置",
        title: "全局设置",
        description: "维护服务参数、处理策略与运行时行为。",
    },
    logs: {
        label: "日志中心",
        title: "最新日志",
        description: "查看最近生成的日志文件和最后输出内容。",
    },
};
