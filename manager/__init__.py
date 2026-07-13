"""Plugin manager package — public API compatible with former manager module."""

from .constants import PLUGIN_DIR, PYTHON_SDK_VERSION
from .manager import PluginManager
from .normalize import PluginSpec
from .python_plugin import PythonPlugin

__all__ = [
    "PLUGIN_DIR",
    "PYTHON_SDK_VERSION",
    "PluginManager",
    "PluginSpec",
    "PythonPlugin",
]
