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
from dataclasses import dataclass
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

    def handles(self, event: str) -> bool:
        return callable(getattr(self.module, event, None))


class PluginManager:
    def __init__(self, folder: Path = PLUGIN_DIR):
        self.folder = folder
        self.plugins: List[LoadedPlugin] = []

    # --- Ladda -----------------------------------------------------------

    def load_all(self) -> None:
        if not self.folder.is_dir():
            log.info("Ingen plugins-mapp hittades, kör utan plugins.")
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

        if self.plugins:
            log.info("%d plugin%s laddade", len(self.plugins), "s" if len(self.plugins) != 1 else "")
        else:
            log.info("Inga plugins är påslagna (se plugins/README.md)")

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
        except Exception:
            log.exception("Kunde inte ladda pluginet %s, hoppar över det", source.name)
            sys.modules.pop(module_name, None)
            return

        name = str(getattr(module, "NAME", source.stem))
        description = str(getattr(module, "DESCRIPTION", ""))
        plugin = LoadedPlugin(name, description, source, module)

        events = [e for e in EVENTS if plugin.handles(e)]
        unknown = [
            attr
            for attr in dir(module)
            if attr.startswith("on_") and attr not in EVENTS and callable(getattr(module, attr))
        ]
        self.plugins.append(plugin)
        log.info("Laddade pluginet %s%s", name, f" ({description})" if description else "")
        if not events:
            log.warning("Pluginet %s lyssnar inte på några händelser", name)
        for attr in unknown:
            log.warning("Pluginet %s har funktionen %s, men det finns ingen sådan händelse", name, attr)

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
