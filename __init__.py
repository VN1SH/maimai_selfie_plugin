from typing import List, Tuple, Type

from src.plugin_system import BasePlugin, ComponentInfo, register_plugin

from .components.action_selfie import SelfieAutoAction
from .components.command_base import SelfieBaseCommand
from .config_schema import CONFIG_SCHEMA, CONFIG_SECTION_DESCRIPTIONS


@register_plugin
class MaimaiSelfiePlugin(BasePlugin):
    plugin_name = "maimai_selfie_plugin"
    enable_plugin = True
    dependencies = []
    python_dependencies = []
    config_file_name = "config.toml"
    config_section_descriptions = CONFIG_SECTION_DESCRIPTIONS
    config_schema = CONFIG_SCHEMA

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (SelfieAutoAction.get_action_info(), SelfieAutoAction),
            (SelfieBaseCommand.get_command_info(), SelfieBaseCommand),
        ]


__all__ = ["MaimaiSelfiePlugin"]
