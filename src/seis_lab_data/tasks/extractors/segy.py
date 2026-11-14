import collections
import datetime as dt
import math
import re
import struct
import typing
from pathlib import Path

from .schemas import SegyMetadata

_TEXTUAL_HEADER_BYTES = 3200
_BINARY_HEADER_BYTES = 400
_TRACE_HEADER_BYTES = 240
_TRACE_DATA_START = _TEXTUAL_HEADER_BYTES + _BINARY_HEADER_BYTES
# A plausible SEG-Y holds at least the two file headers plus one trace header.
_MINIMUM_FILE_BYTES = _TRACE_DATA_START + _TRACE_HEADER_BYTES
# Extended textual header counts beyond this are treated as garbage.
_MAX_EXTENDED_HEADERS = 100
# An EPSG code quoted in the free-text header, as in "PORTUGAL TM06 (EPSG 3763)".
# Names, zones and bare numbers would need guessing, so they are deliberately not read.
_EPSG_CODE = re.compile(r"EPSG\W{0,3}(\d{4,5})(?!\d)", re.IGNORECASE)
# How many trace headers to sample per file; the first and last trace are always
# included, so the cost is constant regardless of file size.
_SAMPLE_TARGET = 100
# Above this fraction of implausible sampled coordinates the file is flagged as
# partially covered - the tell of a variable-length file whose size happened to
# floor-divide evenly, leaving samples landing mid-trace.
_GARBAGE_FRACTION_LIMIT = 0.5
# Projected coordinates beyond this magnitude are implausible in any real CRS.
_MAX_PLAUSIBLE_METRES = 1e7
# A file whose sampled positions span more than one survey line possibly could
# has no usable navigation. Two junk modes are known from the 66k-file archive
# scan: coordinate fields holding noise around the projection origin (3,173 to
# 17,303 km across, the A7808 GEOM family), and a burst of corrupt-nav traces
# inside an otherwise real line (the A7808 ET_SBP files reach 494 to 496 km with
# garbage_count 0, so ONLY the span catches them). Real archive files measure
# 14 m to 61.5 km across, with the 62 to 450 km range completely empty, so the
# 200 km cap discards both junk modes with wide margin and touches no real file.
# Boxes are discarded rather than trimmed: the noise clusters AT the origin, so
# rejecting the outliers instead would leave a small, credible-looking box in
# the middle of Portugal.
_MAX_PLAUSIBLE_SPAN = {"metres": 200_000.0, "geographic": 5.0}
# A bbox built from only a handful of the sampled traces covers a sliver of the
# real line while claiming full coverage. When enough traces were sampled but
# almost none carried usable coordinates, the box is dropped and the coverage
# flagged partial: a family of 95-182 GB GEOM files publishes a ~130 m box from
# 2-3 of 100 sampled fixes. The parsed floor keeps genuinely small files (a few
# traces, a few fixes) from tripping it.
_MIN_SUPPORT_PARSED = 20
_MIN_SUPPORT_FLOOR = 5
_MIN_SUPPORT_FRACTION = 0.10
# INT32 min/max are "unset" fill values, never coordinates (real archive traces
# carry INT32_MIN in the CDP fields).
_INT32_SENTINELS = (-(2**31), 2**31 - 1)

# Data sample format code -> (label, bytes per sample). Anything else yields
# partial metadata because the trace length cannot be computed.
_SAMPLE_FORMATS = {
    1: ("ibm-float32", 4),
    2: ("int32", 4),
    3: ("int16", 2),
    5: ("ieee-float32", 4),
    6: ("ieee-float64", 8),
    8: ("int8", 1),
    10: ("uint32", 4),
    11: ("uint16", 2),
    16: ("uint8", 1),
}

# Coordinate units codes: 2 and 3 are geographic (the only ones that yield a
# bbox_4326), 4 is packed DMS which is never converted (storing the packed
# integers would fake a bbox), and everything else is treated as projected
# metres in an UNDECLARED system - the CRS is never guessed.
_UNITS_ARC_SECONDS = 2
_UNITS_DEGREES = 3
_UNITS_DMS = 4
_UNITS_LABELS = {0: "unset", 1: "metres", 2: "arc-seconds", 3: "degrees", 4: "dms"}


