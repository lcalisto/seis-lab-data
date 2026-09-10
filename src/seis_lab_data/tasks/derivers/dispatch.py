import logging
from pathlib import (
    Path,
    PurePath,
)

from .gdal_raster import derive_raster_preview
from .schemas import DerivedPreview

logger = logging.getLogger(__name__)

# v1 only derives rasters which carry their own CRS. Formats that depend on a
# sidecar (.asc, .flt) or on the mission's implicit CRS (.xyz), as well as
# vectors, KMALL and SEG-Y, come with the later derivers in diferent PR's
_RASTER_EXTENSIONS = frozenset({".tif", ".tiff"})


def can_derive(path: Path | str) -> bool:
    p = Path(path)
    # Because directories such as "F3_2022.tif" exist in the archive
    return p.suffix.lower() in _RASTER_EXTENSIONS and p.is_file()


def is_previewable(
    path: Path | str, relative_path: str, folder_prefixes: frozenset[str]
) -> bool:
    """Whether an archive file is to get a preview.

    Eligibility is a family/stage prefix match on the first two segments of the
    asset's mission-relative path
    """
    family_and_stage = "/".join(PurePath(relative_path).parts[:2])
    return family_and_stage in folder_prefixes and can_derive(path)


def dispatch_deriver(path: Path | str) -> DerivedPreview | None:
    """Route a file to its preview deriver by extension.

    sync and slow: the whole raster is read to build the overview
    Async callers must run this in a worker thread
    Returns None for unsupported extensions and directories.
    """
    p = Path(path)
    if not can_derive(p):
        return None
    return derive_raster_preview(p)
