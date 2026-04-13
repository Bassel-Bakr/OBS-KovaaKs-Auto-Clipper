from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Dict, TypedDict

from src.config import Config
from src.stat import Stat, get_end_time


class CachedDataValue(TypedDict):
    high_score: float
    play_count: int


@dataclass
class CacheData:
    version: str
    last_update: str
    scenarios: Dict[str, CachedDataValue]


@dataclass
class Cache:
    file_path: Path
    data: CacheData
    config: Config

    def __init__(self, config: Config):
        self.config = config
        self.file_path = Path(config.cache_file)

    def get(self, scenario: str) -> CachedDataValue:
        """
        Retrieves the cached data for a given scenario.
        """

        return self.data.scenarios.setdefault(
            scenario, self.get_default_scenario_data()
        )

    def load(self):
        if self.file_path.exists():
            with open(self.file_path, "r") as f:
                self.data = CacheData(**json.load(f))
        else:
            self.data = CacheData(
                version="1.0.0",
                last_update=datetime.strptime(
                    "2000-01-01 00:00", "%Y-%m-%d %H:%M"
                ).isoformat(),
                scenarios={},
            )

    def update(self):
        """
        Updates the scenario PB cache by scanning all existing CSV files in the stats folder.
        This is useful to avoid saving replays that aren't PBs when the application is first started.
        """
        stats_folder = Path(self.config.stats_folder)

        last_update = datetime.fromisoformat(self.data.last_update)
        last_update_timestamp = last_update.timestamp()

        current_update_date = datetime.now()

        for file in stats_folder.glob("*.csv"):
            should_skip = (
                last_update_timestamp is not None
                and get_end_time(file).timestamp() <= last_update_timestamp
            )

            if should_skip:
                continue

            file_path = stats_folder / file
            stat = Stat(file_path)

            if stat.scenario and stat.score:
                scenario_data = self.data.scenarios.setdefault(
                    stat.scenario, self.get_default_scenario_data()
                )

                if scenario_data["play_count"] == 0:
                    scenario_data["high_score"] = stat.score
                else:
                    scenario_data["high_score"] = max(
                        scenario_data["high_score"], stat.score
                    )

                scenario_data["play_count"] += 1

        self.save(current_update_date)

    def save(self, update_time: datetime = datetime.now()):
        """
        Saves the current scenario PB cache to a JSON file. This is called on application exit to persist the cache for the next session.
        """

        previous_update_date = self.data.last_update
        self.data.last_update = update_time.isoformat()

        # Save updated cache to file
        json_data = json.dumps(self.data, default=lambda o: o.__dict__, indent=2)
        with open(self.file_path, "w") as f:
            f.write(json_data)

        self.data.last_update = previous_update_date

    def get_default_scenario_data(self) -> CachedDataValue:
        """
        Returns the default CachedDataValue.
        """
        return CachedDataValue(high_score=0, play_count=0)
