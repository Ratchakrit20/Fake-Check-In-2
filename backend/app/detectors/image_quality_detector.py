import cv2
import numpy as np
from PIL import Image


class ImageQualityDetector:
    """Small deterministic quality measurements used for adaptive verification."""

    @staticmethod
    def blur_variance(image: Image.Image) -> float:
        gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
