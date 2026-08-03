import numpy as np

from vision.depth_protocol import DepthFrame


def make_depth_frame(sequence=1, received_monotonic=0.0, depth_value=500):
    return DepthFrame(sequence, sequence, received_monotonic, "Duami", "landscapeRight",
        np.zeros((1, 1, 3), np.uint8), np.full((1, 1), depth_value, np.uint16),
        np.full((1, 1), 2, np.uint8), (1.0, 1.0, 0.0, 0.0),
        (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0),
        (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
         0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0))
