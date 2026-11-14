"""Unit tests for the metadata extractors package.

Pure functions, no DB: these run by default (no marker). GDAL is required; the
module self-skips where it is unavailable. Everything is exercised against
synthetic files built in-test, so the suite needs no sample-data archive.
"""

import datetime as dt
import logging
import math
import struct
from pathlib import Path

import pytest

pytest.importorskip("osgeo")

from osgeo import (  # noqa: E402
    gdal,
    ogr,
    osr,
)

from seis_lab_data.tasks.extractors import (  # noqa: E402
    dispatch,
    kmall,
    schemas,
    segy,
    xyz,
)
from seis_lab_data.tasks.extractors.gdal_raster import (  # noqa: E402
    extract_raster_metadata,
)
from seis_lab_data.tasks.extractors.gdal_vector import (  # noqa: E402
    extract_vector_metadata,
)
from seis_lab_data.tasks.extractors.kmall import (  # noqa: E402
    collect_position_fixes,
    extract_kmall_metadata,
)
from seis_lab_data.tasks.extractors.segy import (  # noqa: E402
    extract_segy_metadata,
)

gdal.UseExceptions()

# EPSG:3763 (ETRS89 / Portugal TM06); coordinates near its false origin land in
# central Portugal, so projected bboxes fall in a checkable lon/lat window.
_PT_TM06 = 3763
_POINTS = [(0.0, 0.0), (1000.0, 1000.0), (2000.0, 500.0)]


def _srs(epsg: int) -> osr.SpatialReference:
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    return srs


@pytest.fixture(scope="session")
def synthetic_geotiff(tmp_path_factory):
    path = tmp_path_factory.mktemp("raster") / "grid.tif"
    ds = gdal.GetDriverByName("GTiff").Create(str(path), 10, 10, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((0.0, 10.0, 0.0, 2000.0, 0.0, -10.0))
    ds.SetProjection(_srs(_PT_TM06).ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.Fill(1.0)
    ds = None
    return path


@pytest.fixture(scope="session")
def synthetic_xyz(tmp_path_factory):
    path = tmp_path_factory.mktemp("xyz") / "grid.xyz"
    lines = [f"{x} {y} {x + y}" for y in range(3) for x in range(3)]
    path.write_text("\n".join(lines) + "\n")
    return path


def _write_shapefile(path, srs):
    driver = ogr.GetDriverByName("ESRI Shapefile")
    ds = driver.CreateDataSource(str(path))
    layer = ds.CreateLayer("points", srs=srs, geom_type=ogr.wkbPoint)
    for x, y in _POINTS:
        feature = ogr.Feature(layer.GetLayerDefn())
        geom = ogr.Geometry(ogr.wkbPoint)
        geom.AddPoint(x, y)
        feature.SetGeometry(geom)
        layer.CreateFeature(feature)
        feature = None
    ds = None


@pytest.fixture(scope="session")
def synthetic_shapefile(tmp_path_factory):
    path = tmp_path_factory.mktemp("vector") / "points.shp"
    _write_shapefile(path, _srs(_PT_TM06))
    return path


@pytest.fixture(scope="session")
def synthetic_shapefile_no_prj(tmp_path_factory):
    path = tmp_path_factory.mktemp("vector_noprj") / "points.shp"
    _write_shapefile(path, None)
    return path


@pytest.fixture(scope="session")
def broken_vector(tmp_path_factory):
    # A valid shapefile with its .shx removed: reproduces the real prr_eolicas
    # "missing .shx" condition, which GDAL refuses to open (SHAPE_RESTORE_SHX
    # defaults to NO) -> RuntimeError.
    path = tmp_path_factory.mktemp("broken") / "points.shp"
    _write_shapefile(path, _srs(_PT_TM06))
    path.with_suffix(".shx").unlink()
    return path


def test_raster_metadata_fields(synthetic_geotiff):
    result = extract_raster_metadata(synthetic_geotiff)

    assert isinstance(result, schemas.RasterMetadata)
    assert result.driver == "GTiff"
    assert result.width == 10
    assert result.height == 10
    assert result.band_count == 1
    assert result.pixel_size_x == 10.0
    assert result.pixel_size_y == -10.0
    assert result.nodata == -9999.0
    assert result.epsg == _PT_TM06
    assert "TM06" in result.crs_name

    assert result.bbox_native is not None
    minx, miny, maxx, maxy = result.bbox_native
    assert minx < maxx and miny < maxy

    assert result.bbox_4326 is not None
    lon_min, lat_min, lon_max, lat_max = result.bbox_4326
    assert -10.0 < lon_min <= lon_max < -6.0
    assert 36.0 < lat_min <= lat_max < 43.0


def test_xyz_raster(synthetic_xyz):
    result = extract_raster_metadata(synthetic_xyz)

    assert result.driver == "XYZ"
    assert result.width == 3
    assert result.height == 3
    # No .prj alongside an XYZ grid: no CRS, native bbox only.
    assert result.epsg is None
    assert result.bbox_native is not None
    assert result.bbox_4326 is None


def test_vector_metadata_fields(synthetic_shapefile):
    result = extract_vector_metadata(synthetic_shapefile)

    assert isinstance(result, schemas.VectorMetadata)
    assert result.driver == "ESRI Shapefile"
    assert result.layer_count == 1
    assert result.feature_count == 3
    assert "Point" in result.geometry_type
    assert result.epsg == _PT_TM06

    assert result.bbox_native is not None
    minx, miny, maxx, maxy = result.bbox_native
    # Reorder trap: OGR GetExtent returns (minx, maxx, miny, maxy). If it were stored
    # verbatim, miny would be 2000 and this assertion would fail.
    assert minx < maxx
    assert miny < maxy

    assert result.bbox_4326 is not None
    lon_min, lat_min, lon_max, lat_max = result.bbox_4326
    assert -10.0 < lon_min <= lon_max < -6.0
    assert 36.0 < lat_min <= lat_max < 43.0


def test_vector_without_prj(synthetic_shapefile_no_prj):
    result = extract_vector_metadata(synthetic_shapefile_no_prj)

    assert result.epsg is None
    assert result.crs_name is None
    assert result.crs_wkt is None
    assert result.bbox_4326 is None
    assert result.bbox_native is not None
    assert result.feature_count == 3


def test_broken_vector_raises(broken_vector):
    with pytest.raises(RuntimeError):
        extract_vector_metadata(broken_vector)


def test_dispatch_routes_raster(synthetic_geotiff):
    assert isinstance(
        dispatch.dispatch_extractor(synthetic_geotiff), schemas.RasterMetadata
    )


def test_dispatch_routes_xyz(synthetic_xyz):
    result = dispatch.dispatch_extractor(synthetic_xyz)
    assert isinstance(result, schemas.RasterMetadata)
    assert result.driver == "XYZ"


# soundings: irregular x and y, which GDAL's XYZ driver rejects for not being a grid
_SOUNDINGS = [
    (10.5, 20.25, 1.0),
    (13.75, 18.5, 2.0),
    (11.0, 25.5, 1.5),
    (9.25, 21.0, 3),
]


def test_dispatch_routes_ungridded_xyz_to_the_point_cloud_extractor(tmp_path):
    path = tmp_path / "soundings.xyz"
    path.write_text("".join(f"{x} {y} {z}\n" for x, y, z in _SOUNDINGS))

    result = dispatch.dispatch_extractor(path)

    assert isinstance(result, schemas.PointCloudMetadata)
    assert result.point_count == 4
    assert result.bbox_native == (9.25, 18.5, 13.75, 25.5)
    # no CRS in the file: placed by the survey mission's CRS, as an XYZ grid is
    assert result.bbox_4326 is None
    assert result.bbox_native_needing_crs == (9.25, 18.5, 13.75, 25.5)


def test_xyz_points_skip_a_header_and_accept_commas(tmp_path):
    path = tmp_path / "soundings.xyz"
    path.write_text(
        "Easting,Northing,Depth\n" + "".join(f"{x},{y},{z}\n" for x, y, z in _SOUNDINGS)
    )

    result = xyz.extract_xyz_points_metadata(path)

    assert result.point_count == 4
    assert result.bbox_native == (9.25, 18.5, 13.75, 25.5)


def test_xyz_points_of_a_large_file_are_sampled(tmp_path, monkeypatch):
    monkeypatch.setattr(xyz, "_SAMPLE_WINDOWS", 4)
    monkeypatch.setattr(xyz, "_SAMPLE_WINDOW_BYTES", 64)
    # 1000 rows of the same length, x rising along the file: the westernmost and
    # easternmost points are in the first and last windows, while a southernmost
    # point in the middle of the file lies between the windows and is missed
    rows = [
        f"{1000 + index} {4000 if index == 500 else 5000} 1.0" for index in range(1000)
    ]
    path = tmp_path / "soundings.xyz"
    path.write_text("\n".join(rows))
    read_sizes = []
    real_open = Path.open

    def recording_open(self, *args, **kwargs):
        fh = real_open(self, *args, **kwargs)
        real_read = fh.read

        def recording_read(size=-1):
            data = real_read(size)
            read_sizes.append(len(data))
            return data

        fh.read = recording_read
        return fh

    monkeypatch.setattr(Path, "open", recording_open)

    result = xyz.extract_xyz_points_metadata(path)

    assert read_sizes == [64] * 4
    assert result.bbox_native == (1000.0, 5000.0, 1999.0, 5000.0)
    assert result.point_count_estimated
    assert result.point_count == pytest.approx(1000, rel=0.05)


def test_xyz_points_of_a_small_file_are_counted(tmp_path):
    # read whole, its last line without a line break
    path = tmp_path / "soundings.xyz"
    path.write_text("\n".join(f"{x} {y} {z}" for x, y, z in _SOUNDINGS))

    result = xyz.extract_xyz_points_metadata(path)

    assert result.point_count == 4
    assert not result.point_count_estimated
    assert result.bbox_native == (9.25, 18.5, 13.75, 25.5)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "just some text\n",
        "1 2 3\n4 5\n",
        "1 2 3\n4 5 deep\n",
    ],
    ids=["empty", "no numbers", "ragged rows", "not a number"],
)
def test_xyz_points_reject_what_is_not_a_point_cloud(tmp_path, content):
    path = tmp_path / "soundings.xyz"
    path.write_text(content)

    with pytest.raises(ValueError):
        xyz.extract_xyz_points_metadata(path)


