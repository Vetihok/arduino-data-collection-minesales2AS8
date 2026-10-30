from collections import deque
import threading
import time

import serial
from logger import Logger
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

# -------- Configuration --------
SERIAL_PORT = input("Enter the actual serial port : ")
BAUDRATE = 9600

MAX_ROWS = 100
INDEX_HTML_PATH = "index.html"   # same folder as this script

LOG_KF_MODE_PATH = "log_kf.txt"
LOG_DLT_MODE_PATH = "log_dlt.txt"

EVAL_DURATION = 30
EVAL_KF_MODE_PATH = "log_kf_only.txt"
EVAL_DLT_MODE_PATH = "log_kf_dlt.txt"

# -------- Global state --------
ser = None
logger = None            # will hold an instance of logger.Logger once opened
serial_lock = threading.Lock()
status = ""
f_kf = None  # file object for KF mode
f_dlt = None # file object for DLT mode

data_buffer = deque(maxlen=MAX_ROWS)
stats_buffer = deque(maxlen=1)
buffer_lock = threading.Lock()
stats_lock = threading.Lock()

stop_reader = False
compression_eval = False

app = FastAPI()


def parse_frame(line: str):
    """Parse a frame beginning with '@'.

    This is the same logic used by :mod:`logger` so placing it here
    allows both modules to share one implementation.  The function
    returns a dictionary with fields ``seq``, ``ms``, ``type``, ``kv``
    and ``received_at`` or ``None`` if the line is invalid.
    """
    line = line.strip()
    if not line.startswith("@") or "*" not in line:
        print("Error: line doesn't start with @ or doesn't contain * : ", line)
        return None
    payload_part = line[1:]
    body, cs_hex = payload_part.rsplit("*", 1)
    cs_hex = cs_hex.strip()
    try:
        cs = int(cs_hex[:2], 16)
    except ValueError:
        print("Error: parsing checksum failed : ", line)
        return None

    # compute checksum
    x = 0
    for ch in body:
        x ^= ord(ch) & 0xFF
    if x != cs:
        print("Error: checksum invalid : ", line)
        return None

    parts = body.split(",", 3)
    if len(parts) < 4:
        print("Error: less than 4 parts in ", line)
        return None

    seq = int(parts[0])
    ms = int(parts[1])
    ftype = parts[2]
    kv_str = parts[3]
    kv = {}
    for item in kv_str.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            kv[k.strip()] = v.strip()
    return {"seq": seq, "ms": ms, "type": ftype, "kv": kv, "received_at": time.time()}


def open_serial():
    """Create a :class:`logger.Logger` and open the port.

    The original code opened the serial port directly; by going
    through the Logger object we make the serial connection reusable
    elsewhere (for example the on‑disk logging helper).
    """
    global ser, logger
    global f_kf, f_dlt
    # pass the parse_frame function to Logger to avoid circular imports
    logger = Logger(SERIAL_PORT, BAUDRATE, status_callback=_status_callback, parse_frame_cb=parse_frame)
    logger.open()
    ser = logger.ser
    f_kf = open(LOG_KF_MODE_PATH, "w", newline="")
    f_dlt = open(LOG_DLT_MODE_PATH, "w", newline="")


def serial_reader_loop():
    global stop_reader
    global compression_eval
    global status
    while not stop_reader:
        # if the button COMPRESSION EVAL is pressed it triggers an evaluation 
        # of the DLT compression mode during EVAL_DURATION seconds
        if compression_eval:
            try:
                logger.eval(EVAL_KF_MODE_PATH, EVAL_DLT_MODE_PATH, EVAL_DURATION)
            except Exception as exc:
                print("eval() raised", exc)
            compression_eval = False
        
        try:
            line = ser.readline().decode(errors="ignore").strip()
        except Exception:
            time.sleep(0.1)
            continue

        if not line:
            continue

        # if the board sent one of the framed log messages we can parse it
        # using the shared helper in this module and keep it in the buffer
        if line.startswith("@"):
            fr = parse_frame(line)
            if fr is not None:
                if fr.get("kv", {}).get("cmd") == "STATS":
                    with stats_lock:
                        stats_buffer.append(fr)
                        status = "Stats received"
                else:
                    if logger.mode == "KF":
                        f_kf.write(line + "\n")
                    else:
                        f_dlt.write(line + "\n")
                    with buffer_lock:
                        data_buffer.append(fr)
            # drop through so that frames are not mistaken for IMU lines
            continue


