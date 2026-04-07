import os
import json5 as json
import time
import re
import csv
import subprocess
import obsws_python as obs
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

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
            with open(self.stat_file, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)

                for row in reader:
                    if len(row) < 2:
                        continue

                    if row[0].strip() == "Challenge Start:":
                        self.challenge_start = parse_timestamp(row[1].strip())

                    if row[0].strip() == "Scenario:":
                        self.scenario = row[1].strip()

                    if row[0].strip() == "Score:":
                        score = float(row[1].strip())
                        self.score = int(score) if score.is_integer() else score

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

    stats_folder = r"C:\Program Files (x86)\Steam\steamapps\common\FPSAimTrainer\FPSAimTrainer\stats"  # folder where CSV files appear
    obs_recording_folder = ""
    obs_port = 4455
    obs_password = ""
    trim_padding = 5
    process_replay_delay = 5
    only_pb = True

    def load_from_file(self, path="config.json"):
        with open(path, "r") as f:
            data = json.load(f)
            for key, value in data.items():
                setattr(self, key, value)

    def save_to_file(self, path="config.json"):
        json_data = json.dumps(asdict(self))
        with open(path, "w") as f:
            f.write(json_data)


def extract_score_from_csv(file_path: str) -> float:
    try:
        with open(file_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)

            for row in reader:
                if len(row) < 2:
                    continue

                if row[0].strip() == "Score:":
                    score = float(row[1].strip())
                    return int(score) if score.is_integer() else score

    except Exception as e:
        print(f"❌ CSV read error: {e}")
        return None


def find_best_score(folder: str, stat: Stat) -> float:
    best_score = float("-inf")

    for file in os.listdir(folder):
        if (
            file.startswith(stat.scenario + " - Challenge -")
            and file.endswith(".csv")
            # exclude the current stat file since it might be the new PB we're trying to compare against
            and file != stat.stat_file.name 
        ):
            file_path = os.path.join(folder, file)
            score = extract_score_from_csv(file_path)

            best_score = max(best_score, score or best_score)

    return best_score


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

        latest = Path(self.client.get_last_replay_buffer_replay().saved_replay_path)

        should_save, previous_best = self.get_previous_best(stat)
        if not should_save:
            print(
                f"⚠️ Score {stat.score} is not better than previous best {previous_best} for scenario '{stat.scenario}'. Skipping replay save."
            )

            # delete the replay file since we won't be using it
            latest.unlink(missing_ok=True)
            return

        # ==== Trim clip ====
        try:
            duration_seconds = stat.duration.total_seconds() + self.config.trim_padding
            trim_clip(Path(latest), duration_seconds, stat)

            # delete original if desired
            # latest.unlink()

        except Exception as e:
            print(f"❌ Trim error: {e}")

    def get_previous_best(self, stat: Stat) -> bool:
        if not self.config.only_pb:
            return True

        previous_best = SCENARIO_PB.get(stat.scenario, None)

        if previous_best is None:
            previous_best = find_best_score(self.config.stats_folder, stat)
            SCENARIO_PB[stat.scenario] = previous_best

        if stat.score <= previous_best:
            return False, previous_best

        SCENARIO_PB[stat.scenario] = stat.score
        return True, previous_best


def main():
    config = Config()
    config.load_from_file()

    print("🔌 Connecting to OBS...")

    connection_kwargs = {
        "host": "localhost",
        "port": config.obs_port,
        "password": config.obs_password,
    }

    client = obs.ReqClient(**connection_kwargs)

    print("✅ Connected to OBS")

    # Ensure replay buffer is running
    running_replay_buffer: bool = client.get_replay_buffer_status().output_active

    if not running_replay_buffer:
        client.start_replay_buffer()
        print("▶️ Replay buffer started")
    else:
        print("ℹ️ Replay buffer already running")

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
