"""Synthetic fixtures with independently specified, known card pixels."""

import numpy as np
import pytest

from gget_scanner.config.layout_loader import profile_from_dict


@pytest.fixture
def layout_data():
    return {
        "schema_version": 1,
        "profile_id": "synthetic_grid",
        "coordinate_system": {"type": "normalized_integer", "scale": 10000,
                              "point_order": ["TL", "TR", "BR", "BL"]},
        "screen": {"reference_size": [1000, 1000]},
        "grid": {"rows": 2, "columns": 8,
                 "first_card": [[500, 1000], [1300, 1000], [1300, 3000], [500, 3000]],
                 "horizontal_step": [1200, 0], "vertical_step": [0, 3000]},
    }


@pytest.fixture
def profile(layout_data):
    return profile_from_dict(layout_data)


@pytest.fixture
def synthetic_image():
    image = np.zeros((1000, 1000, 3), dtype=np.uint8)
    for row in range(2):
        for column in range(8):
            index = row * 8 + column
            x, y = 50 + column * 120, 100 + row * 300
            image[y:y + 200, x:x + 80] = (20 + index * 10, 40 + index * 7, 200 - index * 8)
            # Asymmetric corner markers expose flipped/shifted perspective results.
            image[y:y + 8, x:x + 8] = (255, 255, 255)
            image[y + 190:y + 200, x + 70:x + 80] = (10, 20, 30)
    return image
