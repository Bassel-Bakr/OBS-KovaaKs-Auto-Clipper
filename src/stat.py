import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from src.utils import get_creation_or_modification_time


@dataclass
class Stat:
    """
    Represents a single stat entry from the CSV file.
    """

    stat_file: Path
    challenge_start: timedelta
    scenario: str
    score: float

    start_dt: datetime = None
    end_dt: datetime = None

    @property
    def duration(self) -> timedelta:
        return self.end_dt - self.start_dt

    def __init__(self, stat_file: Path):
        self.stat_file = stat_file
        self.end_dt = get_end_time(self.stat_file)

        # ==== Read CSV ====
        try:
            with open(self.stat_file, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("Score:"):
                        score = float(line.split(",")[1])
                        self.score = int(score) if score.is_integer() else score
                    elif line.startswith("Challenge Start:"):
                        self.challenge_start = parse_timestamp(
                            line.split(",")[1].strip()
                        )
                    elif line.startswith("Scenario:"):
                        self.scenario = line.split(",")[1].strip()

        except Exception as e:
            print(f"❌ CSV read error: {e}")
            return

        # ==== Compute start time ====
        self.start_dt = compute_start_time(self.end_dt, self.challenge_start)

    def get_end_time(self, stat_file: Path) -> datetime:
        """
        Extracts the end time from the filename if it matches the pattern "YYYY.MM.DD-HH.MM.SS"."
        If the pattern is not found, it falls back to using the file's creation time.
        """
        match = re.search(r"\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}", stat_file.name)
        if match:
            return datetime.strptime(match.group(), "%Y.%m.%d-%H.%M.%S")

        return get_creation_or_modification_time(stat_file)


def parse_timestamp(ts: str) -> timedelta:
    """
    Parses a timestamp string in the format "HH:MM:SS" or "MM:SS" into a timedelta object.
    """
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return timedelta(hours=int(h), minutes=int(m), seconds=float(s))
    elif len(parts) == 2:
        m, s = parts
        return timedelta(minutes=int(m), seconds=float(s))
    else:
        raise ValueError(f"Invalid timestamp: {ts}")


def get_end_time(stat_file: Path) -> datetime:
    """
    Extracts the end time from the filename if it matches the pattern "YYYY.MM.DD-HH.MM.SS"."
    If the pattern is not found, it falls back to using the file's creation time.
    """
    match = re.search(r"\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}", stat_file.name)
    if match:
        return datetime.strptime(match.group(), "%Y.%m.%d-%H.%M.%S")

    return get_creation_or_modification_time(stat_file)


def compute_start_time(end_dt: datetime, challenge_start_td: timedelta) -> datetime:
    """
    Computes the start time of the challenge based on the end time and the challenge start offset.
    """
    total_seconds = int(challenge_start_td.total_seconds())

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    start_dt = end_dt.replace(hour=hours, minute=minutes, second=seconds, microsecond=0)

    if start_dt > end_dt:
        start_dt -= timedelta(days=1)

    return start_dt
