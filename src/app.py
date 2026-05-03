import importlib.util
import shutil
import subprocess
from typing import Tuple
import time
import mss
import obsws_python as obs
import tempfile
from datetime import datetime
from pathlib import Path
from watchdog.observers import Observer
from PIL import Image

from src.cache import Cache
from src.callback import Callbacks, TrimCallbackParams
from src.config import Config
from src.stat import Stat
from src.utils import wait_until_stable
from src.stat_watcher import StatWatcher


def import_file(file: Path, missing_ok: bool = True) -> Callbacks | None:
    """
    Dynamically imports a Python file and returns its module object.
    """

    if not file.exists():
        if missing_ok:
            return None
        else:
            raise FileNotFoundError(f"File not found: {file}")

    spec = importlib.util.spec_from_file_location(file.stem, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def on_new_stat(
    stat_path: Path,
    config: Config,
    cache: Cache,
    client: obs.ReqClient,
    callbacks: Callbacks | None,
):
    print(f"📄 New file detected: {stat_path.name}")

    stat = Stat(stat_path)

    if not stat.challenge_start:
        print("❌ Challenge Start not found")
        return

    # ==== Check previous best ====
    scenario_data = cache.get(stat.scenario)

    should_save = not config.only_pb or (
        scenario_data["play_count"] == 0 or stat.score > scenario_data["high_score"]
    )

    if not should_save:
        print(
            f"⚠️ Score {stat.score} is not better than previous best {scenario_data['high_score']} for scenario '{stat.scenario}'. Skipping replay save."
        )
        return

    scenario_data["high_score"] = stat.score
    scenario_data["play_count"] += 1

    # ==== WAIT a bit ====
    time.sleep(config.trim_padding_end)

    # ==== Take screenshot if enabled ====
    screenshot_path = None
    if config.screenshot["enabled"]:
        screenshot_path = screenshot(client, config, stat)

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

        if screenshot_path:
            shutil.move(screenshot_path, output_path.with_suffix(".png"))
            print(f"📷 Screenshot taken: {screenshot_path}")

        if callbacks and hasattr(callbacks, "after_trimming"):
            params = TrimCallbackParams(
                replay_path=latest,
                trimmed_replay_path=output_path,
                stat=stat,
                config=config,
                client=client,
            )
            callbacks.after_trimming(params)

        if config.delete_after_trimming:
            latest.unlink()

    except Exception as e:
        print(f"❌ Trim error: {e}")


def screenshot(client: obs.ReqClient, config: Config, stat: Stat) -> Path:
    """
    Takes a screenshot using the OBS client and saves it to a temporary file.
    """

    screenshot_path = Path(tempfile.gettempdir()).joinpath(
        f"{stat.formatted_filename}.png"
    )

    with mss.mss() as sct:
        monitor = sct.monitors[1]

        client.save_source_screenshot(
            name="KovaaK's",
            img_format="png",
            width=monitor["width"],
            height=monitor["height"],
            quality=100,
            file_path=str(screenshot_path),
        )

        # Crop the screenshot to the specified region if enabled
        if config.screenshot["region"]:
            img = Image.open(screenshot_path)
            region = config.screenshot["region"]
            left = region["left"]
            top = region["top"]
            width = region["width"]
            height = region["height"]
            cropped_img = img.crop((left, top, left + width, top + height))
            cropped_img.save(screenshot_path)

        return screenshot_path


def trim_clip(input_path: Path, duration_seconds: int, stat: Stat):
    """
    Trims the input video to the specified duration and saves it with a filename based on the challenge name and score.
    """
    output_folder = input_path.with_name("KovaaK's").joinpath(stat.scenario)
    output_folder.mkdir(parents=True, exist_ok=True)

    # For simplicity, we save as MP4. You can change this to match your OBS output format if needed.
    extension = "mp4"
    # extension = input_path.suffix.lstrip(".")

    output_path = output_folder.joinpath(f"{stat.formatted_filename}.{extension}")

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
    print("🔌 Loading config...")
    config = Config()
    config.load_from_file()

    print("🔌 Loading user callbacks...")
    callbacks = import_file(Path(config.callbacks_file))

    print("🔌 Updating cache...")
    cache = Cache(config)
    cache.load()
    cache.update()

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
    event_handler = StatWatcher(
        lambda path: on_new_stat(path, config, cache, client, callbacks)
    )

    observer = Observer()
    observer.schedule(event_handler, config.stats_folder, recursive=False)
    observer.start()

    print(f"👀 Watching folder: {config.stats_folder}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 Stopping...")
        cache.save()  # Save cache on exit
        # Stop replay buffer if we started it, otherwise leave it running as it was before
        if not running_replay_buffer:
            client.stop_replay_buffer()
        client.disconnect()
        observer.stop()

    observer.join()


if __name__ == "__main__":
    main()
