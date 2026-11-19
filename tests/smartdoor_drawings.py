"""Procedural drawings for exercising the real ONNX pipeline without biometric photographs."""

import cv2
import numpy as np


def drawing(variant=0, position=0):
    image = np.full((360, 320, 3), 170, np.uint8)
    center = 160 + position
    if variant == 0:
        skin = (154, 171, 223)
        cv2.ellipse(image, (center, 174), (92, 134), 0, 0, 360, skin, -1)
        eyes = (125 + position, 195 + position)
        eye_y = 153
    else:
        skin = (85, 126, 159)
        cv2.ellipse(image, (center, 180), (103, 110), 0, 0, 360, skin, -1)
        cv2.ellipse(image, (center, 124), (91, 65), 0, 180, 360, (29, 39, 48), -1)
        eyes = (113 + position, 207 + position)
        eye_y = 145
    for x in eyes:
        cv2.ellipse(image, (x, eye_y), (19, 9), 0, 0, 360, (225, 230, 235), -1)
        cv2.circle(image, (x, eye_y), 8, (45, 57, 67), -1)
        cv2.circle(image, (x, eye_y), 4, (25, 22, 20), -1)
        cv2.circle(image, (x - 2, eye_y - 2), 2, (220, 220, 220), -1)
        cv2.ellipse(image, (x, eye_y - 14), (22, 9), 0, 195, 340, (53, 62, 74), 3)
    cv2.ellipse(image, (center, 196), (12, 8), 0, 10, 165, (105, 122, 156), 3)
    cv2.line(image, (center - 5, 165), (center - 9, 194), (136, 149, 191), 2)
    cv2.ellipse(image, (center, 224), (26, 6), 0, 0, 180, (86, 92, 155), 4)
    if variant:
        for x in eyes:
            cv2.ellipse(image, (x, eye_y), (30, 21), 0, 0, 360, (20, 27, 34), 5)
        cv2.line(image, (eyes[0] + 27, eye_y), (eyes[1] - 27, eye_y), (20, 27, 34), 4)
        cv2.ellipse(image, (center, 232), (65, 40), 0, 0, 180, (40, 48, 60), 11)
        cv2.ellipse(image, (center, 213), (30, 6), 0, 180, 360, (40, 48, 60), 6)
    return cv2.imencode(".jpg", image)[1].tobytes()
