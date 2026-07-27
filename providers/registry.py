"""Provider registry — scan plugins/ for provider definitions."""
import importlib.util
import os
from pathlib import Path
from .base import ProviderProfile

_REGISTRY: dict[str, ProviderProfile] = {}


def register(profile: ProviderProfile):
    _REGISTRY[profile.name] = profile


def get(name: str) -> ProviderProfile | None:
    return _REGISTRY.get(name)


def list_providers() -> list[ProviderProfile]:
    return list(_REGISTRY.values())


def discover_providers():
    """Scan plugins/model-providers/ for *.py and import them."""
    plugins_dir = Path(__file__).parent.parent / "plugins" / "model-providers"
    if not plugins_dir.exists():
        return
    for f in plugins_dir.glob("*.py"):
        if f.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f.stem, f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
