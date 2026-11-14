import logging

from osgeo import (
    gdal,
    osr,
)

logger = logging.getLogger(__name__)

gdal.UseExceptions()


def identify_srs(
    srs: "osr.SpatialReference | None",
) -> tuple[int | None, str | None, str | None]:
    """Best-effort (epsg, crs_name, crs_wkt) for a spatial reference.

    AutoIdentifyEPSG fails on some real archive rasters (e.g. ETRS89/PT-TM06),
    so epsg may stay None while crs_name/crs_wkt are still populated.
    """
    if srs is None:
        return None, None, None
    try:
        srs.AutoIdentifyEPSG()
    except RuntimeError as err:
        logger.debug("AutoIdentifyEPSG failed: %s", err)
    # Only trust the code when the authority is EPSG and the code is numeric:
    # an ESRI code (e.g. ESRI:102629) would be mislabelled as EPSG, and a
    # non-numeric code (e.g. IGNF:LAMB93) would crash int().
    code = srs.GetAuthorityCode(None)
    if srs.GetAuthorityName(None) == "EPSG" and code and code.isdigit():
        epsg = int(code)
    else:
        epsg = None
    return epsg, srs.GetName(), srs.ExportToWkt()


def project_bbox_to_wgs84(
    bbox_native: tuple[float, float, float, float],
    src_srs: "osr.SpatialReference",
) -> tuple[float, float, float, float]:
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    src = src_srs.Clone()
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(src, wgs84)
    minx, miny, maxx, maxy = bbox_native
    corners = [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]
    projected = [transform.TransformPoint(x, y) for x, y in corners]
    lons = [p[0] for p in projected]
    lats = [p[1] for p in projected]
    return (min(lons), min(lats), max(lons), max(lats))