def start_background_reader():
    open_serial()
    thread = threading.Thread(target=serial_reader_loop, daemon=True)
    thread.start()
    return thread

# status callback used by Logger to update the shared variable
def _status_callback(msg: str):
    global status
    status = msg

# -------- FastAPI lifecycle --------

@app.on_event("startup")
def on_startup():
    start_background_reader()


@app.on_event("shutdown")
def on_shutdown():
    global stop_reader
    stop_reader = True
    time.sleep(0.2)
    if ser is not None:
        ser.close()


# -------- Routes --------

@app.get("/", response_class=HTMLResponse)
def index():
    # Read index.html from disk and return it
    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(content=html)


@app.get("/data", response_class=JSONResponse)
def get_data():
    with buffer_lock:
        rows = list(data_buffer)
    if len(stats_buffer) > 0:
        with stats_lock:
            stats_frame = stats_buffer.pop()
            arduino_stats = {}
            for axis in ['ax', 'ay', 'az']:
                arduino_stats[axis] = {
                    "mean": stats_frame.get("kv", {}).get(f"{axis}_mean"),
                    "min": stats_frame.get("kv", {}).get(f"{axis}_min"),
                    "max": stats_frame.get("kv", {}).get(f"{axis}_max")
                }
            with buffer_lock:
                imu_rows = [r for r in data_buffer 
                           if r.get("type") in ["KF", "DLT"] and "ax" in r.get("kv", {})]

            recent = imu_rows[-stats_count:]
            python_stats = {}
            for axis in ['ax', 'ay', 'az']:
                vals = []
                for r in recent:
                    kv = r.get("kv", {})
                    key = axis if axis in kv else f"d{axis}"
                    if key in kv:
                        try:
                            vals.append(float(kv[key]))
                        except (ValueError, TypeError):
                            pass
                if vals:
                    python_stats[axis] = {
                        "mean": sum(vals) / len(vals),
                        "min": min(vals),
                        "max": max(vals),
                    }
                else:
                    python_stats[axis] = {"mean": None, "min": None, "max": None}

            _status_callback("Stats request succeeded")
            return {"status": status, "type": "stats",
                    "arduino": arduino_stats,
                    "python": python_stats,
                    "count": stats_count}
    return {"status": status, "type": "data", "rows": rows}


@app.post("/start", response_class=JSONResponse)
def start_recording():
    if ser is None:
        _status_callback("no-serial")
        return {"status": status}
    with serial_lock:
        ser.write(b"START\n")
    _status_callback("START sent")
    return {"status": status}


@app.post("/stop", response_class=JSONResponse)
def stop_recording():
    if ser is None:
        _status_callback("no-serial")
        return {"status": "no-serial"}
    with serial_lock:
        ser.write(b"STOP\n")
    _status_callback("STOP sent")
    return {"status": status}


@app.post("/dlt", response_class=JSONResponse)
def mode_dlt():
    if ser is None:
        _status_callback("no-serial")
        return {"status": "no-serial"}
    with serial_lock:
        ser.write(b"MODE=DLT\n")
        logger.mode = "DLT"
    _status_callback("MODE=DLT sent")
    return {"status": status}


@app.post("/kf", response_class=JSONResponse)
def mode_kf():
    if ser is None:
        _status_callback("no-serial")
        return {"status": "no-serial"}
    with serial_lock:
        ser.write(b"MODE=KF\n")
        logger.mode = "KF"
    _status_callback("MODE=KF sent")
    return {"status": status}


@app.post("/stats/{n}", response_class=JSONResponse)
def request_stats(n: int):
    global stats_count
    stats_count = n if n > 0 else 50
    if ser is None:
        _status_callback("no-serial")
        return {"status": "no-serial"}
    with serial_lock:
        if n == 0:
            ser.write(f"STATS\n".encode())
        else:
            ser.write(f"STATS{n}\n".encode())
    _status_callback("STATS sent")
    return {"status": status}

@app.post("/eval", response_class=JSONResponse)
def eval():
    global compression_eval
    compression_eval = True
    _status_callback("COMPRESSION EVALUATION started")
    return {"status": status}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
