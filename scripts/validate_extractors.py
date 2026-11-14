#!/usr/bin/env python3
"""Standalone extractor validation harness for production-side runs.

Walks archive files with header-only reads and writes a CSV report, one row per
file. Pure standard library on purpose: it must run on any python3 (e.g. the
production server) without installing anything, so it does NOT import the
seis_lab_data package. The KMALL and SEG-Y parsing below mirrors
src/seis_lab_data/tasks/extractors/kmall.py and segy.py - keep them in sync.
Unlike `extract_kmall_metadata`, which reads 16 sampled windows of a file, the
KMALL validation walks every datagram: its counts, bbox and dates are the exact
reference the sampled read is checked against.
The CSV also carries report-only diagnostics (parsed/garbage/accepted counts,
the units and coordinate-source histograms) that the extractors deliberately do
not keep: at scale we need the tallies behind a conclusion, not just the
conclusion. Those are not a divergence from the mirrored parsing.

Typical production run (read-only, low priority, resumable):

    nice -n 19 ionice -c3 python3 validate_extractors.py \
        --root /mnt/seislab_data/surveys \
        --extension .kmall \
        --output ~/kmall-report.csv \
        --resume

Interrupt at will; --resume skips files already present in the output.

SEG-Y takes one pass per extension into the same report, the second with
--resume (which is also what keeps the first pass's rows):

    python3 validate_extractors.py ... --extension .sgy  --output ~/segy-report.csv
    python3 validate_extractors.py ... --extension .segy --output ~/segy-report.csv --resume
"""

import argparse
import collections
import csv
import datetime as dt
import math
import os
import re
import struct
import sys
import time
import typing

# numBytesDgm, dgmType, dgmVersion, systemID, echoSounderID, time_sec, time_nanosec
_DATAGRAM_HEADER = struct.Struct("<I4sBBHII")
_MIN_DATAGRAM_BYTES = _DATAGRAM_HEADER.size + 4
_POSITION_DATAGRAMS = (b"#SPO", b"#CPO")
_SENSOR_DATA_LATLON_OFFSET = 12
_POSITION_BODY_BYTES = 64

_CSV_COLUMNS = [
    "path",
    "size_bytes",
    "status",
    "error",
    "walk_seconds",
    "datagram_count",
    "position_count",
    "position_source",
    "echo_sounder_id",
    "dgm_versions",
    "min_lon",
    "min_lat",
    "max_lon",
    "max_lat",
    "date_begin",
    "date_end",
    # SEG-Y columns; the lon/lat columns above only hold the geographic bbox
    # (declared degrees/arc-seconds), the native bbox goes below
    "trace_count",
    "samples_per_trace",
    "sample_interval",
    "sample_format",
    "coordinate_units",
    "coverage",
    "native_min_x",
    "native_min_y",
    "native_max_x",
    "native_max_y",
    # report-only diagnostics (no counterpart in segy.py, see validate_segy)
    "parsed_count",
    "garbage_count",
    "accepted_count",
    "units_counts",
    # SEG-Y again, kept last so that earlier reports keep their column positions
    "header_epsg_codes",
]


def validate_kmall(path):
    """Mirror of extract_kmall_metadata, returning a plain report dict."""
    size = os.path.getsize(path)
    datagram_count = 0
    min_time = max_time = None
    echo_sounder_id = None
    versions = {}
    boxes = {dgm_type: None for dgm_type in _POSITION_DATAGRAMS}
    fix_counts = {dgm_type: 0 for dgm_type in _POSITION_DATAGRAMS}

    with open(path, "rb") as fh:
        position = 0
        while position + _DATAGRAM_HEADER.size <= size:
            fh.seek(position)
            (
                num_bytes,
                dgm_type,
                dgm_version,
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
                if datagram_count == 0:
                    raise ValueError("does not look like a KMALL file")
                break
            datagram_count += 1
            versions.setdefault(dgm_type, set()).add(dgm_version)
            timestamp = time_sec + time_nanosec / 1e9
            if echo_sounder_id is None:
                echo_sounder_id = sounder_id
            min_time = timestamp if min_time is None else min(min_time, timestamp)
            max_time = timestamp if max_time is None else max(max_time, timestamp)
            if dgm_type in _POSITION_DATAGRAMS:
                body = fh.read(
                    min(num_bytes - _DATAGRAM_HEADER.size, _POSITION_BODY_BYTES)
                )
                fix = _parse_position_fix(body)
                if fix is not None:
                    lon, lat = fix
                    fix_counts[dgm_type] += 1
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
            position += num_bytes

    if datagram_count == 0:
        raise ValueError("does not look like a KMALL file")

    bbox = None
    position_count = 0
    position_source = ""
    for dgm_type in _POSITION_DATAGRAMS:
        if boxes[dgm_type] is not None:
            bbox = boxes[dgm_type]
            position_count = fix_counts[dgm_type]
            position_source = dgm_type.decode()
            break

    return {
        "datagram_count": datagram_count,
        "position_count": position_count,
        "position_source": position_source,
        "echo_sounder_id": echo_sounder_id,
        "dgm_versions": ";".join(
            f"{k.decode()}:{','.join(str(v) for v in sorted(vals))}"
            for k, vals in sorted(versions.items())
        ),
        "min_lon": bbox[0] if bbox else "",
        "min_lat": bbox[1] if bbox else "",
        "max_lon": bbox[2] if bbox else "",
        "max_lat": bbox[3] if bbox else "",
        "date_begin": _utc_date(min_time),
        "date_end": _utc_date(max_time),
    }


def _parse_position_fix(body):
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
        return None
    if abs(latitude) > 90 or abs(longitude) > 180:
        return None
    return longitude, latitude


def _utc_date(timestamp):
    if timestamp is None:
        return ""
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).date().isoformat()


