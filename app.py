import json
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

    def load_from_file(self, path="config.json"):
        with open(path, "r") as f:
            data = json.load(f)
            for key, value in data.items():
                setattr(self, key, value)

    def save_to_file(self, path="config.json"):
        json_data = json.dumps(asdict(self))
        with open(path, "w") as f:
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


def get_end_time(filepath: Path) -> datetime:
    """
    Extracts the end time from the filename if it matches the pattern "YYYY.MM.DD-HH.MM.SS"."
    If the pattern is not found, it falls back to using the file's creation time.
    """
    match = re.search(r"\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}", filepath.name)
    if match:
        return datetime.strptime(match.group(), "%Y.%m.%d-%H.%M.%S")

    return datetime.fromtimestamp(filepath.stat().st_birthtime)


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


def get_latest_mkv(folder: Path) -> Path:
    files = list(folder.glob("*.mkv"))
    if not files:
        raise Exception("No MKV files found")
    return max(files, key=lambda f: f.stat().st_birthtime)


def trim_clip(
    input_path: Path, duration_seconds: int, challenge_name: str, challenge_score: float
):
    """
    Trims the input video to the specified duration and saves it with a filename based on the challenge name and score.
    """
    output_folder = input_path.with_name("KovaaK's").joinpath(challenge_name)
    output_folder.mkdir(parents=True, exist_ok=True)

    clip_time = datetime.now().strftime("%Y.%m.%d-%H.%M.%S")
    extension = input_path.suffix.lstrip(".")
    output_path = output_folder.joinpath(
        f"{challenge_name} - {challenge_score} - {clip_time}.{extension}"
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

        print(f"\n📄 New file detected: {filepath.name}")

        # Wait for file to finish writing
        if not wait_until_ready(filepath):
            print("❌ File not ready")
            return

        # ==== Get end time ====
        end_dt = get_end_time(filepath)
        print(f"🕒 End time: {end_dt}")

        challenge_start = None
        challenge_name = None
        challenge_score = 0

        # ==== Read CSV ====
        try:
            with open(filepath, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)

                for row in reader:
                    if len(row) < 2:
                        continue

                    if row[0].strip() == "Challenge Start:":
                        challenge_start = parse_timestamp(row[1].strip())

                    if row[0].strip() == "Scenario:":
                        challenge_name = row[1].strip()

                    if row[0].strip() == "Score:":
                        challenge_score = float(row[1].strip())
                        challenge_score = (
                            int(challenge_score)
                            if challenge_score.is_integer()
                            else challenge_score
                        )

        except Exception as e:
            print(f"❌ CSV read error: {e}")
            return

        if not challenge_start:
            print("❌ Challenge Start not found")
            return

        print(f"⏱ Challenge offset: {challenge_start}")

        # ==== Compute start time ====
        start_dt = compute_start_time(end_dt, challenge_start)
        print(f"✅ Start time: {start_dt}")

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
            latest: str = self.client.get_last_replay_buffer_replay().saved_replay_path

            duration_seconds = (
                end_dt - start_dt
            ).total_seconds() + self.config.trim_padding

            trim_clip(latest, duration_seconds, challenge_name, challenge_score)

            # delete original if desired
            # latest.unlink()

        except Exception as e:
            print(f"❌ Trim error: {e}")


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