@pytest.mark.parametrize(
    "language, estimated, expected",
    [
        ("en", False, "Auto-extracted: XYZ point cloud, 4 point(s). CRS:"),
        ("en", True, "Auto-extracted: XYZ point cloud, about 4 point(s). CRS:"),
        ("pt", False, "Extração automática: nuvem de pontos XYZ, 4 ponto(s). CRS:"),
        (
            "pt",
            True,
            "Extração automática: nuvem de pontos XYZ, cerca de 4 ponto(s). CRS:",
        ),
    ],
)
def test_xyz_points_describe(language, estimated, expected):
    metadata = schemas.PointCloudMetadata(
        driver="XYZ", point_count=4, point_count_estimated=estimated
    )

    assert metadata.describe(language).startswith(expected)


def test_dispatch_routes_vector(synthetic_shapefile):
    assert isinstance(
        dispatch.dispatch_extractor(synthetic_shapefile), schemas.VectorMetadata
    )


@pytest.mark.parametrize("suffix", [".shx", ".dbf", ".prj", ".cpg", ".qmd", ".sbn"])
def test_dispatch_ignores_sidecars(tmp_path, suffix):
    sidecar = tmp_path / f"points{suffix}"
    sidecar.write_bytes(b"\x00")
    assert dispatch.dispatch_extractor(sidecar) is None


def test_dispatch_unknown_extension(tmp_path):
    unknown = tmp_path / "notes.txt"
    unknown.write_text("hello")
    assert dispatch.dispatch_extractor(unknown) is None


def test_dispatch_directory_named_like_raster(tmp_path):
    # A real directory named "F3_2022.tif" exists in the archive; it must not be opened.
    fake = tmp_path / "F3_2022.tif"
    fake.mkdir()
    assert dispatch.dispatch_extractor(fake) is None


def test_dispatch_big_file_logs(synthetic_geotiff, monkeypatch, caplog):
    monkeypatch.setattr(dispatch, "_BIG_FILE_LOG_BYTES", 0)
    with caplog.at_level(logging.INFO, logger=dispatch.logger.name):
        result = dispatch.dispatch_extractor(synthetic_geotiff)
    assert isinstance(result, schemas.RasterMetadata)
    assert any("large raster" in record.message for record in caplog.records)


def test_raster_describe(synthetic_geotiff):
    text = extract_raster_metadata(synthetic_geotiff).describe()
    assert text.startswith("Auto-extracted: GTiff raster")
    assert "TM06" in text
    assert "EPSG:3763" in text
    assert len(text) <= 500


def test_vector_describe(synthetic_shapefile):
    text = extract_vector_metadata(synthetic_shapefile).describe()
    assert text.startswith("Auto-extracted: ESRI Shapefile vector")
    assert "Point" in text
    assert len(text) <= 500


def test_describe_truncates_to_500():
    absurd = schemas.RasterMetadata(
        driver="GTiff",
        width=1,
        height=1,
        band_count=1,
        crs_name="X" * 2000,
    )
    assert len(absurd.describe()) == 500


def test_describe_crs_unknown():
    text = schemas.VectorMetadata(
        driver="ESRI Shapefile",
        layer_count=1,
        feature_count=0,
        geometry_type="Point",
    ).describe()
    assert "CRS: unknown." in text


