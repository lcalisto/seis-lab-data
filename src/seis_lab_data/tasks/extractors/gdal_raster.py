import logging
from pathlib import Path

from osgeo import (
    gdal,
    osr,
)
from . import common
from .schemas import RasterMetadata

logger = logging.getLogger(__name__)

gdal.UseExceptions()


def extract_raster_metadata(path: Path | str) -> RasterMetadata:
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    try:
        driver = ds.GetDriver().ShortName
        width = ds.RasterXSize
        height = ds.RasterYSize
        band_count = ds.RasterCount

        gt = ds.GetGeoTransform(can_return_null=True)
        if gt is None:
            pixel_size_x = pixel_size_y = None
            bbox_native = None
        else:
            pixel_size_x = gt[1]
            pixel_size_y = gt[5]
            # Transform all four pixel corners so rotated/sheared geotransforms
            # (gt[2] or gt[4] nonzero) get a correct bbox, not just two corners.
            corners_px = [(0, 0), (width, 0), (0, height), (width, height)]
            xs = [gt[0] + px * gt[1] + py * gt[2] for px, py in corners_px]
            ys = [gt[3] + px * gt[4] + py * gt[5] for px, py in corners_px]
            bbox_native = (min(xs), min(ys), max(xs), max(ys))

        wkt = ds.GetProjection()
        src_srs = osr.SpatialReference(wkt) if wkt else None
        epsg, crs_name, crs_wkt = common.identify_srs(src_srs)
        nodata = ds.GetRasterBand(1).GetNoDataValue() if band_count else None
        bbox_4326 = (
            common.project_bbox_to_wgs84(bbox_native, src_srs)
            if bbox_native is not None and src_srs is not None
            else None
        )

        return RasterMetadata(
            driver=driver,
            width=width,
            height=height,
            band_count=band_count,
            epsg=epsg,
            crs_name=crs_name,
            crs_wkt=crs_wkt,
            pixel_size_x=pixel_size_x,
            pixel_size_y=pixel_size_y,
            nodata=nodata,
            bbox_native=bbox_native,
            bbox_4326=bbox_4326,
        )
    finally:
        ds = None  # noqa: F841