class _BinaryHeader(typing.NamedTuple):
    """The fields used from the 400-byte binary file header (file offset 3200)."""

    sample_interval: int  # offset 16; raw and unitless, see SegyMetadata
    samples_per_trace: int  # offset 20; authoritative (the per-trace copy lies)
    sample_format: int  # offset 24; data sample format code
    revision: int  # offset 300; major SEG-Y revision, normalised on parsing
    extended_header_count: int  # offset 304; int16, -1 means "variable"
    extra_trace_headers: int  # offset 306; rev2 additional 240-byte trace headers


# Pad bytes ("x") skip everything between the _BinaryHeader fields above.
_BINARY_HEADER_FORMAT = "16x H 2x H 2x H 274x H 2x h i"
_BIG_ENDIAN_BINARY_HEADER = struct.Struct(">" + _BINARY_HEADER_FORMAT)
_LITTLE_ENDIAN_BINARY_HEADER = struct.Struct("<" + _BINARY_HEADER_FORMAT)


class _TraceHeader(typing.NamedTuple):
    """The fields used from each 240-byte trace header."""

    scalco: int  # offset 70; coordinate scalar: negative divides, positive multiplies
    src_x: int  # offset 72; source coordinates, the preferred position source
    src_y: int  # offset 76
    units: int  # offset 88; coordinate units code, see _UNITS_LABELS
    year: int  # offset 156; trace time (2-digit years are ambiguous -> skipped)
    day: int  # offset 158; day of year
    hour: int  # offset 160
    minute: int  # offset 162
    second: int  # offset 164
    cdp_x: int  # offset 180; CDP coordinates, the fallback position source
    cdp_y: int  # offset 184


_TRACE_HEADER_FORMAT = "70x h i i 8x H 66x H H H H H 14x i i"
_BIG_ENDIAN_TRACE_HEADER = struct.Struct(">" + _TRACE_HEADER_FORMAT)
_LITTLE_ENDIAN_TRACE_HEADER = struct.Struct("<" + _TRACE_HEADER_FORMAT)


