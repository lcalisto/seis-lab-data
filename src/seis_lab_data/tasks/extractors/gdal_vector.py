import logging
from pathlib import Path

from osgeo import (
    gdal,
    ogr,
)
from . import common
from .schemas import VectorMetadata

logger = logging.getLogger(__name__)

gdal.UseExceptions()


def extract_vector_metadata(path: Path | str) -> VectorMetadata:
    ds = gdal.OpenEx(str(path), gdal.OF_VECTOR | gdal.OF_READONLY)
    try:
        driver = ds.GetDriver().ShortName
        layer_count = ds.GetLayerCount()

        feature_count = 0
        geometry_names: set[str] = set()
        native_boxes: list[tuple[float, float, float, float]] = []
        native_srs_names: set[str | None] = set()
        boxes_4326: list[tuple[float, float, float, float]] = []
        epsg = crs_name = crs_wkt = None
        srs_captured = False

        for layer_index in range(layer_count):
            lyr = ds.GetLayer(layer_index)
            count = max(lyr.GetFeatureCount(), 0)
            feature_count += count
            geometry_names.add(ogr.GeometryTypeToName(lyr.GetGeomType()))

            if count == 0:
                continue
            try:
                # OGR GetExtent returns (minx, maxx, miny, maxy); reorder it.
                minx, maxx, miny, maxy = lyr.GetExtent(force=1)
            except RuntimeError:
                continue
            # Capture the CRS from an extent-bearing layer so the reported CRS
            # matches bbox_native's CRS (a 0-feature first layer must not set it).
            srs = lyr.GetSpatialRef()
            if not srs_captured and srs is not None:
                epsg, crs_name, crs_wkt = common.identify_srs(srs)
                srs_captured = True
            native_boxes.append((minx, miny, maxx, maxy))
            native_srs_names.add(srs.GetName() if srs is not None else None)
            if srs is not None:
                boxes_4326.append(
                    common.project_bbox_to_wgs84((minx, miny, maxx, maxy), srs)
                )

        # Native bbox only makes sense when the extent-bearing layers share one CRS.
        bbox_native = _union(native_boxes) if len(native_srs_names) <= 1 else None
        geometry_type = (
            next(iter(geometry_names)) if len(geometry_names) == 1 else "mixed"
        )

        return VectorMetadata(
            driver=driver,
            epsg=epsg,
            crs_name=crs_name,
            crs_wkt=crs_wkt,
            bbox_native=bbox_native,
            bbox_4326=_union(boxes_4326),
            layer_count=layer_count,
            feature_count=feature_count,
            geometry_type=geometry_type,
        )
    finally:
        ds = None  # noqa: F841


def _union(
    boxes: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float] | None:
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )
