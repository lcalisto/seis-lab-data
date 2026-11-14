import datetime as dt
import logging
import math
import struct
import typing
from pathlib import Path

from .schemas import KmallMetadata

logger = logging.getLogger(__name__)

# numBytesDgm, dgmType, dgmVersion, systemID, echoSounderID, time_sec, time_nanosec
_DATAGRAM_HEADER = struct.Struct("<I4sBBHII")
# A datagram is at least the header plus the repeated length field at its tail.
_MIN_DATAGRAM_BYTES = _DATAGRAM_HEADER.size + 4
# #SPO is the primary position source; #CPO duplicates the same sensor feed
# (verified on the archive files) and only serves as a fallback.
_POSITION_DATAGRAMS = (b"#SPO", b"#CPO")
# The position datagram body starts with a common part whose length is the
# leading uint16; the sensor-data block after it opens with two uint32 times
# and a float32 fix quality, then the latitude/longitude doubles.
_SENSOR_DATA_LATLON_OFFSET = 12
_POSITION_BODY_BYTES = 64  # enough to reach the doubles in every revision seen
# each datagram ends with a copy of its length
_TRAILING_LENGTH = struct.Struct("<I")
# `extract_kmall_metadata` reads files larger than _SAMPLE_WINDOWS x
# _SAMPLE_WINDOW_BYTES in that many windows of that size; measured on archive files,
# a window holds about 5 position fixes, and the sampled bbox and dates matched those
# of a full walk
_SAMPLE_WINDOWS = 16
_SAMPLE_WINDOW_BYTES = 256 * 1024
# `collect_position_fixes` needs every fix: large reads, rather than one small read
# per datagram, cut the round trips to storage and the CPU time
_FULL_WALK_BUFFER_BYTES = 1024 * 1024


def extract_kmall_metadata(path: Path | str) -> KmallMetadata:
    """Extract metadata from a Kongsberg KMALL file by reading sampled windows of it.

    A file of up to `_SAMPLE_WINDOWS` windows of `_SAMPLE_WINDOW_BYTES` is read
    whole and walked forward from its start. A larger one is read in
    `_SAMPLE_WINDOWS` such windows: the first is walked forward from the start of
    the file, the last backward from its end, using the copy of each datagram's
    length in its last 4 bytes, and those evenly spaced in between forward from
    their first datagram boundary. The temporal extent and the bbox cover the
    datagrams read: the ends of a survey line are always among them, while the
    extremes of a curved track can be missed by the distance covered between two
    windows. A walk stops at the first truncated or corrupt datagram, keeping what
    it gathered so far. A file whose first datagram is invalid raises ValueError.

    Sampling keeps the discovery of KMALL-heavy survey missions tractable. A KMALL
    file has no index nor summary of its extent: the position of each datagram is
    only known from the length of the previous one, and the position fixes are
    spread through the file, about one every 50 KB, between much larger sounding
    datagrams. An exact bbox therefore needs a walk over every datagram header,
    which costs either one small read per datagram, i.e. tens of thousands of round
    trips to network storage per file, or reading the whole file, since with any
    read buffer above the largest datagrams (about 39 KB) the reads end up covering
    the file. A mission can hold thousands of these files, of up to almost 2 GB
    each, about 800 MB on average, so a full walk amounts to terabytes read and
    hours of CPU time. Measured against the full walk on files of 3 MB to 1.5 GB
    from several vessels and survey areas, the sampled read gave the same bbox and
    dates, while reading about 4 MB per file in `_SAMPLE_WINDOWS` reads, in under
    a second over a slow network mount instead of up to two minutes. The bbox and
    the temporal extent of a record only need to be approximately right: exact for
    straight survey lines, off by at most the distance covered between two windows
    for curved tracks.
    """
    p = Path(path)
    size = p.stat().st_size
    # running min/max, not first/last: real files interleave sensor datagrams
    # with header times backstepping up to ~3 s, which could shift a date at a
    # UTC midnight boundary
    min_time = max_time = None
    echo_sounder_id = None
    boxes: dict[bytes, tuple[float, float, float, float] | None] = {
        dgm_type: None for dgm_type in _POSITION_DATAGRAMS
    }

    with p.open("rb", buffering=0) as fh:
        if size <= _SAMPLE_WINDOWS * _SAMPLE_WINDOW_BYTES:
            windows = [(fh.read(), _walk_window_forward)]
        else:
            tail_start = size - _SAMPLE_WINDOW_BYTES
            middle_starts = [
                _SAMPLE_WINDOW_BYTES
                + index
                * (tail_start - 2 * _SAMPLE_WINDOW_BYTES)
                // (_SAMPLE_WINDOWS - 3)
                for index in range(_SAMPLE_WINDOWS - 2)
            ]
            windows = [(fh.read(_SAMPLE_WINDOW_BYTES), _walk_window_forward)]
            for start in middle_starts:
                fh.seek(start)
                windows.append(
                    (fh.read(_SAMPLE_WINDOW_BYTES), _walk_window_from_boundary)
                )
            fh.seek(tail_start)
            windows.append((fh.read(_SAMPLE_WINDOW_BYTES), _walk_window_backward))
    if _parse_header(windows[0][0], 0, size) is None:
        # empty, smaller than one header, or invalid from its first datagram
        raise ValueError(f"{p.name} does not look like a KMALL file")

    for window, walk in windows:
        for dgm_type, timestamp, sounder_id, body in walk(window, size):
            if echo_sounder_id is None:
                echo_sounder_id = sounder_id
            min_time = timestamp if min_time is None else min(min_time, timestamp)
            max_time = timestamp if max_time is None else max(max_time, timestamp)
            if body is not None and (fix := _parse_position_fix(body)) is not None:
                lon, lat = fix
                box = boxes[dgm_type]
                boxes[dgm_type] = (
                    (lon, lat, lon, lat)
                    if box is None
                    else (
                        min(box[0], lon),
                        min(box[1], lat),
                        max(box[2], lon),
                        max(box[3], lat),
                    )
                )

    bbox = next(
        (boxes[dgm_type] for dgm_type in _POSITION_DATAGRAMS if boxes[dgm_type]),
        None,
    )
    return KmallMetadata(
        driver="KMALL",
        # positions are geographic degrees from the GNSS feed; the format
        # declares no datum, WGS84-family in practice (sub-metre difference,
        # far below the bbox buffer) - documented approximation
        epsg=4326 if bbox is not None else None,
        crs_name="WGS 84" if bbox is not None else None,
        bbox_native=bbox,
        bbox_4326=bbox,
        temporal_extent_begin=_utc_date(min_time),
        temporal_extent_end=_utc_date(max_time),
        echo_sounder_id=echo_sounder_id,
        duration_seconds=(max_time - min_time if min_time is not None else None),
    )


