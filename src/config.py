from dataclasses import dataclass, field
from typing import TypedDict
import json5


class Region(TypedDict):
    top: float
    left: float
    width: float
    height: float


class Screenshot(TypedDict):
    enabled: bool
    region: Region


@dataclass
class Config:
    """
    Configuration for the application. Can be loaded/saved from/to a JSON file.
    """

    stats_folder: str = ""
    obs_recording_folder: str = ""
    obs_port: int = 4455
    obs_password: str = ""
    trim_padding_start: float = 1
    trim_padding_end: float = 5
    delete_after_trimming: bool = False
    process_replay_delay: float = 5
    only_pb: bool = True
    cache_version = "0.0.0"
    cache_file = "cache.json"
    callbacks_file = "src/user_callbacks.py"
    screenshot: Screenshot = field(default_factory=lambda: {"enabled": True})

    def load_from_file(self, path="config.json"):
        with open(path, "r") as f:
            data = json5.load(f)
            for field in self.__dataclass_fields__:
                if field in data:
                    setattr(self, field, data[field])
