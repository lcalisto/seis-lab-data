"""Unit tests for the preview derivers package.

Pure functions, no DB: these run by default (no marker). GDAL is required; the
module self-skips where it is unavailable. Everything is exercised against
synthetic files built in-test, so the suite needs no sample-data archive.
"""

import struct

import numpy as np
import pytest

pytest.importorskip("osgeo")

from osgeo import (  # noqa: E402
    gdal,
    ogr,
    osr,
)

from seis_lab_data.tasks.derivers import dispatch  # noqa: E402
from seis_lab_data.tasks.derivers.bbox_thumbnail import (  # noqa: E402
    BboxStyle,
    build_tms_basemap_xml,
    render_bbox_thumbnail,
)
from seis_lab_data.tasks.derivers.gdal_raster import (  # noqa: E402
    _percentile_cuts,
    derive_raster_preview,
)
from seis_lab_data.tasks.derivers.gdal_vector import (  # noqa: E402
    derive_vector_preview,
)
from seis_lab_data.tasks.derivers.kmall import (  # noqa: E402
    derive_kmall_preview,
)

gdal.UseExceptions()

# EPSG:3763 (ETRS89 / Portugal TM06); coordinates near its false origin land in
# central Portugal, so the warped bounds fall in a checkable lon/lat window.
_PT_TM06 = 3763
_NODATA = -9999.0
# A diagonal in metres from the EPSG:3763 false origin; the asserted lon/lat
# window only fits ~2.8 km east and ~3.5 km north of it
_LINE = [(200.0, 200.0), (2000.0, 1000.0)]
# numBytesDgm, dgmType, dgmVersion, systemID, echoSounderID, time_sec, time_nanosec
_KMALL_HEADER = struct.Struct("<I4sBBHII")
# (lat, lon) fixes, the order KMALL stores them in: a straight run inside the
# asserted window, dense like a real track, since lone pixels lose much of their
# red to WEBP's lossy chroma
_KMALL_FIXES = [(39.645 + index * 4e-5, -8.145 + index * 6e-5) for index in range(500)]
_SEA_RGB = (20, 60, 120)
_BBOX_RGB = (194, 125, 14)
# the web maps' default style
_BBOX_STYLE = BboxStyle(
    fill_color="#c27d0e",
    fill_opacity=0.3,
    outline_color="#c27d0e",
    outline_opacity=1.0,
    outline_width=4,
)
# on the 512x384 thumbnail this bbox spans columns 132-380 and rows 32-352
_THUMBNAIL_BBOX = (-10.0, 38.0, -8.0, 40.0)
_WEB_MERCATOR_HALF_SIDE = 20037508.342789244


def _write_geotiff(path, width, height, values, epsg=_PT_TM06):
    ds = gdal.GetDriverByName("GTiff").Create(
        str(path), width, height, 1, gdal.GDT_Float32
    )
    ds.SetGeoTransform((0.0, 1.0, 0.0, float(height), 0.0, -1.0))
    if epsg is not None:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg)
        ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(_NODATA)
    band.WriteArray(values)
    ds = None  # noqa: F841
    return path


def _write_xyz_grid(path):
    # the layout the XYZ driver reads: no header, y in the outer loop and x
    # varying fastest; metres near the EPSG:3763 false origin, with no CRS
    rows = (
        f"{column * 10.0} {row * 10.0} {float(column + row)}"
        for row in range(60)
        for column in range(120)
    )
    path.write_text("\n".join(rows) + "\n")
    return path


def _write_shapefile(path, lines, epsg=_PT_TM06):
    srs = None
    if epsg is not None:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg)
    ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(str(path))
    layer = ds.CreateLayer("lines", srs=srs, geom_type=ogr.wkbLineString)
    for vertices in lines:
        geom = ogr.Geometry(ogr.wkbLineString)
        for x, y in vertices:
            geom.AddPoint_2D(x, y)
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(geom)
        layer.CreateFeature(feature)
        feature = None
    ds = None  # noqa: F841
    return path


def _kmall_datagram(dgm_type, body):
    total = _KMALL_HEADER.size + len(body) + 4
    header = _KMALL_HEADER.pack(total, dgm_type, 0, 0, 0, 0, 0)
    return header + body + struct.pack("<I", total)


