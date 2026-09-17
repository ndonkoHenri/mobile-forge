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
drivers and no GDAL data directory. **Formats** below says what that rules out — GeoPackage
is not one of the six.

EPSG codes resolve too: PROJ's database reaches the device through `flet-libproj` on iOS and
through [`pyproj`](../pyproj) on Android, and pyogrio points PROJ at whichever copy is there.
Automatic on iOS; on Android it needs pyproj installed and `extract_packages` set, for the
reason **Coordinate systems** gives. Proj-strings need no database at all and are the
portable choice for code that runs on both.

Both platforms link one shared GDAL, so the wheels are small and near-identical: an iOS slice
is 0.6–0.7 MB compressed and 2.2–2.3 MB unpacked, against 0.6 MB and 1.7–2.0 MB for an
Android wheel. The GDAL chain itself ships separately, in `flet-libgdal` and `flet-libproj`,
and **App size** covers it.

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

**A PROJ string or WKT always works** — it names a projection by its parameters, so it needs
no database:

```python
write(..., crs="+proj=longlat +datum=WGS84 +no_defs")
```

**An EPSG code needs PROJ's database, and where that comes from differs by platform.**
Every GDAL or PROJ consumer in the app shares one PROJ, so whichever package supplies the
database supplies it for all of them.

- **iOS: codes just work.** `flet-libproj` ships `proj.db` and `pyogrio/__init__.py` points
  PROJ at it before the first extension import.
- **Android: install [`pyproj`](../pyproj) and extract it.** The database cannot ride in
  `flet-libproj` there, because Flet lifts only `*.so` out of a `flet-lib*` `opt/` tree, so it
  travels inside pyproj — and a file inside Flet's `sitepackages.zip` is not a path PROJ can
  open. Both halves are needed:

  ```toml
  dependencies = ["flet", "pyogrio", "pyproj"]

  [tool.flet.android]
  extract_packages = ["pyproj"]   # without this the database stays in the zip
  ```

  `extract_packages` is read from **your** pyproject and is never inherited from a
  dependency, so nothing sets it on your behalf. Miss it and `crs="EPSG:4326"` goes on
  raising `pyogrio.errors.CRSError: Could not set CRS: EPSG:4326`.

**Without a database, a code is not just unavailable — it can be reported wrongly.** A WKT
carrying `AUTHORITY["EPSG","32630"]` reaches a GeoJSON file as
`"crs": { … "urn:ogc:def:crs:EPSG::32630" }`, but reading it back is a code lookup, so
`meta["crs"]` comes back `EPSG:4326` and nothing warns. A Shapefile is immune, because the
`.prj` holds the WKT itself. That is the strongest argument for supplying the database on
both platforms rather than relying on proj-strings and hoping the round trip is faithful.

And nothing here reprojects: **the driver writes the coordinates you hand it under whatever
CRS you name.** UTM easting and northing written to GeoJSON with a UTM CRS came back
unchanged and tagged `EPSG:4326` on a desktop GDAL 3.11.4, silently. Transform before writing.

### App size

On Android the wheels are approximately 0.60–0.64 MB compressed and 1.7–2.0 MB unpacked, but
the shared GDAL chain behind them adds 14.9–23.6 MB of libraries per ABI — 21.5 MB on
arm64-v8a, where `libgdal.so` is 14.0 MB and `libproj.so` 4.6 MB, then libturbojpeg, libtiff,
libcurl, libjpeg and libpsl. Use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI.

On iOS the chain is two dylibs: `libgdal.dylib` from `flet-libgdal`, and `libproj.dylib`
from `flet-libproj`, which absorbs libtiff, libjpeg-turbo, libcurl, libpsl and OpenSSL and
ships `proj.db` beside it. An `ipa` carries one slice. On both platforms the chain is shared
by every GDAL consumer in the app — [`gdal`](../gdal), [`fiona`](../fiona),
[`rasterio`](../rasterio) — and its PROJ also by [`pyproj`](../pyproj), so pairing any of
them with pyogrio adds no second GDAL or PROJ.

Over half of each unpacked Android wheel — 1,008,031 bytes on every architecture — is
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
handful of drivers on device. GeoPackage and FlatGeobuf open there and not on the phone, and
EPSG codes resolve there without the Android setup **Coordinate systems** describes, so
validate format and CRS choices on a device or emulator.

## Things to know

