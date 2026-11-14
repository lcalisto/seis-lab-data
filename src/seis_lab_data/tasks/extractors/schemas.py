import datetime as dt
import typing

import pydantic

from ... import constants

# The natural-language words that go into describe(), per language. Keys are
# identical across languages (a parity test enforces it). Counts keep the
# literal "(s)" convention in both languages rather than resolving plurals.
# Technical identifiers stay in English on purpose and are NOT here: driver
# names, geometry types, sample-format codes, "CRS", "nodata", "px", "EM <id>",
# "Kongsberg KMALL" and "SEG-Y".
_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "auto_extracted": "Auto-extracted",
        "raster_kind": "{driver} raster",
        "vector_kind": "{driver} vector",
        "bands": "band(s)",
        "pixel_size": "pixel size",
        "layers": "layer(s)",
        "features": "feature(s)",
        "geometry": "geometry",
        "unknown_sounder": "unknown sounder",
        "of_data": "of data",
        "point_cloud_kind": "{driver} point cloud",
        "points": "point(s)",
        "about": "about",
        "traces": "trace(s)",
        "samples_per_trace": "sample(s) per trace",
        "sample_interval": "sample interval {value} (raw)",
        "coordinates_in": "coordinates in",
        "partly_unreliable": "Coordinate sampling was partly unreliable.",
        "crs_unknown": "unknown",
        "crs_from_mission": "from the survey mission",
        "native_bbox": "Native bbox",
    },
    "pt": {
        "auto_extracted": "Extração automática",
        "raster_kind": "raster {driver}",
        "vector_kind": "vetor {driver}",
        "bands": "banda(s)",
        "pixel_size": "tamanho do pixel",
        "layers": "camada(s)",
        "features": "elemento(s)",
        "geometry": "geometria",
        "unknown_sounder": "sonda desconhecida",
        "of_data": "de dados",
        "point_cloud_kind": "nuvem de pontos {driver}",
        "points": "ponto(s)",
        "about": "cerca de",
        "traces": "traço(s)",
        "samples_per_trace": "amostra(s) por traço",
        "sample_interval": "intervalo de amostragem {value} (bruto)",
        "coordinates_in": "coordenadas em",
        "partly_unreliable": ("A amostragem de coordenadas foi parcial, pouco fiável."),
        "crs_unknown": "desconhecido",
        "crs_from_mission": "da missão",
        "native_bbox": "Extensão nativa",
    },
}

# the beginnings of the summaries produced by describe(), in every language
EXTRACTED_SUMMARY_PREFIXES: typing.Final[tuple[str, ...]] = tuple(
    f"{words['auto_extracted']}: " for words in _WORDS.values()
)

# The closed set of SEG-Y coordinate-unit labels that translate; "dms" and the
# dynamic "code N" fallback pass through unchanged. A test pins that every
# segy._UNITS_LABELS value except "dms" has an entry here.
_UNITS_PT = {
    "unset": "unidades desconhecidas",
    "metres": "metros",
    "arc-seconds": "segundos de arco",
    "degrees": "graus",
}


def _format_crs(
    epsg: int | None, crs_name: str | None, crs_from_mission: bool, language: str
) -> str:
    if crs_name and epsg is not None:
        if crs_from_mission:
            marker = _WORDS[language]["crs_from_mission"]
            return f"{crs_name} (EPSG:{epsg}, {marker})"
        return f"{crs_name} (EPSG:{epsg})"
    if epsg is not None:
        return f"EPSG:{epsg}"
    if crs_name:
        return crs_name
    return _WORDS[language]["crs_unknown"]


def _native_bbox_clause(
    bbox: tuple[float, float, float, float] | None, language: str
) -> str:
    if bbox is None:
        return ""
    minx, miny, maxx, maxy = bbox
    label = _WORDS[language]["native_bbox"]
    return f" {label}: {minx:.8g}, {miny:.8g}, {maxx:.8g}, {maxy:.8g}."


class ExtractedMetadata(pydantic.BaseModel):
    driver: str | None = None
    epsg: int | None = None
    crs_name: str | None = None
    crs_wkt: str | None = None
    # set by discovery when the survey mission's implicit CRS placed the file
    crs_from_mission: bool = False
    bbox_native: tuple[float, float, float, float] | None = None
    bbox_4326: tuple[float, float, float, float] | None = None
    temporal_extent_begin: dt.date | None = None
    temporal_extent_end: dt.date | None = None

    @property
    def bbox_native_needing_crs(self) -> tuple[float, float, float, float] | None:
        """Native bbox that can only be mapped if someone declares its CRS.

        Formats like SEG-Y and XYZ have nowhere to record a CRS, so the extractor
        reports coordinates but no bbox_4326. Whoever knows the CRS can project
        this bbox; the file itself never tells us.
        """
        declares_own_crs = self.epsg is not None or self.crs_wkt is not None
        if self.bbox_4326 is None and not declares_own_crs:
            return self.bbox_native
        return None

    def describe(self, language: typing.Literal["en", "pt"] = "en") -> str:
        raise NotImplementedError