def _write_kmall_track(path, fixes):
    datagrams = []
    for lat, lon in fixes:
        # common part (8 bytes) + sensor data: two times, fix quality, lat/lon
        common = struct.pack("<HHHH", 8, 0, 0, 0)
        sensor = struct.pack("<IIf", 0, 0, 1.0) + struct.pack("<dd", lat, lon)
        datagrams.append(_kmall_datagram(b"#SPO", common + sensor))
    path.write_bytes(b"".join(datagrams))
    return path


def _write_web_mercator_basemap(path):
    """An opaque single-colour RGBA base map over the whole web mercator square."""
    ds = gdal.GetDriverByName("GTiff").Create(
        str(path), 256, 256, 4, gdal.GDT_Byte, options=["ALPHA=YES"]
    )
    half_side = _WEB_MERCATOR_HALF_SIDE
    pixel_size = 2 * half_side / 256
    ds.SetGeoTransform((-half_side, pixel_size, 0.0, half_side, 0.0, -pixel_size))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3857)
    ds.SetProjection(srs.ExportToWkt())
    for band_index, value in enumerate((*_SEA_RGB, 255), start=1):
        ds.GetRasterBand(band_index).Fill(value)
    ds = None  # noqa: F841
    return path


def _read_webp(image):
    """Decode rendered preview bytes into their driver, size and bands."""
    vsi_path = "/vsimem/test-preview.webp"
    gdal.FileFromMemBuffer(vsi_path, image)
    ds = gdal.Open(vsi_path)
    try:
        return (
            ds.GetDriver().ShortName,
            ds.RasterXSize,
            ds.RasterYSize,
            [ds.GetRasterBand(i + 1).ReadAsArray() for i in range(ds.RasterCount)],
        )
    finally:
        ds = None  # noqa: F841
        gdal.Unlink(vsi_path)


def test_derive_raster_preview_renders_a_downscaled_webp(tmp_path):
    values = np.tile(np.arange(1200, dtype=np.float32), (600, 1))
    path = _write_geotiff(tmp_path / "grid.tif", 1200, 600, values)

    preview = derive_raster_preview(path)

    driver, width, height, bands = _read_webp(preview.image)
    assert driver == "WEBP"
    assert max(width, height) == 1024
    # 3, not 4: the encoder omits an all-opaque alpha plane, and this fixture
    # has no nodata pixels - transparency is pinned by the nodata test below
    assert len(bands) == 3
    min_x, min_y, max_x, max_y = preview.bounds_4326
    # the synthetic EPSG:3763 grid reprojects to central Portugal
    assert -8.2 < min_x < max_x < -8.1
    assert 39.6 < min_y < max_y < 39.7


def test_derive_raster_preview_pseudocolours_a_single_band(tmp_path):
    values = np.tile(np.arange(256, dtype=np.float32), (128, 1))
    path = _write_geotiff(tmp_path / "gradient.tif", 256, 128, values)

    preview = derive_raster_preview(path)

    *_, bands = _read_webp(preview.image)
    # a greyscale rendering would have R == G == B everywhere
    assert not np.array_equal(bands[0], bands[2])
    # turbo runs from blue (low values) to red (high values);
    # columns at 20-30% and 70-80% of the width keep the dark ends of the ramp
    # and lossy noise out of the comparison
    low_columns, high_columns = slice(51, 77), slice(179, 205)
    assert bands[2][:, low_columns].mean() > bands[0][:, low_columns].mean()
    assert bands[0][:, high_columns].mean() > bands[2][:, high_columns].mean()


def test_derive_raster_preview_makes_nodata_transparent(tmp_path):
    values = np.tile(np.arange(100, dtype=np.float32), (100, 1))
    values[:50, :] = _NODATA
    path = _write_geotiff(tmp_path / "with-nodata.tif", 100, 100, values)

    preview = derive_raster_preview(path)

    *_, bands = _read_webp(preview.image)
    alpha = bands[-1]
    assert alpha.min() < 128 < alpha.max()


def test_derive_raster_preview_requires_a_crs(tmp_path):
    values = np.tile(np.arange(100, dtype=np.float32), (100, 1))
    path = _write_geotiff(tmp_path / "no-crs.tif", 100, 100, values, epsg=None)

    with pytest.raises(ValueError):
        derive_raster_preview(path)


def test_derive_raster_preview_applies_the_implicit_crs(tmp_path):
    path = _write_xyz_grid(tmp_path / "grid.xyz")

    preview = derive_raster_preview(path, _PT_TM06)

    driver, *_ = _read_webp(preview.image)
    assert driver == "WEBP"
    min_x, min_y, max_x, max_y = preview.bounds_4326
    assert -8.2 < min_x < max_x < -8.1
    assert 39.6 < min_y < max_y < 39.7


