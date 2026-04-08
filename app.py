from typing import Tuple
import json5
import json
import time
import re
import subprocess
import obsws_python as obs
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Cache file to store PBs for each scenario. This is used to avoid saving replays that aren't PBs when the application is first started.
CACHE_PATH = Path("cache.json")

# This is used to track the best score of the current session for each scenario.
# We decide whether to save a new replay based on the "only_pb" config option.
# Key: scenario name, Value: best score
SCENARIO_PB = dict()


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
        self.end_dt = self.get_end_time(self.stat_file)

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

        return datetime.fromtimestamp(stat_file.stat().st_birthtime)


@dataclass
class Config:
    """
    Configuration for the application. Can be loaded/saved from/to a JSON file.
    """

    stats_folder: str = (
        r"C:\Program Files (x86)\Steam\steamapps\common\FPSAimTrainer\FPSAimTrainer\stats"  # folder where CSV files appear
    )
    obs_recording_folder: str = ""
    obs_port: int = 4455
    obs_password: str = ""
    trim_padding: float = 5
    process_replay_delay: float = 5
    only_pb: bool = True

    def load_from_file(self, path="config.json"):
        with open(path, "r") as f:
            data = json5.load(f)
            for field in self.__dataclass_fields__:
                if field in data:
                    setattr(self, field, data[field])


def init_cache(config: Config):
    """
    Initializes the scenario PB cache by scanning all existing CSV files in the stats folder.
    This is useful to avoid saving replays that aren't PBs when the application is first started.
    """
    folder = Path(config.stats_folder)

    cache = json5.load(open(CACHE_PATH, "r")) if CACHE_PATH.exists() else {}

    global SCENARIO_PB
    SCENARIO_PB = cache["pbs"] if "pbs" in cache else {}

    last_update = (
        datetime.fromisoformat(cache["last_update"]) if "last_update" in cache else None
    )
    last_update_timestamp = last_update.timestamp() if last_update else None

    current_update_date = datetime.now()

    for file in folder.glob("*.csv"):
        should_skip = (
            last_update_timestamp is not None
            and file.stat().st_birthtime <= last_update_timestamp
        )

        if should_skip:
            continue

        file_path = folder / file
        stat = Stat(file_path)

        if stat.scenario and stat.score:
            previous_best = SCENARIO_PB.get(stat.scenario, None)

            if previous_best is None or stat.score > previous_best:
                SCENARIO_PB[stat.scenario] = stat.score

    cache = {"pbs": SCENARIO_PB, "last_update": current_update_date.isoformat()}

    # Save updated cache to file
    json_data = json.dumps(cache, default=str, indent=2)
    with open(CACHE_PATH, "w") as f:
        f.write(json_data)


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


def wait_until_ready(path: Path, timeout: int = 5) -> bool:
    """
    Waits until the file at the given path is ready (i.e., can be opened without error).
    """
    start = time.time()
    while True:
        try:
            with open(path, "rb"):
                return True
        except:
            if time.time() - start > timeout:
                return False
            time.sleep(0.2)


def trim_clip(input_path: Path, duration_seconds: int, stat: Stat):
    """
    Trims the input video to the specified duration and saves it with a filename based on the challenge name and score.
    """
    output_folder = input_path.with_name("KovaaK's").joinpath(stat.scenario)
    output_folder.mkdir(parents=True, exist_ok=True)

    clip_time = datetime.now().strftime("%Y.%m.%d-%H.%M.%S")

    # For simplicity, we save as MP4. You can change this to match your OBS output format if needed.
    extension = "mp4"
    # extension = input_path.suffix.lstrip(".")

    output_path = output_folder.joinpath(
        f"{stat.scenario} - {stat.score} - {clip_time}.{extension}"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-sseof",
        f"-{duration_seconds}",
        "-i",
        str(input_path),
        "-t",
        str(duration_seconds),
        "-c",
        "copy",
        str(output_path),
    ]

    subprocess.run(cmd)
    print(f"✂️ Trimmed clip: {output_path}")


class NewStatsHandler(FileSystemEventHandler):
    """
    Handler for new CSV files in the stats folder. Extracts challenge info and triggers OBS replay save.
    """

    def __init__(self, client: obs.ReqClient, config: Config):
        self.client = client
        self.config = config
        self.last_trigger = 0

    def on_created(self, event):
        if event.is_directory:
            return

        filepath = Path(event.src_path)

        # Only process CSV files
        if not filepath.name.endswith(".csv"):
            return

        print(f"📄 New file detected: {filepath.name}")

        # Wait for file to finish writing
        if not wait_until_ready(filepath):
            print("❌ File not ready")
            return

        stat = Stat(filepath)

        if not stat.challenge_start:
            print("❌ Challenge Start not found")
            return

        # ==== Check previous best ====
        previous_best = SCENARIO_PB.get(stat.scenario, None)

        should_save = not self.config.only_pb or (
            previous_best is None or stat.score > previous_best
        )

        if not should_save:
            print(
                f"⚠️ Score {stat.score} is not better than previous best {previous_best} for scenario '{stat.scenario}'. Skipping replay save."
            )
            return

        # ==== WAIT a bit ====
        time.sleep(self.config.trim_padding)

        # ==== Save replay buffer ====
        try:
            self.client.save_replay_buffer()
            print("🎬 Replay saved")
        except Exception as e:
            print(f"❌ OBS error: {e}")
            return

        # ==== Wait for OBS file ====
        time.sleep(self.config.process_replay_delay)

        # ==== Trim clip ====
        try:
            latest = Path(self.client.get_last_replay_buffer_replay().saved_replay_path)
            duration_seconds = stat.duration.total_seconds() + self.config.trim_padding
            trim_clip(Path(latest), duration_seconds, stat)

            # delete original if desired
            # latest.unlink()

        except Exception as e:
            print(f"❌ Trim error: {e}")

    def get_previous_best(self, stat: Stat) -> Tuple[bool, float | int | None]:
        if not self.config.only_pb:
            return True, None

        previous_best = SCENARIO_PB.get(stat.scenario, None)

        if previous_best is None:
            return True, None

        if stat.score <= previous_best:
            return False, previous_best

        SCENARIO_PB[stat.scenario] = stat.score
        return True, previous_best


def main():
    config = Config()
    config.load_from_file()

    # if config.only_pb:
    print("🔌 Initializing cache...")
    init_cache(config)

    print("🔌 Connecting to OBS...")

    connection_kwargs = {
        "host": "localhost",
        "port": config.obs_port,
        "password": config.obs_password,
    }

    client: obs.ReqClient

    try:
        client = obs.ReqClient(**connection_kwargs)
    except Exception as e:
        print(f"❌ Failed to connect to OBS: {e}")
        return

    print("✅ Connected to OBS")

    # Ensure replay buffer is running
    running_replay_buffer: bool = client.get_replay_buffer_status().output_active

    if not running_replay_buffer:
        client.start_replay_buffer()
        print("▶️  Replay buffer started")
    else:
        print("ℹ️  Replay buffer already running")

    # Set up stats folder watcher
    event_handler = NewStatsHandler(client, config)

    observer = Observer()
    observer.schedule(event_handler, config.stats_folder, recursive=False)
    observer.start()

    print(f"👀 Watching folder: {config.stats_folder}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 Stopping...")
        client.stop_replay_buffer()
        client.disconnect()
        observer.stop()

    observer.join()


if __name__ == "__main__":
    main()
