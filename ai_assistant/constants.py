"""AI assistant constants and provider catalog."""

from __future__ import annotations

from pathlib import Path

AI_ASSISTANT_SETTINGS_KEY = "ai_assistant_settings"
MAX_CONVERSATION_MESSAGES = 16
MAX_TOOL_RESULT_ITEMS = 40
MAX_TOOL_RESULT_STRING_LENGTH = 1600
DEFAULT_PROVIDER_REQUEST_TIMEOUT_SECONDS = 180.0
MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS = 600.0
RETRYABLE_PROVIDER_STATUS_CODES = {502, 503, 504}
DEFAULT_PROVIDER_RETRY_COUNT = 1
DEFAULT_PROVIDER_RETRY_DELAY_SECONDS = 1.0

DEFAULT_SYSTEM_PROMPT = (
    "你是 wxrobot_api 的智能插件助手。"
    "当用户提出微信自动化或查询需求时，优先使用提供给你的 wxrobot_api 工具完成任务。"
    "当任务依赖当前时间、日期、星期或相对时间窗口时，不要猜测当前时刻，优先调用 current_datetime 获取精确时间。"
    "如果信息不足以安全执行写操作（例如发送消息、修改标签、邀请进群、删除成员），先向用户索取必要参数，"
    "不要臆造 wxid、roomid、wxpid、文件路径或消息内容。"
    "对于只读查询，尽量先调用工具获取事实，再给出简洁结论。"
    "当工具执行失败时，明确说明失败原因并给出下一步建议。"
)

INTERNAL_TOOL_ROUTING_PROMPT = (
    "工具选择规则："
    "当用户问题涉及现在几点、今天/昨天/明天、最近几小时、截至目前、本周、本月或其他相对时间判断时，"
    "优先调用 current_datetime 获取精确当前时间，再决定是否调用其他工具。"
    "当用户询问两个群聊是否有重复成员、共同成员、相同成员、重叠成员或群成员交集时，"
    "优先调用 count_shared_room_members 或 list_shared_room_members。"
    "对于这类问题，不要先调用 get_room_members 或 get_room_members_summary 这类全量列表工具，"
    "除非上述聚合工具不可用或执行失败。"
    "如果用户只问有没有、多少或统计结果，先用 count_shared_room_members；"
    "如果用户要名单、明细或继续翻页，优先用 list_shared_room_members。"
    "当用户询问某个群里有多少成员是其好友、某个群里哪些成员是其好友、统计群好友数量、分页列出群好友时，"
    "优先调用 count_room_friend_members 或 list_room_friend_members。"
    "对于这类问题，不要先调用 get_user_list、get_room_members、get_user_list_summary、get_room_members_summary，"
    "除非上述聚合工具不可用或执行失败。"
    "如果用户只问数量，先用 count_room_friend_members；"
    "如果用户要名单、明细或继续翻页，优先用 list_room_friend_members。"
)

PROVIDER_CATALOG = {
    "zhipu": {
        "key": "zhipu",
        "label": "智谱",
        "description": "GLM 系列，接口参数固定内置在代码中。",
        "default_model": "glm-4-plus",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "chat_path": "/chat/completions",
        "models_path": "/models",
        "allow_custom_base_url": False,
        "custom_headers": {},
        "extra_body": {},
    },
    "deepseek": {
        "key": "deepseek",
        "label": "DeepSeek",
        "description": "DeepSeek Chat，接口参数固定内置在代码中。",
        "default_model": "deepseek-chat",
        "default_base_url": "https://api.deepseek.com/v1",
        "chat_path": "/chat/completions",
        "models_path": "/models",
        "allow_custom_base_url": False,
        "custom_headers": {},
        "extra_body": {},
    },
    "minimax": {
        "key": "minimax",
        "label": "MiniMax",
        "description": "MiniMax，接口参数固定内置在代码中。",
        "default_model": "MiniMax-Text-01",
        "default_base_url": "https://api.minimax.chat/v1",
        "chat_path": "/chat/completions",
        "models_path": "/models",
        "allow_custom_base_url": False,
        "custom_headers": {},
        "extra_body": {},
    },
    "openai": {
        "key": "openai",
        "label": "通用 OpenAI",
        "description": "适配任意 OpenAI-compatible 网关，支持自定义 Base URL。",
        "default_model": "gpt-4o-mini",
        "default_base_url": "https://api.openai.com/v1",
        "chat_path": "/chat/completions",
        "models_path": "/models",
        "allow_custom_base_url": True,
        "custom_headers": {},
        "extra_body": {},
    },
}

DEFAULT_AI_ASSISTANT_SETTINGS = {
    "active_provider": "zhipu",
    "active_prompt_plugin_id": "default-smart-plugin",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "temperature": 0.2,
    "max_tool_rounds": 20,
    "allow_write_tools": False,
    "prompt_plugins": [],
    "providers": {
        key: {
            "configs": [],
        }
        for key, provider in PROVIDER_CATALOG.items()
    },
}

_JSON_OBJECT_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": True,
}

MCP_SERVER_SOURCE_CANDIDATES = (
    Path(__file__).resolve().parent.parent.parent / "wxrobot_api" / "api" / "mcp_server.py",
    Path(__file__).resolve().parent.parent / "wxrobot_api" / "api" / "mcp_server.py",
)
