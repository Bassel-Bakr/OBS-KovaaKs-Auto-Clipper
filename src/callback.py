from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import obsws_python as obs

from src.config import Config
from src.stat import Stat


@dataclass
class TrimCallbackParams:
    replay_path: Path
    trimmed_replay_path: Path
    stat: Stat
    config: Config
    client: obs.ReqClient


class Callbacks(Protocol):
    def after_trimming(self, params: TrimCallbackParams):
        """
        Called after a replay has been trimmed and saved. Can be used for custom actions like uploading the clip.
        """
        ...