def test_derive_raster_preview_prefers_the_declared_crs(tmp_path):
    values = np.tile(np.arange(100, dtype=np.float32), (100, 1))
    path = _write_geotiff(tmp_path / "grid.tif", 100, 100, values)

    # applied over the declared EPSG:3763, it would read the metres as degrees
    preview = derive_raster_preview(path, 4326)

    min_x, min_y, max_x, max_y = preview.bounds_4326
    assert -8.2 < min_x < max_x < -8.1
    assert 39.6 < min_y < max_y < 39.7


def test_derive_raster_preview_rejects_an_implausible_implicit_crs(tmp_path):
    path = _write_xyz_grid(tmp_path / "grid.xyz")

    # the grid's metres read as degrees reach far beyond the lon/lat range
    with pytest.raises(ValueError, match="outside the lon/lat range"):
        derive_raster_preview(path, 4326)


def test_percentile_cuts_ignore_nodata():
    ds = gdal.GetDriverByName("MEM").Create("", 100, 100, 1, gdal.GDT_Float32)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(_NODATA)
    values = np.tile(np.arange(100, dtype=np.float32), (100, 1))
    values[:50, :] = _NODATA
    band.WriteArray(values)

    low, high = _percentile_cuts(band)

    assert 0.0 <= low < high <= 99.0
    ds = None  # noqa: F841


@pytest.mark.parametrize(
    "name, is_directory, expected",
    [
        ("grid.tif", False, True),
        ("grid.tiff", False, True),
        ("grid.xyz", False, True),
        ("grid.asc", False, True),
        ("grid.flt", False, True),
        ("track.shp", False, True),
        ("track.gpkg", False, True),
        ("track.geojson", False, True),
        ("track.kmall", False, True),
        ("line.sgy", False, False),
        # the archive holds directories such as "F3_2022.tif"
        ("grid.tif", True, False),
    ],
)
def test_can_derive(tmp_path, name, is_directory, expected):
    path = tmp_path / name
    if is_directory:
        path.mkdir()
    else:
        path.touch()
    assert dispatch.can_derive(path) is expected


def test_derive_raster_preview_expands_a_palette(tmp_path):
    ds = gdal.GetDriverByName("GTiff").Create(str(tmp_path / "map.tif"), 64, 64, 1)
    ds.SetGeoTransform((0.0, 1.0, 0.0, 64.0, 0.0, -1.0))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(_PT_TM06)
    ds.SetProjection(srs.ExportToWkt())
    table = gdal.ColorTable()
    table.SetColorEntry(0, (255, 0, 0, 255))
    table.SetColorEntry(1, (0, 0, 255, 255))
    band = ds.GetRasterBand(1)
    band.SetRasterColorTable(table)
    values = np.zeros((64, 64), dtype=np.uint8)
    values[:, 32:] = 1
    band.WriteArray(values)
    ds = None  # noqa: F841

    preview = derive_raster_preview(tmp_path / "map.tif")

    _, _, _, bands = _read_webp(preview.image)
    # a stretched-index rendering would be greyscale (R == G == B everywhere)
    assert not np.array_equal(bands[0], bands[2])


def test_derive_raster_preview_stretches_16bit_colours(tmp_path):
    ds = gdal.GetDriverByName("GTiff").Create(
        str(tmp_path / "img.tif"), 64, 64, 3, gdal.GDT_UInt16
    )
    ds.SetGeoTransform((0.0, 1.0, 0.0, 64.0, 0.0, -1.0))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(_PT_TM06)
    ds.SetProjection(srs.ExportToWkt())
    rng = np.random.default_rng(7)
    for index, centre in enumerate((20000, 10000, 5000), start=1):
        values = rng.normal(centre, 2000, (64, 64)).astype(np.uint16)
        ds.GetRasterBand(index).WriteArray(values)
    ds = None  # noqa: F841

    preview = derive_raster_preview(tmp_path / "img.tif")

    _, _, _, bands = _read_webp(preview.image)
    # a bare Byte cast would clamp every 16-bit value to solid white
    assert bands[0].mean() < 250


