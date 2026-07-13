from __future__ import annotations

from core.config import PluginServiceSettings
from server import create_app


def _collect_route_paths(app) -> set[str]:
    paths: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
    return paths


def test_create_app_registers_expected_routes() -> None:
    app = create_app(PluginServiceSettings())
    paths = _collect_route_paths(app)

    for expected_path in (
        "/",
        "/health",
        "/api/overview",
        "/api/messages",
        "/api/settings",
        "/api/ai-assistant",
        "/api/plugins",
        "/api/events/stream",
        "/api/message-types",
        "/messages",
    ):
        assert expected_path in paths