# SEG-Y header sampling, mirroring src/seis_lab_data/tasks/extractors/segy.py.

_TEXTUAL_HEADER_BYTES = 3200
_BINARY_HEADER_BYTES = 400
_TRACE_HEADER_BYTES = 240
_TRACE_DATA_START = _TEXTUAL_HEADER_BYTES + _BINARY_HEADER_BYTES
_MINIMUM_FILE_BYTES = _TRACE_DATA_START + _TRACE_HEADER_BYTES
_MAX_EXTENDED_HEADERS = 100
# see segy.py: only an explicit EPSG code is read, never names, zones or bare numbers
_EPSG_CODE = re.compile(r"EPSG\W{0,3}(\d{4,5})(?!\d)", re.IGNORECASE)
_SAMPLE_TARGET = 100
_GARBAGE_FRACTION_LIMIT = 0.5
_MAX_PLAUSIBLE_METRES = 1e7
# see segy.py: a box spanning more than a real survey line means the coordinate
# fields hold noise, so it is discarded rather than trimmed. 200 km catches both
# junk modes the 66k scan found (origin-noise 3,173-17,303 km, and the A7808
# ET_SBP burst corruption at 494-496 km with garbage 0) with the 62-450 km range
# empty of real files (real max 61.5 km).
_MAX_PLAUSIBLE_SPAN = {"metres": 200_000.0, "geographic": 5.0}
# see segy.py: a box built from a sliver of the sampled traces is dropped and the
# coverage flagged partial, once enough traces were sampled to trust the ratio.
_MIN_SUPPORT_PARSED = 20
_MIN_SUPPORT_FLOOR = 5
_MIN_SUPPORT_FRACTION = 0.10
_INT32_SENTINELS = (-(2**31), 2**31 - 1)

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

_UNITS_ARC_SECONDS = 2
_UNITS_DEGREES = 3
_UNITS_DMS = 4
_UNITS_LABELS = {0: "unset", 1: "metres", 2: "arc-seconds", 3: "degrees", 4: "dms"}


class _BinaryHeader(typing.NamedTuple):
    sample_interval: int  # offset 16
    samples_per_trace: int  # offset 20
    sample_format: int  # offset 24
    revision: int  # offset 300; major revision, normalised on parsing
    extended_header_count: int  # offset 304
    extra_trace_headers: int  # offset 306; rev2 additional 240-byte trace headers


_BINARY_HEADER_FORMAT = "16x H 2x H 2x H 274x H 2x h i"
_BIG_ENDIAN_BINARY_HEADER = struct.Struct(">" + _BINARY_HEADER_FORMAT)
_LITTLE_ENDIAN_BINARY_HEADER = struct.Struct("<" + _BINARY_HEADER_FORMAT)


class _TraceHeader(typing.NamedTuple):
    scalco: int  # offset 70
    src_x: int  # offset 72
    src_y: int  # offset 76
    units: int  # offset 88
    year: int  # offset 156
    day: int  # offset 158
    hour: int  # offset 160
    minute: int  # offset 162
    second: int  # offset 164
    cdp_x: int  # offset 180
    cdp_y: int  # offset 184


_TRACE_HEADER_FORMAT = "70x h i i 8x H 66x H H H H H 14x i i"
_BIG_ENDIAN_TRACE_HEADER = struct.Struct(">" + _TRACE_HEADER_FORMAT)
_LITTLE_ENDIAN_TRACE_HEADER = struct.Struct("<" + _TRACE_HEADER_FORMAT)