def extract_segy_metadata(path: Path | str) -> SegyMetadata:
    """Extract metadata from a SEG-Y file by sampling ~100 trace headers.

    Only the two file headers plus a constant number of trace headers are read,
    so a multi-GB file costs the same as a tiny one. Sampled coordinates give a
    native bbox; bbox_4326 is only set when the traces declare geographic units,
    because projected metres in an undeclared CRS must never be guessed at (the
    units go into the description instead). A file too small to hold a single
    trace, or whose binary header is not recognisable in either byte order,
    raises ValueError.
    The EPSG codes quoted in the textual header are reported, never applied here.
    """
    p = Path(path)
    size = p.stat().st_size
    if size < _MINIMUM_FILE_BYTES:
        raise ValueError(f"{p.name} does not look like a SEG-Y file")
    with p.open("rb") as fh:
        textual_header = fh.read(_TEXTUAL_HEADER_BYTES)
        # EBCDIC by the standard, else ASCII; the wrong decoding never spells "EPSG"
        epsg_codes = _EPSG_CODE.findall(textual_header.decode("cp037"))
        if not epsg_codes:
            epsg_codes = _EPSG_CODE.findall(textual_header.decode("latin-1"))
        headers = _parse_binary_header(fh.read(_BINARY_HEADER_BYTES))
        if headers is None:
            raise ValueError(f"{p.name} does not look like a SEG-Y file")
        binary_header, trace_header_struct = headers
        format_label, bytes_per_sample = _SAMPLE_FORMATS.get(
            binary_header.sample_format,
            (f"format code {binary_header.sample_format}", None),
        )
        header_facts = {
            "driver": "SEG-Y",
            "sample_interval": binary_header.sample_interval or None,
            "samples_per_trace": binary_header.samples_per_trace or None,
            "sample_format": format_label,
            "header_epsg_codes": tuple(int(code) for code in epsg_codes),
        }
        if (
            bytes_per_sample is None
            or binary_header.samples_per_trace == 0
            # rev2 lets every trace carry N additional 240-byte headers; no real
            # file uses them, so rather than assume a layout we keep the header
            # facts - a wrong trace length would desync the whole sampling grid
            or (binary_header.revision >= 2 and binary_header.extra_trace_headers)
        ):
            # without a trustworthy trace length the traces cannot be walked;
            # keep the header facts instead of failing
            return SegyMetadata(**header_facts)
        data_start = _locate_trace_data(binary_header, size)
        trace_length = (
            _TRACE_HEADER_BYTES + binary_header.samples_per_trace * bytes_per_sample
        )
        # FLOOR division: a non-zero remainder is a trailing chunk (real files
        # carry small trailers), never a reason to fail.
        trace_count = (size - data_start) // trace_length
        if trace_count == 0:
            return SegyMetadata(**header_facts, trace_count=0)

        boxes: dict[str, tuple[float, float, float, float] | None] = {
            "metres": None,
            "geographic": None,
        }
        accepted = {"metres": 0, "geographic": 0}
        units_counts: collections.Counter[int] = collections.Counter()
        parsed_count = 0
        garbage_count = 0
        min_date = max_date = None
        for index in _sample_indices(trace_count):
            fh.seek(data_start + index * trace_length)
            buffer = fh.read(_TRACE_HEADER_BYTES)
            if len(buffer) < trace_header_struct.size:
                break
            trace = _TraceHeader(*trace_header_struct.unpack_from(buffer))
            parsed_count += 1
            units_counts[trace.units] += 1
            date = _parse_trace_date(trace)
            if date is not None:
                min_date = date if min_date is None else min(min_date, date)
                max_date = date if max_date is None else max(max_date, date)
            raw = _select_raw_coordinate(trace)
            if raw is None or trace.units == _UNITS_DMS:
                continue
            point = _plausible_point(raw, trace.scalco, trace.units)
            if point is None:
                garbage_count += 1
                continue
            category, x, y = point
            accepted[category] += 1
            box = boxes[category]
            boxes[category] = (
                (x, y, x, y)
                if box is None
                else (min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y))
            )

    if parsed_count == 0:
        return SegyMetadata(**header_facts, trace_count=trace_count)
    for category, box in boxes.items():
        span = _MAX_PLAUSIBLE_SPAN[category]
        if box is not None and (box[2] - box[0] > span or box[3] - box[1] > span):
            # the points behind it were garbage that slipped the per-value
            # filter, so counting them as such is what flags the coverage
            boxes[category] = None
            garbage_count += accepted[category]
            accepted[category] = 0
    # A box supported by only a sliver of the sampled traces is dropped and the
    # coverage flagged, but only once enough traces were sampled to trust the
    # ratio - a genuinely small file with a few real fixes must keep its box.
    accepted_total = accepted["metres"] + accepted["geographic"]
    low_support = parsed_count >= _MIN_SUPPORT_PARSED and 0 < accepted_total < max(
        _MIN_SUPPORT_FLOOR, parsed_count * _MIN_SUPPORT_FRACTION
    )
    if low_support:
        boxes["metres"] = boxes["geographic"] = None
        accepted["metres"] = accepted["geographic"] = 0
    dominant_units = units_counts.most_common(1)[0][0]
    shared_facts = {
        **header_facts,
        "trace_count": trace_count,
        "coordinate_units": _UNITS_LABELS.get(dominant_units, f"code {dominant_units}"),
        "coverage": (
            "partial"
            if low_support or garbage_count > parsed_count * _GARBAGE_FRACTION_LIMIT
            else "full"
        ),
        "temporal_extent_begin": min_date,
        "temporal_extent_end": max_date,
    }
    if accepted["geographic"] > accepted["metres"]:
        return SegyMetadata(
            **shared_facts,
            # geographic positions carry no datum declaration; WGS84-family in
            # practice (sub-metre difference, far below the bbox buffer) - the
            # same documented approximation as KMALL
            epsg=4326,
            crs_name="WGS 84",
            bbox_native=boxes["geographic"],
            bbox_4326=boxes["geographic"],
        )
    return SegyMetadata(**shared_facts, bbox_native=boxes["metres"])


