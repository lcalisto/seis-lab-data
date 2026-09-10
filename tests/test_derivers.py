"""Unit tests for the preview derivers package.

Pure functions, no DB: these run by default (no marker). GDAL is required; the
module self-skips where it is unavailable. Everything is exercised against
synthetic files built in-test, so the suite needs no sample-data archive.
"""

import numpy as np
import pytest

pytest.importorskip("osgeo")

from osgeo import gdal, osr  # noqa: E402

from seis_lab_data.tasks.derivers import dispatch  # noqa: E402
from seis_lab_data.tasks.derivers.gdal_raster import (  # noqa: E402
    _percentile_cuts,
    derive_raster_preview,
)

gdal.UseExceptions()

# EPSG:3763 (ETRS89 / Portugal TM06); coordinates near its false origin land in
# central Portugal, so the warped bounds fall in a checkable lon/lat window.
_PT_TM06 = 3763
_NODATA = -9999.0
_PREVIEW_FOLDERS = frozenset(
    {"s04-gis-master-survey/s01-final", "s06-mbes/s05-processed-data"}
)


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


def test_is_previewable_accepts_a_listed_family_and_stage(tmp_path):
    path = tmp_path / "grid.tif"
    path.touch()
    assert dispatch.is_previewable(
        path, "s04-gis-master-survey/s01-final/sub/grid.tif", _PREVIEW_FOLDERS
    )


def test_is_previewable_rejects_an_unlisted_family_and_stage(tmp_path):
    path = tmp_path / "grid.tif"
    path.touch()
    assert not dispatch.is_previewable(
        path, "s06-mbes/s02-raw-data/sub/grid.tif", _PREVIEW_FOLDERS
    )


def test_is_previewable_rejects_an_extension_without_a_deriver(tmp_path):
    path = tmp_path / "grid.xyz"
    path.touch()
    assert not dispatch.is_previewable(
        path, "s06-mbes/s05-processed-data/grid.xyz", _PREVIEW_FOLDERS
    )


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
