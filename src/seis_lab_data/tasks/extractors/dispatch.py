import logging
from pathlib import Path

from .gdal_raster import extract_raster_metadata
from .gdal_vector import extract_vector_metadata
from .kmall import extract_kmall_metadata
from .schemas import ExtractionResult
from .segy import extract_segy_metadata
from .xyz import extract_xyz_points_metadata

logger = logging.getLogger(__name__)

_RASTER_EXTENSIONS = frozenset(
    {".tif", ".tiff", ".asc", ".flt", ".grd", ".xyz", ".nc", ".nc4"}
)
# .nc/.nc4 are kept for gridded NetCDF (served by the plain GDAL raster path); the
# ubuntu-small image has no netCDF driver yet, so extraction fails best-effort until the
# base image moves to gdal:ubuntu-full. Production has 0 .nc files today.

# Sidecars (.shx/.dbf/.prj/.cpg/.qmd/.sbn/.sbx ...) are deliberately absent so they never
# trigger extraction; GDAL reads them implicitly when opening the primary file. .kmz is
# excluded (needs LIBKML, absent from the image); .gdb (a directory) and S-57 .000 too.
_VECTOR_EXTENSIONS = frozenset({".shp", ".gpkg", ".geojson", ".kml", ".dxf"})

_KMALL_EXTENSIONS = frozenset({".kmall"})

# No big-file log for SEG-Y: header sampling reads ~100 trace headers no matter
# the file size, so even a 200 GB file costs a constant number of reads.
_SEGY_EXTENSIONS = frozenset({".sgy", ".segy"})

_SUPPORTED_EXTENSIONS = (
    _RASTER_EXTENSIONS | _VECTOR_EXTENSIONS | _KMALL_EXTENSIONS | _SEGY_EXTENSIONS
)

_BIG_FILE_LOG_BYTES = 1024**3  # log-only threshold; no hard size limit


def dispatch_extractor(path: Path | str) -> ExtractionResult | None:
    """Route a file to its metadata extractor by extension.

    Pure sync and potentially slow, so async callers run it in a worker thread or
    process: GDAL's XYZ driver scans a whole gridded file on open, so a multi-GB
    XYZ grid takes about a minute. An XYZ point cloud, which the driver rejects for
    not being a grid, goes to `extract_xyz_points_metadata`. Point clouds, KMALL
    and SEG-Y files are sampled, in a constant number of reads whatever their
    size. Returns None for unsupported extensions and directories, the
    extension being checked first, as checking a path for a file costs a round
    trip to network storage.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix not in _SUPPORTED_EXTENSIONS:
        return None
    if not p.is_file():
        # A real directory named "F3_2022.tif" exists in the archive.
        return None
    if suffix in _RASTER_EXTENSIONS:
        size = p.stat().st_size
        if size > _BIG_FILE_LOG_BYTES:
            logger.info("Extracting metadata from large raster %s (%d bytes)", p, size)
        try:
            return extract_raster_metadata(p)
        except RuntimeError:
            if suffix != ".xyz":
                raise
            # the XYZ driver only reads grids, soundings do not form one
            return extract_xyz_points_metadata(p)
    if suffix in _VECTOR_EXTENSIONS:
        return extract_vector_metadata(p)
    if suffix in _KMALL_EXTENSIONS:
        return extract_kmall_metadata(p)
    return extract_segy_metadata(p)
