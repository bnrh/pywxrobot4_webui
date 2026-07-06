import pytest

from manager import PluginManager, PluginSpec
from pathlib import Path


def test_describe_plugin_does_not_force_reload_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    def fake_load(spec: PluginSpec, force_reload: bool = False):
        calls.append(force_reload)
        raise AssertionError("should not load module in this unit test")

    monkeypatch.setattr(PluginManager, "_load_python_module", staticmethod(fake_load))

    spec = PluginSpec(module_name="plugins.auto_download_image", path=Path("plugins/auto_download_image.py"), stem="auto_download_image")
    with pytest.raises(AssertionError):
        PluginManager.describe_plugin(spec)

    assert calls == [False]