def test_bbox_native_needing_crs_when_file_declares_none():
    # the SEG-Y / XYZ case: coordinates, but nothing saying which CRS they are in
    metadata = schemas.SegyMetadata(bbox_native=(0.0, 1900.0, 100.0, 2000.0))
    assert metadata.bbox_native_needing_crs == (0.0, 1900.0, 100.0, 2000.0)


def test_bbox_native_needing_crs_is_none_when_epsg_is_known():
    metadata = schemas.SegyMetadata(bbox_native=(0.0, 1900.0, 100.0, 2000.0), epsg=3763)
    assert metadata.bbox_native_needing_crs is None


def test_bbox_native_needing_crs_is_none_when_only_wkt_is_known():
    # AutoIdentifyEPSG fails on some archive files, leaving wkt as the only CRS
    metadata = schemas.SegyMetadata(
        bbox_native=(0.0, 1900.0, 100.0, 2000.0),
        crs_wkt='PROJCS["ETRS89 / Portugal TM06"]',
    )
    assert metadata.bbox_native_needing_crs is None


def test_bbox_native_needing_crs_is_none_when_already_projected():
    metadata = schemas.SegyMetadata(
        bbox_native=(0.0, 1900.0, 100.0, 2000.0),
        bbox_4326=(-8.2, 39.6, -8.1, 39.7),
    )
    assert metadata.bbox_native_needing_crs is None


def test_bbox_native_needing_crs_is_none_without_coordinates():
    assert schemas.SegyMetadata().bbox_native_needing_crs is None


def test_raster_describe_pt(synthetic_geotiff):
    text = extract_raster_metadata(synthetic_geotiff).describe("pt")
    assert text.startswith("Extração automática: raster GTiff")
    assert "banda(s)" in text
    assert "TM06" in text
    assert "EPSG:3763" in text
    assert len(text) <= 500


def test_vector_describe_pt(synthetic_shapefile):
    text = extract_vector_metadata(synthetic_shapefile).describe("pt")
    assert text.startswith("Extração automática: vetor ESRI Shapefile")
    assert "elemento(s)" in text
    assert "Point" in text  # a geometry type stays an English identifier
    assert len(text) <= 500


def test_describe_truncates_to_500_pt():
    absurd = schemas.RasterMetadata(
        driver="GTiff",
        width=1,
        height=1,
        band_count=1,
        crs_name="X" * 2000,
    )
    assert len(absurd.describe("pt")) == 500


def test_describe_crs_unknown_pt():
    text = schemas.VectorMetadata(
        driver="ESRI Shapefile",
        layer_count=1,
        feature_count=0,
        geometry_type="Point",
    ).describe("pt")
    assert "CRS: desconhecido." in text


def test_words_lexicon_parity():
    # adding a key to one language but not the other must be a hard failure
    assert set(schemas._WORDS["en"]) == set(schemas._WORDS["pt"])


def test_segy_units_labels_have_pt():
    # every translatable SEG-Y units label (all but the pass-through "dms") needs
    # a Portuguese entry, so a rename in segy.py cannot leak English into pt
    translatable = set(segy._UNITS_LABELS.values()) - {"dms"}
    assert translatable <= set(schemas._UNITS_PT)


# 2024-09-28 18:48:31 UTC, matching the archive's EM712 line 0419
_KMALL_T0 = 1_727_549_311
_KMALL_HEADER = struct.Struct("<I4sBBHII")


def _kmall_datagram(dgm_type, time_sec, body=b""):
    total = _KMALL_HEADER.size + len(body) + 4
    header = _KMALL_HEADER.pack(total, dgm_type, 0, 0, 712, time_sec, 0)
    return header + body + struct.pack("<I", total)


def _kmall_position_body(lat, lon):
    # common part (8 bytes) + sensor data: two times, fix quality, lat/lon
    common = struct.pack("<HHHH", 8, 0, 0, 0)
    sensor = struct.pack("<IIf", 0, 0, 1.0) + struct.pack("<dd", lat, lon)
    return common + sensor


def _write_kmall(path, fixes, dgm_type=b"#SPO", cpo_fixes=()):
    datagrams = [_kmall_datagram(b"#SVT", _KMALL_T0)]
    for index, (lat, lon) in enumerate(fixes):
        datagrams.append(
            _kmall_datagram(dgm_type, _KMALL_T0 + index, _kmall_position_body(lat, lon))
        )
    for index, (lat, lon) in enumerate(cpo_fixes):
        datagrams.append(
            _kmall_datagram(b"#CPO", _KMALL_T0 + index, _kmall_position_body(lat, lon))
        )
    # a final datagram on the next day exercises the temporal range
    datagrams.append(_kmall_datagram(b"#SVT", _KMALL_T0 + 86400))
    path.write_bytes(b"".join(datagrams))


def test_kmall_metadata_fields(tmp_path):
    path = tmp_path / "line.kmall"
    _write_kmall(path, [(40.5, -9.3), (40.7, -9.1), (40.6, -9.2)])

    result = extract_kmall_metadata(path)

    assert isinstance(result, schemas.KmallMetadata)
    assert result.driver == "KMALL"
    assert result.echo_sounder_id == 712
    assert result.duration_seconds == 86400
    assert result.epsg == 4326
    assert result.bbox_4326 == (-9.3, 40.5, -9.1, 40.7)
    assert result.bbox_native == result.bbox_4326
    assert result.temporal_extent_begin == dt.date(2024, 9, 28)
    assert result.temporal_extent_end == dt.date(2024, 9, 29)


def test_kmall_cpo_fallback(tmp_path):
    path = tmp_path / "line.kmall"
    _write_kmall(path, [(40.5, -9.3), (40.7, -9.1)], dgm_type=b"#CPO")

    result = extract_kmall_metadata(path)

    assert result.bbox_4326 == (-9.3, 40.5, -9.1, 40.7)


def test_kmall_spo_takes_precedence_over_cpo(tmp_path):
    # SPO is the primary source; a divergent CPO feed must be IGNORED, never
    # merged into the bbox
    path = tmp_path / "line.kmall"
    _write_kmall(path, [(40.5, -9.3), (40.7, -9.1)], cpo_fixes=[(50.0, 5.0)])

    result = extract_kmall_metadata(path)

    assert result.bbox_4326 == (-9.3, 40.5, -9.1, 40.7)


def test_kmall_collect_position_fixes_prefers_spo(tmp_path):
    path = tmp_path / "line.kmall"
    _write_kmall(path, [(40.5, -9.3), (40.7, -9.1)], cpo_fixes=[(50.0, 5.0)])

    assert collect_position_fixes(path) == [(-9.3, 40.5), (-9.1, 40.7)]


