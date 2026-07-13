"""AI assistant package — public API compatible with former ai_assistant module."""

from .chat import run_ai_assistant
from .constants import (
    AI_ASSISTANT_SETTINGS_KEY,
    DEFAULT_AI_ASSISTANT_SETTINGS,
    DEFAULT_SYSTEM_PROMPT,
    PROVIDER_CATALOG,
)
from .providers import load_openai_compatible_model_options, run_openai_compatible_chat_completion
from .settings import (
    build_ai_assistant_payload,
    get_default_ai_assistant_settings,
    get_tool_schemas,
    is_write_tool,
    list_available_tools,
    normalize_ai_assistant_settings,
    resolve_ai_assistant_prompt_plugin,
)
from .tool_registry import LOCAL_TOOL_REGISTRY, TOOL_REGISTRY, get_tool_registry

__all__ = [
    "AI_ASSISTANT_SETTINGS_KEY",
    "DEFAULT_AI_ASSISTANT_SETTINGS",
    "DEFAULT_SYSTEM_PROMPT",
    "LOCAL_TOOL_REGISTRY",
    "PROVIDER_CATALOG",
    "TOOL_REGISTRY",
    "build_ai_assistant_payload",
    "get_default_ai_assistant_settings",
    "get_tool_registry",
    "get_tool_schemas",
    "is_write_tool",
    "list_available_tools",
    "load_openai_compatible_model_options",
    "normalize_ai_assistant_settings",
    "resolve_ai_assistant_prompt_plugin",
    "run_ai_assistant",
    "run_openai_compatible_chat_completion",
]