def test_derive_vector_preview_renders_lines(tmp_path):
    path = _write_shapefile(tmp_path / "track.shp", [_LINE])

    preview = derive_vector_preview(path)

    driver, width, height, bands = _read_webp(preview.image)
    assert driver == "WEBP"
    assert max(width, height) == 1024
    # 4: the transparent background keeps the alpha plane in the encoded image
    assert len(bands) == 4
    alpha = bands[3]
    # the alpha plane is lossless in WEBP, so it keeps its exact values
    assert alpha.min() == 0
    assert alpha.max() == 255
    # lossy chroma shifts the burnt red a few levels, so only its dominance
    # over the opaque pixels is checked
    reds = bands[0][alpha == 255]
    blues = bands[2][alpha == 255]
    assert reds.max() > 150
    assert (reds.astype(int) - blues.astype(int)).max() > 60
    min_x, min_y, max_x, max_y = preview.bounds_4326
    # the synthetic EPSG:3763 line reprojects to central Portugal
    assert -8.2 < min_x < max_x < -8.1
    assert 39.6 < min_y < max_y < 39.7


def test_derive_vector_preview_requires_a_crs(tmp_path):
    path = _write_shapefile(tmp_path / "no-crs.shp", [_LINE], epsg=None)

    with pytest.raises(ValueError):
        derive_vector_preview(path)


def test_derive_vector_preview_requires_features(tmp_path):
    path = _write_shapefile(tmp_path / "empty.shp", [])

    with pytest.raises(ValueError):
        derive_vector_preview(path)


def test_derive_kmall_preview_renders_track(tmp_path):
    path = _write_kmall_track(tmp_path / "line.kmall", _KMALL_FIXES)

    preview = derive_kmall_preview(path)

    # rendered by the vector deriver, so the same checks as for the vector lines
    driver, width, height, bands = _read_webp(preview.image)
    assert driver == "WEBP"
    assert max(width, height) == 1024
    assert len(bands) == 4
    alpha = bands[3]
    assert alpha.min() == 0
    assert alpha.max() == 255
    reds = bands[0][alpha == 255]
    blues = bands[2][alpha == 255]
    assert reds.max() > 150
    assert (reds.astype(int) - blues.astype(int)).max() > 60
    min_x, min_y, max_x, max_y = preview.bounds_4326
    # lon first: a lat/lon swap would miss both windows
    assert -8.2 < min_x < max_x < -8.1
    assert 39.6 < min_y < max_y < 39.7


def test_derive_kmall_preview_requires_fixes(tmp_path):
    # a valid KMALL file whose only datagram carries no position
    path = tmp_path / "startup.kmall"
    path.write_bytes(_kmall_datagram(b"#MRZ", bytes(32)))

    with pytest.raises(ValueError, match="no position fixes"):
        derive_kmall_preview(path)


def test_render_bbox_thumbnail_draws_the_bbox_over_the_base_map(tmp_path):
    basemap = _write_web_mercator_basemap(tmp_path / "basemap.tif")

    image = render_bbox_thumbnail(str(basemap), _THUMBNAIL_BBOX, _BBOX_STYLE)

    driver, width, height, bands = _read_webp(image)
    assert (driver, width, height) == ("WEBP", 512, 384)
    rgb = np.stack(bands[:3]).astype(int)
    fill = np.array(_SEA_RGB) * 0.7 + np.array(_BBOX_RGB) * 0.3
    # lossy WEBP shifts the colours a little
    assert np.abs(rgb[:, 192, 256] - fill).max() <= 10
    assert np.abs(rgb[:, 192, 131] - _BBOX_RGB).max() <= 10
    assert np.abs(rgb[:, 192, 60] - _SEA_RGB).max() <= 10


def test_tms_basemap_xml_requests_the_tiles_of_the_url_template():
    tile = gdal.GetDriverByName("MEM").Create("", 256, 256, 4, gdal.GDT_Byte)
    for band_index, value in enumerate((*_SEA_RGB, 255), start=1):
        tile.GetRasterBand(band_index).Fill(value)
    # zoom 0 is a single tile, the whole base map
    tile_path = "/vsimem/tiles/0/0/0"
    gdal.GetDriverByName("PNG").CreateCopy(tile_path, tile)
    try:
        with gdal.config_option("CPL_CURL_ENABLE_VSIMEM", "YES"):
            image = render_bbox_thumbnail(
                build_tms_basemap_xml("/vsimem/tiles/{z}/{x}/{y}", max_zoom=0),
                _THUMBNAIL_BBOX,
                _BBOX_STYLE,
            )
    finally:
        gdal.Unlink(tile_path)

    _, _, _, bands = _read_webp(image)
    rgb = np.stack(bands[:3]).astype(int)
    assert np.abs(rgb[:, 192, 60] - _SEA_RGB).max() <= 10