def test_kmall_collect_position_fixes_falls_back_to_cpo(tmp_path):
    # a #SPO datagram is present but holds no usable fix, so #CPO takes over
    path = tmp_path / "line.kmall"
    _write_kmall(path, [(0.0, 0.0)], cpo_fixes=[(40.5, -9.3), (40.7, -9.1)])

    assert collect_position_fixes(path) == [(-9.3, 40.5), (-9.1, 40.7)]


def test_kmall_short_position_body_skipped(tmp_path):
    # a position datagram whose body ends before the lat/lon doubles must be
    # skipped without crashing
    short_body = struct.pack("<HHHH", 8, 0, 0, 0) + struct.pack("<IIf", 0, 0, 1.0)
    datagrams = [
        _kmall_datagram(b"#SPO", _KMALL_T0, short_body),
        _kmall_datagram(b"#SPO", _KMALL_T0 + 1, _kmall_position_body(40.6, -9.2)),
    ]
    path = tmp_path / "line.kmall"
    path.write_bytes(b"".join(datagrams))

    result = extract_kmall_metadata(path)

    assert result.bbox_4326 == (-9.2, 40.6, -9.2, 40.6)


def test_kmall_without_positions(tmp_path):
    path = tmp_path / "line.kmall"
    _write_kmall(path, [])

    result = extract_kmall_metadata(path)

    assert result.bbox_4326 is None
    assert result.epsg is None
    assert result.temporal_extent_begin == dt.date(2024, 9, 28)
    assert result.temporal_extent_end == dt.date(2024, 9, 29)


def test_kmall_skips_garbage_fixes(tmp_path):
    path = tmp_path / "line.kmall"
    _write_kmall(
        path,
        [
            (200.0, 5.0),  # out-of-range sentinel
            (0.0, 0.0),  # null-island GNSS dropout
            (math.nan, -9.2),
            (40.6, -9.2),  # the only valid fix
        ],
    )

    result = extract_kmall_metadata(path)

    assert result.bbox_4326 == (-9.2, 40.6, -9.2, 40.6)


def test_kmall_truncated_tail_garbage(tmp_path):
    path = tmp_path / "line.kmall"
    _write_kmall(path, [(40.5, -9.3)])
    with path.open("ab") as fh:
        fh.write(b"X" * 40)  # parses as an invalid header -> walk stops

    result = extract_kmall_metadata(path)

    assert result.bbox_4326 == (-9.3, 40.5, -9.3, 40.5)
    assert result.temporal_extent_end == dt.date(2024, 9, 29)


def test_kmall_truncated_tail_beyond_eof(tmp_path):
    # the realistic acquisition-crash shape: a well-formed header whose
    # num_bytes claims data beyond the end of the file
    path = tmp_path / "line.kmall"
    _write_kmall(path, [(40.5, -9.3)])
    with path.open("ab") as fh:
        fh.write(_KMALL_HEADER.pack(99999, b"#MRZ", 0, 0, 712, _KMALL_T0 + 2, 0))

    result = extract_kmall_metadata(path)

    assert result.bbox_4326 == (-9.3, 40.5, -9.3, 40.5)
    assert result.temporal_extent_end == dt.date(2024, 9, 29)