def _parse_header(
    window: bytes, offset: int, size: int
) -> tuple[int, bytes, int, float] | None:
    """Parse the datagram header at `offset` of a window of a file of `size` bytes.

    Returns the datagram's length, type, echo sounder id and timestamp, or None
    if the header does not fit in the window, or is invalid: a length too short
    for a datagram or longer than the file, or a type not starting with `#`.
    """
    if offset < 0 or offset + _DATAGRAM_HEADER.size > len(window):
        return None
    (
        num_bytes,
        dgm_type,
        _dgm_version,
        _system_id,
        sounder_id,
        time_sec,
        time_nanosec,
    ) = _DATAGRAM_HEADER.unpack_from(window, offset)
    if (
        num_bytes < _MIN_DATAGRAM_BYTES
        or num_bytes > size
        or not dgm_type.startswith(b"#")
    ):
        return None
    return num_bytes, dgm_type, sounder_id, time_sec + time_nanosec / 1e9


def _position_body(window: bytes, offset: int, num_bytes: int, dgm_type: bytes):
    """The head of the #SPO/#CPO datagram at `offset`; None for other types."""
    if dgm_type not in _POSITION_DATAGRAMS:
        return None
    start = offset + _DATAGRAM_HEADER.size
    # capped here, once: the cap decides which fixes are usable, so the bbox and
    # the collected fixes must share it
    return window[
        start : start + min(num_bytes - _DATAGRAM_HEADER.size, _POSITION_BODY_BYTES)
    ]


def _walk_window_forward(
    window: bytes, size: int, offset: int = 0
) -> typing.Iterator[tuple[bytes, float, int, bytes | None]]:
    """Yield (dgm_type, timestamp, sounder_id, body) from `offset` of a window on.

    The walk stops at the first invalid datagram, or at the first one that does
    not end within the window.
    """
    while (header := _parse_header(window, offset, size)) is not None:
        num_bytes, dgm_type, sounder_id, timestamp = header
        if offset + num_bytes > len(window):
            break
        yield (
            dgm_type,
            timestamp,
            sounder_id,
            _position_body(window, offset, num_bytes, dgm_type),
        )
        offset += num_bytes


def _walk_window_backward(
    window: bytes, size: int
) -> typing.Iterator[tuple[bytes, float, int, bytes | None]]:
    """Yield (dgm_type, timestamp, sounder_id, body) from the end of a window back.

    The window must end where the file does. Each datagram is found from the copy
    of its length in its last 4 bytes; the walk stops at the first one whose
    header does not repeat that length.
    """
    end = len(window)
    while end >= _MIN_DATAGRAM_BYTES:
        (num_bytes,) = _TRAILING_LENGTH.unpack_from(window, end - 4)
        offset = end - num_bytes
        header = _parse_header(window, offset, size)
        if header is None or header[0] != num_bytes:
            break
        _, dgm_type, sounder_id, timestamp = header
        yield (
            dgm_type,
            timestamp,
            sounder_id,
            _position_body(window, offset, num_bytes, dgm_type),
        )
        end = offset