class RasterMetadata(ExtractedMetadata):
    width: int
    height: int
    band_count: int
    pixel_size_x: float | None = None
    pixel_size_y: float | None = None
    nodata: float | None = None

    def describe(self, language: typing.Literal["en", "pt"] = "en") -> str:
        words = _WORDS[language]
        summary = (
            f"{words['auto_extracted']}: "
            f"{words['raster_kind'].format(driver=self.driver)}, "
            f"{self.width} x {self.height} px, {self.band_count} {words['bands']}"
        )
        if self.pixel_size_x is not None and self.pixel_size_y is not None:
            summary += (
                f", {words['pixel_size']} "
                f"{abs(self.pixel_size_x):g} x {abs(self.pixel_size_y):g}"
            )
        if self.nodata is not None:
            summary += f", nodata {self.nodata:g}"
        crs = _format_crs(self.epsg, self.crs_name, self.crs_from_mission, language)
        summary += f". CRS: {crs}."
        summary += _native_bbox_clause(self.bbox_native, language)
        return summary[: constants.DESCRIPTION_MAX_LENGTH]


class VectorMetadata(ExtractedMetadata):
    layer_count: int
    feature_count: int
    geometry_type: str

    def describe(self, language: typing.Literal["en", "pt"] = "en") -> str:
        words = _WORDS[language]
        crs = _format_crs(self.epsg, self.crs_name, self.crs_from_mission, language)
        summary = (
            f"{words['auto_extracted']}: "
            f"{words['vector_kind'].format(driver=self.driver)}, "
            f"{self.layer_count} {words['layers']}, "
            f"{self.feature_count} {words['features']}, "
            f"{words['geometry']}: {self.geometry_type}. "
            f"CRS: {crs}."
        )
        summary += _native_bbox_clause(self.bbox_native, language)
        return summary[: constants.DESCRIPTION_MAX_LENGTH]


class PointCloudMetadata(ExtractedMetadata):
    point_count: int
    # estimated from the rows of a sampled read rather than counted
    point_count_estimated: bool = False

    def describe(self, language: typing.Literal["en", "pt"] = "en") -> str:
        words = _WORDS[language]
        crs = _format_crs(self.epsg, self.crs_name, self.crs_from_mission, language)
        summary = (
            f"{words['auto_extracted']}: "
            f"{words['point_cloud_kind'].format(driver=self.driver)}, "
            + (f"{words['about']} " if self.point_count_estimated else "")
            + f"{self.point_count} {words['points']}. "
            f"CRS: {crs}."
        )
        summary += _native_bbox_clause(self.bbox_native, language)
        return summary[: constants.DESCRIPTION_MAX_LENGTH]


class KmallMetadata(ExtractedMetadata):
    echo_sounder_id: int | None = None
    # from the earliest to the latest datagram timestamp read
    duration_seconds: float | None = None

    def describe(self, language: typing.Literal["en", "pt"] = "en") -> str:
        words = _WORDS[language]
        sounder = (
            f"EM {self.echo_sounder_id}"
            if self.echo_sounder_id
            else words["unknown_sounder"]
        )
        crs = _format_crs(self.epsg, self.crs_name, self.crs_from_mission, language)
        summary = (
            f"{words['auto_extracted']}: Kongsberg KMALL, {sounder}"
            + (
                f", {round(self.duration_seconds / 60)} min {words['of_data']}"
                if self.duration_seconds is not None
                else ""
            )
            + f". CRS: {crs}."
        )
        summary += _native_bbox_clause(self.bbox_native, language)
        return summary[: constants.DESCRIPTION_MAX_LENGTH]


class SegyMetadata(ExtractedMetadata):
    trace_count: int | None = None
    samples_per_trace: int | None = None
    # the raw header value, deliberately unitless: time files store microseconds
    # here but depth-domain files store a length (50 == 0.05 m) and rev0/1 has
    # no flag to tell them apart
    sample_interval: int | None = None
    sample_format: str | None = None
    coordinate_units: str | None = None
    coverage: str = "full"
    # codes quoted in the free-text header; discovery decides whether one applies
    header_epsg_codes: tuple[int, ...] = ()

    def describe(self, language: typing.Literal["en", "pt"] = "en") -> str:
        words = _WORDS[language]
        summary = f"{words['auto_extracted']}: SEG-Y"
        if self.trace_count is not None:
            summary += f", {self.trace_count} {words['traces']}"
        if self.samples_per_trace is not None:
            summary += f", {self.samples_per_trace} {words['samples_per_trace']}"
        if self.sample_interval is not None:
            summary += (
                f", {words['sample_interval'].format(value=self.sample_interval)}"
            )
        if self.sample_format is not None:
            summary += f", {self.sample_format}"
        if self.coordinate_units is not None:
            units = self.coordinate_units
            if language == "pt":
                units = _UNITS_PT.get(units, units)
            summary += f", {words['coordinates_in']} {units}"
        crs = _format_crs(self.epsg, self.crs_name, self.crs_from_mission, language)
        summary += f". CRS: {crs}."
        summary += _native_bbox_clause(self.bbox_native, language)
        if self.coverage == "partial":
            summary += f" {words['partly_unreliable']}"
        return summary[: constants.DESCRIPTION_MAX_LENGTH]


ExtractionResult = (
    RasterMetadata | PointCloudMetadata | VectorMetadata | KmallMetadata | SegyMetadata
)
