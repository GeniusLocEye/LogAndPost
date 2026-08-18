import csv
import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk

import requests


DEFAULT_LOG_DIRECTORY = r"C:\Users\shado\AppData\Local\VRC Speech To Text\Exceptions"
DEFAULT_FILTER_PATH = r"Z:\STT-TTS\LogAndPost\filter.csv"
DEFAULT_AUTH_URL = "http://localhost:3000/auth"
DEFAULT_SEND_URL = "http://localhost:3000/send"
DEFAULT_PASSCODE = "7654"

POLL_INTERVAL = 0.1
MARKER = "Full Translation:"


class TranslationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Translation Log Sender")
        self.geometry("850x620")
        self.minsize(760, 540)

        self.worker_thread = None
        self.stop_event = threading.Event()
        self.ui_queue = queue.Queue()
        self.running = False

        self.log_directory = tk.StringVar(value=DEFAULT_LOG_DIRECTORY)
        self.filter_path = tk.StringVar(value=DEFAULT_FILTER_PATH)
        self.auth_url = tk.StringVar(value=DEFAULT_AUTH_URL)
        self.send_url = tk.StringVar(value=DEFAULT_SEND_URL)
        self.passcode = tk.StringVar(value=DEFAULT_PASSCODE)

        self.status_text = tk.StringVar(value="Stopped")
        self.auth_text = tk.StringVar(value="Not authenticated")
        self.file_text = tk.StringVar(value="No file being watched")
        self.sent_count = tk.IntVar(value=0)
        self.skipped_count = tk.IntVar(value=0)

        self._build_ui()
        self.after(100, self._process_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        settings = ttk.LabelFrame(outer, text="Settings", padding=10)
        settings.pack(fill="x")
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="Log directory:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(settings, textvariable=self.log_directory).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(settings, text="Browse", command=self._browse_log_directory).grid(row=0, column=2, padx=(8, 0), pady=4)

        ttk.Label(settings, text="Filter CSV:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(settings, textvariable=self.filter_path).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(settings, text="Browse", command=self._browse_filter).grid(row=1, column=2, padx=(8, 0), pady=4)

        ttk.Label(settings, text="Auth URL:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(settings, textvariable=self.auth_url).grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(settings, text="Send URL:").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(settings, textvariable=self.send_url).grid(row=3, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(settings, text="Passcode:").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(settings, textvariable=self.passcode, show="*").grid(row=4, column=1, columnspan=2, sticky="ew", pady=4)

        controls = ttk.Frame(outer, padding=(0, 12, 0, 8))
        controls.pack(fill="x")

        self.start_button = ttk.Button(controls, text="Start", command=self.start_watcher)
        self.start_button.pack(side="left")

        self.stop_button = ttk.Button(controls, text="Stop", command=self.stop_watcher, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))

        ttk.Button(controls, text="Clear Log", command=self._clear_log).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Reload Filters", command=self._request_filter_reload).pack(side="left", padx=(8, 0))

        status = ttk.LabelFrame(outer, text="Status", padding=10)
        status.pack(fill="x", pady=(0, 10))
        status.columnconfigure(1, weight=1)

        ttk.Label(status, text="Watcher:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(status, textvariable=self.status_text).grid(row=0, column=1, sticky="w")

        ttk.Label(status, text="Authentication:").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Label(status, textvariable=self.auth_text).grid(row=1, column=1, sticky="w")

        ttk.Label(status, text="Current file:").grid(row=2, column=0, sticky="nw", padx=(0, 8))
        ttk.Label(status, textvariable=self.file_text, wraplength=650).grid(row=2, column=1, sticky="w")

        ttk.Label(status, text="Sent:").grid(row=3, column=0, sticky="w", padx=(0, 8))
        counts = ttk.Frame(status)
        counts.grid(row=3, column=1, sticky="w")
        ttk.Label(counts, textvariable=self.sent_count).pack(side="left")
        ttk.Label(counts, text="    Skipped duplicates:").pack(side="left")
        ttk.Label(counts, textvariable=self.skipped_count).pack(side="left")

        log_frame = ttk.LabelFrame(outer, text="Activity", padding=8)
        log_frame.pack(fill="both", expand=True)

        self.log_box = scrolledtext.ScrolledText(log_frame, height=15, state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True)

    def _browse_log_directory(self):
        path = filedialog.askdirectory(initialdir=self.log_directory.get() or None)
        if path:
            self.log_directory.set(path)

    def _browse_filter(self):
        path = filedialog.askopenfilename(
            initialdir=os.path.dirname(self.filter_path.get()) or None,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.filter_path.set(path)

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _request_filter_reload(self):
        self.ui_queue.put(("reload_filters", None))

    def _append_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{timestamp}] {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _queue_log(self, message):
        self.ui_queue.put(("log", message))

    def _process_ui_queue(self):
        try:
            while True:
                action, value = self.ui_queue.get_nowait()

                if action == "log":
                    self._append_log(value)
                elif action == "status":
                    self.status_text.set(value)
                elif action == "auth":
                    self.auth_text.set(value)
                elif action == "file":
                    self.file_text.set(value)
                elif action == "sent":
                    self.sent_count.set(self.sent_count.get() + 1)
                elif action == "skipped":
                    self.skipped_count.set(self.skipped_count.get() + 1)
                elif action == "stopped":
                    self._set_running_state(False)
                elif action == "reload_filters":
                    # This button is useful while stopped too; while running the worker
                    # reloads filters automatically before each translation.
                    try:
                        count = len(load_filters(self.filter_path.get()))
                        self._append_log(f"Filters loaded successfully ({count} entries).")
                    except Exception as exc:
                        self._append_log(f"Filter reload failed: {exc}")
        except queue.Empty:
            pass

        self.after(100, self._process_ui_queue)

    def _set_running_state(self, running):
        self.running = running
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        if not running and self.status_text.get() != "Error":
            self.status_text.set("Stopped")

    def start_watcher(self):
        if self.running:
            return

        log_dir = self.log_directory.get().strip()
        filter_path = self.filter_path.get().strip()
        auth_url = self.auth_url.get().strip()
        send_url = self.send_url.get().strip()
        passcode = self.passcode.get()

        if not log_dir or not filter_path or not auth_url or not send_url:
            messagebox.showerror("Missing settings", "Log directory, filter file, auth URL, and send URL are required.")
            return

        self.stop_event.clear()
        self.sent_count.set(0)
        self.skipped_count.set(0)
        self._set_running_state(True)
        self.status_text.set("Starting...")
        self.auth_text.set("Authenticating...")

        self.worker_thread = threading.Thread(
            target=self._watcher_worker,
            args=(log_dir, filter_path, auth_url, send_url, passcode),
            daemon=True,
        )
        self.worker_thread.start()

    def stop_watcher(self):
        if not self.running:
            return
        self.stop_event.set()
        self.status_text.set("Stopping...")
        self._append_log("Stop requested.")

    def _watcher_worker(self, log_dir, filter_path, auth_url, send_url, passcode):
        session = requests.Session()
        last_translation = None

        try:
            filters = load_filters(filter_path)
            self._queue_log(f"Loaded {len(filters)} filter entries.")
        except Exception as exc:
            self._queue_log(f"[FILTER ERROR] {exc}")
            self.ui_queue.put(("status", "Error"))
            self.ui_queue.put(("auth", "Not authenticated"))
            self.ui_queue.put(("stopped", None))
            return

        if not authenticate(session, auth_url, passcode, self._queue_log):
            self.ui_queue.put(("auth", "Authentication failed"))
            self.ui_queue.put(("status", "Error"))
            self.ui_queue.put(("stopped", None))
            return

        self.ui_queue.put(("auth", "Authenticated"))
        self.ui_queue.put(("status", "Watching"))

        try:
            while not self.stop_event.is_set():
                path = get_log_path(log_dir)
                self.ui_queue.put(("file", path))

                for line in tail_file(path, self.stop_event, self._queue_log):
                    if self.stop_event.is_set():
                        break

                    # Handles a date change while the program is still running.
                    new_path = get_log_path(log_dir)
                    if new_path != path:
                        self._queue_log("Date changed; switching to today's log file.")
                        break

                    if MARKER not in line:
                        continue

                    translation = line.split(MARKER, 1)[1].strip()

                    # Reloading here means edits to filter.csv take effect without restarting.
                    try:
                        filters = load_filters(filter_path)
                    except Exception as exc:
                        self._queue_log(f"[FILTER ERROR] {exc}")
                        continue

                    translation = apply_filters(translation, filters)

                    if not translation:
                        continue

                    if translation == last_translation:
                        self._queue_log(f"[SKIPPED] Duplicate: {translation}")
                        self.ui_queue.put(("skipped", None))
                        continue

                    sent, auth_ok = send_translation(
                        session,
                        translation,
                        auth_url,
                        send_url,
                        passcode,
                        self._queue_log,
                    )

                    if not auth_ok:
                        self.ui_queue.put(("auth", "Authentication failed"))
                    else:
                        self.ui_queue.put(("auth", "Authenticated"))

                    if sent:
                        last_translation = translation
                        self.ui_queue.put(("sent", None))
        finally:
            session.close()
            self.ui_queue.put(("auth", "Not authenticated"))
            self.ui_queue.put(("stopped", None))

    def _on_close(self):
        self.stop_event.set()
        self.destroy()


def get_log_path(log_directory):
    filename = datetime.now().strftime("Log-%Y%m%d.txt")
    return os.path.join(log_directory, filename)


def authenticate(session, auth_url, passcode, logger=print):
    logger("[AUTH] Authenticating...")
    try:
        response = session.post(
            auth_url,
            json={"passcode": passcode},
            timeout=5,
        )
        response.raise_for_status()
        logger("[AUTH] Authentication successful")
        return True
    except requests.RequestException as exc:
        logger(f"[AUTH ERROR] {exc}")
        return False


def send_translation(session, text, auth_url, send_url, passcode, logger=print):
    text = text.strip()
    if not text:
        return False, True

    payload = {"Message": text}

    try:
        response = session.post(send_url, json=payload, timeout=5)

        if response.status_code in (401, 403):
            logger("[AUTH] Session expired. Re-authenticating...")

            if not authenticate(session, auth_url, passcode, logger):
                logger("[AUTH] Re-authentication failed.")
                return False, False

            response = session.post(send_url, json=payload, timeout=5)

        response.raise_for_status()
        logger(f"[SENT] {text}")
        return True, True

    except requests.RequestException as exc:
        logger(f"[SEND ERROR] {exc}")
        return False, True


def load_filters(filename):
    filters = {}
    with open(filename, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames or "find" not in reader.fieldnames or "replace" not in reader.fieldnames:
            raise ValueError('Filter CSV must contain headers named "find" and "replace".')

        for row in reader:
            find = row.get("find")
            replace = row.get("replace")
            if find is None or replace is None:
                continue
            filters[find] = replace

    return filters


def apply_filters(text, filters):
    for find, replace in filters.items():
        text = text.replace(find, replace)
    return text


def tail_file(path, stop_event, logger=print):
    """Follow a file like tail -f, starting at the current end of the file."""
    waiting_message_shown = False

    while not stop_event.is_set():
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as file:
                file.seek(0, 2)
                logger(f"Watching: {path}")
                waiting_message_shown = False

                while not stop_event.is_set():
                    line = file.readline()

                    if not line:
                        if stop_event.wait(POLL_INTERVAL):
                            return

                        try:
                            current_size = os.path.getsize(path)
                            if current_size < file.tell():
                                logger("Log file was truncated/replaced. Reopening...")
                                break
                        except OSError:
                            break

                        continue

                    yield line

        except FileNotFoundError:
            if not waiting_message_shown:
                logger(f"Waiting for log file: {path}")
                waiting_message_shown = True
            if stop_event.wait(1):
                return

        except PermissionError:
            logger("Permission denied reading log file. Retrying...")
            if stop_event.wait(1):
                return

        except OSError as exc:
            logger(f"Log error: {exc}")
            if stop_event.wait(1):
                return


if __name__ == "__main__":
    app = TranslationApp()
    app.mainloop()
