"""Single authority for source-plan to issued-board coordinate transforms.

Mechanical geometry must never be stretched independently in X and Y.  The
same uniform affine transform is used by copied architecture, graph-native
routes, equipment and the exact-output QA evidence.
"""
from __future__ import annotations

import math


def uniform_fit(source_bounds, target_bounds):
    sx1, sy1, sx2, sy2 = map(float, source_bounds)
    tx1, ty1, tx2, ty2 = map(float, target_bounds)
    sw, sh = sx2 - sx1, sy2 - sy1
    tw, th = tx2 - tx1, ty2 - ty1
    if min(sw, sh, tw, th) <= 1e-9 or not all(map(math.isfinite, (sx1, sy1, sx2, sy2, tx1, ty1, tx2, ty2))):
        raise ValueError("INVALID_COORDINATE_BOUNDS")
    scale = min(tw / sw, th / sh)
    width, height = sw * scale, sh * scale
    offset_x = tx1 + (tw - width) / 2.0
    offset_y = ty1 + (th - height) / 2.0
    return {
        "scale": scale, "scale_x": scale, "scale_y": scale,
        "offset_x": offset_x, "offset_y": offset_y,
        "source_origin": (sx1, sy1),
        "source_bounds": (sx1, sy1, sx2, sy2),
        "target_bounds": (tx1, ty1, tx2, ty2),
        "fitted_bounds": (offset_x, offset_y, offset_x + width, offset_y + height),
    }


def map_point(point, transform):
    x, y = map(float, point[:2])
    sx1, sy1 = transform["source_origin"]
    scale = transform["scale"]
    return (transform["offset_x"] + (x - sx1) * scale,
            transform["offset_y"] + (y - sy1) * scale)


def inverse_point(point, transform):
    x, y = map(float, point[:2])
    scale = transform["scale"]
    if abs(scale) <= 1e-12:
        raise ValueError("ZERO_COORDINATE_SCALE")
    sx1, sy1 = transform["source_origin"]
    return (sx1 + (x - transform["offset_x"]) / scale,
            sy1 + (y - transform["offset_y"]) / scale)


def transform_evidence(transform, sample_points):
    mapped = [map_point(point, transform) for point in sample_points]
    recovered = [inverse_point(point, transform) for point in mapped]
    error = max((math.dist(tuple(map(float, source[:2])), restored)
                 for source, restored in zip(sample_points, recovered)), default=0.0)
    scale_x = float(transform["scale_x"]); scale_y = float(transform["scale_y"])
    anisotropy = abs(scale_x / scale_y - 1.0) if abs(scale_y) > 1e-12 else math.inf
    return {
        "scale_x": scale_x, "scale_y": scale_y,
        "anisotropy": anisotropy, "roundtrip_max_error": error,
        "uniform": anisotropy <= 0.005,
        "roundtrip_pass": error <= 1e-6,
        "source_bounds": list(transform["source_bounds"]),
        "target_bounds": list(transform["target_bounds"]),
        "fitted_bounds": list(transform["fitted_bounds"]),
    }
