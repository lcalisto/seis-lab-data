# Supported file formats

This page documents the file formats found in the marine data archive and their support status
in the SeisLabData extraction pipeline.

## GDAL raster formats

These formats are read using GDAL raster drivers. The extractor can retrieve: bounding box,
CRS/EPSG code, band count, pixel resolution, and nodata value.

### GeoTIFF

| Property | Value |
|----------|-------|
| Extension(s) | `.tif`, `.tiff` |
| Media type | `image/tiff` |
| GDAL driver | GTiff |
| Categories | Bathymetry, Backscatter |
| Stages | QC, Processed data, Interpreted data |

Georeferenced raster format with embedded CRS and metadata. Widely supported across GIS tools.
Used as primary file for processed bathymetry/backscatter grids and interpreted products.

### XYZ grid

| Property | Value |
|----------|-------|
| Extension(s) | `.xyz` |
| Media type | `text/plain` |
| GDAL driver | XYZ |
| Categories | Bathymetry, Backscatter |
| Stages | Raw data, QC, Interpreted data |

Plain text point cloud format with X, Y, Z columns. Used as primary file for raw/QC bathymetry
data and as secondary file in some stages. GDAL reads it as a gridded raster dataset. When its
points do not form a regular grid, as with accepted soundings, GDAL rejects it, and discovery
reads 128 windows of 64 KB spread over the file instead, taking the bounding box of the points in
them and estimating the point count. On the files measured, that bounding box fell short of the
exact one by under 1% of its extent.

### ASCII Grid

| Property | Value |
|----------|-------|
| Extension(s) | `.asc` |
| Media type | `text/plain` |
| GDAL driver | AAIGrid |
| Categories | Bathymetry, Backscatter |
| Stages | Interpreted data |

ESRI ASCII raster format. Header defines grid dimensions, cell size, origin, and nodata value,
followed by space-delimited cell values. Used as primary file for interpreted products.

### Float Grid

| Property | Value |
|----------|-------|
| Extension(s) | `.flt` + `.hdr` |
| Media type | `application/octet-stream` |
| GDAL driver | EHdr |
| Categories | Bathymetry, Backscatter |
| Stages | Processed data, Interpreted data |

Binary raster format storing 32-bit IEEE floating-point values in row-major order. Requires a
companion `.hdr` header file containing grid metadata (ncols, nrows, cellsize, nodata_value,
byteorder). Used as secondary file for processed data and as primary/secondary for interpreted
products.

### NetCDF

| Property | Value |
|----------|-------|
| Extension(s) | `.nc`, `.nc4` |
| Media type | `application/x-netcdf` |
| GDAL driver | netCDF |
| Categories | Bathymetry, Backscatter |
| Stages | Processed data, Interpreted data |

Network Common Data Form, a self-describing binary format widely used for oceanographic,
atmospheric, and climate data. GDAL can read NetCDF files as raster datasets, but only when
they follow the CF (Climate and Forecast) conventions with properly defined coordinate
variables, dimensions, and grid mapping attributes. Unstructured NetCDF files or files that
do not follow the CF standard structure cannot be read by GDAL.

### CSV

| Property | Value |
|----------|-------|
| Extension(s) | `.csv` |
| Media type | `text/csv` |
| GDAL driver | CSV |
| Categories | Bathymetry, Backscatter |
| Stages | Raw data, QC, Interpreted data |

Comma-separated or delimited text file containing point data (X, Y, Z or lon, lat, value).
Similar to XYZ but with header row and flexible column naming. OGR reads it as a point vector
dataset; can also be treated as raster via VRT.


## OGR vector formats

These formats are read using OGR vector drivers. The extractor can retrieve: bounding box,
CRS/EPSG code, feature count, and geometry type.

### Shapefile

| Property | Value |
|----------|-------|
| Extension(s) | `.shp` + `.shx` + `.dbf` |
| Media type | `application/x-shapefile` |
| OGR driver | ESRI Shapefile |
| Categories | Bathymetry |
| Stages | Raw data, QC, Processed data, Interpreted data |

ESRI vector format storing point, line, or polygon geometries with attribute data. Companion
files `.shx` (index) and `.dbf` (attributes) are required. Used as secondary file across all
workflow stages.

Shapefiles are downloaded as a zip archive holding the `.shp` file together with all of its
companion files (every file in the same directory that shares its name, such as `.shx`, `.dbf`,
`.prj`, `.cpg` or `.shp.xml`).

### CSV

| Property | Value |
|----------|-------|
| Extension(s) | `.csv` |
| Media type | `text/csv` |
| OGR driver | CSV |
| Categories | Bathymetry, Backscatter |
| Stages | Raw data, QC, Interpreted data |

Comma-separated or delimited text file containing point data with coordinate columns
(X/Y, lon/lat). OGR reads it as a point vector dataset when columns with coordinates are
identified. Also listed under GDAL raster formats as it can be treated as a gridded raster
via VRT.

### File Geodatabase

