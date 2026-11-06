"""Pixel-to-table calibration for a fixed-height, planar grasp workspace."""

from __future__ import annotations

import json
import math
from pathlib import Path


class CalibrationError(ValueError):
    """The requested pixel is not covered by a valid workspace calibration."""


class CalibrationRecord:
    """Four image/table correspondences mapped into arm-base meters.

    Points must be ordered around the workspace in the same direction. Image
    points use the camera frame passed to the detector; base points are XY in
    the arm base frame. `fixed_height_m` is the calibrated grasp height.
    """

    def __init__(
        self,
        image_points=None,
        base_xy_points=None,
        fixed_height_m=None,
    ):
        self.image_points = self._points(image_points, "image_points")
        self.base_xy_points = self._points(base_xy_points, "base_xy_points")
        self.fixed_height = None if fixed_height_m is None else float(fixed_height_m)

    @staticmethod
    def _points(points, name):
        if points is None:
            return None
        parsed = [tuple(map(float, point)) for point in points]
        if len(parsed) != 4 or any(len(point) != 2 for point in parsed):
            raise CalibrationError(f"{name} must contain four (x, y) points")
        if not all(math.isfinite(value) for point in parsed for value in point):
            raise CalibrationError(f"{name} contains a non-finite value")
        return parsed

    @classmethod
    def load(cls, path):
        with Path(path).open("r", encoding="utf-8") as source:
            config = json.load(source)
        return cls(
            image_points=config.get("image_points_px"),
            base_xy_points=config.get("base_xy_points_m"),
            fixed_height_m=config.get("fixed_height_m"),
        )

    def ready(self):
        if (
            self.image_points is None
            or self.base_xy_points is None
            or self.fixed_height is None
            or not math.isfinite(self.fixed_height)
            or self.fixed_height < 0.2
        ):
            return False
        try:
            self._homography()
        except CalibrationError:
            return False
        return True

    def _homography(self):
        import numpy as np

        if (
            self.image_points is None
            or self.base_xy_points is None
            or self.fixed_height is None
            or not math.isfinite(self.fixed_height)
            or self.fixed_height < 0.2
        ):
            raise CalibrationError("Calibration needs four point pairs and a finite grasp height >= 0.2 m")
        rows = []
        values = []
        for (u, v), (x, y) in zip(self.image_points, self.base_xy_points):
            rows.append([u, v, 1, 0, 0, 0, -x * u, -x * v])
            values.append(x)
            rows.append([0, 0, 0, u, v, 1, -y * u, -y * v])
            values.append(y)
        try:
            coefficients = np.linalg.solve(np.asarray(rows, dtype=float), np.asarray(values, dtype=float))
        except np.linalg.LinAlgError as exc:
            raise CalibrationError("Calibration points are degenerate") from exc
        return np.append(coefficients, 1.0).reshape(3, 3)

    def _inside_image_workspace(self, u, v):
        inside = False
        points = self.image_points
        j = len(points) - 1
        for i, (xi, yi) in enumerate(points):
            xj, yj = points[j]
            if (yi > v) != (yj > v):
                crossing_x = (xj - xi) * (v - yi) / (yj - yi) + xi
                if u < crossing_x:
                    inside = not inside
            j = i
        return inside

    def pixel_to_plane(self, u, v):
        import numpy as np

        u, v = float(u), float(v)
        if not math.isfinite(u) or not math.isfinite(v):
            raise CalibrationError("Pixel coordinate is not finite")
        if self.image_points is None or not self._inside_image_workspace(u, v):
            raise CalibrationError("Detection is outside the calibrated workspace")
        homography = self._homography()
        mapped = homography @ np.asarray([u, v, 1.0], dtype=float)
        if abs(mapped[2]) < 1e-9:
            raise CalibrationError("Pixel maps to an invalid plane coordinate")
        x, y = mapped[:2] / mapped[2]
        if not np.isfinite(x) or not np.isfinite(y):
            raise CalibrationError("Pixel maps to a non-finite plane coordinate")
        return float(x), float(y), self.fixed_height