def _write_sampled_kmall(path, fix_lon, sounding_bytes=30_000, count=200):
    """A KMALL file larger than the sampled read's windows, one second per datagram.

    Every fourth datagram is a #SPO fix at the longitude `fix_lon(index)` and a
    latitude rising along the file, the others are soundings whose payload holds
    `#` bytes and lengths, so that only a validated boundary is taken for one.
    """
    filler = (struct.pack("<I4s", 1000, b"#MRZ") + b"x#" * 16) * (sounding_bytes // 40)
    datagrams = []
    for index in range(count):
        if index % 4 == 0:
            body = _kmall_position_body(40.0 + index * 1e-4, fix_lon(index))
            datagrams.append(_kmall_datagram(b"#SPO", _KMALL_T0 + index, body))
        else:
            datagrams.append(
                _kmall_datagram(b"#MRZ", _KMALL_T0 + index, filler[:sounding_bytes])
            )
    content = b"".join(datagrams)
    assert len(content) > kmall._SAMPLE_WINDOWS * kmall._SAMPLE_WINDOW_BYTES
    path.write_bytes(content)


def test_kmall_sampled_read_covers_both_ends_and_the_middle(tmp_path):
    # the easternmost fixes are only in the middle of the file, between the
    # windows at its ends
    path = tmp_path / "line.kmall"
    _write_sampled_kmall(
        path, lambda index: -9.3 if index < 20 else -9.2 if index >= 180 else -9.0
    )

    result = extract_kmall_metadata(path)

    west, south, east, north = result.bbox_4326
    assert (west, east) == (-9.3, -9.0)
    # the first and last fixes, from the windows at the ends of the file
    assert south == 40.0
    assert north == pytest.approx(40.0 + 196 * 1e-4)
    assert result.duration_seconds == 199
    assert result.temporal_extent_begin == dt.date(2024, 9, 28)


def test_kmall_sampled_read_reads_windows_only(tmp_path, monkeypatch):
    path = tmp_path / "line.kmall"
    _write_sampled_kmall(path, lambda index: -9.3)
    read_sizes = []
    real_open = Path.open

    def recording_open(self, *args, **kwargs):
        fh = real_open(self, *args, **kwargs)
        real_read = fh.read

        def recording_read(size=-1):
            data = real_read(size)
            read_sizes.append(len(data))
            return data

        fh.read = recording_read
        return fh

    monkeypatch.setattr(Path, "open", recording_open)

    extract_kmall_metadata(path)

    assert read_sizes == [kmall._SAMPLE_WINDOW_BYTES] * kmall._SAMPLE_WINDOWS


def test_kmall_sampled_read_survives_a_truncated_tail(tmp_path):
    path = tmp_path / "line.kmall"
    _write_sampled_kmall(path, lambda index: -9.3)
    with path.open("ab") as fh:
        fh.write(_KMALL_HEADER.pack(99999, b"#MRZ", 0, 0, 712, _KMALL_T0 + 300, 0))

    result = extract_kmall_metadata(path)

    # the tail window yields nothing, the last middle window ends the extent
    assert result.bbox_4326[0] == -9.3
    assert 150 < result.duration_seconds < 199


def test_kmall_sampled_read_rejects_an_invalid_start(tmp_path):
    path = tmp_path / "line.kmall"
    _write_sampled_kmall(path, lambda index: -9.3)
    content = path.read_bytes()
    path.write_bytes(b"not a datagram" + content)

    with pytest.raises(ValueError):
        extract_kmall_metadata(path)


def test_kmall_garbage_raises(tmp_path):
    path = tmp_path / "junk.kmall"
    path.write_bytes(b"this is definitely not a kmall file")
    with pytest.raises(ValueError):
        extract_kmall_metadata(path)


@pytest.mark.parametrize("content", [b"", b"tiny"])
def test_kmall_too_small_raises(tmp_path, content):
    # empty or sub-header files never enter the walk and must still raise
    path = tmp_path / "empty.kmall"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        extract_kmall_metadata(path)


@pytest.mark.parametrize("content", [b"", b"tiny"])
def test_kmall_collect_position_fixes_rejects_non_kmall(tmp_path, content):
    path = tmp_path / "empty.kmall"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        collect_position_fixes(path)


def test_dispatch_routes_kmall(tmp_path):
    path = tmp_path / "line.kmall"
    _write_kmall(path, [(40.5, -9.3)])
    assert isinstance(dispatch.dispatch_extractor(path), schemas.KmallMetadata)


def test_kmall_describe(tmp_path):
    path = tmp_path / "line.kmall"
    _write_kmall(path, [(40.5, -9.3)])
    text = extract_kmall_metadata(path).describe()
    assert text.startswith("Auto-extracted: Kongsberg KMALL, EM 712, 1440 min of data.")
    assert "EPSG:4326" in text
    assert len(text) <= 500


def test_kmall_describe_pt(tmp_path):
    path = tmp_path / "line.kmall"
    _write_kmall(path, [(40.5, -9.3)])
    text = extract_kmall_metadata(path).describe("pt")
    assert text.startswith(
        "Extração automática: Kongsberg KMALL, EM 712, 1440 min de dados."
    )
    assert "EPSG:4326" in text
    assert len(text) <= 500


# SEG-Y builders: tiny files with the real layout (3200-byte textual header +
# 400-byte binary header + fixed-length traces), big-endian by default. Day 272
# of 2024 is 2024-09-28, matching the archive's survey dates.
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1


def _segy_binary_header(ns, sample_format, interval, revision, n_ext, order):
    header = bytearray(400)
    struct.pack_into(order + "H", header, 16, interval)
    struct.pack_into(order + "H", header, 20, ns)
    struct.pack_into(order + "H", header, 24, sample_format)
    header[300] = revision
    struct.pack_into(order + "h", header, 304, n_ext)
    return bytes(header)


def _segy_trace(
    ns=4,
    bytes_per_sample=4,
    src=(0, 0),
    cdp=(0, 0),
    scalco=0,
    units=1,
    year=2024,
    day=272,
    hour=12,
    minute=30,
    second=15,
    order=">",
):
    header = bytearray(240)
    struct.pack_into(order + "h", header, 70, scalco)
    struct.pack_into(order + "ii", header, 72, *src)
    struct.pack_into(order + "H", header, 88, units)
    struct.pack_into(order + "HHHHH", header, 156, year, day, hour, minute, second)
    struct.pack_into(order + "ii", header, 180, *cdp)
    return bytes(header) + b"\x00" * (ns * bytes_per_sample)


def _write_segy(
    path,
    traces,
    ns=4,
    sample_format=5,
    interval=250,
    revision=1,
    n_ext=0,
    order=">",
    textual=b"",
    extended=b"",
    trailer=b"",
):
    path.write_bytes(
        textual.ljust(3200, b" ")
        + _segy_binary_header(ns, sample_format, interval, revision, n_ext, order)
        + extended
        + b"".join(traces)
        + trailer
    )


def test_segy_metres_path(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [
            _segy_trace(src=(-50000, 150000), day=272),
            _segy_trace(src=(-48000, 152000), day=273),
            _segy_trace(src=(-49000, 151000), day=272),
        ],
    )

    result = extract_segy_metadata(path)

    assert isinstance(result, schemas.SegyMetadata)
    assert result.driver == "SEG-Y"
    assert result.trace_count == 3
    assert result.samples_per_trace == 4
    assert result.sample_interval == 250
    assert result.sample_format == "ieee-float32"
    assert result.coordinate_units == "metres"
    assert result.coverage == "full"
    # undeclared projected metres: native bbox only, the CRS is never guessed
    assert result.bbox_native == (-50000.0, 150000.0, -48000.0, 152000.0)
    assert result.bbox_4326 is None
    assert result.epsg is None
    assert result.temporal_extent_begin == dt.date(2024, 9, 28)
    assert result.temporal_extent_end == dt.date(2024, 9, 29)


def test_segy_geographic_degrees(tmp_path):
    # units=3 with scalco=-10000: raw ints are degrees times 10000
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [
            _segy_trace(src=(-87500, 422300), scalco=-10000, units=3),
            _segy_trace(src=(-87000, 422800), scalco=-10000, units=3),
        ],
    )

    result = extract_segy_metadata(path)

    assert result.coordinate_units == "degrees"
    assert result.epsg == 4326
    assert result.crs_name == "WGS 84"
    assert result.bbox_4326 == (-8.75, 42.23, -8.7, 42.28)
    assert result.bbox_native == result.bbox_4326


def test_segy_geographic_arc_seconds(tmp_path):
    # the real CW HAT.sgy shape: units=2, stationary, arc-seconds with a
    # negative scalar; -8.7385 deg is -31458.6 arc-seconds
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [_segy_trace(src=(-314586, 1520280), scalco=-10, units=2)],
    )

    result = extract_segy_metadata(path)

    assert result.coordinate_units == "arc-seconds"
    assert result.epsg == 4326
    lon_min, lat_min, lon_max, lat_max = result.bbox_4326
    assert lon_min == lon_max == pytest.approx(-8.7385)
    assert lat_min == lat_max == pytest.approx(42.23)


def test_segy_dms_units_skipped(tmp_path):
    # packed DDDMMSS.ss is never converted in v1; storing the packed integers
    # verbatim would fake a bbox
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(83030450, 421512), units=4)])

    result = extract_segy_metadata(path)

    assert result.coordinate_units == "dms"
    assert result.bbox_native is None
    assert result.bbox_4326 is None
    assert result.coverage == "full"


def test_segy_scalco_multiplies(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(-5000, 15000), scalco=10)])

    result = extract_segy_metadata(path)

    assert result.bbox_native == (-50000.0, 150000.0, -50000.0, 150000.0)


def test_segy_cdp_sentinel_fill_ignored(tmp_path):
    # real archive traces carry INT32_MIN fill in the CDP fields while src holds
    # the good coordinates. The scalar matters: scaled by -10000 a sentinel
    # becomes -214748.36, well inside the plausible-metres range, so only the
    # sentinel guard itself keeps it out of the bbox
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [
            _segy_trace(src=(-500000000, 1500000000), scalco=-10000),
            _segy_trace(src=(0, 0), cdp=(_INT32_MIN, _INT32_MIN), scalco=-10000),
            _segy_trace(src=(_INT32_MAX, _INT32_MAX), scalco=-10000),
        ],
    )

    result = extract_segy_metadata(path)

    assert result.bbox_native == (-50000.0, 150000.0, -50000.0, 150000.0)
    assert result.coverage == "full"


