#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Live-Anonymisierung (Pixelation) für RTSP-Kameras mit Netzwerk-Streaming.
- Liest RTSP-Stream einer IP-Kamera ein (RTSP über TCP)
- Erkennt Personen robust mit YOLOv8 (ultralytics) und verpixelt diese vollständig
- Tracking (CSRT) hält Verpixelung stabil, auch wenn Erkennung kurz aussetzt
- Stellt den anonymisierten Stream als MJPEG über HTTP im Netzwerk bereit
- Kleine HTML-Seite zeigt den Stream im Browser an
- Optional zusätzlich Anzeige im lokalen Fenster

Abhängigkeiten:
    pip install ultralytics opencv-python numpy flask

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
import math

# RTSP über TCP für OpenCV/FFmpeg erzwingen (muss vor dem ersten OpenCV-Call gesetzt sein)
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

import cv2
import numpy as np
from flask import Flask, Response, render_template_string

# YOLOv8 (ultralytics)
from ultralytics import YOLO


# =========================
# Konfiguration (anpassen)
# =========================

# Deine RTSP-URL
DEFAULT_RTSP_URL = "rtsp://Io48S87WqWjPuaSh:Nx9UVb2ozhy0dtsH@192.168.178.73/live0"

# Skalierung für Performance (1.0 = original; 0.75 oder 0.5 spart CPU)
FRAME_DOWNSCALE = 0.75

# Pixelations-Parameter
PIXEL_BLOCKS_PERSON = 22      # höher = gröberes Mosaik
BBOX_SCALE_PERSON = 1.20      # Box etwas größer, damit nichts „durchrutscht“

# YOLO-Einstellungen
YOLO_MODEL_NAME = "yolov8n.pt"  # leicht und schnell; alternativ "yolov8s.pt"
YOLO_CONFIDENCE = 0.35          # Konfidenzschwelle
YOLO_IOU_NMS = 0.45             # NMS IoU-Schwelle
YOLO_CLASSES = [0]              # nur "person"
DETECT_EVERY = 2                # alle N Frames neu detektieren (dazwischen nur tracken)
MIN_BOX_AREA = 28 * 28          # sehr kleine Boxen filtern (nach Downscale gemessen)

# Tracking
TRACKER_TYPE = "CSRT"           # "CSRT" (genauer) oder "KCF" (schneller)
TRACK_TTL = 10                  # wie viele Frames darf ein Track ohne frische Erkennung leben
MAX_TRACKS = 32                 # Schutz vor Tracker-Explosion
IOU_MATCH_THRESH = 0.3          # Zuordnung Detection↔Track

# Debug-Rahmen zeichnen
DRAW_DEBUG_BOXES = False

# Reconnect-Strategie bei Streamabbruch
RECONNECT_DELAY_SEC = 2.0
MAX_RECONNECT_TRIES = 0  # 0 = unendlich probieren

# Anzeige im lokalen Fenster (True → zusätzlich cv2.imshow)
SHOW_LOCAL_WINDOW = False
WINDOW_TITLE = "Live-Personen-Anonymisierung (YOLOv8 + Tracking)"

# JPEG-Qualität für den MJPEG-Stream (100 = beste Qualität, größte Dateien)
JPEG_QUALITY = 55  # 50–70 ist meist ein guter Bereich


# =========================
# Hilfsfunktionen
# =========================

