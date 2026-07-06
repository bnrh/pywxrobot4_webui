"""FastAPI 路由共享上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app_builders import AppBuilders
from runtime import PluginRuntime


@dataclass(slots=True)
class AppContext:
    runtime: PluginRuntime
    builders: AppBuilders

    def with_mutation_payload(self, reload_state: dict[str, Any]) -> dict[str, Any]:
        return {
            **reload_state,
            "overview": self.builders.build_overview(),
            "plugins": self.builders.build_plugin_payload(),
            "settings": self.builders.build_settings_payload(),
        }