def test_segy_src_takes_precedence_over_cdp(tmp_path):
    # src is the primary source; a divergent cdp feed must be IGNORED, never
    # merged into the bbox (the KMALL SPO/CPO rule, applied to SEG-Y)
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [
            _segy_trace(src=(-50000, 150000), cdp=(-90000, 190000)),
            _segy_trace(src=(-48000, 152000), cdp=(-91000, 191000)),
        ],
    )

    result = extract_segy_metadata(path)

    assert result.bbox_native == (-50000.0, 150000.0, -48000.0, 152000.0)


def test_segy_cdp_fallback(tmp_path):
    # chirp/Innomar/sbp populate only src, UHRS both; a src-less trace must
    # still yield its CDP coordinates
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(0, 0), cdp=(-50000, 150000))])

    result = extract_segy_metadata(path)

    assert result.bbox_native == (-50000.0, 150000.0, -50000.0, 150000.0)


def test_segy_without_coordinates(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(), _segy_trace()])

    result = extract_segy_metadata(path)

    assert result.bbox_native is None
    assert result.bbox_4326 is None
    assert result.coverage == "full"
    assert result.temporal_extent_begin == dt.date(2024, 9, 28)


def test_segy_mostly_garbage_coordinates_partial(tmp_path):
    # implausible coordinate magnitudes are the tell of samples landing
    # mid-trace; above half the samples the coverage is flagged partial, but
    # the plausible traces still contribute
    path = tmp_path / "line.sgy"
    garbage = [_segy_trace(src=(2_000_000_000, 7)) for _ in range(8)]
    good = [
        _segy_trace(src=(-50000, 150000)),
        _segy_trace(src=(-48000, 152000)),
    ]
    _write_segy(path, garbage + good)

    result = extract_segy_metadata(path)

    assert result.coverage == "partial"
    assert result.bbox_native == (-50000.0, 150000.0, -48000.0, 152000.0)


def test_segy_two_digit_year_temporal_none(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(-50000, 150000), year=24)])

    result = extract_segy_metadata(path)

    assert result.temporal_extent_begin is None
    assert result.temporal_extent_end is None
    assert result.bbox_native is not None


def test_segy_corrupt_time_fields_skipped(tmp_path):
    # a single corrupt time field skips only that trace's date and never aborts
    # the extraction (the KMALL guarantee)
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [
            _segy_trace(src=(-50000, 150000), hour=99),
            _segy_trace(src=(-48000, 152000), year=2023, day=366),  # not a leap year
            _segy_trace(src=(-49000, 151000), day=272),
        ],
    )

    result = extract_segy_metadata(path)

    assert result.temporal_extent_begin == dt.date(2024, 9, 28)
    assert result.temporal_extent_end == dt.date(2024, 9, 28)
    assert result.bbox_native == (-50000.0, 150000.0, -48000.0, 152000.0)


def test_segy_trailing_bytes_tolerated(tmp_path):
    # a real BSTK file carries a 5,056-byte trailer: floor division ignores it
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [_segy_trace(src=(-50000, 150000)), _segy_trace(src=(-48000, 152000))],
        trailer=b"\x87" * 100,
    )

    result = extract_segy_metadata(path)

    assert result.trace_count == 2
    assert result.coverage == "full"
    assert result.bbox_native == (-50000.0, 150000.0, -48000.0, 152000.0)


def test_segy_zero_samples_partial_metadata(tmp_path):
    # ns=0 in the binary header leaves no trustworthy trace length; keep the
    # header facts, never fall back to the unreliable per-trace ns field
    path = tmp_path / "line.sgy"
    _write_segy(path, [b"\x00" * 240], ns=0)

    result = extract_segy_metadata(path)

    assert result.samples_per_trace is None
    assert result.trace_count is None
    assert result.sample_format == "ieee-float32"
    assert result.sample_interval == 250
    assert result.bbox_native is None


def test_segy_unknown_format_partial_metadata(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace()], sample_format=9)

    result = extract_segy_metadata(path)

    assert result.sample_format == "format code 9"
    assert result.trace_count is None
    assert result.bbox_native is None


def test_segy_little_endian(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [_segy_trace(src=(-50000, 150000), order="<")],
        order="<",
    )

    result = extract_segy_metadata(path)

    assert result.sample_format == "ieee-float32"
    assert result.samples_per_trace == 4
    assert result.bbox_native == (-50000.0, 150000.0, -50000.0, 150000.0)


def test_segy_rev0_extended_count_ignored(tmp_path):
    # the rev0 bytes at offset 304 are undefined noise; trusting them would
    # push data_start past the traces
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [_segy_trace(src=(-50000, 150000)), _segy_trace(src=(-48000, 152000))],
        revision=0,
        n_ext=50,
    )

    result = extract_segy_metadata(path)

    assert result.trace_count == 2
    assert result.bbox_native == (-50000.0, 150000.0, -48000.0, 152000.0)


def test_segy_variable_extended_count_untrusted(tmp_path):
    # n_ext == -1 means "variable, stanza-terminated" and is not trusted
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(-50000, 150000))], revision=1, n_ext=-1)

    result = extract_segy_metadata(path)

    assert result.trace_count == 1
    assert result.bbox_native == (-50000.0, 150000.0, -50000.0, 150000.0)


def test_segy_extended_textual_headers(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [_segy_trace(src=(-50000, 150000)), _segy_trace(src=(-48000, 152000))],
        revision=1,
        n_ext=1,
        extended=b" " * 3200,
    )

    result = extract_segy_metadata(path)

    assert result.trace_count == 2
    assert result.bbox_native == (-50000.0, 150000.0, -48000.0, 152000.0)


@pytest.mark.parametrize(
    "textual, expected",
    [
        pytest.param(
            "C17 PROJECTION TYPE: PORTUGAL TM06 (EPSG 3763);".encode("cp037"),
            (3763,),
            id="ebcdic",
        ),
        pytest.param(
            b"C 9 crs: etrs89 / portugal tm06, epsg : 3763",
            (3763,),
            id="ascii in lower case",
        ),
        pytest.param(
            (
                "C17 PROJECTION TYPE: TRANSVERSE MERCATOR(EPSG:9807); "
                "C18 VERTICAL DATUM: ZERO HIDROGRAFICO(ZH,EPSG:10349);"
            ).encode("cp037"),
            (9807, 10349),
            id="method and vertical datum",
        ),
        pytest.param(
            "C24 GEODETIC: 3763 : ETRS89 / Portugal TM06 EPSG:258290".encode("cp037"),
            (),
            id="bare number or six digits",
        ),
    ],
)
def test_segy_header_epsg_codes(tmp_path, textual, expected):
    # every explicit code is reported, even those that are no CRS (9807 is a
    # method, 10349 a vertical datum): which one applies is for discovery
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(-50000, 150000))], textual=textual)

    assert extract_segy_metadata(path).header_epsg_codes == expected