- **`import pyogrio` warns about missing data files, and it is expected.** The wheels ship no
  GDAL data directory, so the import raises `RuntimeWarning: Could not detect GDAL data files.
  Set GDAL_DATA environment variable to the correct path.` and GDAL logs `Cannot find
  header.dxf (GDAL_DATA is not defined)` — both reproduced on a desktop by deleting the bundled
  directory, after which GeoJSON and Shapefile round trips still came back with zero wrong
  values. A second probe calls `OSRImportFromEPSG(4326)`, and where no `proj.db` reached the
  device — Android without pyproj extracted — it fails too, adding `RuntimeWarning: Could
  not detect PROJ data files. Set PROJ_LIB environment variable to the correct path.` — that
  probe is the very lookup the CRS advice above is about, so the pair of warnings is the
  whole CRS story arriving at import time.

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

This is a consumer of the `flet-libgdal` chain, and both platforms resolve one shared image:
`libgdal.so` on Android, `libgdal.dylib` on iOS. All five extensions — `_ogr`, `_io`,
`_geometry`, `_err`, `_vsi` — link it, so an app has one driver registry, shared with gdal,
fiona and rasterio, and one PROJ, which pyproj shares too. `ios-libgdal-preload.patch`'s
preamble owns its mechanism and `meta.yaml`'s comments own the individual settings; do not
restate either here.

**The shared library is load-bearing, not an optimisation.** A static GDAL is copied *into*
every extension that links it, giving each its own driver registry and configuration.
pyogrio registers in `_ogr` while reads and writes resolve driver names in `_io`, so with a
static GDAL the registry populated is not the one consulted: `list_drivers()` reports a full
table and every read and write fails.

### Upgrade hazards

The whole link is pyogrio's own `get_gdal_config()` environment branch — `GDAL_INCLUDE_PATH`,
`GDAL_LIBRARY_PATH` (one directory) and `GDAL_VERSION` — with its default
`gdal_libs = ["gdal"]`. That branch exists only because upstream still uses `setup.py`, so a
move to meson or scikit-build-core retires the `script_env` block: treat that release as a
redesign, not a bump. Bumping
`flet-libgdal` is the other hazard, because `OGR_BUILD_OPTIONAL_DRIVERS=OFF` there is what
keeps the driver set to the handful this page names.

### Re-verification checklist

- **That libgdal is SHARED on iOS, first.** `file` `flet-libgdal`'s
  `opt/lib/libgdal.dylib` — it must be a `Mach-O … dynamically linked shared library`,
  `otool -D` must report `@rpath/libgdal.dylib`, and its only `@rpath` dependency must be
  `@rpath/libproj.dylib`. Then confirm no extension *defines* `GDALAllRegister`
  (`nm -a <ext> | grep " [tT] _GDALAllRegister"` → empty) while all five name
  `@rpath/libgdal.dylib` in `otool -L`. A definition means that extension links GDAL
  statically, which gives it a driver registry of its own.
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
- **PROJ data:** confirm `flet-libproj` still ships `opt/share/proj/proj.db` and that
  `pyogrio/__init__.py` still points `PROJ_DATA` at it — the wheel size is the cheap tell,
  since the database is 9.26 MB. On Android confirm the other route instead: pyproj's wheel
  carrying `proj_dir/share/proj/proj.db`, and `extract.zip` in a built APK being ~9.6 MB
  rather than 22 bytes, which is what an unextracted build looks like.
- **Size:** re-measure the wheels, the native chain and the `pyogrio/tests` payload.

### Coverage gaps

Only the two round-trip tests reach `_io`. `list_drivers()` and `__gdal_version__` are `_ogr`
calls and pass whether or not `_io` can open a dataset, so a test built on them proves
nothing about I/O.

`test_vector_round_trip` writes a GeoJSON layer with a proj-string CRS and reads it back, so
it checks I/O alone; an authority code there would fail at the CRS on a device without the
database, before reaching the thing it exists to check.
`test_epsg_codes_work_where_proj_db_reached_the_device` owns the database. It picks its
branch from whether `proj.db` is on disk, not from what PROJ reports: with one, an
`EPSG:32633` write reads back as that code and an RFC7946 write reprojects the point to 15°E,
60°N; without one, the write must raise `CRSError`. `meta.yaml` installs and extracts pyproj
for the tests, and a run with the no-database branch made to fail confirmed the database
branch on an iPhone simulator and an Android emulator.

Not covered on device: the attribute round trip, the Shapefile's sibling files, in-memory `/vsimem`
datasets, the Arrow API, appending to a layer, and geopandas. The **Formats**, **Coordinate
systems** and **Threading** figures come from a desktop wheel carrying a different GDAL, and
are stated that way; promote those to device coverage first.