def validate_segy(path):
    """Mirror of extract_segy_metadata, returning a plain report dict."""
    size = os.path.getsize(path)
    if size < _MINIMUM_FILE_BYTES:
        raise ValueError("does not look like a SEG-Y file")
    with open(path, "rb") as fh:
        textual_header = fh.read(_TEXTUAL_HEADER_BYTES)
        epsg_codes = _EPSG_CODE.findall(textual_header.decode("cp037"))
        if not epsg_codes:
            epsg_codes = _EPSG_CODE.findall(textual_header.decode("latin-1"))
        headers = _parse_binary_header(fh.read(_BINARY_HEADER_BYTES))
        if headers is None:
            raise ValueError("does not look like a SEG-Y file")
        binary_header, trace_header_struct = headers
        format_label, bytes_per_sample = _SAMPLE_FORMATS.get(
            binary_header.sample_format,
            ("format code %d" % binary_header.sample_format, None),
        )
        row = {
            "sample_interval": binary_header.sample_interval or "",
            "samples_per_trace": binary_header.samples_per_trace or "",
            "sample_format": format_label,
            "header_epsg_codes": ";".join(str(int(code)) for code in epsg_codes),
        }
        if (
            bytes_per_sample is None
            or binary_header.samples_per_trace == 0
            or (binary_header.revision >= 2 and binary_header.extra_trace_headers)
        ):
            return row
        data_start = _locate_trace_data(binary_header, size)
        trace_length = (
            _TRACE_HEADER_BYTES + binary_header.samples_per_trace * bytes_per_sample
        )
        trace_count = (size - data_start) // trace_length
        row["trace_count"] = trace_count
        if trace_count == 0:
            return row

        boxes = {"metres": None, "geographic": None}
        accepted = {"metres": 0, "geographic": 0}
        units_counts = collections.Counter()
        source_counts = collections.Counter()
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
            # report-only: which of the two coordinate sources answered
            source_counts["src" if raw == (trace.src_x, trace.src_y) else "cdp"] += 1
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

    for category, box in boxes.items():
        span = _MAX_PLAUSIBLE_SPAN[category]
        if box is not None and (box[2] - box[0] > span or box[3] - box[1] > span):
            boxes[category] = None
            garbage_count += accepted[category]
            accepted[category] = 0

    # Report-only diagnostics, deliberately NOT in segy.py: the extractor keeps
    # only its conclusions, but at scale we need the raw tallies behind them -
    # a desynced sampling grid lands around the 0.5 garbage fraction, so
    # coverage alone hides it, whereas real files score exactly 0.
    row["parsed_count"] = parsed_count
    row["garbage_count"] = garbage_count
    row["accepted_count"] = accepted["metres"] + accepted["geographic"]
    row["units_counts"] = ";".join(
        "%d:%d" % (code, n) for code, n in sorted(units_counts.items())
    )
    row["position_source"] = ";".join(
        "%s:%d" % (name, n) for name, n in sorted(source_counts.items())
    )
    if parsed_count == 0:
        return row
    dominant_units = units_counts.most_common(1)[0][0]
    row["coordinate_units"] = _UNITS_LABELS.get(
        dominant_units, "code %d" % dominant_units
    )
    # accepted_count above keeps the pre-drop tally for the report; here a sliver
    # of support drops the box and flags the coverage, mirroring segy.py.
    low_support = parsed_count >= _MIN_SUPPORT_PARSED and 0 < row[
        "accepted_count"
    ] < max(_MIN_SUPPORT_FLOOR, parsed_count * _MIN_SUPPORT_FRACTION)
    if low_support:
        boxes["metres"] = boxes["geographic"] = None
        accepted["metres"] = accepted["geographic"] = 0
    row["coverage"] = (
        "partial"
        if low_support or garbage_count > parsed_count * _GARBAGE_FRACTION_LIMIT
        else "full"
    )
    row["date_begin"] = min_date.isoformat() if min_date else ""
    row["date_end"] = max_date.isoformat() if max_date else ""
    if accepted["geographic"] > accepted["metres"]:
        bbox = boxes["geographic"]
        row["min_lon"], row["min_lat"], row["max_lon"], row["max_lat"] = bbox
    else:
        bbox = boxes["metres"]
    if bbox is not None:
        (
            row["native_min_x"],
            row["native_min_y"],
            row["native_max_x"],
            row["native_max_y"],
        ) = bbox
    return row


def _parse_binary_header(buffer):
    if len(buffer) < _BIG_ENDIAN_BINARY_HEADER.size:
        return None
    for binary_struct, trace_struct in (
        (_BIG_ENDIAN_BINARY_HEADER, _BIG_ENDIAN_TRACE_HEADER),
        (_LITTLE_ENDIAN_BINARY_HEADER, _LITTLE_ENDIAN_TRACE_HEADER),
    ):
        header = _BinaryHeader(*binary_struct.unpack_from(buffer))
        if 1 <= header.sample_format <= 16:
            code = header.revision
            return (
                header._replace(revision=code >> 8 if code > 0xFF else code),
                trace_struct,
            )
    return None