def _walk_window_from_boundary(
    window: bytes, size: int
) -> typing.Iterator[tuple[bytes, float, int, bytes | None]]:
    """Yield (dgm_type, timestamp, sounder_id, body) from a window that starts anywhere.

    The walk starts at the first offset where a datagram with a valid header ends
    with a copy of its length, and is followed by another valid header, which
    rules out a `#` inside a payload being taken for a datagram type.
    """
    index = window.find(b"#", 4)
    while index != -1:
        offset = index - 4
        if (
            (header := _parse_header(window, offset, size)) is not None
            and offset + header[0] <= len(window)
            and _TRAILING_LENGTH.unpack_from(window, offset + header[0] - 4)[0]
            == header[0]
            and _parse_header(window, offset + header[0], size) is not None
        ):
            yield from _walk_window_forward(window, size, offset)
            return
        index = window.find(b"#", index + 1)


def collect_position_fixes(path: Path | str) -> list[tuple[float, float]]:
    """Every usable (lon, lat) position fix of a KMALL file, in file order.

    Same filter and precedence as the bbox of extract_kmall_metadata: the #SPO
    fixes, or the #CPO when no single #SPO fix is usable. An empty list
    is a valid outcome since a file may hold no position datagram at all. The
    whole file is walked, read in blocks of `_FULL_WALK_BUFFER_BYTES`.
    """
    p = Path(path)
    size = p.stat().st_size
    fixes: dict[bytes, list[tuple[float, float]]] = {
        dgm_type: [] for dgm_type in _POSITION_DATAGRAMS
    }
    with p.open("rb", buffering=_FULL_WALK_BUFFER_BYTES) as fh:
        for dgm_type, _timestamp, _sounder_id, body in _walk_datagrams(fh, size):
            if body is not None:
                fix = _parse_position_fix(body)
                if fix is not None:
                    fixes[dgm_type].append(fix)
    for dgm_type in _POSITION_DATAGRAMS:
        if fixes[dgm_type]:
            return fixes[dgm_type]
    return []


def _walk_datagrams(
    fh: typing.BinaryIO, size: int
) -> typing.Iterator[tuple[bytes, float, int, bytes | None]]:
    """Yield (dgm_type, timestamp, sounder_id, body) for each valid datagram.

    body is the head of a #SPO/#CPO datagram, None for every other type. A
    truncated or corrupt datagram ends the walk; a file without a valid first
    datagram raises ValueError.
    """
    position = 0
    while position + _DATAGRAM_HEADER.size <= size:
        fh.seek(position)
        (
            num_bytes,
            dgm_type,
            _dgm_version,
            _system_id,
            sounder_id,
            time_sec,
            time_nanosec,
        ) = _DATAGRAM_HEADER.unpack(fh.read(_DATAGRAM_HEADER.size))
        if (
            num_bytes < _MIN_DATAGRAM_BYTES
            or position + num_bytes > size
            or not dgm_type.startswith(b"#")
        ):
            if position > 0:
                logger.debug(
                    "Truncated or corrupt datagram at offset %d in %s - keeping "
                    "the metadata gathered so far",
                    position,
                    fh.name,
                )
            break
        body = None
        if dgm_type in _POSITION_DATAGRAMS:
            # capped here, once: the cap decides which fixes are usable, so the
            # bbox and the collected fixes must share it
            body = fh.read(min(num_bytes - _DATAGRAM_HEADER.size, _POSITION_BODY_BYTES))
        yield dgm_type, time_sec + time_nanosec / 1e9, sounder_id, body
        position += num_bytes
    if position == 0:
        # empty, smaller than one header, or invalid from its first datagram
        raise ValueError(f"{Path(fh.name).name} does not look like a KMALL file")


def _parse_position_fix(body: bytes) -> tuple[float, float] | None:
    """Best-effort (lon, lat) from a #SPO/#CPO body; None when unusable."""
    if len(body) < 2:
        return None
    (num_bytes_common,) = struct.unpack_from("<H", body, 0)
    offset = num_bytes_common + _SENSOR_DATA_LATLON_OFFSET
    if offset + 16 > len(body):
        return None
    latitude, longitude = struct.unpack_from("<dd", body, offset)
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if latitude == 0.0 and longitude == 0.0:
        # null-island fix from a GNSS dropout - one of these would blow the
        # bbox out to the equator
        return None
    if abs(latitude) > 90 or abs(longitude) > 180:
        # the spec uses out-of-range sentinels (e.g. 200.0) for "unavailable"
        return None
    return longitude, latitude


def _utc_date(timestamp: float | None) -> dt.date | None:
    if timestamp is None:
        return None
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).date()
