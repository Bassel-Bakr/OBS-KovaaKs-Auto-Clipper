from pathlib import Path
from typing import Callable
from watchdog.events import FileSystemEventHandler

from src.utils import wait_until_ready


class StatWatcher(FileSystemEventHandler):
    """
    Handler for new CSV files in the stats folder. Extracts challenge info and triggers OBS replay save.
    """

    def __init__(self, handler: Callable[[Path], None]):
        self.handler = handler

    def on_created(self, event):
        if event.is_directory:
            return

        filepath = Path(event.src_path)

        # Only process CSV files
        if not filepath.name.endswith(".csv"):
            return

        # Wait for file to finish writing
        if not wait_until_ready(filepath):
            print("❌ File not ready")
            return

        if self.handler:
            self.handler(filepath)
