"""
Pluginsystemet: laddar plugins från mappen plugins/ och anropar dem
när saker händer på servern.

Ett plugin är en vanlig Python-fil med funktioner som har särskilda namn,
till exempel:

    def on_player_spawned(lobby, player):
        player.send_chat("Välkommen!")

Servern letar efter plugins så här i mappen plugins/:

  - halsning.py           en fil = ett plugin
  - mitt_plugin/          en mapp med __init__.py = ett plugin
  - Mina-Plugins-main/    en mapp utan __init__.py = en samling plugins,
                          varje .py-fil i den är ett eget plugin
                          (bra om man laddar ner ett helt plugin-repo)

Filer och mappar som börjar med _ hoppas över. Byt namn på
"_tarning.py" till "tarning.py" för att slå på det pluginet.

Se plugins/README.md för alla händelser och vad ett plugin kan göra.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, List

from .config import PROJECT_DIR

log = logging.getLogger("plugin")

PLUGIN_DIR = PROJECT_DIR / "plugins"

# Alla händelser som ett plugin kan lyssna på. Se plugins/README.md.
EVENTS = (
    "on_server_started",
    "on_game_created",
    "on_player_joined",
    "on_player_spawned",
    "on_player_left",
    "on_host_changed",
    "on_chat",
    "on_color_changed",
    "on_settings_changed",
    "on_privacy_changed",
    "on_game_started",
    "on_game_ended",
)


@dataclass
class LoadedPlugin:
    name: str
    description: str
    path: Path
    module: ModuleType
    version: str = ""
    author: str = ""
    warnings: List[str] = field(default_factory=list)

    def handles(self, event: str) -> bool:
        return callable(getattr(self.module, event, None))

    def __str__(self) -> str:
        text = self.name
        if self.version:
            text += f" {self.version}"
        if self.author:
            text += f" av {self.author}"
        return text


@dataclass
class FailedPlugin:
    file: str
    error: str  # kort felmeddelande
    details: str  # hela felet (traceback), för att kunna hitta vad som är fel


class PluginManager:
    def __init__(self, folder: Path = PLUGIN_DIR):
        self.folder = folder
        self.plugins: List[LoadedPlugin] = []
        self.failed: List[FailedPlugin] = []
        self.enabled = True

    # --- Ladda -----------------------------------------------------------

    def load_all(self) -> None:
        """Laddar alla plugins. Vad som laddades visas sedan med summary()."""
        if not self.folder.is_dir():
            log.debug("Ingen plugins-mapp hittades, kör utan plugins.")
            return

        for entry in sorted(self.folder.iterdir(), key=lambda p: p.name.lower()):
            if self._skip(entry):
                continue
            if entry.is_file() and entry.suffix == ".py":
                self._load(entry)
            elif entry.is_dir():
                if (entry / "__init__.py").exists():
                    self._load(entry / "__init__.py", package_dir=entry)
                else:
                    # En samling plugins, t.ex. ett nedladdat plugin-repo.
                    for file in sorted(entry.glob("*.py"), key=lambda p: p.name.lower()):
                        if not self._skip(file):
                            self._load(file)


    @staticmethod
    def _skip(path: Path) -> bool:
        return path.name.startswith(("_", ".")) or path.name == "__pycache__"

    def _load(self, file: Path, package_dir: Any = None) -> None:
        source = package_dir or file
        module_name = "emergency_plugins." + re.sub(r"\W", "_", str(source.relative_to(self.folder)))
        try:
            spec = importlib.util.spec_from_file_location(
                module_name,
                file,
                submodule_search_locations=[str(package_dir)] if package_dir else None,
            )
            if spec is None or spec.loader is None:
                raise ImportError("kunde inte läsa filen")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as error:
            sys.modules.pop(module_name, None)
            self.failed.append(
                FailedPlugin(
                    file=str(source.relative_to(self.folder)),
                    error=f"{type(error).__name__}: {error}",
                    details=traceback.format_exc(),
                )
            )
            return

        plugin = LoadedPlugin(
            name=str(getattr(module, "NAME", source.stem)),
            description=str(getattr(module, "DESCRIPTION", "")),
            path=source,
            module=module,
            version=str(getattr(module, "VERSION", "")),
            author=str(getattr(module, "AUTHOR", "")),
        )

        events = [e for e in EVENTS if plugin.handles(e)]
        unknown = [
            attr
            for attr in dir(module)
            if attr.startswith("on_") and attr not in EVENTS and callable(getattr(module, attr))
        ]
        self.plugins.append(plugin)
        log.debug("Laddade pluginet %s från %s", plugin, source)
        if not events:
            plugin.warnings.append("lyssnar inte på några händelser")
        for attr in unknown:
            plugin.warnings.append(f"funktionen {attr} är ingen händelse som finns")

    # --- Visa vad som laddades -------------------------------------------

    def summary(self) -> List[str]:
        """Raderna i rutan LADDAR PLUGINS som visas när servern har startat."""
        if not self.enabled:
            return ["Plugins är avstängda i config.json."]

        count = len(self.plugins)
        lines = [f"Laddat {count} plugin{'s' if count != 1 else ''}..."]
        for plugin in self.plugins:
            lines.append(f"  - {plugin}")
            if plugin.description:
                lines.append(f"      {plugin.description}")
            for warning in plugin.warnings:
                lines.append(f"      Obs: {warning}")
        if count == 0:
            lines.append("  Lägg plugins i mappen plugins/ (se plugins/README.md).")

        if self.failed:
            lines.append("")
            lines.append(f"Kunde inte ladda {len(self.failed)} plugin{'s' if len(self.failed) != 1 else ''}:")
            for failure in self.failed:
                lines.append(f"  - {failure.file}: {failure.error}")
            lines.append("  (hela felet står nedanför)")
        return lines

    def log_failures(self) -> None:
        for failure in self.failed:
            log.error("Fel i %s:\n%s", failure.file, failure.details.rstrip())

    # --- Anropa ----------------------------------------------------------

    def fire(self, event: str, *args: Any) -> bool:
        """
        Anropar `event` i alla plugins som har den funktionen.
        Returnerar False om något plugin returnerade False ("stoppa det här"),
        annars True.
        """
        allowed = True
        for plugin in self.plugins:
            handler = getattr(plugin.module, event, None)
            if not callable(handler):
                continue
            try:
                if handler(*args) is False:
                    allowed = False
            except Exception:
                log.exception("Fel i pluginet %s (%s). Servern fortsätter som vanligt.", plugin.name, event)
        return allowed
