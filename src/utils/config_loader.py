"""
Utility to load channel configurations from YAML.
"""
import yaml
from pathlib import Path
from typing import Dict
from src.models import ChannelConfig


def load_channel_config(channel_name: str) -> ChannelConfig:
    """
    Load channel configuration from channels.yaml.

    Args:
        channel_name: Name of the channel to load

    Returns:
        ChannelConfig instance

    Raises:
        FileNotFoundError: If channels.yaml doesn't exist
        KeyError: If channel_name not found in config
    """
    config_path = Path(__file__).parent.parent / "config" / "channels.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r") as f:
        all_channels = yaml.safe_load(f)

    if channel_name not in all_channels:
        available = ", ".join(all_channels.keys())
        raise KeyError(
            f"Channel '{channel_name}' not found. Available channels: {available}"
        )

    channel_data = all_channels[channel_name]
    return ChannelConfig(**channel_data)


def list_available_channels() -> Dict[str, str]:
    """
    List all available channels with their themes.

    Returns:
        Dictionary mapping channel names to their themes
    """
    config_path = Path(__file__).parent.parent / "config" / "channels.yaml"

    if not config_path.exists():
        return {}

    with open(config_path, "r") as f:
        all_channels = yaml.safe_load(f)

    return {name: config.get("theme", "") for name, config in all_channels.items()}