| Property | Value |
|----------|-------|
| Extension(s) | `.gdb` (directory) |
| Media type | `application/x-filegdb` |
| OGR driver | OpenFileGDB |
| Categories | Bathymetry, Backscatter |
| Stages | Raw data, QC, Processed data, Interpreted data |

ESRI File Geodatabase, a directory containing multiple database files that store vector and
raster datasets. Used as secondary file for raw/QC/processed data and as primary/secondary for
interpreted products. Read-only access via the OpenFileGDB driver (no ESRI license required).

### GeoJSON

| Property | Value |
|----------|-------|
| Extension(s) | `.geojson`, `.json` |
| Media type | `application/geo+json` |
| OGR driver | GeoJSON |
| Categories | Bathymetry, Backscatter |
| Stages | Processed data, Interpreted data |

Open standard format for encoding geographic data structures using JSON. Supports point, line,
polygon, and multi-geometry types with associated properties. Always uses WGS 84 (EPSG:4326)
as its coordinate reference system.

### GeoPackage

| Property | Value |
|----------|-------|
| Extension(s) | `.gpkg` |
| Media type | `application/geopackage+sqlite3` |
| OGR driver | GPKG |
| Categories | Bathymetry, Backscatter |
| Stages | Processed data, Interpreted data |

OGC open standard based on SQLite. Can store both vector and raster data in a single file.
Supports multiple layers, spatial indexes, and arbitrary CRS. Modern alternative to Shapefile
and File Geodatabase.

### KML/KMZ

| Property | Value |
|----------|-------|
| Extension(s) | `.kml`, `.kmz` |
| Media type | `application/vnd.google-earth.kml+xml` |
| OGR driver | KML / LIBKML |
| Categories | Bathymetry, Backscatter |
| Stages | Interpreted data |

Google Earth markup format for geographic visualization. KML is XML-based; KMZ is a compressed
(ZIP) archive containing a KML file and optional resources. Supports point, line, and polygon
geometries. Always uses WGS 84 (EPSG:4326). OGR can read both KML and KMZ via the KML or
LIBKML drivers.


## Specialized formats (future)

These formats require dedicated extractors that are not yet implemented. They will be added in
future iterations.

### CSAR

| Property | Value |
|----------|-------|
| Extension(s) | `.csar` |
| Media type | `application/octet-stream` |
| Categories | Bathymetry, Backscatter |
| Stages | Processed data |

CARIS Spatial Archive file. Proprietary raster format for gridded bathymetry and elevation data.
Used as primary file for processed data. Requires CARIS software/license for full access.

### KMALL

| Property | Value |
|----------|-------|
| Extension(s) | `.kmall` |
| Categories | Bathymetry, Backscatter |
| Stages | Raw data |

Binary datagram-based format from Kongsberg multibeam echosounder systems. Contains position
data (latitude, longitude, timestamp), depth measurements, and quality indicators. The `#SPO`
datagram provides position data; `#MRZ` provides depth/reflectivity.

A Python reader module is available on GitHub for parsing datagrams.

Discovery does not read KMALL files whole: it takes the bounding box and the temporal extent from
16 windows of 256 KB, at both ends of the file and evenly spaced in between. Both ends of a survey
line are always read, while the extremes of a curved track can be missed by the distance covered
between two windows.

### SEG-Y

| Property | Value |
|----------|-------|
| Extension(s) | `.segy`, `.sgy` |
| Categories | Seismic |
| Stages | Raw data |

Standard seismic data exchange format (SEG-Y Revision 2.0). Structure:

- Text File Header (3200 bytes)
- Binary Header (400 bytes)
- Extended Text Header (optional)
- Traces (individual seismic traces with 240-byte trace headers)

Python libraries: **segyio** (actively maintained, by Equinor) and **segpy**.

### JSF

| Property | Value |
|----------|-------|
| Extension(s) | `.jsf` |
| Categories | Seismic |
| Stages | Raw data |

EdgeTech sonar data format. Binary format with defined header structure (JSFDefs.h).
Used for sub-bottom profiler (SBP) raw data.

### P1/11

| Property | Value |
|----------|-------|
| Extension(s) | `.p111` |
| Categories | Geophysical position data |
| Stages | Raw data |

Geophysical position data exchange format. Can be imported using the SeisPos_Import QGIS plugin.


## Other formats

### HIPS Project

| Property | Value |
|----------|-------|
| Extension(s) | Directory (proprietary structure) |
| Categories | Bathymetry |
| Stages | Processed data |

CARIS HIPS and SIPS project directory. Proprietary format containing processed multibeam data.
No automated extraction is planned, treated as an opaque directory.

### XLS

| Property | Value |
|----------|-------|
| Extension(s) | `.xls`, `.xlsx` |
| Media type | `application/vnd.ms-excel` |
| Categories | Bathymetry |
| Stages | Raw data, QC, Processed data |

Spreadsheet/tabular data. Used as secondary file for metadata or ancillary information.
No GDAL/OGR support — would require a dedicated reader if extraction is needed.
