import importlib.util
import subprocess
from typing import Tuple
import json5
import json
import time
import obsws_python as obs
from datetime import datetime
from pathlib import Path
from watchdog.observers import Observer

from src.callback import Callbacks, TrimCallbackParams
from src.config import Config
from src.stat import Stat, get_end_time
from src.utils import wait_until_stable
from src.stat_watcher import StatWatcher


def import_file(file: Path) -> Callbacks | None:
    """
    Dynamically imports a Python file and returns its module object.
    """

    if not file.exists():
        return None

    spec = importlib.util.spec_from_file_location(file.stem, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


callbacks = import_file(Path("src/user_callbacks.py"))

# Cache file to store PBs for each scenario. This is used to avoid saving replays that aren't PBs when the application is first started.
CACHE_PATH = Path("cache.json")

# This is used to track the best score of the current session for each scenario.
# We decide whether to save a new replay based on the "only_pb" config option.
# Key: scenario name, Value: best score
SCENARIO_PB = dict()


def save_cache(update_time: datetime = datetime.now()):
    """
    Saves the current scenario PB cache to a JSON file. This is called on application exit to persist the cache for the next session.
    """
    cache = {"pbs": SCENARIO_PB, "last_update": update_time.isoformat()}

    # Save updated cache to file
    json_data = json.dumps(cache, default=str, indent=2)
    with open(CACHE_PATH, "w") as f:
        f.write(json_data)


def update_cache(config: Config):
    """
    Updates the scenario PB cache by scanning all existing CSV files in the stats folder.
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
            and get_end_time(file).timestamp() <= last_update_timestamp
        )

        if should_skip:
            continue

        file_path = folder / file
        stat = Stat(file_path)

        if stat.scenario and stat.score:
            previous_best = SCENARIO_PB.get(stat.scenario, None)

            if previous_best is None or stat.score > previous_best:
                SCENARIO_PB[stat.scenario] = stat.score

    save_cache(current_update_date)


def on_new_stat(stat_path: Path, config: Config, client: obs.ReqClient):
    print(f"📄 New file detected: {stat_path.name}")

    stat = Stat(stat_path)

    if not stat.challenge_start:
        print("❌ Challenge Start not found")
        return

    # ==== Check previous best ====
    previous_best = SCENARIO_PB.get(stat.scenario, None)

    should_save = not config.only_pb or (
        previous_best is None or stat.score > previous_best
    )

    if not should_save:
        print(
            f"⚠️ Score {stat.score} is not better than previous best {previous_best} for scenario '{stat.scenario}'. Skipping replay save."
        )
        return

    SCENARIO_PB[stat.scenario] = stat.score

    # ==== WAIT a bit ====
    time.sleep(config.trim_padding_end)

    # ==== Save replay buffer ====
    last_replay_path = client.get_last_replay_buffer_replay().saved_replay_path

    try:
        client.save_replay_buffer()
        print("🎬 Replay saved")
    except Exception as e:
        print(f"❌ OBS error: {e}")
        return

    # ==== Wait for OBS file to be fully written ====
    replay_path = last_replay_path
    while True:
        replay_path = client.get_last_replay_buffer_replay().saved_replay_path

        if replay_path != last_replay_path:
            wait_until_stable(Path(replay_path))
            break

    # ==== Trim clip ====
    try:
        latest = Path(replay_path)
        duration_seconds = (
            config.trim_padding_start
            + stat.duration.total_seconds()
            + config.trim_padding_end
        )
        output_path = trim_clip(Path(latest), duration_seconds, stat)

        print(f"✂️ Trimmed clip: {output_path}")

        if callbacks and hasattr(callbacks, "after_trimming"):
            params = TrimCallbackParams(
                replay_path=latest,
                trimmed_replay_path=output_path,
                stat=stat,
                config=config,
                client=client
            )
            callbacks.after_trimming(params)

        if config.delete_after_trimming:
            latest.unlink()

    except Exception as e:
        print(f"❌ Trim error: {e}")


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
    return output_path


def connect_to_obs(config: Config) -> Tuple[obs.ReqClient | None, Exception | None]:
    """
    Attempts to connect to OBS using the provided configuration. Returns the client if successful, or an error if it fails.
    """
    connection_kwargs = {
        "host": "localhost",
        "port": config.obs_port,
        "password": config.obs_password,
    }

    try:
        client = obs.ReqClient(**connection_kwargs)
        return client, None
    except Exception as e:
        return None, e


def main():
    config = Config()
    config.load_from_file()

    print("🔌 Updating cache...")
    update_cache(config)

    print("🔌 Connecting to OBS...")
    client, err = connect_to_obs(config)

    if err:
        print(f"❌ Failed to connect to OBS: {err}")
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
    event_handler = StatWatcher(lambda path: on_new_stat(path, config, client))

    observer = Observer()
    observer.schedule(event_handler, config.stats_folder, recursive=False)
    observer.start()

    print(f"👀 Watching folder: {config.stats_folder}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 Stopping...")
        save_cache()  # Save cache on exit
        client.stop_replay_buffer()
        client.disconnect()
        observer.stop()

    observer.join()


if __name__ == "__main__":
    main()
