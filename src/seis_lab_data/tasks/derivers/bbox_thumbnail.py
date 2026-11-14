import logging
from xml.sax.saxutils import escape

import numpy as np
import pydantic
from osgeo import (
    gdal,
    osr,
)
from . import common

logger = logging.getLogger(__name__)

gdal.UseExceptions()

_WEB_MERCATOR_HALF_SIDE = 20037508.342789244
# latitudes beyond this one have no web mercator projection
_WEB_MERCATOR_MAX_LATITUDE = 85.0511
# added around the bbox, as a fraction of its larger side, to show its surroundings
_PADDING_FRACTION = 0.1
# 4:3, the aspect of the 160x120 list card slot which shows the thumbnail
_THUMBNAIL_WIDTH = 512
_THUMBNAIL_HEIGHT = 384


class BboxStyle(pydantic.BaseModel):
    """How the bbox is drawn, the same as on the web maps."""

    fill_color: str  # hex, e.g. "#c27d0e"
    fill_opacity: float
    outline_color: str
    outline_opacity: float
    outline_width: int  # pixels


def build_tms_basemap_xml(tile_url_template: str, max_zoom: int) -> str:
    """Describe a TMS base map as an XML source for GDAL's WMS driver.

    The template uses the same {z}/{x}/{y} placeholders as the web maps.
    """
    # GDAL wants ${z}/${x}/${y}, which docker compose would interpolate in the setting
    server_url = escape(
        tile_url_template.replace("{z}", "${z}")
        .replace("{x}", "${x}")
        .replace("{y}", "${y}")
    )
    # YOrigin top: martin serves XYZ tiles, which are numbered from the top
    # BandsCount 4: the tiles are RGBA, with fewer bands areas without tiles turn black
    # Timeout 20: the 300 s default outlasts the task, a GDAL thread cannot be cancelled
    return f"""<GDAL_WMS>
    <Service name="TMS">
        <ServerUrl>{server_url}</ServerUrl>
    </Service>
    <DataWindow>
        <UpperLeftX>{-_WEB_MERCATOR_HALF_SIDE}</UpperLeftX>
        <UpperLeftY>{_WEB_MERCATOR_HALF_SIDE}</UpperLeftY>
        <LowerRightX>{_WEB_MERCATOR_HALF_SIDE}</LowerRightX>
        <LowerRightY>{-_WEB_MERCATOR_HALF_SIDE}</LowerRightY>
        <TileLevel>{max_zoom}</TileLevel>
        <TileCountX>1</TileCountX>
        <TileCountY>1</TileCountY>
        <YOrigin>top</YOrigin>
    </DataWindow>
    <Projection>EPSG:3857</Projection>
    <BlockSizeX>256</BlockSizeX>
    <BlockSizeY>256</BlockSizeY>
    <BandsCount>4</BandsCount>
    <Timeout>20</Timeout>
</GDAL_WMS>"""


