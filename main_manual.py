import time
import requests
import threading
import queue
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

RECEIPT_SESSION = requests.Session()
POST_SESSION = requests.Session()
POLL_INTERVAL = 0.1
REQUEST_URL = "http://localhost:5000/transcript"
PREFIX_COMMAND = "/s"
AUTH_URL = "http://localhost:3000/auth"
SEND_URL = "http://localhost:3000/send"
PASSCODE = "7654"
STABLE_TIME = 1
stop_event = threading.Event()
log_queue = queue.Queue()
last_value = None
last_seen = None
last_change = 0
last_sent = None
def log(message):
    log_queue.put(message)
    
def authenticate(POST_SESSION):
    log("[AUTH] Authenticating...")

    try:
        response = POST_SESSION.post(
            AUTH_URL,
            json={"passcode": PASSCODE},
            timeout=5
        )

        response.raise_for_status()

        log("[AUTH] Authentication successful")
        return True

    except requests.RequestException as e:
        log(f"[AUTH ERROR] {e}")
        return False

def send_translation(POST_SESSION, text):
    text = text.strip()

    if not text:
        return False

    payload = {
        "Message": f"{PREFIX_COMMAND} {text}"
    }

    try:
        response = POST_SESSION.post(
            SEND_URL,
            json=payload,
            timeout=5
        )

        # Session expired / authentication lost
        if response.status_code in (401, 403):
            log("[AUTH] Session expired. Re-authenticating...")

            if not authenticate(POST_SESSION):
                log("[AUTH] Re-authentication failed.")
                return False

            # Try the exact same message again
            response = POST_SESSION.post(
                SEND_URL,
                json=payload,
                timeout=5
            )
        response.raise_for_status()

        log(f"[SENT] {text}")
        return True

    except requests.RequestException as e:
        log(f"[SEND ERROR] {e}")
        return False
    

def request_response():
    global last_seen, last_change, last_sent

    try:
        response = RECEIPT_SESSION.get(REQUEST_URL, timeout=5)
        response.raise_for_status()

        value = response.json()[0]

        # Transcript changed
        if value != last_seen:
            last_seen = value
            last_change = time.time()
            return None

        # Transcript hasn't changed long enough
        if time.time() - last_change >= STABLE_TIME:
            if value != last_sent:
                last_sent = value
                return value
            
    except requests.RequestException as e:
        log(f"Request error: {e}")

    except (ValueError, TypeError) as e:
        log(f"Invalid response: {e}")
    return None
    
def main():
        # Authenticate FIRST
        if not authenticate(POST_SESSION):
            
            log("[FATAL] Initial authentication failed.")
            return
        
        log("[INFO] Authentication complete.")
        log("[INFO] Starting log watcher...")
        
        while not stop_event.is_set():
            value = request_response()
            
            if value is not None:
                send_translation(POST_SESSION, value)

            stop_event.wait(POLL_INTERVAL)

def create_gui():
    # Variables that should appear in the GUI
    config_fields = [
        "REQUEST_URL",
        "POLL_INTERVAL",
        "PREFIX_COMMAND",
        "AUTH_URL",
        "SEND_URL",
        "PASSCODE",
        "STABLE_TIME",
    ]

    root = tk.Tk()
    root.title("Transcription Settings")
    root.geometry("650x550")

    gui_vars = {}

    # Create all labels + entry boxes
    for row, name in enumerate(config_fields):

        ttk.Label(
            root,
            text=name
        ).grid(
            row=row,
            column=0,
            sticky="w",
            padx=10,
            pady=5
        )

        gui_vars[name] = tk.StringVar(
            value=str(globals()[name])
        )

        entry = ttk.Entry(
            root,
            textvariable=gui_vars[name],
            width=60
        )

        entry.grid(
            row=row,
            column=1,
            sticky="ew",
            padx=10,
            pady=5
        )

        # Hide passcode
        if name == "PASSCODE":
            entry.config(show="*")

    # Allow entry column to resize
    root.columnconfigure(1, weight=1)
    def apply_settings():
        for name, var in gui_vars.items():
            globals()[name] = type(globals()[name])(var.get())
    def start_main():
        apply_settings()
        stop_event.clear()
        log("[INFO] Started")
        threading.Thread(target=main, daemon=True).start()
    def stop_main():
        log("[INFO] Stopped")
        stop_event.set()
    ttk.Button(
        root,
        text="Start",
        command=start_main
    ).grid(
        row=len(config_fields) + 1,
        column=0,
        columnspan=2,
        pady=10
    )
    ttk.Button(
        root,
        text="Stop",
        command=stop_main
    ).grid(
        row=len(config_fields) + 2,
        column=0,
        columnspan=2,
        pady=10
    )
    log_box = ScrolledText(
        root,
        height=10,
        width=70,
        state="disabled"
    )

    log_box.grid(
        row=len(config_fields) + 3,
        column=0,
        columnspan=2,
        sticky="nsew",
        padx=10,
        pady=10
    )
    def update_log():
        while not log_queue.empty():
            message = log_queue.get()

            log_box.config(state="normal")
            log_box.insert("end", message + "\n")
            log_box.see("end")
            log_box.config(state="disabled")
        root.after(100, update_log)
    def clear_log():
        log_box.config(state="normal")
        log_box.delete("1.0", "end")
        log_box.config(state="disabled")
    ttk.Button(
        root,
        text="Clear Log",
        command=clear_log
    ).grid(
        row=len(config_fields) + 4,
        column=0,
        columnspan=2,
        pady=5
    )

    update_log()
    root.mainloop()
create_gui()