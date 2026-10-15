"""Track objects in a video: a detector finds them in every frame, a tracker keeps their IDs.
stdin/stdout JSON, like every runner.

    {"video": "clips/street.mp4", "workspace": "<workspace>", "out_dir": "<workspace>/tracks",
     "classes": "car" | ["car", "truck"] | "", "tracker": "bytetrack", "max_frames": 0,
     "threshold": 0.5, "model": "nano"}

Tracker: Roboflow `trackers` (Apache-2.0, https://trackers.roboflow.com, PyPI `trackers`):
SORTTracker, ByteTrackTracker, OCSORTTracker, BoTSORTTracker, CBIoUTracker - each takes
`supervision.Detections` through `tracker.update(detections, frame=None)` and returns them
with `tracker_id` filled in. Detector: RF-DETR (`rfdetr`, Apache-2.0 for Nano/Small/Medium/
Large) - `RFDETRNano().predict(image, threshold=0.5)` returns `supervision.Detections`. Its
weights are downloaded once on first use. Video in and out, and the drawing, is
`supervision` (MIT) on OpenCV.

Writes into the workspace (never outside it): <stem>-tracked.mp4 (boxes, IDs and traces),
<stem>-tracks.json and <stem>-tracks.csv (one row per track). Every heavy import is lazy, so
this file loads with the standard library only; tests inject fake parts through `Kit`.
"""
from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

SETUP_HINT = "Turn on vision-track: python tools/setup_extras.py vision, then enable it in Settings > Capabilities"
TRACKERS = {"sort": "SORTTracker", "bytetrack": "ByteTrackTracker", "ocsort": "OCSORTTracker",
            "botsort": "BoTSORTTracker", "cbiou": "CBIoUTracker"}
MODELS = {"nano": "RFDETRNano", "small": "RFDETRSmall", "medium": "RFDETRMedium", "large": "RFDETRLarge"}
VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv")
# Plain words people use -> COCO class names the detector knows.
ALIASES = {"cars": ["car"], "vehicle": ["car", "truck", "bus", "motorcycle"],
           "vehicles": ["car", "truck", "bus", "motorcycle"], "people": ["person"], "persons": ["person"],
           "pedestrians": ["person"], "pedestrian": ["person"], "humans": ["person"], "human": ["person"],
           "bikes": ["bicycle"], "bike": ["bicycle"], "motorbike": ["motorcycle"], "motorbikes": ["motorcycle"],
           "trucks": ["truck"], "buses": ["bus"], "dogs": ["dog"], "cats": ["cat"], "birds": ["bird"],
           "boats": ["boat"], "planes": ["airplane"], "plane": ["airplane"], "horses": ["horse"],
           "cows": ["cow"], "sheep": ["sheep"], "bicycles": ["bicycle"], "motorcycles": ["motorcycle"],
           "trains": ["train"], "balls": ["sports ball"], "ball": ["sports ball"]}
CROSSED = 0.5   # a track "crossed the frame" when its centre moved over half the width or height


class MissingPackage(RuntimeError):
    pass