def test_segy_sampling_includes_endpoints(tmp_path):
    # 150 single-sample traces: only ~100 are sampled, but the first and last
    # trace (the line endpoints) must always contribute to the bbox
    path = tmp_path / "line.sgy"
    first = _segy_trace(ns=1, bytes_per_sample=1, src=(-52000, 148000))
    middle = [
        _segy_trace(ns=1, bytes_per_sample=1, src=(-49000, 151000)) for _ in range(148)
    ]
    last = _segy_trace(ns=1, bytes_per_sample=1, src=(-45000, 155000))
    _write_segy(path, [first, *middle, last], ns=1, sample_format=8)

    result = extract_segy_metadata(path)

    assert result.trace_count == 150
    assert result.sample_format == "int8"
    assert result.bbox_native == (-52000.0, 148000.0, -45000.0, 155000.0)


@pytest.mark.parametrize(
    "content",
    [b"", b"tiny", b"\x00" * 4000, b"\xff" * 4000],
)
def test_segy_not_a_segy_raises(tmp_path, content):
    # too small to hold a trace, or a binary header whose format code is
    # invalid in both byte orders
    path = tmp_path / "junk.sgy"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        extract_segy_metadata(path)


# production holds 925 .SEGY files besides the 68k lowercase ones, so the
# uppercase variants are pinned here too
@pytest.mark.parametrize("suffix", [".sgy", ".segy", ".SGY", ".SEGY"])
def test_dispatch_routes_segy(tmp_path, suffix):
    path = tmp_path / f"line{suffix}"
    _write_segy(path, [_segy_trace(src=(-50000, 150000))])
    assert isinstance(dispatch.dispatch_extractor(path), schemas.SegyMetadata)


def test_segy_implausible_span_discards_bbox(tmp_path):
    # real owf-2025 files exist whose src AND cdp fields hold noise around the
    # projection origin with sporadic spikes into the millions; the resulting
    # box spanned thousands of km while coverage still said "full". Rejecting
    # the outliers instead would leave a small credible box AT the origin,
    # which is on land in central Portugal, so the whole box goes.
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [
            _segy_trace(src=(140, 120), scalco=-100),
            _segy_trace(src=(-240, -330), scalco=-100),
            _segy_trace(src=(588515700, 600505400), scalco=-100),
            _segy_trace(src=(-100, -80), scalco=-100),
        ],
    )

    result = extract_segy_metadata(path)

    assert result.bbox_native is None
    assert result.bbox_4326 is None
    assert result.coverage == "partial"
    # the rest of the metadata is unaffected and still worth having
    assert result.trace_count == 4
    assert result.sample_format == "ieee-float32"
    assert result.temporal_extent_begin == dt.date(2024, 9, 28)


def test_segy_implausible_span_without_any_rejected_value(tmp_path):
    # the case a garbage-count rule cannot catch: every value stays inside the
    # per-value plausibility filter, so only the span betrays the noise
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [
            _segy_trace(src=(140, 120), scalco=-100),
            _segy_trace(src=(-986000000, -493000000), scalco=-100),
            _segy_trace(src=(995000000, 497000000), scalco=-100),
        ],
    )

    result = extract_segy_metadata(path)

    assert result.bbox_native is None
    assert result.coverage == "partial"


def test_segy_geographic_implausible_span_discards_bbox(tmp_path):
    # the same protection on the only path that draws a map rectangle
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [
            _segy_trace(src=(-87500, 422300), scalco=-10000, units=3),
            _segy_trace(src=(1200000, -600000), scalco=-10000, units=3),
        ],
    )

    result = extract_segy_metadata(path)

    assert result.bbox_4326 is None
    assert result.bbox_native is None
    assert result.epsg is None  # no CRS claim without a box to attach it to
    assert result.coverage == "partial"


def test_segy_survey_wide_span_is_kept(tmp_path):
    # a legitimately long line must survive: real files measure up to 61.5 km
    # and the cap is 200 km, so a 60 km line is still stored
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [
            _segy_trace(src=(-13000000, 2200000), scalco=-100),
            _segy_trace(src=(-13000000, 8200000), scalco=-100),
        ],
    )

    result = extract_segy_metadata(path)

    assert result.bbox_native == (-130000.0, 22000.0, -130000.0, 82000.0)
    assert result.coverage == "full"


def test_segy_burst_corruption_span_discards_bbox(tmp_path):
    # the second junk mode the 66k scan found (A7808 ET_SBP): a real ~2.5 km
    # line with a burst of corrupt-nav traces stretched the box to ~494 km with
    # garbage_count 0, which the old 500 km cap let through as coverage=full.
    # The 200 km cap catches it while leaving every real line (<= 61.5 km) alone.
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [
            _segy_trace(src=(-12198249, 5017758), scalco=-100),  # (-121982, 50177)
            _segy_trace(src=(-738249, -44428591), scalco=-100),  # (-7382, -444285)
        ],
    )

    result = extract_segy_metadata(path)

    assert result.bbox_native is None
    assert result.coverage == "partial"
    # the header facts are unaffected and still worth keeping
    assert result.trace_count == 2


def test_segy_low_support_bbox_dropped(tmp_path):
    # the third junk mode the scan found (A7808 GEOM): a 95-182 GB file where
    # only 2-3 of 100 sampled traces carry a fix and the rest are coordinate-less.
    # A box from 3 points covers a sliver of the real line while claiming full
    # coverage, so it is dropped and the coverage flagged.
    path = tmp_path / "line.sgy"
    traces = [_segy_trace(src=(-50000, 150000))] * 3 + [_segy_trace()] * 97
    _write_segy(path, traces)

    result = extract_segy_metadata(path)

    assert result.trace_count == 100
    assert result.bbox_native is None
    assert result.coverage == "partial"


def test_segy_low_support_kept_for_small_file(tmp_path):
    # the guard: a genuinely small file with only a few traces keeps its box even
    # when only some carry a fix - too few samples to trust the support ratio
    path = tmp_path / "line.sgy"
    traces = [
        _segy_trace(src=(-50000, 150000)),
        _segy_trace(src=(-48000, 152000)),
    ] + [_segy_trace()] * 6
    _write_segy(path, traces)

    result = extract_segy_metadata(path)

    assert result.trace_count == 8
    assert result.bbox_native == (-50000.0, 150000.0, -48000.0, 152000.0)
    assert result.coverage == "full"


def test_segy_units_unset_treated_as_metres(tmp_path):
    # the real raw-file case: the UHRS rev1.segy files leave units at 0
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(-50000, 150000), units=0)])

    result = extract_segy_metadata(path)

    assert result.coordinate_units == "unset"
    assert result.bbox_native == (-50000.0, 150000.0, -50000.0, 150000.0)
    assert result.bbox_4326 is None
    assert result.epsg is None