def render_bbox_thumbnail(
    basemap_source: str,
    bbox_4326: tuple[float, float, float, float],
    style: BboxStyle,
) -> bytes:
    """Render a bbox as a rectangle over the base map, as a small WEBP image.

    The base map is any RGBA source which GDAL opens in EPSG:3857.
    In production it is the XML of `build_tms_basemap_xml`.

    Pure sync and slow (the base map tiles are fetched over HTTP), so async
    callers must run this in a worker thread (e.g. anyio.to_thread.run_sync).
    """
    min_x, min_y, max_x, max_y = _to_web_mercator(bbox_4326)
    if max_x <= min_x or max_y <= min_y:
        raise ValueError(f"Bbox {bbox_4326} has no area in web mercator")
    source = gdal.Open(basemap_source, gdal.GA_ReadOnly)
    try:
        rendered = gdal.Translate(
            "",
            source,
            format="MEM",
            projWin=_build_window(min_x, min_y, max_x, max_y),
            width=_THUMBNAIL_WIDTH,
            height=_THUMBNAIL_HEIGHT,
            # small bboxes overscale the deepest tiles, smoothly like the web maps
            resampleAlg="bilinear",
            # a window wholly outside the base map would otherwise render blank
            options=["-eco"],
        )
        image = rendered.ReadAsArray() / 255
        # missing tiles (HTTP 204) come in transparent, all of them means a failure
        if not image[3].any():
            raise RuntimeError(f"Base map rendered an empty image for bbox {bbox_4326}")
        origin_x, pixel_width, _, origin_y, _, pixel_height = rendered.GetGeoTransform()
        left = round((min_x - origin_x) / pixel_width)
        right = round((max_x - origin_x) / pixel_width)
        top = round((max_y - origin_y) / pixel_height)
        bottom = round((min_y - origin_y) / pixel_height)
        fill = np.zeros(image.shape[1:], dtype=bool)
        fill[top:bottom, left:right] = True
        # centred on the edges like the lines of the web maps, the padding keeps it in
        inner_width = style.outline_width // 2
        outer_width = style.outline_width - inner_width
        outline = np.zeros(image.shape[1:], dtype=bool)
        outline[
            top - outer_width : bottom + outer_width,
            left - outer_width : right + outer_width,
        ] = True
        outline[
            top + inner_width : bottom - inner_width,
            left + inner_width : right - inner_width,
        ] = False
        _paint_over(image, fill, style.fill_color, style.fill_opacity)
        _paint_over(image, outline, style.outline_color, style.outline_opacity)
        rendered.WriteArray(np.rint(image * 255).astype(np.uint8))
        return common.to_webp(rendered)
    finally:
        # Clear / close gdal used datasets
        rendered = None  # noqa: F841
        source = None  # noqa: F841


def _to_web_mercator(
    bbox_4326: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = bbox_4326
    min_lat, max_lat = np.clip(
        (min_lat, max_lat), -_WEB_MERCATOR_MAX_LATITUDE, _WEB_MERCATOR_MAX_LATITUDE
    )
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    web_mercator = osr.SpatialReference()
    web_mercator.ImportFromEPSG(3857)
    web_mercator.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(wgs84, web_mercator)
    # meridians and parallels stay straight in web mercator, two corners are enough
    min_x, min_y, _ = transform.TransformPoint(min_lon, min_lat)
    max_x, max_y, _ = transform.TransformPoint(max_lon, max_lat)
    return min_x, min_y, max_x, max_y


def _build_window(
    min_x: float, min_y: float, max_x: float, max_y: float
) -> list[float]:
    """Pad the bbox and grow it to the thumbnail's aspect, keeping it centred.

    Without the fixed aspect a long and thin bbox would render as a strip.
    Returns GDAL's projWin: upper left x and y, then lower right x and y.
    """
    padding = _PADDING_FRACTION * max(max_x - min_x, max_y - min_y)
    width = max_x - min_x + 2 * padding
    height = max_y - min_y + 2 * padding
    aspect = _THUMBNAIL_WIDTH / _THUMBNAIL_HEIGHT
    if width / height < aspect:
        width = height * aspect
    else:
        height = width / aspect
    centre_x = (min_x + max_x) / 2
    centre_y = (min_y + max_y) / 2
    return [
        centre_x - width / 2,
        centre_y + height / 2,
        centre_x + width / 2,
        centre_y - height / 2,
    ]


def _paint_over(
    image: np.ndarray, mask: np.ndarray, color: str, opacity: float
) -> None:
    """Paint a flat colour over the masked pixels of an RGBA image with values in 0-1.

    Porter-Duff "over" on straight alpha, so the bbox shows over transparent pixels too.
    """
    rgb = np.array(tuple(bytes.fromhex(color.removeprefix("#")))) / 255
    base_alpha = image[3, mask]
    alpha = opacity + base_alpha * (1 - opacity)
    blended = rgb[:, None] * opacity + image[:3, mask] * base_alpha * (1 - opacity)
    image[:3, mask] = np.divide(
        blended, alpha, out=np.zeros_like(blended), where=alpha > 0
    )
    image[3, mask] = alpha