def _locate_trace_data(binary_header, size):
    count = binary_header.extended_header_count
    if (
        binary_header.revision >= 1
        and 0 < count <= _MAX_EXTENDED_HEADERS
        and _TRACE_DATA_START + count * _TEXTUAL_HEADER_BYTES + _TRACE_HEADER_BYTES
        <= size
    ):
        return _TRACE_DATA_START + count * _TEXTUAL_HEADER_BYTES
    return _TRACE_DATA_START


def _sample_indices(trace_count):
    if trace_count <= _SAMPLE_TARGET:
        return list(range(trace_count))
    last = trace_count - 1
    return sorted(
        {step * last // (_SAMPLE_TARGET - 1) for step in range(_SAMPLE_TARGET)}
    )


def _select_raw_coordinate(trace):
    for raw_x, raw_y in ((trace.src_x, trace.src_y), (trace.cdp_x, trace.cdp_y)):
        if raw_x in _INT32_SENTINELS or raw_y in _INT32_SENTINELS:
            continue
        if raw_x == 0 and raw_y == 0:
            continue
        return raw_x, raw_y
    return None


def _plausible_point(raw, scalco, units):
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


def _apply_coordinate_scalar(value, scalco):
    if scalco < 0:
        return value / -scalco
    if scalco > 0:
        return float(value * scalco)
    return float(value)


def _parse_trace_date(trace):
    if not 1970 <= trace.year <= 2100:
        return None
    if not 1 <= trace.day <= 366:
        return None
    if trace.hour > 23 or trace.minute > 59 or trace.second > 59:
        return None
    date = dt.date(trace.year, 1, 1) + dt.timedelta(days=trace.day - 1)
    if date.year != trace.year:
        return None
    return date


_VALIDATORS = {
    ".kmall": validate_kmall,
    ".segy": validate_segy,
    ".sgy": validate_segy,
}


def iter_target_files(root, extension, file_list):
    if file_list:
        with open(file_list) as fh:
            for line in fh:
                candidate = line.rstrip("\n").split("\t")[-1]
                if candidate.lower().endswith(extension):
                    yield os.path.join(root, candidate.removeprefix("./"))
    else:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in sorted(filenames):
                if name.lower().endswith(extension):
                    yield os.path.join(dirpath, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="archive root directory")
    parser.add_argument("--extension", default=".kmall", choices=sorted(_VALIDATORS))
    parser.add_argument("--output", required=True, help="CSV report path")
    parser.add_argument(
        "--file-list",
        help="optional listing (plain paths, or size<TAB>path); paths are "
        "resolved against --root; when absent the root is walked",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip files already present in the output CSV",
    )
    parser.add_argument("--limit", type=int, help="stop after N files (trial runs)")
    args = parser.parse_args()

    validator = _VALIDATORS[args.extension]
    done = set()
    has_report = os.path.exists(args.output) and os.path.getsize(args.output) > 0
    if has_report:
        with open(args.output) as fh:
            reader = csv.DictReader(fh)
            # appended rows would not line up with another header's columns
            if reader.fieldnames != _CSV_COLUMNS:
                sys.exit(
                    f"{args.output} was written with other columns; start a new "
                    "report (choose another --output)"
                )
            # SEG-Y needs one pass per extension (.sgy then .segy) into the same
            # report, so refuse to silently truncate hours of work: --resume both
            # keeps the existing rows and skips the files already in them.
            if not args.resume:
                sys.exit(
                    f"{args.output} already holds a report; pass --resume to add "
                    "to it (or choose another --output)"
                )
            done = {row["path"] for row in reader}

    mode = "a" if has_report else "w"
    processed = ok = failed = 0
    with open(args.output, mode, newline="") as out:
        writer = csv.DictWriter(out, fieldnames=_CSV_COLUMNS)
        if mode == "w":
            writer.writeheader()
        for path in iter_target_files(args.root, args.extension, args.file_list):
            relative = os.path.relpath(path, args.root)
            if relative in done:
                continue
            row = {"path": relative}
            started = time.perf_counter()
            try:
                row["size_bytes"] = os.path.getsize(path)
                row.update(validator(path))
                row["status"] = "ok"
                ok += 1
            except Exception as err:  # report and carry on - this is a survey
                row["status"] = "error"
                row["error"] = f"{type(err).__name__}: {err}"
                failed += 1
            row["walk_seconds"] = f"{time.perf_counter() - started:.2f}"
            writer.writerow(row)
            out.flush()
            processed += 1
            if processed % 50 == 0:
                print(
                    f"{processed} files ({ok} ok, {failed} errors)...",
                    file=sys.stderr,
                    flush=True,
                )
            if args.limit and processed >= args.limit:
                break

    print(f"done: {processed} files, {ok} ok, {failed} errors", file=sys.stderr)


if __name__ == "__main__":
    main()
