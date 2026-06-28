"""Background removal helpers for generated character sprites."""

from __future__ import annotations

from collections import deque

from PIL import Image


def remove_solid_background(image: Image.Image, threshold: int = 30) -> Image.Image:
    """Make the connected corner background transparent.

    The character generators are prompted to draw on a pure white background.
    A connected flood fill from the corners avoids removing white details that
    are inside the character itself, such as belly patches or eye highlights.
    """
    import numpy as np

    rgba = image.convert("RGBA")
    rgb = np.array(rgba.convert("RGB"), dtype=np.int16)
    alpha = np.array(rgba.getchannel("A"), dtype=np.uint8)
    height, width = alpha.shape
    if height == 0 or width == 0:
        return rgba

    corners = [(0, 0), (0, width - 1), (height - 1, 0), (height - 1, width - 1)]
    bg_colors = [rgb[row, col].copy() for row, col in corners]

    visited = np.zeros((height, width), dtype=bool)
    background = np.zeros((height, width), dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for row, col in corners:
        if not visited[row, col]:
            visited[row, col] = True
            queue.append((row, col))

    def is_background(row: int, col: int) -> bool:
        if alpha[row, col] == 0:
            return True
        pixel = rgb[row, col]
        return any(np.abs(pixel - bg).max() <= threshold for bg in bg_colors)

    while queue:
        row, col = queue.popleft()
        if not is_background(row, col):
            continue
        background[row, col] = True
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = row + dr, col + dc
            if 0 <= nr < height and 0 <= nc < width and not visited[nr, nc]:
                visited[nr, nc] = True
                queue.append((nr, nc))

    alpha[background] = 0
    output = np.dstack([np.array(rgba.convert("RGB"), dtype=np.uint8), alpha])
    return Image.fromarray(output, "RGBA")