def pixelate_region(img: np.ndarray, blocks: int) -> np.ndarray:
    """Verpixelt eine Bildregion (Mosaik). 'blocks' steuert die Grobheit."""
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return img
    temp = cv2.resize(img, (max(1, w // blocks), max(1, h // blocks)), interpolation=cv2.INTER_LINEAR)
    return cv2.resize(temp, (w, h), interpolation=cv2.INTER_NEAREST)


def expand_bbox(x: int, y: int, w: int, h: int, scale: float, bounds: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """Vergrößert eine Box gleichmäßig und clamped sie an die Bildgrenzen."""
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


def draw_box(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int, color=(0, 255, 0), label: str = "") -> None:
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    if label:
        cv2.putText(frame, label, (x1, max(0, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def iou_xyxy(a: np.ndarray, b: np.ndarray) -> float:
    """IoU zweier Boxen im Format [x1,y1,x2,y2]."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    iw = max(0, inter_x2 - inter_x1)
    ih = max(0, inter_y2 - inter_y1)
    inter = iw * ih
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return (inter / union) if union > 0 else 0.0


def create_opencv_tracker():
    """Erzeugt einen OpenCV-Tracker (CSRT bevorzugt, sonst KCF)."""
    tracker = None
    if TRACKER_TYPE.upper() == "CSRT":
        create_names = ["legacy.TrackerCSRT_create", "TrackerCSRT_create"]
    else:
        create_names = ["legacy.TrackerKCF_create", "TrackerKCF_create"]
    for name in create_names:
        parts = name.split(".")
        obj = cv2
        try:
            for p in parts:
                obj = getattr(obj, p)
            tracker = obj()
            break
        except Exception:
            continue
    if tracker is None:
        # Fallback auf MIL (breit verfügbar)
        create_names = ["legacy.TrackerMIL_create", "TrackerMIL_create"]
        for name in create_names:
            parts = name.split(".")
            obj = cv2
            try:
                for p in parts:
                    obj = getattr(obj, p)
                tracker = obj()
                break
            except Exception:
                continue
    if tracker is None:
        raise RuntimeError("Kein geeigneter OpenCV-Tracker verfügbar (CSRT/KCF/MIL nicht gefunden).")
    return tracker


# =========================
# Tracking-Manager
# =========================

class Track:
    def __init__(self, box_xyxy: Tuple[int, int, int, int], frame: np.ndarray):
        self.tracker = create_opencv_tracker()
        x1, y1, x2, y2 = box_xyxy
        w = max(1, x2 - x1)
        h = max(1, y2 - y1)
        self.tracker.init(frame, (x1, y1, w, h))
        self.missed = 0  # wie viele Frames ohne frische Erkennung

    def update(self, frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        ok, box = self.tracker.update(frame)
        if not ok or box is None:
            self.missed += 1
            return None
        x, y, w, h = box
        x1 = int(x)
        y1 = int(y)
        x2 = int(x + w)
        y2 = int(y + h)
        return (x1, y1, x2, y2)


class TrackManager:
    def __init__(self):
        self.tracks: List[Track] = []

    def update_with_detections(self, frame: np.ndarray, dets_xyxy: List[Tuple[int, int, int, int]]) -> None:
        """Detections den bestehenden Tracks zuordnen (IoU) und ggf. neue Tracks anlegen."""
        # Bestehende BBoxen holen
        current_boxes = []
        for t in self.tracks:
            bb = t.update(frame)
            current_boxes.append(bb)

        # IoU-Zuordnung: jede Detection einem besten Track zuweisen (wenn IoU >= Schwelle)
        used_tracks = set()
        used_dets = set()
        for di, det in enumerate(dets_xyxy):
            best_iou, best_ti = 0.0, -1
            for ti, bb in enumerate(current_boxes):
                if bb is None or ti in used_tracks:
                    continue
                iou = iou_xyxy(np.array(det), np.array(bb))
                if iou > best_iou:
                    best_iou, best_ti = iou, ti
            if best_iou >= IOU_MATCH_THRESH and best_ti >= 0:
                # Track mit Detection „re-initen“, damit er sauber sitzt
                self.tracks[best_ti] = Track(det, frame)
                used_tracks.add(best_ti)
                used_dets.add(di)

        # Für nicht zugeordnete Detections neue Tracks erzeugen
        for di, det in enumerate(dets_xyxy):
            if di in used_dets:
                continue
            if len(self.tracks) >= MAX_TRACKS:
                break
            self.tracks.append(Track(det, frame))

        # Nicht gematchte Tracks „altern“ lassen
        for ti, t in enumerate(self.tracks):
            if ti in used_tracks:
                t.missed = 0
            else:
                t.missed += 1

        # Abgelaufene Tracks entfernen
        self.tracks = [t for t in self.tracks if t.missed <= TRACK_TTL]

    def update_only(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Nur Tracks updaten (kein neuerkennungslauf) und BBoxen zurückgeben."""
        boxes = []
        for t in self.tracks:
            bb = t.update(frame)
            if bb is not None:
                boxes.append(bb)
        # Abgelaufene Tracks entfernen
        self.tracks = [t for t in self.tracks if t.missed <= TRACK_TTL]
        return boxes

    def boxes(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Aktuelle Track-BBoxen (nach Update) liefern."""
        out = []
        for t in self.tracks:
            bb = t.update(frame)
            if bb is not None:
                out.append(bb)
        return out


# =========================
# RTSP → Anonymisierte Frames (YOLO + Tracking)
# =========================

class AnonymizerWorker(threading.Thread):
    """
    Hintergrund-Thread:
    - Liest RTSP (über TCP) mit OpenCV/FFmpeg
    - YOLOv8-Detektion (Personen), skaliert und auf Originalreihenfolge zurückgerechnet
    - Tracking (CSRT) hält Boxen stabil
    - Verpixelung auf Originalframe
    - Stellt das letzte verarbeitete Frame bereit
    """

    def __init__(self, rtsp_url: str):
        super().__init__(daemon=True)
        self.rtsp_url = rtsp_url
        self.last_frame: Optional[np.ndarray] = None
        self.lock = threading.Lock()
        self._stop = threading.Event()

        # YOLO-Modell laden (wird beim ersten Mal automatisch heruntergeladen)
        self.yolo = YOLO(YOLO_MODEL_NAME)

        # Tracking-Manager
        self.tracks = TrackManager()

    def stop(self):
        self._stop.set()

    def run(self):
        reconnect_tries = 0
        frame_idx = 0

        while not self._stop.is_set():
            # OpenCV/FFmpeg-Backend mit TCP (OPENCV_FFMPEG_CAPTURE_OPTIONS oben gesetzt)
            cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # kleinen Puffer versuchen
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

                # Downscale für Erkennung/Tracking (Performance)
                if FRAME_DOWNSCALE != 1.0:
                    small_w = int(orig_w * FRAME_DOWNSCALE)
                    small_h = int(orig_h * FRAME_DOWNSCALE)
                    frame_small = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_AREA)
                else:
                    frame_small = frame
                    small_h, small_w = orig_h, orig_w

                out_frame = frame.copy()
                scale_back = (1.0 / FRAME_DOWNSCALE) if FRAME_DOWNSCALE != 0 else 1.0

                det_boxes_small: List[Tuple[int, int, int, int]] = []

                # Alle N Frames: YOLO-Detektion (Personen)
                if frame_idx % DETECT_EVERY == 0:
                    # YOLO erwartet RGB; OpenCV liefert BGR
                    rgb_small = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)
                    results = self.yolo.predict(
                        source=rgb_small,
                        classes=YOLO_CLASSES,
                        conf=YOLO_CONFIDENCE,
                        iou=YOLO_IOU_NMS,
                        verbose=False
                    )
                    dets = []
                    if results and len(results) > 0:
                        r0 = results[0]
                        if r0.boxes is not None and r0.boxes.xyxy is not None:
                            xyxy = r0.boxes.xyxy.cpu().numpy() if hasattr(r0.boxes.xyxy, "cpu") else np.array(r0.boxes.xyxy)
                            confs = r0.boxes.conf.cpu().numpy() if hasattr(r0.boxes.conf, "cpu") else np.array(r0.boxes.conf)
                            for (x1, y1, x2, y2), c in zip(xyxy, confs):
                                w = max(0.0, x2 - x1)
                                h = max(0.0, y2 - y1)
                                if (w * h) < MIN_BOX_AREA:
                                    continue
                                dets.append((int(x1), int(y1), int(x2), int(y2)))
                    det_boxes_small = dets

                    # Tracking-Manager mit neuen Detections auf Originalgröße aktualisieren
                    det_boxes_orig = []
                    for (sx1, sy1, sx2, sy2) in det_boxes_small:
                        # Box leicht vergrößern
                        ex, ey, ew, eh = expand_bbox(sx1, sy1, sx2 - sx1, sy2 - sy1, BBOX_SCALE_PERSON, (small_w, small_h))
                        ox1 = int(ex * scale_back)
                        oy1 = int(ey * scale_back)
                        ox2 = int((ex + ew) * scale_back)
                        oy2 = int((ey + eh) * scale_back)
                        # Clampen
                        ox1 = max(0, min(orig_w - 1, ox1))
                        oy1 = max(0, min(orig_h - 1, oy1))
                        ox2 = max(0, min(orig_w, ox2))
                        oy2 = max(0, min(orig_h, oy2))
                        if ox2 > ox1 and oy2 > oy1:
                            det_boxes_orig.append((ox1, oy1, ox2, oy2))

                    self.tracks.update_with_detections(out_frame, det_boxes_orig)

                else:
                    # Nur vorhandene Tracks fortschreiben
                    self.tracks.update_only(out_frame)

                # Alle Track-Boxen holen und verpixeln
                for (x1, y1, x2, y2) in self.tracks.boxes(out_frame):
                    # Sicherheitshalber nochmals Box minimal vergrößern
                    w = x2 - x1
                    h = y2 - y1
                    ex, ey, ew, eh = expand_bbox(x1, y1, w, h, 1.02, (orig_w, orig_h))
                    X1, Y1, X2, Y2 = ex, ey, ex + ew, ey + eh
                    roi = out_frame[Y1:Y2, X1:X2]
                    out_frame[Y1:Y2, X1:X2] = pixelate_region(roi, blocks=PIXEL_BLOCKS_PERSON)
                    if DRAW_DEBUG_BOXES:
                        draw_box(out_frame, X1, Y1, X2, Y2, (0, 255, 0), "person")

                # Letztes Frame aktualisieren
                with self.lock:
                    self.last_frame = out_frame

                if SHOW_LOCAL_WINDOW:
                    cv2.imshow(WINDOW_TITLE, out_frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q') or key == 27:
                        self.stop()
                        break

                frame_idx += 1

            # Reconnect
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
                    time.sleep(0.02)
                    continue
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
    parser = argparse.ArgumentParser(description="RTSP → anonymisierter MJPEG-Stream über HTTP (YOLOv8 + Tracking).")
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