import math
from pathlib import Path

import numpy as np

from .schemas import PointCloudMetadata

# files larger than _SAMPLE_WINDOWS x _SAMPLE_WINDOW_BYTES are read in that many
# windows of that size; many small windows sample a point cloud more evenly than a
# few large ones holding as many bytes
_SAMPLE_WINDOWS = 128
_SAMPLE_WINDOW_BYTES = 64 * 1024
# lines at the start of the file looked at for the first row of numbers, past any
# header
_MAX_HEADER_LINES = 100
# separators accepted besides whitespace, as by GDAL's XYZ driver
_SEPARATORS_TO_SPACES = bytes.maketrans(b",;", b"  ")


def extract_xyz_points_metadata(path: Path | str) -> PointCloudMetadata:
    """Extract the point count and the native bbox of an XYZ point cloud.

    Each row holds an x, a y and possibly further values, separated by whitespace,
    commas or semicolons. Lines before the first row of numbers, such as a header,
    are skipped. A file of up to `_SAMPLE_WINDOWS` windows of
    `_SAMPLE_WINDOW_BYTES` is parsed whole. A larger one is read in
    `_SAMPLE_WINDOWS` such windows, at both ends of the file and evenly spaced in
    between, each parsed from its first to its last complete line: the bbox covers
    the points read, and the point count is estimated from the file size and the
    average length of the rows read. The coordinates come without a CRS. Raises
    ValueError if none of the first `_MAX_HEADER_LINES` lines is a row of at least
    two numbers, if a row has a different number of values than the first or a
    value that is not a number, or if no row is read.

    GDAL's XYZ driver, which extracts the metadata of gridded XYZ files, only reads
    grids: rows of points at a constant spacing, sorted by line. It rejects files
    of irregular points, such as the accepted soundings of a multibeam survey,
    with an "Ungridded dataset" error, which left their records without a bbox.
    Here the text is split and converted to floats by numpy instead. These files
    hold millions of points, often hundreds of MB of text, and parsing one whole
    reads all of it over network storage, at about 60 MB of text per second of
    CPU, about half the speed of GDAL's scan of a gridded file. A record's bbox
    only needs to be approximately right, as it drives map filtering and shows
    where the data lies, so the file is sampled. Measured on accepted soundings
    files of 150 to 360 MB spanning 22 to 56 km, the sampled bboxes fell short of
    the exact ones by at most 335 m on a side, under 1% of their extent, and the
    estimated point counts were within 0.02% of the exact ones, while reading
    8.4 MB per file. Few large windows did worse for as many bytes, as the points
    of these files are not ordered along a survey line: 32 windows of 256 KB fell
    short by up to 1.6 km.
    """
    p = Path(path)
    size = p.stat().st_size
    with p.open("rb", buffering=0) as fh:
        if size <= _SAMPLE_WINDOWS * _SAMPLE_WINDOW_BYTES:
            windows = [(0, fh.read())]
        else:
            last_start = size - _SAMPLE_WINDOW_BYTES
            windows = []
            for index in range(_SAMPLE_WINDOWS):
                start = index * last_start // (_SAMPLE_WINDOWS - 1)
                fh.seek(start)
                windows.append((start, fh.read(_SAMPLE_WINDOW_BYTES)))

    column_count = None
    rows_read = 0
    bytes_read = 0
    min_x = min_y = math.inf
    max_x = max_y = -math.inf
    for start, window in windows:
        end = start + len(window)
        if start > 0:
            # starts within a line, which belongs to the window before
            window = window[window.find(b"\n") + 1 :]
        if end < size:
            # ends within a line, which belongs to the window after
            window = window[: window.rfind(b"\n") + 1]
        window = window.translate(_SEPARATORS_TO_SPACES)
        if column_count is None:
            lines = window.split(b"\n", _MAX_HEADER_LINES)
            for index, line in enumerate(lines[:_MAX_HEADER_LINES]):
                try:
                    values = [float(value) for value in line.split()]
                except ValueError:
                    continue
                if len(values) >= 2:
                    column_count = len(values)
                    window = b"\n".join(lines[index:])
                    break
            else:
                raise ValueError(
                    f"{p.name} has no row of numbers in its first "
                    f"{_MAX_HEADER_LINES} lines"
                )
        values = np.array(window.split(), dtype=np.float64)
        if values.size % column_count:
            raise ValueError(
                f"{p.name} has rows which do not hold {column_count} values"
            )
        if values.size:
            points = values.reshape(-1, column_count)
            rows_read += len(points)
            bytes_read += len(window)
            min_x = min(min_x, float(np.nanmin(points[:, 0])))
            min_y = min(min_y, float(np.nanmin(points[:, 1])))
            max_x = max(max_x, float(np.nanmax(points[:, 0])))
            max_y = max(max_y, float(np.nanmax(points[:, 1])))
    if rows_read == 0:
        raise ValueError(f"{p.name} has no row of numbers")
    return PointCloudMetadata(
        driver="XYZ",
        point_count=(
            rows_read if len(windows) == 1 else round(size * rows_read / bytes_read)
        ),
        point_count_estimated=len(windows) > 1,
        bbox_native=(min_x, min_y, max_x, max_y),
    )
