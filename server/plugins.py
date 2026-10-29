"""
The plugin system: loads plugins from the plugins/ folder and calls them
when things happen on the server.

A plugin is an ordinary Python file with functions that have special names,
for example:

    def on_player_spawned(lobby, player):
        player.send_chat("Welcome!")

The server looks for plugins like this in the plugins/ folder:

  - greeting.py           a file = a plugin
  - my_plugin/            a folder with __init__.py = a plugin
  - My-Plugins-main/      a folder without __init__.py = a collection of plugins,
                          every .py file in it is its own plugin
                          (good if you download a whole plugin repo)

Files and folders that start with _ are skipped. Rename "_dice.py" to
"dice.py" to turn that plugin on.

A plugin can also have translations for the server's terminal window:

    TRANSLATIONS = {"sv": {"Welcome!": "Välkommen!"}}

See plugins/README.md for all events and what a plugin can do.
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

from . import i18n
from .config import PROJECT_DIR
from .i18n import tr

log = logging.getLogger("plugin")

PLUGIN_DIR = PROJECT_DIR / "plugins"

# All events a plugin can listen to. See plugins/README.md.
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
    "on_player_killed",
    "on_meeting_started",
    "on_player_exiled",
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
            text += tr(" by {author}", author=self.author)
        return text


@dataclass
class FailedPlugin:
    file: str
    error: str  # short error message
    details: str  # the whole error (traceback), to be able to find what's wrong


class PluginManager:
    def __init__(self, folder: Path = PLUGIN_DIR):
        self.folder = folder
        self.plugins: List[LoadedPlugin] = []
        self.failed: List[FailedPlugin] = []
        self.enabled = True

    # --- Load ------------------------------------------------------------

    def load_all(self) -> None:
        """Loads all plugins. What was loaded is shown afterwards with summary()."""
        if not self.folder.is_dir():
            log.debug("No plugins folder was found, running without plugins.")
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
                    # A collection of plugins, for example a downloaded plugin repo.
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
                raise ImportError("could not read the file")
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
        self._add_translations(plugin)
        self.plugins.append(plugin)
        log.debug("Loaded the plugin %s from %s", plugin, source)
        if not events:
            plugin.warnings.append(tr("doesn't listen to any events"))
        for attr in unknown:
            plugin.warnings.append(tr("the function {name} isn't an event that exists", name=attr))

    @staticmethod
    def _add_translations(plugin: LoadedPlugin) -> None:
        """TRANSLATIONS = {"sv": {"English text": "Svensk text"}} in a plugin."""
        translations = getattr(plugin.module, "TRANSLATIONS", None)
        if not isinstance(translations, dict):
            return
        for code, texts in translations.items():
            if isinstance(texts, dict):
                i18n.add_translations(str(code), texts)

    # --- Show what was loaded --------------------------------------------

    def summary(self) -> List[str]:
        """The lines in the box LOADING PLUGINS that is shown when the server has started."""
        if not self.enabled:
            return [tr("Plugins are turned off in config.json.")]

        count = len(self.plugins)
        if count == 1:
            lines = [tr("Loaded 1 plugin...")]
        else:
            lines = [tr("Loaded {count} plugins...", count=count)]
        for plugin in self.plugins:
            lines.append(f"  - {plugin}")
            if plugin.description:
                lines.append(f"      {tr(plugin.description)}")
            for warning in plugin.warnings:
                lines.append("      " + tr("Note: {warning}", warning=warning))
        if count == 0:
            lines.append(tr("  Put plugins in the plugins/ folder (see plugins/README.md)."))

        if self.failed:
            lines.append("")
            if len(self.failed) == 1:
                lines.append(tr("Could not load 1 plugin:"))
            else:
                lines.append(tr("Could not load {count} plugins:", count=len(self.failed)))
            for failure in self.failed:
                lines.append(f"  - {failure.file}: {failure.error}")
            lines.append(tr("  (the whole error is below)"))
        return lines

    def log_failures(self) -> None:
        for failure in self.failed:
            log.error("Error in %s:\n%s", failure.file, failure.details.rstrip())

    # --- Call ------------------------------------------------------------

    def fire(self, event: str, *args: Any) -> bool:
        """
        Calls `event` in all plugins that have that function.
        Returns False if some plugin returned False ("stop this"),
        otherwise True.
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
                log.exception("Error in the plugin %s (%s). The server continues as usual.", plugin.name, event)
        return allowed
