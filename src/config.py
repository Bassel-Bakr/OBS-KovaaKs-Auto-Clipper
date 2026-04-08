from dataclasses import dataclass
import json5


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

    def load_from_file(self, path="config.json"):
        with open(path, "r") as f:
            data = json5.load(f)
            for field in self.__dataclass_fields__:
                if field in data:
                    setattr(self, field, data[field])