def inside(workspace: str | Path, name: str | Path) -> Path:
    """The same rule as loki.resolve_in_workspace: the path must resolve inside the workspace."""
    root = Path(workspace).resolve()
    cleaned = str(name).strip().strip('"').strip("'").strip()
    for prefix in ("res://", "res:/", "./"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    path = (root / cleaned).resolve()
    if path != root and root not in path.parents:
        raise ValueError("path escapes workspace: %s" % name)
    return path


def wanted_classes(value: Any) -> list[str]:
    items = value if isinstance(value, (list, tuple)) else str(value or "").replace(";", ",").replace(" and ", ",").split(",")
    out: list[str] = []
    for item in items:
        word = str(item).strip().lower()
        if not word or word in ("all", "any", "everything", "objects", "things"):
            continue
        for name in ALIASES.get(word, [word]):
            if name not in out:
                out.append(name)
    return out


@dataclass
class Kit:
    """Everything the pipeline touches. `real_kit` builds it from the packages; tests fake it."""
    frames: Iterable[Any]                       # BGR frames (numpy arrays)
    fps: float
    width: int
    height: int
    detect: Callable[[Any], Any]                # frame -> Detections
    tracker: Any                                # .update(detections, frame=None) -> Detections
    keep: Callable[[Any, list], Any]            # (detections, wanted class names) -> Detections
    sink: Callable[[str], Any]                  # path -> context manager with write_frame(frame)
    annotate: Callable[[Any, Any], Any]         # (frame, tracked) -> frame
    names: dict = field(default_factory=dict)   # class_id -> name
    pass_frame: bool = False                    # BoT-SORT uses the frame for camera motion


def _need(module: str, pip_name: str):
    import importlib
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise MissingPackage("%s is not installed in LOKI's environment (pip install %s). %s"
                             % (pip_name, pip_name, SETUP_HINT)) from exc


def _class_names(rfdetr_module) -> dict:
    import importlib
    for where in ("rfdetr.assets.coco_classes", "rfdetr.util.coco_classes"):
        try:
            table = importlib.import_module(where).COCO_CLASSES
        except (ImportError, AttributeError):
            continue
        return dict(table) if isinstance(table, dict) else dict(enumerate(table))
    return {}


def real_kit(video: Path, tracker_name: str, model: str, threshold: float, max_frames: int) -> Kit:
    sv = _need("supervision", "supervision")
    trackers = _need("trackers", "trackers")
    rfdetr = _need("rfdetr", "rfdetr")
    _need("cv2", "opencv-python-headless")
    info = sv.VideoInfo.from_video_path(str(video))
    detector = getattr(rfdetr, MODELS.get(model, "RFDETRNano"))()
    tracker = getattr(trackers, TRACKERS[tracker_name])(frame_rate=float(info.fps or 30))
    names = _class_names(rfdetr)

    def detect(frame):
        return detector.predict(frame[:, :, ::-1].copy(), threshold=threshold)   # BGR -> RGB

    def keep(detections, wanted):
        if not wanted or len(detections) == 0:
            return detections
        import numpy as np
        labels = _labels(detections, names)
        return detections[np.array([label in wanted for label in labels], dtype=bool)]

    boxes, labels_ann = sv.BoxAnnotator(), sv.LabelAnnotator()
    traces = sv.TraceAnnotator(trace_length=int((info.fps or 30) * 2))

    def annotate(frame, tracked):
        text = ["#%s %s" % (tid, label) for tid, label in zip(_ids(tracked), _labels(tracked, names))]
        frame = traces.annotate(frame.copy(), tracked)
        frame = boxes.annotate(frame, tracked)
        return labels_ann.annotate(frame, tracked, labels=text)

    end = max_frames if max_frames > 0 else None
    return Kit(frames=sv.get_video_frames_generator(str(video), end=end), fps=float(info.fps or 30),
               width=int(info.width), height=int(info.height), detect=detect, tracker=tracker, keep=keep,
               sink=lambda path: sv.VideoSink(path, info), annotate=annotate, names=names,
               pass_frame=tracker_name == "botsort")


def _ids(detections) -> list:
    raw = getattr(detections, "tracker_id", None)
    return [] if raw is None else [None if t is None else int(t) for t in list(raw)]


def _labels(detections, names: dict) -> list[str]:
    data = getattr(detections, "data", None) or {}
    if "class_name" in data and data["class_name"] is not None and len(data["class_name"]) == len(detections):
        return [str(n).lower() for n in list(data["class_name"])]
    ids = getattr(detections, "class_id", None)
    ids = [] if ids is None else list(ids)
    return [str(names.get(int(c), "class %s" % c) if c is not None else "object").lower() for c in ids]


def _plural(word: str, n: int) -> str:
    if n == 1:
        return word
    return word + ("es" if word.endswith(("s", "sh", "ch", "x")) else "s")


def summarise(tracks: dict, width: int, height: int, frames_read: int, wanted: list) -> str:
    if not tracks:
        what = " or ".join(_plural(w, 2) for w in wanted) if wanted else "objects"
        return "Found no %s in %d frames." % (what, frames_read)
    by_class: dict[str, list] = {}
    for row in tracks.values():
        by_class.setdefault(row["class"], []).append(row)
    parts = []
    for name, rows in sorted(by_class.items(), key=lambda kv: -len(kv[1])):
        crossed = sum(1 for r in rows if r["crossed"])
        part = "%d %s" % (len(rows), _plural(name, len(rows)))
        if crossed:
            part += "; %d crossed the frame" % crossed
        parts.append(part)
    return "Found " + ", ".join(parts) + " (%d frames)." % frames_read


def run_pipeline(kit: Kit, video: Path, out_dir: Path, wanted: list, max_frames: int = 0) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = video.stem[:80] or "video"
    mp4 = out_dir / (stem + "-tracked.mp4")
    tracks: dict[int, dict] = {}
    frames_read = 0
    with kit.sink(str(mp4)) as sink:
        for index, frame in enumerate(kit.frames):
            if max_frames and index >= max_frames:
                break
            frames_read += 1
            detections = kit.keep(kit.detect(frame), wanted)
            tracked = kit.tracker.update(detections, frame=frame) if kit.pass_frame else kit.tracker.update(detections)
            ids, labels = _ids(tracked), _labels(tracked, kit.names)
            boxes = list(getattr(tracked, "xyxy", []) if getattr(tracked, "xyxy", None) is not None else [])
            for tid, label, box in zip(ids, labels, boxes):
                if tid is None or tid < 0:            # not confirmed yet
                    continue
                x1, y1, x2, y2 = (float(v) for v in list(box)[:4])
                centre = ((x1 + x2) / 2, (y1 + y2) / 2)
                row = tracks.setdefault(tid, {"track_id": tid, "class": label, "first_frame": index,
                                              "last_frame": index, "frames_seen": 0, "start": centre})
                row["last_frame"] = index
                row["frames_seen"] += 1
                row["end"] = centre
            sink.write_frame(kit.annotate(frame, tracked))
    for row in tracks.values():
        sx, sy = row.pop("start")
        ex, ey = row.pop("end")
        row["crossed"] = bool((kit.width and abs(ex - sx) >= CROSSED * kit.width)
                              or (kit.height and abs(ey - sy) >= CROSSED * kit.height))
        row["first_second"] = round(row["first_frame"] / kit.fps, 2) if kit.fps else None
        row["last_second"] = round(row["last_frame"] / kit.fps, 2) if kit.fps else None
    rows = [tracks[k] for k in sorted(tracks)]
    summary = summarise(tracks, kit.width, kit.height, frames_read, wanted)
    json_path = out_dir / (stem + "-tracks.json")
    csv_path = out_dir / (stem + "-tracks.csv")
    json_path.write_text(json.dumps({"video": str(video), "summary": summary, "frames": frames_read,
                                     "fps": kit.fps, "size": [kit.width, kit.height], "classes": wanted,
                                     "tracks": rows}, indent=2), encoding="utf-8")
    columns = ["track_id", "class", "first_frame", "last_frame", "frames_seen", "first_second", "last_second", "crossed"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c) for c in columns})
    return {"summary": summary, "video": str(mp4), "json": str(json_path), "csv": str(csv_path),
            "tracks": len(rows), "frames": frames_read}


