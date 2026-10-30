import serial
import time
import numpy as np
import os
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# Import parse_frame at module level to avoid repeated import inside methods
try:
    from main import parse_frame as main_parse_frame
except ImportError:
    main_parse_frame = None

class Logger:
    """Simple object for serial logging and frame analysis.

    The parsing logic is kept in :func:`main.parse_frame` so that the
    primary application can be the single source of truth.  Methods on
    this class that need to decode a frame simply import and delegate
    back to that function.
    """

    def __init__(self, port: str, baud: int = 115200, mode: str = "KF", status_callback=None, parse_frame_cb=None):
        self.port = port
        self.baud = baud
        self.ser = None
        self.mode = mode
        # callable called with a string when status should update
        self._status_callback = status_callback
        # optional callback to parse a frame string -> dict
        self._parse_frame_cb = parse_frame_cb

    # ----- serial helpers ------------------------------------------------

    def open(self):
        """Open the serial port and let the board reset."""
        self.ser = serial.Serial(self.port, self.baud, timeout=1)
        time.sleep(2)

    def close(self):
        """Close the underlying port if it is open."""
        if self.ser is not None:
            self.ser.close()
            self.ser = None

    def log_to_file(self, out_file: str, duration_s: float, mode: str):
        """Record lines beginning with ``@`` into *out_file* for
        *duration_s* seconds.
        """
        if self.ser is None:
            self.open()

        self.ser.write(b"START\n")
        mode_cmd = f"MODE={mode}\n"
        self.ser.write(mode_cmd.encode("ascii"))

        t0 = time.time()
        with open(out_file, "w", newline="") as f:
            while (time.time() - t0) < duration_s:
                if self._status_callback:
                    self._status_callback(f"Compression evaluation in {out_file} : {time.time() - t0:.1f}s/{duration_s}s")
                line = self.ser.readline().decode("ascii", errors="ignore").strip()
                if line.startswith("@"):
                    f.write(line + "\n")

        self.ser.write(b"STOP\n")

        if self._status_callback:
            self._status_callback(f"Compression evaluation in {out_file} finished")

    # ---- parsing / analysis helpers -------------------------------------

    def parse_frame(self, line: str):
        """Return the decoded frame dictionary or ``None``.

        Delegates to :func:`main.parse_frame` so that the algorithm is
        defined in a single place.
        """
        # prefer an instance callback to avoid circular imports
        if self._parse_frame_cb is not None:
            return self._parse_frame_cb(line)
        if main_parse_frame is None:
            return None
        return main_parse_frame(line)

    def eval(self, raw_path, lossless_path, duration_s):
        keys = ["ax", "ay", "az"] # baseline and lossless keys

        self.log_to_file(raw_path, duration_s, "KF")
        self.log_to_file(lossless_path, duration_s, "DLT")

        raw_bytes = os.path.getsize(raw_path)
        lossless_bytes = os.path.getsize(lossless_path)

        if self._status_callback:
            ratio = raw_bytes / lossless_bytes if lossless_bytes > 0 else 0
            self._status_callback(f"Raw bytes: {raw_bytes} | Lossless bytes: {lossless_bytes} | Ratio: {ratio:.2f}")
        




