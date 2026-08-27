# pyogrio

[`pyogrio`](https://pyogrio.readthedocs.io/) reads and writes **vector** geospatial data —
points, lines and polygons carrying attributes — through [GDAL](https://gdal.org/)'s OGR
layer, a whole layer at a time into numpy arrays rather than a feature at a time. It is one of
the two engines
[`geopandas`](https://geopandas.org/en/stable/docs/user_guide/io.html#reading-spatial-data)
hands `read_file`'s arguments to. On a phone it lets an app hold, edit and exchange real
vector data with no server and no database, in-process, on files in app storage.

## Install

Add pyogrio to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "pyogrio",
]
```

Both platforms read and write, and this is a deliberately small GDAL behind them: six vector
drivers, no `proj.db`, no GDAL data directory. **Formats** and **Coordinate systems** below
say what that rules out — GeoPackage is not one of the six, and a CRS has to be spelled as a
proj-string rather than `EPSG:4326`.

The one number to check against an app's budget first is the iOS size. Every iOS extension
links its own static copy of GDAL, so a slice is 28–31 MB compressed and 78–84 MB unpacked,
against 0.6 MB and 1.9 MB for an Android wheel; **App size** puts that beside Android's
shared native chain, which is the comparison that actually decides it.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`vector-io`](examples/vector-io) — a point layer with four attributes and a CRS written to
  app storage as GeoJSON or a Shapefile and read straight back, compared value by value.

## Usage in a Flet app

Reading and writing are two calls, and numpy is the whole interface:

```python
import numpy as np
from pyogrio.raw import read, write

# geometry is one WKB byte string per feature; attributes are one array per column
write(path, geometry, [names, counts], np.array(["station_name", "reading_count"]),
      driver="GeoJSON", geometry_type="Point", crs="+proj=longlat +datum=WGS84 +no_defs")

meta, _fids, geometry, columns = read(path)
```

`meta` carries the field names, dtypes, geometry type and CRS that came back — which is not
always what went in. These two are the layer
[`read_dataframe`](https://pyogrio.readthedocs.io/en/latest/api.html#pyogrio.read_dataframe)
and [`write_dataframe`](https://pyogrio.readthedocs.io/en/latest/api.html#pyogrio.write_dataframe)
are built on, and those need geopandas, which this recipe has not validated on device.
[`read_info`](https://pyogrio.readthedocs.io/en/latest/api.html#pyogrio.read_info) reports a
layer's schema, feature count and bounds without reading it.

### Storage

Datasets belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
which is app-private and durable. It has to be a **writable** directory — OGR creates the
dataset in place — so a layer bundled as an [asset](https://flet.dev/docs/cookbook/assets)
must be copied out before it can be written to.

**Give each dataset a directory of its own**, because a Shapefile is not one file: writing a
point layer with a CRS produced `stations.shp`, `stations.shx`, `stations.dbf`, `stations.cpg`
and `stations.prj`, and without a CRS the `.prj` is not written. Copy, move and delete them as
a unit:

```python
directory = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "stations")
os.makedirs(directory, exist_ok=True)
write(os.path.join(directory, "stations.shp"), ...)
```

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for layers that can be regenerated and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for intermediates. Writing to a path that already holds a layer replaces it.

### Threading

**Each call opens its own dataset and closes it again**, so no application-wide lock is
needed: on a desktop, eight threads reading one 5,000-feature Shapefile five times each came
back right on 40 of 40 iterations, and eight threads writing GeoJSON to eight separate paths
all succeeded. Two threads writing the *same* path is still your bug to avoid.

What you do not get is parallelism: `_io.pyx` contains no `nogil` block, so a read holds the
GIL for nearly all of its native work — while a 200,000-feature Shapefile read was in flight
on a desktop, a counting thread beside it kept under 15% of its solo throughput. Use
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) anyway so
the event handler returns, catch exceptions inside the worker, and finish with the explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
needs.

### Formats

Six vector drivers are registered. Three of them write files: **GeoJSON**, **ESRI Shapefile**
and **GeoJSONSeq**, which writes the same features one JSON object per line. **ESRIJSON** and
**TopoJSON** are read-only. **MEM** also reports `rw` in `list_drivers()`, but it is a
scratch dataset in RAM, not something you can hand to another app. Asking for anything else
gives `DataSourceError: Could not obtain driver: GPKG (check that it was installed correctly
into GDAL)` — a name, not a missing file.

GeoJSON and the Shapefile keep different things, and neither says so loudly. Writing the
same four columns through each, on a desktop:

| | GeoJSON | ESRI Shapefile |
| --- | --- | --- |
| field names | kept | truncated to 10 characters |
| 64-bit integers | narrowed to `int32` when the values fit | kept as `int64` |
| strings | kept | truncated at 254 characters |
| datetimes | returned as `datetime64[ms]` | returned as strings |
| coordinates | worst residual 8.9e-16 | exactly 0 |

The Shapefile announces every one of its losses as a `RuntimeWarning` — `Normalized/laundered
field name: 'station_name' to 'station_na'`, `Value '...' of field longtext has been truncated
to 254 characters`, `Field when created as String field, though DateTime requested`. GeoJSON's
integer narrowing is the one that arrives silently. Keep field names to ten characters if a
Shapefile is anywhere in the app's future, and read `meta["fields"]` and `meta["dtypes"]` back
rather than trusting what you passed in.

### Coordinate systems

**Write a CRS as a PROJ string or WKT, not as an EPSG code.** Resolving `"EPSG:4326"` means
looking the code up in `proj.db`, and no such database reaches the device: neither the pyogrio
wheels nor the `flet-libgdal` and `flet-libproj` wheels behind them carry one, on either
platform, and the diagnostic `Cannot find proj.db` is compiled into Android's `libproj.so` and
into every iOS extension that carries GDAL. Writing with `crs="EPSG:4326"` raises
`pyogrio.errors.CRSError: Could not set CRS: EPSG:4326`, while
`"+proj=longlat +datum=WGS84 +no_defs"` needs no lookup and works. Everything in this section
was reproduced on a desktop by pointing `PROJ_DATA` at a directory holding an unusable
`proj.db`, which is the condition the device is in.

What you give up is naming, not storing: a Shapefile written that way reads back as an unnamed
`GEOGCS[...]`. GeoJSON reads back as `EPSG:4326` — that format is defined in WGS84, and the
WKT compiled into GDAL for it carries `AUTHORITY["EPSG","4326"]`, so no lookup is needed to
report it.

**It reports `EPSG:4326` for a layer that is not in it, too.** A WKT carrying
`AUTHORITY["EPSG","32630"]` does reach the file, as `"crs": { … "urn:ogc:def:crs:EPSG::32630"
}` — but reading it back is a code lookup, so with no database `meta["crs"]` is `EPSG:4326`
and nothing warns; the same file on a desktop reports `EPSG:32630`. A Shapefile has no such
problem, because the `.prj` holds the WKT itself: that CRS came back as
`PROJCS["WGS_84_UTM_zone_30N", …]` with no database anywhere. For anything but WGS84, write
the Shapefile.

And nothing here reprojects: **the driver writes the coordinates you hand it under whatever
CRS you name.** UTM easting and northing written to GeoJSON with a UTM CRS came back
unchanged and tagged `EPSG:4326` on a desktop GDAL 3.11.4, silently. Transform before writing.

### App size

On Android the wheels are approximately 0.60–0.64 MB compressed and 1.7–2.0 MB unpacked, but
the shared GDAL chain behind them adds about 21.5 MB of libraries per ABI — on arm64-v8a,
`libgdal.so` at 14.0 MB and `libproj.so` at 4.6 MB, then libturbojpeg, libtiff, libcurl,
libjpeg and libpsl. Use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI.

iOS has no shared GDAL to amortise, so the chain is inside the wheels: 27.8–30.6 MB
compressed and 78.3–83.7 MB unpacked per slice, measured on build 2. Compare *totals* rather
than wheels — an Android ABI costs about 1.9 MB of wheel plus 21.5 MB of shared libraries,
so iOS is roughly three times an ABI, not forty times. An `ipa` carries one slice, and
nothing else in the chain ships alongside it.

Just over half of each unpacked Android wheel — 1,008,031 bytes on every architecture — is
`pyogrio/tests` and its fixtures, which your app never imports. Flet's default
[cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) strips headers and static
archives, not test suites, so name it:

```toml
[tool.flet.cleanup]
package_files = ["pyogrio/tests"]
```

### Other considerations

A desktop `flet run` uses PyPI's own wheel, and it is a different GDAL: for 0.12.1 on macOS
arm64 it bundles GDAL 3.11.4 with 64 vector drivers and a PROJ database, against 3.13.1 and a
handful of drivers on device. GeoPackage, FlatGeobuf, EPSG codes and every CRS a file names
by authority resolve there and do not on the phone, so validate format and CRS choices on a
device or emulator.

## Things to know

- **`import pyogrio` warns about missing data files, and it is expected.** The wheels ship no
  GDAL data directory, so the import raises `RuntimeWarning: Could not detect GDAL data files.
  Set GDAL_DATA environment variable to the correct path.` and GDAL logs `Cannot find
  header.dxf (GDAL_DATA is not defined)` — both reproduced on a desktop by deleting the bundled
  directory, after which GeoJSON and Shapefile round trips still came back with zero wrong
  values. A second probe calls `OSRImportFromEPSG(4326)`, and with no usable `proj.db` it
  fails too, adding `RuntimeWarning: Could not detect PROJ data files. Set PROJ_LIB
  environment variable to the correct path.` — that probe is the very lookup the CRS advice
  above is about, so the pair of warnings is the whole CRS story arriving at import time.

- **`pyogrio.raw.read` and `pyogrio.raw.write` are not in the upstream API reference.** They
  are what `read_dataframe` and `write_dataframe` call, and the only route that needs nothing
  beyond numpy, which is why the example uses them. The documented dataframe API is the stable
  one; treat a version bump as a reason to re-check these two signatures.

- **Geometry crosses the boundary as WKB.** `write` wants an object array of
  [WKB](https://libgeos.org/specifications/wkb/) byte strings and `read` returns one, so
  either encode it yourself — 21 bytes for a 2-D point — or bring
  [`shapely`](../shapely), whose `to_wkb`/`from_wkb` cover every geometry type.

## Build notes (maintainers)

### Recipe shape

This is a consumer of the `flet-libgdal` chain, and the platform difference in that chain
drives both patches: Android gets one shared `libgdal.so` that all five extensions resolve
against, while iOS links `libgdal.a` into each extension separately. Each patch preamble owns
its own mechanism and `meta.yaml`'s comments own the individual settings; do not restate
either here.

The two solve different halves of that. `GDAL_LIBS` names GDAL's static dependency chain so
dyld stops aborting on an unresolved `_geod_init` at import — a *load* failure.
`ios-driver-registry.patch` addresses the *table* above it: a GDAL per extension means a
driver registry per extension, and pyogrio registered only in `_ogr` while `_io` and
`_geometry` are where a read or a write resolves a driver name. Three of the five extensions
carry a whole static GDAL, which is also why an iOS wheel is 28–31 MB against Android's 0.6.

What the patch does not do is merge those copies, and one consequence is worth carrying:
`set_gdal_config_options` is exported by `_ogr`, while `_io` and `_geometry` each define
their own `CPLSetConfigOption` and import it from nowhere. On iOS a config option set through
the public API therefore lands in `_ogr`'s GDAL, and the read or write that should observe it
happens in a different one. That is read from the binary rather than measured on device;
**Coverage gaps** carries it. A shared libgdal for iOS is the complete fix, and would settle
rasterio, fiona and pyogrio in one change.

### Upgrade hazards

The build is steered entirely through `get_gdal_config()`'s environment branch —
`GDAL_INCLUDE_PATH`, `GDAL_LIBRARY_PATH`, `GDAL_VERSION` — which exists only because upstream
still uses `setup.py`. A move to meson or scikit-build-core retires both the `script_env`
block and the patch at once: treat that release as a redesign, not a bump. Bumping
`flet-libgdal` is the other hazard, because `OGR_BUILD_OPTIONAL_DRIVERS=OFF` there is what
keeps the driver set to the handful this page names.

### Re-verification checklist

- **The iOS registry, first:** count `GDALAllRegister` *call sites* with `otool -tV` on each
  extension's `__text`. `nm` cannot answer this — every extension defines the symbol, so a
  definition proves nothing about who calls it. `_ogr`, `_io` and `_geometry` must each show
  exactly one; build 2 does. A release that renames the `.pyx` files or moves the driver
  lookups drops the patch's hunks quietly, and `test_vector_round_trip` is what catches it.
- **Android's single table:** every extension names `libgdal.so` in `DT_NEEDED`, `_ogr`
  imports `GDALAllRegister` as undefined — that, not `OGRRegisterAll`, is what `_ogr.pyx`
  calls — and `_io` imports `GDALGetDriverByName`, `GDALOpenEx` and `GDALCreate` as
  undefined. Also check the 16 KB `PT_LOAD` alignment on all five.
- **Android's `DT_NEEDED` closure:** `libproj.so` names `libsqlite3_python.so`, and
  `libcurl.so` names `libssl_python.so` and `libcrypto_python.so` — three libraries the
  Python runtime ships, not this chain. A python-build bump that renames them turns
  `import pyogrio` into `dlopen failed: library "…" not found`, so walk the closure after
  one.
- **Formats:** re-derive the registered drivers from the binary — `RegisterOGR*` in
  `libgdal.so` is the list — and re-measure the field-name, string, integer and datetime rows
  rather than assuming a GDAL bump preserved them.
- **PROJ data:** confirm the chain still ships no `proj.db` and none is embedded in
  `libproj.so` — `flet-libproj` 9.5 predates PROJ's `EMBED_RESOURCE_FILES`. If one ever
  arrives, EPSG codes start resolving and the CRS advice needs rewriting, not relaxing. A
  desktop stands in for the device here: an empty file named `proj.db` in a directory named
  by `PROJ_DATA` makes PROJ fail the same way, warnings and `CRSError` included.
- **Size:** re-measure the wheels, the native chain and the `pyogrio/tests` payload.

### Coverage gaps

`test_vector_round_trip` writes a GeoJSON layer and reads it back, which is the only test
here that reaches `_io` and therefore the only one that can see the iOS driver registry.
Keep that asymmetry in mind before adding tests: `list_drivers()` and `__gdal_version__` are
`_ogr` calls, and they passed on iOS throughout the period the package could not open a
dataset there. It should always write with a proj-string CRS, never an authority code, or it
fails at the CRS before reaching the thing it exists to check.

Not covered on device: whether a config option set through `_ogr` reaches `_io` on iOS — the
limit under **Recipe shape**, and the one claim on this page taken from a binary rather than
a run — plus the attribute round trip, the Shapefile's sibling files, in-memory `/vsimem`
datasets, the Arrow API, appending to a layer, and geopandas. The **Formats**, **Coordinate
systems** and **Threading** figures come from a desktop wheel carrying a different GDAL, and
are stated that way; promote those to device coverage first.
