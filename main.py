#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Live-Anonymisierung (Pixelation) für RTSP-Kameras mit Netzwerk-Streaming.
- Liest RTSP-Stream einer IP-Kamera ein
- Erkennt Gesichter und Personen und verpixelt diese live
- Stellt den anonymisierten Stream als MJPEG über HTTP im Netzwerk bereit
- Kleine HTML-Seite zeigt den Stream im Browser an
- Zusätzlich Anzeige im lokalen Fenster optional möglich

Abhängigkeiten:
    pip install opencv-python numpy flask

Startbeispiel:
    python live_anonymizer_stream.py --host 0.0.0.0 --port 8000
Danach im Browser öffnen:
    http://<IP-dieses-Rechners>:8000/
Direkter Stream-Endpunkt:
    http://<IP-dieses-Rechners>:8000/video
"""

import argparse
import time
import threading
from typing import Tuple, List, Optional
import os

import cv2
import numpy as np
from flask import Flask, Response, render_template_string


# =========================
# Konfiguration (anpassen)
# =========================

# Deine RTSP-URL (vom User geliefert)
DEFAULT_RTSP_URL = "rtsp://Io48S87WqWjPuaSh:Nx9UVb2ozhy0dtsH@192.168.178.73/live0"

# Skalierung für Performance (1.0 = original; 0.75 oder 0.5 spart CPU)
FRAME_DOWNSCALE = 0.75

# Pixelations-Parameter
PIXEL_BLOCKS_FACE = 12
PIXEL_BLOCKS_PERSON = 20

# Gesichts-Erkennung
FACE_MIN_SIZE = (40, 40)  # Mindestgröße (Breite, Höhe) nach Downscale

# Debug-Rahmen zeichnen
DRAW_DEBUG_BOXES = False

# Reconnect-Strategie bei Streamabbruch
RECONNECT_DELAY_SEC = 2.0
MAX_RECONNECT_TRIES = 0  # 0 = unendlich probieren

# Anzeige im lokalen Fenster (True → zusätzlich cv2.imshow)
SHOW_LOCAL_WINDOW = False
WINDOW_TITLE = "Live-Personen-Anonymisierung (anonymisierter Stream)"

# JPEG-Qualität für den MJPEG-Stream (100 = beste Qualität, größte Dateien)
JPEG_QUALITY = 50  # starte mit 60; später ggf. auf 50 oder 70 feinjustieren


# =========================
# Hilfsfunktionen
# =========================

def pixelate_region(img: np.ndarray, blocks: int) -> np.ndarray:
    """
    Verpixelt eine Bildregion (Mosaik). 'blocks' steuert die Grobheit.
    """
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return img
    temp = cv2.resize(img, (max(1, w // blocks), max(1, h // blocks)), interpolation=cv2.INTER_LINEAR)
    return cv2.resize(temp, (w, h), interpolation=cv2.INTER_NEAREST)


def expand_bbox(x: int, y: int, w: int, h: int, scale: float, bounds: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """
    Vergrößert eine Box gleichmäßig und clamped sie an die Bildgrenzen.
    """
    cx = x + w / 2
    cy = y + h / 2
    nw = int(w * scale)
    nh = int(h * scale)
    nx = int(cx - nw / 2)
    ny = int(cy - nh / 2)
    nx = max(0, nx)
    ny = max(0, ny)
    nx2 = min(bounds[0], nx + nw)
    ny2 = min(bounds[1], ny + nh)
    return nx, ny, max(0, nx2 - nx), max(0, ny2 - ny)


def draw_box(frame: np.ndarray, x: int, y: int, w: int, h: int, color=(0, 255, 0), label: str = "") -> None:
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
    if label:
        cv2.putText(frame, label, (x, max(0, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def non_max_suppression(boxes: np.ndarray, overlapThresh: float = 0.65) -> List[Tuple[int, int, int, int]]:
    """
    Einfache NMS für Boxen im Format [x1, y1, x2, y2].
    """
    if len(boxes) == 0:
        return []
    boxes = boxes.astype("float")
    pick = []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]

    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    idxs = np.argsort(y2)

    while len(idxs) > 0:
        i = idxs[-1]
        pick.append(i)
        suppress = [len(idxs) - 1]

        for pos in range(0, len(idxs) - 1):
            j = idxs[pos]
            xx1 = max(x1[i], x1[j])
            yy1 = max(y1[i], y1[j])
            xx2 = min(x2[i], x2[j])
            yy2 = min(y2[i], y2[j])

            w = max(0, xx2 - xx1 + 1)
            h = max(0, yy2 - yy1 + 1)

            overlap = float(w * h) / area[j]
            if overlap > overlapThresh:
                suppress.append(pos)

        idxs = np.delete(idxs, suppress)

    picked = boxes[pick].astype("int")
    return [(int(a), int(b), int(c), int(d)) for (a, b, c, d) in picked]


# =========================
# Detector-Setup
# =========================

def create_face_detector():
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face_cascade = cv2.CascadeClassifier(cascade_path)
    if face_cascade.empty():
        raise RuntimeError(f"Gesichts-Cascade nicht gefunden: {cascade_path}")
    return face_cascade


def create_person_detector():
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return hog


# =========================
# RTSP → Anonymisierte Frames
# =========================

class AnonymizerWorker(threading.Thread):
    """
    Hintergrund-Thread: Liest RTSP, anonymisiert Frames und stellt das letzte verarbeitete Frame bereit.
    """

    def __init__(self, rtsp_url: str):
        super().__init__(daemon=True)
        self.rtsp_url = rtsp_url
        self.face_cascade = create_face_detector()
        self.hog = create_person_detector()
        self.last_frame: Optional[np.ndarray] = None
        self.lock = threading.Lock()
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        reconnect_tries = 0
        while not self._stop.is_set():
          # Backend: FFMPEG verwenden (robuster bei RTSP)
          cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)

          # Kleinen Capture-Puffer erzwingen (verhindert „alten“ Frame-Stau)
          try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
          except Exception:
            pass
            if not cap.isOpened():
                reconnect_tries += 1
                if MAX_RECONNECT_TRIES and reconnect_tries > MAX_RECONNECT_TRIES:
                    print("RTSP konnte nicht geöffnet werden. Beende Worker.")
                    return
                time.sleep(RECONNECT_DELAY_SEC)
                continue

            reconnect_tries = 0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    cap.release()
                    time.sleep(RECONNECT_DELAY_SEC)
                    break

                orig_h, orig_w = frame.shape[:2]

                # Downscale für Performance
                if FRAME_DOWNSCALE != 1.0:
                    frame_small = cv2.resize(
                        frame,
                        (int(orig_w * FRAME_DOWNSCALE), int(orig_h * FRAME_DOWNSCALE)),
                        interpolation=cv2.INTER_AREA
                    )
                else:
                    frame_small = frame

                small_h, small_w = frame_small.shape[:2]

                # Gesichter
                gray = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)
                faces = self.face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=FACE_MIN_SIZE
                )

                # Personen
                rects, weights = self.hog.detectMultiScale(
                    frame_small,
                    winStride=(8, 8),
                    padding=(8, 8),
                    scale=1.05
                )
                rects_np = np.array([[x, y, x + w, y + h] for (x, y, w, h) in rects])
                picks = non_max_suppression(rects_np, overlapThresh=0.65)

                # Pixelation anwenden (auf Originalgröße zurückrechnen)
                out_frame = frame.copy()
                scale_back = (1.0 / FRAME_DOWNSCALE) if FRAME_DOWNSCALE != 0 else 1.0

                for (x, y, w, h) in faces:
                    x, y, w, h = expand_bbox(x, y, w, h, scale=1.15, bounds=(small_w, small_h))
                    X = int(x * scale_back)
                    Y = int(y * scale_back)
                    W = int(w * scale_back)
                    H = int(h * scale_back)
                    roi = out_frame[Y:Y + H, X:X + W]
                    out_frame[Y:Y + H, X:X + W] = pixelate_region(roi, blocks=PIXEL_BLOCKS_FACE)
                    if DRAW_DEBUG_BOXES:
                        draw_box(out_frame, X, Y, W, H, (0, 255, 255), "Face")

                for (x1, y1, x2, y2) in picks:
                    w = x2 - x1
                    h = y2 - y1
                    x, y, w, h = expand_bbox(x1, y1, w, h, scale=1.05, bounds=(small_w, small_h))
                    X = int(x * scale_back)
                    Y = int(y * scale_back)
                    W = int(w * scale_back)
                    H = int(h * scale_back)
                    roi = out_frame[Y:Y + H, X:X + W]
                    out_frame[Y:Y + H, X:X + W] = pixelate_region(roi, blocks=PIXEL_BLOCKS_PERSON)
                    if DRAW_DEBUG_BOXES:
                        draw_box(out_frame, X, Y, W, H, (255, 0, 0), "Person")

                # Letztes Frame aktualisieren
                with self.lock:
                    self.last_frame = out_frame

                if SHOW_LOCAL_WINDOW:
                    cv2.imshow(WINDOW_TITLE, out_frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q') or key == 27:
                        self.stop()
                        break

            # innere while (Reconnect) endet, erneuter Verbindungsversuch folgt

        if SHOW_LOCAL_WINDOW:
            cv2.destroyAllWindows()


# =========================
# Flask-App (MJPEG Stream)
# =========================

HTML_INDEX = """
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Anonymisierter Live-Stream</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    html, body { margin:0; padding:0; background:#111; color:#eee; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; }
    .wrap { max-width: 100vw; display:flex; flex-direction:column; align-items:center; gap:12px; padding:16px; }
    img { max-width: 100%; height: auto; border: 2px solid #444; border-radius: 6px; }
    code { background:#222; padding:4px 8px; border-radius:4px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Anonymisierter Live-Stream (MJPEG)</h1>
    <p>Direkter Stream-Endpunkt: <code>/video</code></p>
    <img src="/video" alt="MJPEG Stream">
  </div>
</body>
</html>
"""

def create_app(worker: AnonymizerWorker) -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(HTML_INDEX)

    @app.route("/video")
    def video():
        def mjpeg_generator():
            boundary = "frame"
            while True:
                with worker.lock:
                    frame = None if worker.last_frame is None else worker.last_frame.copy()
                if frame is None:
                    # Noch kein Frame – kurz warten
                    time.sleep(0.05)
                    continue
                # JPEG kodieren
                ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if not ok:
                    continue
                jpg_bytes = buffer.tobytes()
                yield (
                    b"--" + boundary.encode() + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpg_bytes)).encode() + b"\r\n\r\n" +
                    jpg_bytes + b"\r\n"
                )

        return Response(mjpeg_generator(),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

    return app


# =========================
# Main
# =========================

def parse_args():
    parser = argparse.ArgumentParser(description="RTSP → anonymisierter MJPEG-Stream über HTTP.")
    parser.add_argument("--rtsp", type=str, default=DEFAULT_RTSP_URL, help="RTSP-URL der Kamera")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Bind-Adresse des HTTP-Servers")
    parser.add_argument("--port", type=int, default=8000, help="Port des HTTP-Servers")
    parser.add_argument("--show", action="store_true", help="Lokales Fenster zusätzlich anzeigen")
    return parser.parse_args()


def main():
    args = parse_args()
    global SHOW_LOCAL_WINDOW
    SHOW_LOCAL_WINDOW = bool(args.show)

    worker = AnonymizerWorker(rtsp_url=args.rtsp)
    worker.start()

    app = create_app(worker)
    try:
        app.run(host=args.host, port=args.port, debug=False, threaded=True)
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
        worker.join(timeout=2.0)


if __name__ == "__main__":
    main()
