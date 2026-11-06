"""Board-side four-category detector backed by the course-compatible Ascend OM."""

from __future__ import annotations

import time
from pathlib import Path

from shared.schemas import DetectResult


# This order is part of the exported model contract. Map IDs to names here;
# shared.schemas.CLASSES intentionally has a different order.
MODEL_CLASSES = ("recyclable", "kitchen", "hazardous", "other")
IMAGE_SIZE = 640


class MockDetector:
    def __init__(self, script):
        self.script = list(script)

    def detect(self):
        if not self.script:
            return None
        item = self.script.pop(0)
        if item is None:
            return None
        return item if isinstance(item, DetectResult) else DetectResult(**item)


class ScriptedColorTracker:
    """Confidence-below-0.5 fallback. None means locating the target failed."""

    def __init__(self, result=None):
        if result is None:
            self.script = []
        elif isinstance(result, list):
            self.script = list(result)
        else:
            self.script = None
            self.result = result

    def locate(self, detect):
        if self.script is not None:
            if not self.script:
                return None
            return self.script.pop(0)
        return self.result


def _letterbox(image, cv2):
    height, width = image.shape[:2]
    ratio = min(IMAGE_SIZE / height, IMAGE_SIZE / width)
    resized_width, resized_height = round(width * ratio), round(height * ratio)
    pad_x = (IMAGE_SIZE - resized_width) / 2
    pad_y = (IMAGE_SIZE - resized_height) / 2
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    top = round(pad_y - 0.1)
    bottom = round(pad_y + 0.1)
    left = round(pad_x - 0.1)
    right = round(pad_x + 0.1)
    padded = cv2.copyMakeBorder(
        resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
    )
    return padded, ratio, (left, top)


def _decode(output, ratio, pad, image_shape, cv2, confidence_threshold, iou_threshold):
    import numpy as np

    prediction = np.asarray(output, dtype=np.float32)
    if prediction.ndim == 3:
        prediction = prediction[0]
    if prediction.shape[0] != 4 + len(MODEL_CLASSES) and prediction.shape[-1] == 4 + len(MODEL_CLASSES):
        prediction = prediction.T
    if prediction.shape[0] != 4 + len(MODEL_CLASSES):
        raise ValueError(f"Unexpected OM output shape: {prediction.shape}")

    prediction = prediction.T
    class_scores = prediction[:, 4:]
    class_ids = class_scores.argmax(axis=1)
    scores = class_scores[np.arange(len(class_ids)), class_ids]
    selected = scores >= confidence_threshold
    if not selected.any():
        return []

    prediction = prediction[selected]
    class_ids = class_ids[selected]
    scores = scores[selected]
    centers = (prediction[:, :2] - np.asarray(pad, dtype=np.float32)) / ratio
    sizes = prediction[:, 2:4] / ratio
    boxes = np.column_stack((centers - sizes / 2, sizes))

    detections = []
    image_height, image_width = image_shape[:2]
    for class_id in np.unique(class_ids):
        indices = np.where(class_ids == class_id)[0]
        nms_indices = cv2.dnn.NMSBoxes(
            boxes[indices].tolist(), scores[indices].tolist(),
            confidence_threshold, iou_threshold,
        )
        if nms_indices is None or len(nms_indices) == 0:
            continue
        for local_index in np.asarray(nms_indices).reshape(-1):
            x, y, width, height = boxes[indices[int(local_index)]]
            x0 = max(0, min(image_width - 1, int(round(x))))
            y0 = max(0, min(image_height - 1, int(round(y))))
            x1 = max(x0 + 1, min(image_width, int(round(x + width))))
            y1 = max(y0 + 1, min(image_height, int(round(y + height))))
            detections.append((
                MODEL_CLASSES[int(class_id)], float(scores[indices[int(local_index)]]),
                (x0, y0, x1, y1),
            ))
    return sorted(detections, key=lambda item: item[1], reverse=True)


class AscendDetector:
    """Single-frame detector for an OpenCV camera and ais_bench OM inference."""

    def __init__(
        self,
        model_path=None,
        camera_index=0,
        device_id=0,
        frame_source=None,
        confidence_threshold=0.25,
        iou_threshold=0.5,
    ):
        import cv2  # Keep non-board/mock imports independent of board packages.
        import numpy as np
        from ais_bench.infer.interface import InferSession

        self.cv2 = cv2
        self.np = np
        self.model_path = Path(model_path) if model_path else (
            Path(__file__).resolve().parents[1]
            / "models" / "blocks4_v3" / "blocks4_yolov8n.om"
        )
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Ascend model not found: {self.model_path}")
        self.session = InferSession(int(device_id), str(self.model_path))
        self.camera_index = camera_index
        self.frame_source = frame_source
        self.camera = None
        self.confidence_threshold = float(confidence_threshold)
        self.iou_threshold = float(iou_threshold)

    def _read_frame(self):
        if self.frame_source is not None:
            frame = self.frame_source()
            if frame is None:
                raise RuntimeError("Camera frame source returned no frame")
            return frame
        if self.camera is None:
            self.camera = self.cv2.VideoCapture(self.camera_index)
            if not self.camera.isOpened():
                self.camera.release()
                self.camera = None
                raise RuntimeError(f"Cannot open camera index {self.camera_index}")
        ok, frame = self.camera.read()
        if not ok or frame is None:
            raise RuntimeError("Camera failed to return a frame")
        return frame

    def detect(self):
        image = self._read_frame()
        padded, ratio, pad = _letterbox(image, self.cv2)
        tensor = self.np.ascontiguousarray(
            padded[:, :, ::-1].transpose(2, 0, 1), dtype=self.np.float32
        )[None] / 255.0
        outputs = self.session.infer([tensor])
        detections = _decode(
            outputs[0], ratio, pad, image.shape, self.cv2,
            self.confidence_threshold, self.iou_threshold,
        )
        if not detections:
            return None
        category, confidence, (x0, y0, x1, y1) = detections[0]
        return DetectResult(
            cls=category,
            u=(x0 + x1) / 2.0,
            v=(y0 + y1) / 2.0,
            conf=confidence,
            ts=int(time.time() * 1000),
        )

    def close(self):
        if self.camera is not None:
            self.camera.release()
            self.camera = None
