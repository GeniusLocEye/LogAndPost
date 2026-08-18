import json
import time
import requests
import os
import csv
from datetime import datetime


LOG_DIRECTORY = r"C:\Users\shado\AppData\Local\VRC Speech To Text\Exceptions"
FILTER_PATH = r"Z:\STT-TTS\LogAndPost\filter.csv"
PREFIX_COMMAND = r"/s"

def get_log_path():
    filename = datetime.now().strftime("Log-%Y%m%d.txt")
    return os.path.join(LOG_DIRECTORY, filename)

LOG_FILE = get_log_path()
AUTH_URL = "http://localhost:3000/auth"
SEND_URL = "http://localhost:3000/send"
OUTPUT_SEARCH = "Full Translation:"
PASSCODE = "7654"

POLL_INTERVAL = 0.1

session = requests.Session()
def authenticate(session):
    print("[AUTH] Authenticating...")

    try:
        response = session.post(
            AUTH_URL,
            json={"passcode": PASSCODE},
            timeout=5
        )

        response.raise_for_status()

        print("[AUTH] Authentication successful")
        return True

    except requests.RequestException as e:
        print(f"[AUTH ERROR] {e}")
        return False


def send_translation(session, text):
    text = text.strip()

    if not text:
        return False

    payload = {
        "Message": f"{PREFIX_COMMAND}{text}"
    }

    try:
        response = session.post(
            SEND_URL,
            json=payload,
            timeout=5
        )

        # Session expired / authentication lost
        if response.status_code in (401, 403):
            print("[AUTH] Session expired. Re-authenticating...")

            if not authenticate(session):
                print("[AUTH] Re-authentication failed.")
                return False

            # Try the exact same message again
            response = session.post(
                SEND_URL,
                json=payload,
                timeout=5
            )

        response.raise_for_status()

        print(f"[SENT] {text}")
        return True

    except requests.RequestException as e:
        print(f"[SEND ERROR] {e}")
        return False

def load_filters(filename):
    filters = {}

    with open(filename, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            filters[row["find"]] = row["replace"]
    return filters
def apply_filters(text, filters):
    for find, replace in filters.items():
        text = text.replace(find, replace)
    return text
def tail_file(path):
    """
    Follow a file like `tail -f`.

    Starts at the current end of the file, so existing
    log entries aren't processed.
    """

    while True:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as file:
                # Start at the end of the existing log.
                file.seek(0, 2)

                print(f"Watching: {path}")

                while True:
                    line = file.readline()

                    if not line:
                        time.sleep(POLL_INTERVAL)

                        # Detect log rotation/replacement.
                        try:
                            current_size = __import__("os").path.getsize(path)

                            if current_size < file.tell():
                                print("Log file was truncated/replaced. Reopening...")
                                break

                        except OSError:
                            break

                        continue

                    yield line

        except FileNotFoundError:
            print(f"Waiting for log file: {path}")
            time.sleep(1)

        except PermissionError:
            print("Permission denied reading log file. Retrying...")
            time.sleep(1)

        except OSError as e:
            print(f"Log error: {e}")
            time.sleep(1)


def main():
    session = requests.Session()

    # Authenticate FIRST
    if not authenticate(session):
        print("[FATAL] Initial authentication failed.")
        return

    print("[INFO] Authentication complete.")
    print("[INFO] Starting log watcher...")

    last_translation = None
    filters = load_filters(FILTER_PATH)
    for line in tail_file(get_log_path()):

        marker = "{OUTPUT_SEARCH}"

        if marker not in line:
            continue

        translation = line.split(marker, 1)[1].strip()
        translation = apply_filters(translation, filters)
        
        if not translation:
            continue

        # Prevent consecutive duplicates
        if translation == last_translation:
            print(f"[SKIPPED] Duplicate: {translation}")
            continue

        if send_translation(session, translation):
            last_translation = translation


if __name__ == "__main__":
    main()