def test_segy_geographic_out_of_range_rejected(tmp_path):
    # the plausibility filter guards the only path that draws a map rectangle:
    # a trace claiming degrees but carrying projected metres must not become a
    # bbox somewhere off the planet
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [
            _segy_trace(src=(-87500, 422300), scalco=-10000, units=3),
            _segy_trace(src=(-500000, 1500000), units=3),  # metres in a degrees file
        ],
    )

    result = extract_segy_metadata(path)

    assert result.bbox_4326 == (-8.75, 42.23, -8.75, 42.23)
    assert result.coverage == "full"  # one garbage trace out of two is not "> half"


def test_segy_coverage_boundary_at_exactly_half(tmp_path):
    # exactly half the samples garbage stays "full"; one more tips it to partial
    path = tmp_path / "line.sgy"
    good = [_segy_trace(src=(-50000, 150000)), _segy_trace(src=(-48000, 152000))]
    garbage = [_segy_trace(src=(2_000_000_000, 7)) for _ in range(2)]
    _write_segy(path, good + garbage)
    assert extract_segy_metadata(path).coverage == "full"

    _write_segy(path, good + garbage + [_segy_trace(src=(2_000_000_000, 7))])
    assert extract_segy_metadata(path).coverage == "partial"


def test_segy_extended_headers_not_fitting_are_ignored(tmp_path):
    # a declared extended-header count that would leave no room for a trace is
    # garbage; trusting it would push data_start past the end of the file and
    # yield a negative trace_count
    path = tmp_path / "line.sgy"
    _write_segy(
        path,
        [_segy_trace(src=(-50000, 150000))],
        revision=1,
        n_ext=99,  # 99 * 3200 bytes that are not in the file
    )

    result = extract_segy_metadata(path)

    assert result.trace_count == 1
    assert result.bbox_native == (-50000.0, 150000.0, -50000.0, 150000.0)


def test_segy_little_endian_revision_word(tmp_path):
    # a little-endian writer storing the rev1-style uint16 0x0100 puts the major
    # number in the SECOND byte; reading a single byte would see revision 0 and
    # then ignore the extended header, shifting the whole trace grid
    path = tmp_path / "line.sgy"
    header = bytearray(_segy_binary_header(4, 5, 250, 1, 1, "<"))
    header[300:302] = b"\x00\x01"
    path.write_bytes(
        b" " * 3200
        + bytes(header)
        + b" " * 3200
        + _segy_trace(src=(-50000, 150000), order="<")
        + _segy_trace(src=(-48000, 152000), order="<")
    )

    result = extract_segy_metadata(path)

    assert result.trace_count == 2
    assert result.bbox_native == (-50000.0, 150000.0, -48000.0, 152000.0)


def test_segy_rev2_extra_trace_headers_partial_metadata(tmp_path):
    # rev2 lets each trace carry additional 240-byte headers; the trace length
    # is then unknown to us, and a desynced grid would store a confidently
    # wrong bbox, so only the header facts survive
    path = tmp_path / "line.sgy"
    header = bytearray(_segy_binary_header(4, 5, 250, 2, 0, ">"))
    struct.pack_into(">i", header, 306, 1)
    path.write_bytes(
        b" " * 3200
        + bytes(header)
        + b"".join(
            _segy_trace(src=src) + b"\x00" * 240
            for src in ((-50000, 150000), (-48000, 152000))
        )
    )

    result = extract_segy_metadata(path)

    assert result.sample_format == "ieee-float32"
    assert result.trace_count is None
    assert result.bbox_native is None


def test_segy_truncated_binary_header_raises(tmp_path):
    # a file that ends inside the binary header must still raise ValueError
    # rather than let a struct error escape
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(-50000, 150000))])
    truncated = tmp_path / "truncated.sgy"
    truncated.write_bytes(path.read_bytes()[:3400])

    with pytest.raises(ValueError):
        extract_segy_metadata(truncated)


def test_segy_trace_count_zero(tmp_path):
    # a file holding the headers but less than one full trace
    path = tmp_path / "line.sgy"
    path.write_bytes(
        b" " * 3200 + _segy_binary_header(1000, 5, 250, 1, 0, ">") + b"\x00" * 300
    )

    result = extract_segy_metadata(path)

    assert result.trace_count == 0
    assert result.samples_per_trace == 1000
    assert result.bbox_native is None
    assert result.temporal_extent_begin is None


def test_segy_describe_partial_metadata(tmp_path):
    # a file whose traces cannot be walked still gets a useful description
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace()], sample_format=9)
    text = extract_segy_metadata(path).describe()
    assert text.startswith("Auto-extracted: SEG-Y")
    assert "format code 9" in text
    assert "trace(s)" not in text
    assert "CRS: unknown." in text


def test_segy_describe_partial_coverage(tmp_path):
    path = tmp_path / "line.sgy"
    garbage = [_segy_trace(src=(2_000_000_000, 7)) for _ in range(8)]
    _write_segy(path, garbage + [_segy_trace(src=(-50000, 150000))])
    text = extract_segy_metadata(path).describe()
    assert "partly unreliable" in text


def test_segy_describe(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(-50000, 150000))])
    text = extract_segy_metadata(path).describe()
    assert text.startswith("Auto-extracted: SEG-Y")
    assert "1 trace(s)" in text
    assert "coordinates in metres" in text
    assert "CRS: unknown." in text
    assert "Native bbox:" in text
    assert len(text) <= 500


def test_segy_describe_geographic(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(-87500, 422300), scalco=-10000, units=3)])
    text = extract_segy_metadata(path).describe()
    assert "coordinates in degrees" in text
    assert "EPSG:4326" in text


def test_segy_describe_pt(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(-50000, 150000))])
    text = extract_segy_metadata(path).describe("pt")
    assert text.startswith("Extração automática: SEG-Y")
    assert "1 traço(s)" in text
    assert "coordenadas em metros" in text
    assert "CRS: desconhecido." in text
    assert "Extensão nativa:" in text
    assert len(text) <= 500


def test_segy_describe_partial_coverage_pt(tmp_path):
    path = tmp_path / "line.sgy"
    garbage = [_segy_trace(src=(2_000_000_000, 7)) for _ in range(8)]
    _write_segy(path, garbage + [_segy_trace(src=(-50000, 150000))])
    text = extract_segy_metadata(path).describe("pt")
    assert "pouco fiável" in text


def test_segy_describe_partial_metadata_pt(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace()], sample_format=9)
    text = extract_segy_metadata(path).describe("pt")
    assert "format code 9" in text  # a technical identifier stays English
    assert "traço(s)" not in text
    assert "CRS: desconhecido." in text


def test_segy_describe_geographic_pt(tmp_path):
    path = tmp_path / "line.sgy"
    _write_segy(path, [_segy_trace(src=(-87500, 422300), scalco=-10000, units=3)])
    text = extract_segy_metadata(path).describe("pt")
    assert "coordenadas em graus" in text
    assert "EPSG:4326" in text
