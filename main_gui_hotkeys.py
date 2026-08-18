import csv
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk

import requests

try:
    import keyboard  # Global hotkeys on Windows
except ImportError:
    keyboard = None


DEFAULT_LOG_DIRECTORY = r"%localappdata%\VRC Speech To Text\Exceptions"
DEFAULT_FILTER_PATH = r"Z:\STT-TTS\LogAndPost\filter.csv"
DEFAULT_AUTH_URL = "http://localhost:3000/auth"
DEFAULT_SEND_URL = "http://localhost:3000/send"
DEFAULT_PASSCODE = "7654"

POLL_INTERVAL = 0.1
DEFAULT_MARKER_TEXT = "Full Translation:"
MAX_PREFIX_PRESETS = 6

DEFAULT_PRESETS = [
    ("Say", "/s ", "ctrl+s"),
    ("Party", "/p ", "ctrl+p"),
    ("Yell", "/y ", "ctrl+y"),
    ("Free Company", "/fc", "ctrl+f"),
    ("Novice Network", "/nn", "ctrl+n"),
    ("Alliance", "/a", "ctrl+a"),
]


class TranslationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Translation Log Sender")
        self.geometry("980x800")
        self.minsize(880, 680)

        self.worker_thread = None
        self.stop_event = threading.Event()
        self.ui_queue = queue.Queue()
        self.running = False
        self.hotkey_handles = []

        self.log_directory = tk.StringVar(value=DEFAULT_LOG_DIRECTORY)
        self.filter_path = tk.StringVar(value=DEFAULT_FILTER_PATH)
        self.auth_url = tk.StringVar(value=DEFAULT_AUTH_URL)
        self.send_url = tk.StringVar(value=DEFAULT_SEND_URL)
        self.passcode = tk.StringVar(value=DEFAULT_PASSCODE)
        self.marker_text = tk.StringVar(value=DEFAULT_MARKER_TEXT)

        self.active_prefix_index = tk.IntVar(value=0)
        self.active_prefix_text = tk.StringVar(value="")
        self.active_hotkey_text = tk.StringVar(value="Hotkeys not applied")
        self._active_prefix_value = DEFAULT_PRESETS[0][1]

        self.preset_names = []
        self.preset_prefixes = []
        self.preset_hotkeys = []
        for name, prefix, hotkey in DEFAULT_PRESETS:
            name_var = tk.StringVar(value=name)
            prefix_var = tk.StringVar(value=prefix)
            hotkey_var = tk.StringVar(value=hotkey)
            prefix_var.trace_add("write", self._on_active_prefix_edited)
            name_var.trace_add("write", self._on_active_prefix_edited)
            self.preset_names.append(name_var)
            self.preset_prefixes.append(prefix_var)
            self.preset_hotkeys.append(hotkey_var)

        self.status_text = tk.StringVar(value="Stopped")
        self.auth_text = tk.StringVar(value="Not authenticated")
        self.file_text = tk.StringVar(value="No file being watched")
        self.sent_count = tk.IntVar(value=0)
        self.skipped_count = tk.IntVar(value=0)

        self._build_ui()
        self._refresh_active_prefix_display()
        self.after(100, self._process_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        settings = ttk.LabelFrame(outer, text="Connection and Files", padding=10)
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
        
        ttk.Label(settings, text="Marker Text:").grid(row=5, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(settings, textvariable=self.marker_text).grid(row=5, column=1, columnspan=2, sticky="ew", pady=4)

        prefixes = ttk.LabelFrame(outer, text="Prefix Presets and Global Hotkeys", padding=10)
        prefixes.pack(fill="x", pady=(10, 0))
        prefixes.columnconfigure(2, weight=1)

        ttk.Label(prefixes, text="Active").grid(row=0, column=0, padx=(0, 8), sticky="w")
        ttk.Label(prefixes, text="Name").grid(row=0, column=1, padx=(0, 8), sticky="w")
        ttk.Label(prefixes, text="Prefix").grid(row=0, column=2, padx=(0, 8), sticky="w")
        ttk.Label(prefixes, text="Hotkey").grid(row=0, column=3, padx=(0, 8), sticky="w")

        for index in range(MAX_PREFIX_PRESETS):
            row = index + 1
            ttk.Radiobutton(
                prefixes,
                variable=self.active_prefix_index,
                value=index,
                command=self._select_prefix_from_gui,
            ).grid(row=row, column=0, padx=(0, 8), pady=3)

            ttk.Entry(prefixes, textvariable=self.preset_names[index], width=16).grid(
                row=row, column=1, padx=(0, 8), pady=3, sticky="ew"
            )
            ttk.Entry(prefixes, textvariable=self.preset_prefixes[index]).grid(
                row=row, column=2, padx=(0, 8), pady=3, sticky="ew"
            )
            ttk.Entry(prefixes, textvariable=self.preset_hotkeys[index], width=18).grid(
                row=row, column=3, padx=(0, 8), pady=3, sticky="ew"
            )

        hotkey_controls = ttk.Frame(prefixes)
        hotkey_controls.grid(row=MAX_PREFIX_PRESETS + 1, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        ttk.Button(hotkey_controls, text="Apply Hotkeys", command=self._apply_hotkeys).pack(side="left")
        ttk.Button(hotkey_controls, text="Clear Hotkeys", command=self._clear_hotkeys).pack(side="left", padx=(8, 0))
        ttk.Label(hotkey_controls, textvariable=self.active_hotkey_text).pack(side="left", padx=(14, 0))

        active_frame = ttk.Frame(prefixes)
        active_frame.grid(row=MAX_PREFIX_PRESETS + 2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Label(active_frame, text="Currently active prefix:").pack(side="left")
        ttk.Label(active_frame, textvariable=self.active_prefix_text).pack(side="left", padx=(6, 0))

        ttk.Label(
            prefixes,
            text="Hotkey examples: ctrl+1, alt+s, ctrl+shift+p, f8. Blank hotkeys are ignored.",
        ).grid(row=MAX_PREFIX_PRESETS + 3, column=0, columnspan=4, sticky="w", pady=(8, 0))

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
        ttk.Label(status, textvariable=self.file_text, wraplength=760).grid(row=2, column=1, sticky="w")

        ttk.Label(status, text="Sent:").grid(row=3, column=0, sticky="w", padx=(0, 8))
        counts = ttk.Frame(status)
        counts.grid(row=3, column=1, sticky="w")
        ttk.Label(counts, textvariable=self.sent_count).pack(side="left")
        ttk.Label(counts, text="    Skipped duplicates:").pack(side="left")
        ttk.Label(counts, textvariable=self.skipped_count).pack(side="left")

        log_frame = ttk.LabelFrame(outer, text="Activity", padding=8)
        log_frame.pack(fill="both", expand=True)

        self.log_box = scrolledtext.ScrolledText(log_frame, height=14, state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True)

    # ---------- Prefix / hotkey handling ----------

    def _on_active_prefix_edited(self, *_):
        self._refresh_active_prefix_display()

    def _select_prefix_from_gui(self):
        self._activate_prefix(self.active_prefix_index.get(), source="GUI")

    def _activate_prefix(self, index, source="Hotkey"):
        if not 0 <= index < MAX_PREFIX_PRESETS:
            return

        self.active_prefix_index.set(index)
        self._active_prefix_value = self.preset_prefixes[index].get()
        self._refresh_active_prefix_display()

        name = self.preset_names[index].get().strip() or f"Prefix {index + 1}"
        prefix = self.preset_prefixes[index].get()
        self._append_log(f"[PREFIX] {source} selected {name}: {prefix!r}")

    def _refresh_active_prefix_display(self):
        try:
            index = self.active_prefix_index.get()
            prefix = self.preset_prefixes[index].get()
            name = self.preset_names[index].get().strip() or f"Prefix {index + 1}"
        except (IndexError, tk.TclError):
            return

        self._active_prefix_value = prefix
        shown = repr(prefix)
        self.active_prefix_text.set(f"{name}  {shown}")

    def _apply_hotkeys(self):
        if keyboard is None:
            messagebox.showerror(
                "keyboard module missing",
                "Global hotkeys require the 'keyboard' package.\n\nInstall it with:\n\npip install keyboard",
            )
            self.active_hotkey_text.set("Hotkeys unavailable: install keyboard")
            return

        self._clear_hotkeys(log_message=False)
        used = set()
        registered = 0

        try:
            for index, hotkey_var in enumerate(self.preset_hotkeys):
                hotkey = hotkey_var.get().strip().lower()
                if not hotkey:
                    continue

                if hotkey in used:
                    raise ValueError(f"Duplicate hotkey: {hotkey}")
                used.add(hotkey)

                # keyboard callbacks run outside Tk's GUI thread, so queue the change.
                handle = keyboard.add_hotkey(
                    hotkey,
                    lambda i=index: self.after(0, self.__prefix, i),
                    suppress=False,
                    trigger_on_release=False,
                )
                self.hotkey_handles.append(handle)
                registered += 1

            self.active_hotkey_text.set(f"{registered} global hotkey(s) active")
            self._append_log(f"[HOTKEY] Applied {registered} global hotkey(s).")

        except Exception as exc:
            self._clear_hotkeys(log_message=False)
            self.active_hotkey_text.set("Hotkey registration failed")
            messagebox.showerror("Hotkey error", str(exc))
            self._append_log(f"[HOTKEY ERROR] {exc}")

    def _clear_hotkeys(self, log_message=True):
        if keyboard is not None:
            for handle in self.hotkey_handles:
                try:
                    keyboard.remove_hotkey(handle)
                except Exception:
                    pass

        self.hotkey_handles.clear()
        self.active_hotkey_text.set("Hotkeys not applied")
        if log_message:
            self._append_log("[HOTKEY] Cleared all global hotkeys.")

    # ---------- GUI helpers ----------

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
                elif action == "activate_prefix":
                    self._activate_prefix(value, source="Hotkey")
                elif action == "reload_filters":
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

    # ---------- Watcher ----------

    def start_watcher(self):
        if self.running:
            return

        log_dir = self.log_directory.get().strip()
        filter_path = self.filter_path.get().strip()
        auth_url = self.auth_url.get().strip()
        send_url = self.send_url.get().strip()
        passcode = self.passcode.get()

        if not log_dir or not filter_path or not auth_url or not send_url:
            messagebox.showerror(
                "Missing settings",
                "Log directory, filter file, auth URL, and send URL are required.",
            )
            return

        self._refresh_active_prefix_display()
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
        marker = self.marker_text.get()
        
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

                    new_path = get_log_path(log_dir)
                    if new_path != path:
                        self._queue_log("Date changed; switching to today's log file.")
                        break

                    if marker not in line:
                        continue

                    translation = line.split(marker, 1)[1].strip()

                    # Reload each time so CSV edits take effect immediately.
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

                    # Plain Python value, updated by GUI/hotkeys on the Tk thread.
                    prefix = self._active_prefix_value

                    sent, auth_ok = send_translation(
                        session,
                        translation,
                        prefix,
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
        self._clear_hotkeys(log_message=False)
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


def send_translation(session, text, prefix, auth_url, send_url, passcode, logger=print):
    text = text.strip()
    if not text:
        return False, True

    full_message = f"{prefix}{text}"
    payload = {"Message": full_message}

    try:
        response = session.post(send_url, json=payload, timeout=5)

        if response.status_code in (401, 403):
            logger("[AUTH] Session expired. Re-authenticating...")

            if not authenticate(session, auth_url, passcode, logger):
                logger("[AUTH] Re-authentication failed.")
                return False, False

            response = session.post(send_url, json=payload, timeout=5)

        response.raise_for_status()
        logger(f"[SENT] {full_message}")
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