def _parse_binary_header(
    buffer: bytes,
) -> tuple[_BinaryHeader, struct.Struct] | None:
    """Read the binary header, detecting endianness via the format code.

    Big-endian (every real file so far) is tried first; a byte order is accepted
    when it yields a sample format code in 1..16. Returns the header together
    with the matching trace-header struct, or None when neither order works or
    the file ended mid-header (it can shrink between the stat and the read).
    """
    if len(buffer) < _BIG_ENDIAN_BINARY_HEADER.size:
        return None
    for binary_struct, trace_struct in (
        (_BIG_ENDIAN_BINARY_HEADER, _BIG_ENDIAN_TRACE_HEADER),
        (_LITTLE_ENDIAN_BINARY_HEADER, _LITTLE_ENDIAN_TRACE_HEADER),
    ):
        header = _BinaryHeader(*binary_struct.unpack_from(buffer))
        if 1 <= header.sample_format <= 16:
            # The revision is a uint16 whose major number is the high byte
            # (conformant rev1 writers store 0x0100 and rev2 splits it into
            # major/minor bytes), except for writers that store a plain 1.
            # Reading a single byte instead would miss it on a little-endian file.
            code = header.revision
            return (
                header._replace(revision=code >> 8 if code > 0xFF else code),
                trace_struct,
            )
    return None


def _locate_trace_data(binary_header: _BinaryHeader, size: int) -> int:
    """Offset of the first trace: 3600 plus any trusted extended textual headers.

    The count at offset 304 is only meaningful from revision 1 on (the rev0
    bytes are undefined); -1 means "variable" and a count that is absurd or
    leaves no room for a single trace header is ignored too.
    """
    count = binary_header.extended_header_count
    if (
        binary_header.revision >= 1
        and 0 < count <= _MAX_EXTENDED_HEADERS
        and _TRACE_DATA_START + count * _TEXTUAL_HEADER_BYTES + _TRACE_HEADER_BYTES
        <= size
    ):
        return _TRACE_DATA_START + count * _TEXTUAL_HEADER_BYTES
    return _TRACE_DATA_START


def _sample_indices(trace_count: int) -> list[int]:
    """Up to ~_SAMPLE_TARGET evenly spread indices, endpoints always included."""
    if trace_count <= _SAMPLE_TARGET:
        return list(range(trace_count))
    last = trace_count - 1
    return sorted(
        {step * last // (_SAMPLE_TARGET - 1) for step in range(_SAMPLE_TARGET)}
    )


def _select_raw_coordinate(trace: _TraceHeader) -> tuple[int, int] | None:
    """Raw (x, y) from the source fields, falling back to CDP; None when absent.

    INT32 min/max fill and all-zero pairs mean "no coordinates", not values.
    """
    for raw_x, raw_y in ((trace.src_x, trace.src_y), (trace.cdp_x, trace.cdp_y)):
        if raw_x in _INT32_SENTINELS or raw_y in _INT32_SENTINELS:
            continue
        if raw_x == 0 and raw_y == 0:
            continue
        return raw_x, raw_y
    return None


def _plausible_point(
    raw: tuple[int, int], scalco: int, units: int
) -> tuple[str, float, float] | None:
    """Scaled, plausibility-checked point as (category, x, y); None when garbage.

    Geographic units must land inside the lon/lat range; anything else is
    treated as projected metres and rejected only on absurd magnitude. This
    filter is what catches samples that landed mid-trace.
    """
    x = _apply_coordinate_scalar(raw[0], scalco)
    y = _apply_coordinate_scalar(raw[1], scalco)
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    if units in (_UNITS_ARC_SECONDS, _UNITS_DEGREES):
        if units == _UNITS_ARC_SECONDS:
            x /= 3600.0
            y /= 3600.0
        if abs(x) > 180.0 or abs(y) > 90.0:
            return None
        return "geographic", x, y
    if abs(x) >= _MAX_PLAUSIBLE_METRES or abs(y) >= _MAX_PLAUSIBLE_METRES:
        return None
    return "metres", x, y


def _apply_coordinate_scalar(value: int, scalco: int) -> float:
    if scalco < 0:
        return value / -scalco
    if scalco > 0:
        return float(value * scalco)
    return float(value)


def _parse_trace_date(trace: _TraceHeader) -> dt.date | None:
    """Best-effort date from one trace's time fields; None when implausible.

    A single corrupt time field must never abort the extraction (the same
    guarantee as KMALL), so every field is range-checked per trace: a 4-digit
    year (2-digit years are ambiguous), a day of year, and a sane time of day
    as a corruption tell.
    """
    if not 1970 <= trace.year <= 2100:
        return None
    if not 1 <= trace.day <= 366:
        return None
    if trace.hour > 23 or trace.minute > 59 or trace.second > 59:
        return None
    date = dt.date(trace.year, 1, 1) + dt.timedelta(days=trace.day - 1)
    if date.year != trace.year:
        # day 366 of a non-leap year rolls into January
        return None
    return date