def track(job: dict, kit_factory: Callable[..., Kit] = real_kit) -> dict:
    workspace = str(job.get("workspace") or "").strip()
    if not workspace:
        raise ValueError("no workspace given")
    name = str(job.get("video") or "").strip()
    if not name:
        raise ValueError("give a video file in the workspace (url=clips/street.mp4)")
    video = inside(workspace, name)
    out_dir = inside(workspace, job.get("out_dir") or "tracks")
    if video.suffix.lower() not in VIDEO_EXT:
        raise ValueError("%s is not a video file (%s)" % (video.name, ", ".join(VIDEO_EXT)))
    if not video.is_file():
        raise ValueError("no such video in the workspace: %s" % name)
    tracker_name = str(job.get("tracker") or "bytetrack").strip().lower().replace("-", "").replace("_", "")
    if tracker_name not in TRACKERS:
        raise ValueError("tracker must be one of " + ", ".join(TRACKERS))
    model = str(job.get("model") or "nano").strip().lower()
    if model not in MODELS:
        raise ValueError("model must be one of " + ", ".join(MODELS))
    max_frames = max(0, int(job.get("max_frames") or 0))
    threshold = float(job.get("threshold") or 0.5)
    wanted = wanted_classes(job.get("classes"))
    kit = kit_factory(video, tracker_name, model, threshold, max_frames)
    result = run_pipeline(kit, video, out_dir, wanted, max_frames)
    result["tracker"] = tracker_name
    return result


def main() -> None:
    try:
        job = json.loads(sys.stdin.read() or "{}")
        print(json.dumps({"ok": True, **track(job if isinstance(job, dict) else {})}, default=str))
    except MissingPackage as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(exc).__name__, str(exc)[:400])}))


if __name__ == "__main__":
    main()
