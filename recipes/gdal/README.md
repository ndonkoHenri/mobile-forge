# gdal

[GDAL](https://gdal.org/)'s own Python bindings — `osgeo.gdal`, `osgeo.ogr`, `osgeo.osr` —
the raster and vector engine that sits underneath most of the geospatial stack, with the
thin SWIG wrapper the C++ API was designed around. On a phone that buys you a GeoTIFF round
trip, windowed reads out of a raster far larger than RAM, and GeoJSON or Shapefile I/O,
entirely in-process and with no network.

These wheels are a deliberately small GDAL: **eleven drivers**, no `GDAL_DATA`, no libcurl, no
GEOS. None of that announces itself at import; each missing piece surfaces as one call failing,
at the point of use. EPSG codes resolve on iOS as installed, and on Android once
[`pyproj`](../pyproj) is installed and extracted, for the reason
[Coordinate systems](#coordinate-systems) gives. [`rasterio`](../rasterio) and
[`pyogrio`](../pyogrio) wrap the same GDAL with friendlier APIs; installed together, they and
this package share one `libgdal` — see [Extension modules](#extension-modules).

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
]

[tool.flet.android]
dependencies = [
    "gdal",
]

[tool.flet.ios]
dependencies = [
    "gdal",
]
```

**Keep gdal out of `[project] dependencies`, and not for the usual reason.** Both platforms
have wheels on the index, but **upstream publishes no wheel for any desktop** — PyPI carries
a source tarball whose build wants a system libgdal and `gdal-config`. Flet
[appends](https://flet.dev/docs/publish/#app-dependencies) `[tool.flet.<platform>].dependencies`
to the project list rather than replacing it, so a top-level `"gdal"` is *also* handed to the
host resolve `flet build` performs first, which tries that sdist and stops the build with
`Call to setuptools.build_meta.build_wheel failed` before it reaches a device. Measured
2026-08-19 against `flet build apk` and `flet build ios-simulator` alike.

The cost is that **gdal is then absent from `flet run` and from a web build**, since nothing
outside an Android or iOS `flet build` reads those tables: `from osgeo import gdal` raises
`ModuleNotFoundError` everywhere you develop. Guard the import so those runs explain
themselves instead of crashing, as [`geotiff-roundtrip`](examples/geotiff-roundtrip) does.

**`numpy` is an optional extra, not a dependency.** Write `"gdal[numpy]"`, or add `"numpy"`
alongside it, if you want the array API; a bare `"gdal"` leaves
[`band.ReadAsArray()`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Band.ReadAsArray)
raising `ModuleNotFoundError: No module named 'numpy'` at the point of use rather than at
import. numpy raises your own `requires-python` floor as a side effect — 2.4.6 needs
`>=3.11`, and `uv` fails the resolve for lower splits otherwise.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`geotiff-roundtrip`](examples/geotiff-roundtrip) — a GeoTIFF written to app storage and
  read back, with the `gdal_array`, `osr` and `ogr` paths measured beside it.

## Usage in a Flet app

Write a raster, close it, read a window back:

```python
gdal.UseExceptions()  # once, at startup — see Things to know

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "surface.tif")
ds = gdal.GetDriverByName("GTiff").Create(
    path, 512, 512, 1, gdal.GDT_Float32,
    options=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES"],
)
ds.SetGeoTransform([10.0, 0.001, 0.0, 60.0, 0.0, -0.001])  # origin, then pixel size
ds.GetRasterBand(1).WriteRaster(0, 0, 512, 512, values.tobytes())
ds = None  # dropping the last reference is what flushes the file

ds = gdal.Open(path)
raw = ds.GetRasterBand(1).ReadRaster(128, 128, 64, 64)  # a window, not the whole band
caption = ft.Text(f"{ds.GetDriver().ShortName}: {len(raw):,} bytes back")
```

`ds = None` is not tidiness — GDAL flushes and closes when the last reference drops, and a
file still held open is one `Driver.Create` on the same path will refuse to replace.
[`ReadRaster`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Band.ReadRaster)
returns `bytes` in the band's dtype and native byte order, which
[`array.frombytes`](https://docs.python.org/3/library/array.html#array.array.frombytes) or
`numpy.frombuffer` unpacks; `ReadAsArray()` returns the numpy array directly, at the cost of
the optional extra above. Reading a window rather than a whole band is what lets a phone open
a raster larger than its RAM.

### Storage

Rasters and vector files belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, durable, included in backups, and from Flet 0.86.0 also the process working
directory on device. It has to be a **writable** directory rather than a bundled asset,
because GDAL writes beside the file: `band.ComputeStatistics(False)` on the example's
512×512 GeoTIFF left a 385-byte `surface.tif.aux.xml` next to it (measured on a host GDAL
3.13.0; PAM sidecars are GDAL's behaviour, not a mobile quirk), and updating an existing
raster needs `gdal.GA_Update` on the file itself.

Avoid
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it) and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) for anything you want to keep.

### Coordinate systems

**Proj-strings and WKT always work.** They name a projection by its parameters, so they need no
database and behave identically on both platforms — still the portable choice for code that
must run on both:

```python
srs = osr.SpatialReference()
srs.SetFromUserInput("+proj=longlat +datum=WGS84 +no_defs")
ds.SetSpatialRef(srs)
```

**EPSG codes need PROJ's database, and where that is depends on the platform.** gdal,
[`fiona`](../fiona), [`rasterio`](../rasterio), [`pyogrio`](../pyogrio) and
[`pyproj`](../pyproj) all link one shared PROJ, so whichever package supplies the database
supplies it for all of them.

- **iOS: they just work.** `flet-libproj` ships `proj.db` and `osgeo/__init__.py` points PROJ
  at it before the first extension import.
  [`ImportFromEPSG(4326)`](https://gdal.org/en/stable/api/python/spatial_ref_api.html#osgeo.osr.SpatialReference.ImportFromEPSG)
  resolves.
- **Android: install [`pyproj`](../pyproj) and extract it.** The database cannot travel in
  `flet-libproj` there — Flet lifts only `*.so` out of a `flet-lib*` `opt/` tree — so it ships
  inside pyproj instead, and a file inside Flet's `sitepackages.zip` is not a path PROJ can
  open. Both halves are needed:

  ```toml
  [tool.flet.android]
  dependencies = ["gdal", "pyproj"]
  extract_packages = ["pyproj"]   # without this the database stays in the zip
  ```

  `extract_packages` is read from **your** pyproject; it is never inherited from a
  dependency, so nothing supplies it on your behalf. `osgeo` finds pyproj's copy without
  importing pyproj. Miss either half and `ImportFromEPSG` goes on raising
  `RuntimeError: PROJ: proj_create_from_database: Cannot find proj.db` under
  `UseExceptions()`, or returning a non-zero error code without it.

The [`geotiff-roundtrip`](examples/geotiff-roundtrip) example builds its CRS from a proj-string
and runs the EPSG call beside it, with the Android configuration above, so a device that did
not get the database shows it on screen.

To use your **own** database instead — a newer PROJ data release, or one carrying datum grids —
set `PROJ_DATA` to the directory holding it before importing `osgeo`, from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir)
if you bundle it as an asset. An environment variable already set is left alone, so yours
wins. It has to be set before the import: PROJ reads it when it creates its first context.
The database has to suit this chain's PROJ **9.5.0**, which checks a database's declared layout
version and rejects an incompatible one with *"It comes from another PROJ installation"*.
gdal, fiona, rasterio and pyogrio all read that variable. pyproj on Android prefers its
extracted copy, so also call `pyproj.datadir.set_data_dir` after importing it; see
[`pyproj`](../pyproj).

### Drivers and codecs

**Eleven drivers, four of them raster: `GTiff`, `COG`, `VRT`, `MEM`, plus `ESRI Shapefile`,
`GeoJSON`, `GeoJSONSeq`, `ESRIJSON`, `TopoJSON` and the two network drivers `GNMFile` and
`GNMDatabase`.** No PNG, JPEG, GPKG, SQLite, CSV, GML, KML, netCDF, GRIB or JP2 — decode a
PNG or JPEG with [`pillow`](../pillow) or [`opencv-python`](../opencv-python) instead, and
convert other formats off-device. Ask the live registry rather than trusting a list, this one
included:

```python
[gdal.GetDriver(i).ShortName for i in range(gdal.GetDriverCount())]
ogr.GetDriverCount()  # the vector-capable subset
```

**Five TIFF codecs are linked: LZW, Deflate, PackBits, JPEG and LERC. ZSTD, WEBP and LZMA are
not**, despite GDAL advertising all of them in the
[GTiff `COMPRESS` option list](https://gdal.org/en/stable/drivers/raster/gtiff.html#creation-options),
which it compiles in unconditionally and filters at runtime. `COMPRESS=DEFLATE` with
`PREDICTOR=3` for floats is the sane default.

Asking for one of the missing three is a **hard failure, not a fallback** — and a
neighbouring mistake behaves the opposite way, which is what makes this worth knowing. On a
host GDAL 3.13.0 built without WEBP, `Create(..., options=["COMPRESS=WEBP"])` logged
`ERROR 1: Cannot create TIFF file due to missing codec for WEBP.` and returned `None`, no
file written. A *misspelt* codec logs only `Warning 5: COMPRESS=NOTACODEC value not
recognised, ignoring.` and hands back a dataset that writes an uncompressed TIFF. Read
`ds.GetMetadata("IMAGE_STRUCTURE")` back to see which compression is actually in force.

**GDAL is compiled without libcurl and without GEOS.** Both platforms carry GDAL's
`#else`-branch diagnostics *"GDAL/OGR not compiled with libcurl support, remote requests not
supported."* and *"GEOS support not enabled."*, so `/vsicurl/`, `/vsis3/`, `/vsigs/` and
`/vsiaz/` are dead strings and OGR geometry predicates are unavailable. The virtual file
systems that do work are `/vsimem/`, `/vsizip/`, `/vsitar/`, `/vsigzip/`, `/vsisubfile/` and
`/vsisparse/`.

### Extension modules

`osgeo` is six compiled extensions — `_gdal`, `_gdalconst`, `_ogr`, `_osr`, `_gnm` and
`_gdal_array` — and **on both platforms they link one shared GDAL**: `libgdal.so` on Android,
`libgdal.dylib` on iOS, which in turn links one shared PROJ. A process therefore has one
driver registry and one set of configuration options, which [`fiona`](../fiona),
[`rasterio`](../rasterio) and [`pyogrio`](../pyogrio) share when installed alongside;
[`pyproj`](../pyproj) shares only the PROJ underneath. `band.ReadAsArray()` (`_gdal_array`
code on a `_gdal` object),
[`ds.GetSpatialRef()`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Dataset.GetSpatialRef)
(a `_gdal` result whose methods run in `_osr`) and
[`gdal.OpenEx(path, gdal.OF_VECTOR).GetLayer(0)`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.OpenEx)
(a `_gdal` pointer handed to `_ogr`) all operate on that one GDAL;
[`geotiff-roundtrip`](examples/geotiff-roundtrip) measures each of them.

`import osgeo.gdal` is never one extension — **it maps four**: `_gdal`, `_gdalconst`, `_ogr`
and `_osr`, because `osgeo/gdal.py` does a module-level `from . import ogr` / `from . import
osr`. The imports are unconditional in upstream's SWIG output. The four are thin wrappers —
2,873,720 bytes on Android arm64-v8a — over the one `libgdal`; the example prints the live
number on screen.

On iOS, flet moves each extension and each dylib into its own framework, rewrites the
extensions' `@rpath` links to match, and leaves a `.fwork` marker in `opt/lib`.
`osgeo/__init__.py` also preloads `libproj`, then `libgdal`, `RTLD_GLOBAL` — from `opt/lib`,
or through the marker — before the first extension import.

### Threading

**A GDAL dataset handle is not safe to use from two threads at once.** That matters more than
usual under
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), which
submits to a shared pool, so two taps really do overlap. On this same GDAL build, eight
threads doing overlapping reads on one shared handle took the interpreter down with SIGBUS on
four of five runs — a native crash with no Python traceback. Open one dataset per thread (the
simplest rule, and what the example does), or hold a `threading.Lock` around the whole use.

**There is no per-thread environment to enter, unlike rasterio.** Driver registration happens
once, in the extension's own module init, so a worker thread can call
[`gdal.Open`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Open) with no
preamble; the example's slider worker does exactly that, which is what tests it. GDAL's own
thread-safe dataset mode is compiled in and reachable —
`gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_THREAD_SAFE)` returned a dataset reporting
[`IsThreadSafe`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Dataset.IsThreadSafe)`(gdal.OF_RASTER) == True`
on a host GDAL 3.13.0 — but it has not been exercised on a device.

The standing Flet caveats apply on top: `run_thread` never retrieves the worker's future, so
an exception inside one surfaces nowhere — wrap the body — and auto-update does not reach
background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### App size

**The wheel is small and about the same on both platforms; the shared GDAL chain behind it is
the payload.** On Android arm64-v8a the wheel is about 1.4 MB, unpacking to about 5.4 MB, of
which 3,153,032 bytes is the six extensions — on top of 22.8 MB of shared native libraries,
most of it `libgdal.so` itself. An iOS slice is 1.3–1.4 MB compressed and 5.3–5.6 MB
unpacked, plus the `libgdal.dylib` and `libproj.dylib` that `flet-libgdal` and `flet-libproj`
install. Those libraries are shared with every other GDAL or PROJ consumer in the app, so
adding `fiona`, `rasterio`, `pyogrio` or `pyproj` does not add a second copy.

Use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI.

Leave Flet's default [compilation and
cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) on: about 2.2 MB of the
payload is `.py`, of which 1,325,117 bytes is `osgeo_utils/` — command-line tools nothing in
the package imports — and nothing here reads its own source, so `.pyc` is safe.

### Other considerations

**Your desktop is not a preview of the device.** `flet run` resolves GDAL from PyPI or
Homebrew — a full `proj.db` and a registry of 214 drivers against the mobile build's eleven
on the machine this page was written on. PNG and `ZSTD` work on your Mac and fail on the phone,
and so do EPSG codes on an Android build without extracted pyproj.
Validate on a device or simulator, and make the app render its own exceptions on screen — an
unhandled exception in a Flet handler produces `SESSION_CRASHED` and you lose the diagnosis.

## Things to know

- **Exceptions are off by default, and the bindings nag about it.** Without a call, a failed
  [`gdal.Open`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Open) or
  [`Driver.Create`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Driver.Create)
  returns `None`, and the first such call emits `FutureWarning: Neither gdal.UseExceptions()
  nor gdal.DontUseExceptions() has been explicitly called. In GDAL 4.0, exceptions will be
  enabled by default.` There are 21 call sites in `osgeo/gdal.py` — `Open`, `OpenEx`,
  `Driver.Create`, `Driver.CreateMultiDimensional`, `Driver.CreateCopy`, `Driver.Delete`,
  `Info`, `VectorInfo`, `MultiDimInfo`, `Translate`, `Warp`, `VectorTranslate`,
  `DEMProcessing`, `Nearblack`, `Grid`, `Contour`, `Rasterize`, `Footprint`, `BuildVRT`,
  `TileIndex` and `MultiDimTranslate`. A `None` dataset dereferenced later is an
  `AttributeError` a long way from the real failure, so turn exceptions on and print
  `type(err).__name__` plus
  [`gdal.GetLastErrorMsg()`](https://gdal.org/en/stable/api/python/general.html#osgeo.gdal.GetLastErrorMsg).

- **[`gdal.UseExceptions()`](https://gdal.org/en/stable/api/python/general.html#osgeo.gdal.UseExceptions)
  — the call every GDAL tutorial opens with — maps two more extensions.** It loops over gdal,
  gdal_array, ogr, osr and gnm, so it adds `_gnm` and, when numpy is installed, `_gdal_array`:
  all six. Call it once at startup rather than per handler — error-code returns are worse.

- **[`gdal.ExceptionMgr()`](https://gdal.org/en/stable/api/python/general.html#osgeo.gdal.ExceptionMgr)
  looks like the lighter switch and is not.** It skips `_gnm`, but its `__enter__` does
  `from . import gdal_array` inside a `try/except ImportError`, so it maps `_gdal_array`
  **even when numpy is absent** — and the Python wrapper then fails anyway.
  `UseExceptions()` is guarded by `find_spec("numpy")` and does not have that failure mode.
  Prefer one `UseExceptions()` at startup to a context manager per call.

- **The `gdalplugins/drivers.ini` that ships beside GDAL is not a capability list.** It is a
  2,787-byte ordering table naming 251 drivers, installed unconditionally; reading it as what
  was compiled in over-counts the registry by a factor of twenty-three, and on Android it does
  not even reach the device. Ask the live registry instead.

- **`Driver.Create` silently deletes an existing file first — until it can't.**
  `GDALDriver::Create` runs `QuietDelete` on the path before handing over to the driver, so a
  second `gdal.GetDriverByName("GeoJSON").Create(path, 0, 0, 0, gdal.GDT_Unknown)` on a
  *closed* file simply replaces it. `RuntimeError: The GeoJSON driver does not overwrite
  existing files.` appears only where that delete cannot happen: the previous dataset is
  still referenced, the directory is read-only, the path is a directory, or
  `APPEND_SUBDATASET=YES` is passed (four cases, all measured on host GDAL 3.13.0). So drop
  the writer reference before re-creating a path — `ds = None`, as the example does after
  every write — and remember that a re-run overwrites your data without a word.

## Build notes (maintainers)

### Recipe shape

Two recipes: `flet-libgdal` builds GDAL, `recipes/gdal` builds upstream's own bindings
against it. Each patch explains itself in its preamble — `config.patch` its `gdal-config`
short-circuit, `ios-libgdal-preload.patch` the iOS dylib preload and the `PROJ_DATA` lookup —
and `meta.yaml` comments its version pin, `LDFLAGS` and `pyproj` test entries in place.

**Almost everything the consumer sections warn about is a `flet-libgdal` decision, not a gdal
one.** The eleven-driver registry, the codec set, the missing `GDAL_DATA`, where `proj.db`
lives, and the absent GEOS and libcurl all come from that recipe and from `flet-libproj`. A
`flet-libgdal` bump can invalidate most of this README without a line changing here.

**The extensions link `gdal` alone — setup.py's own `libraries = ['gdal']` — and that is
load-bearing.** On iOS `flet-libgdal` ships one de-versioned `opt/lib/libgdal.dylib`, install
id `@rpath/libgdal.dylib`, built on GDAL's internal libtiff, libjpeg, zlib and json-c. Its only
`@rpath` dependency is `@rpath/libproj.dylib`, which carries PROJ's own libtiff,
libjpeg-turbo, libcurl, libpsl and OpenSSL; the rest is the system sqlite3 and zlib. The six
extensions link that one image and share one driver registry. If an extension ever links a
static `libgdal.a`, or a link hook starts naming archives from the chain, it gets a private
GDAL and a private registry — the check is under **Upgrade hazards**.

`-undefined dynamic_lookup` is not used: an unresolved symbol against a real dylib is a defect
that has to fail at link, not at `dlopen` on a device. iOS links with
`-Wl,-headerpad_max_install_names` because serious_python rewrites each extension's
`@rpath/libgdal.dylib` dependency to the longer framework path; without the padding
`install_name_tool` fails and `flet build` still exits 0, with an app missing its
site-packages.

### Upgrade hazards

The version pin in `meta.yaml` is exact for a reason — the bindings hard-require a
major.minor match with libgdal. Bump the two together and re-read the consumer claims off the
built wheels.

**The registry is shared through `libgdal`, so no SWIG module needs to register on its own.**
Confirm on a bump that no extension *defines* `GDALAllRegister` — `nm -a <ext> | grep
" [tT] _GDALAllRegister"` must be empty for all six, while `otool -L` names
`@rpath/libgdal.dylib` on each. A definition means the link picked up a static GDAL, which
gives that extension a private registry and produces the failure that is hardest to read:
a full driver listing beside an open that cannot find the driver it just listed.

The Android database route depends on another recipe's layout: the preload shim looks for
`pyproj/proj_dir/share/proj/proj.db`. A `pyproj` bump that moves it leaves EPSG codes raising
on Android with nothing in this recipe changed.

The import graph moves on any bindings release too: four-modules-on-import and
six-after-`UseExceptions()` are upstream source behaviour, not ours.

### Re-verification checklist

- **That nothing in the wheel reads a file from its own installation.** This is what keeps
  gdal off `extract_packages` on Android, where site-packages is a zip: the wheel ships no
  non-code data files at all, and `osgeo/__init__.py` uses `__file__` only to derive a module
  name for `swig_import_helper` and, in the preload shim, to look in `site-packages/opt/`
  for `lib/libproj.dylib`, `lib/libgdal.dylib` or their `.fwork` markers
  (reading a marker it finds) and for `share/proj/proj.db`. Each read waits on an
  `os.path.exists` hit, and that `opt/` never reaches Android's site-packages, so none runs
  there. A bump that starts shipping a data file — a `drivers.ini`, a PROJ or GDAL data tree —
  or that opens one relative to `__file__` turns that into a `NotADirectoryError` on Android
  and nothing anywhere else. Re-check both on every bump: `unzip -l` the wheel for
  non-`.py`/`.so` entries, and grep `osgeo/` for `__file__`.

A green build establishes almost none of what this page claims.

- **The linkage.** Android: `DT_NEEDED` still naming `libgdal.so` by bare soname,
  `libc++_shared.so` on exactly five of six extensions, `libgdal.so` still *not* naming
  `libc++_shared.so` itself, the libproj chain intact, and 16 KB `PT_LOAD` alignment
  everywhere. Note where the requirement actually comes
  from: `libgdal.so` does not name `libc++_shared.so` at all, and gets its C++ symbols from
  `libproj.so`, which statically links libc++. It is gdal's own SWIG extensions — every one
  but `_gdalconst` — that each name `libc++_shared.so` directly, which is why
  dropping the wheel fails at `dlopen` of an extension rather than at anything GDAL-shaped.
  iOS: six `MH_DYLIB`, each with `otool -L` naming `@rpath/libgdal.dylib` and none defining
  `GDALAllRegister`; `otool -hv` `TWOLEVEL`; and in the `flet-libgdal` wheel a single
  un-versioned `opt/lib/libgdal.dylib` whose `otool -D` is `@rpath/libgdal.dylib` and whose
  `otool -L` names `@rpath/libproj.dylib` as its only `@rpath` dependency.
- **Registration in module init.** `otool -tV` on the iOS `_gdal` for `PyInit__gdal` →
  `GDALAllRegister`, which is what lets a worker thread call `gdal.Open` with no preamble.
- **The import graph.** Re-run it against the new `osgeo/*.py`: run the wheel's Python half
  with the six extensions replaced by recording stubs.
- **The driver set**, two independent ways: `otool -tV` on the iOS `libgdal.dylib` shows
  `GDALAllRegister` branching to exactly `GDALRegister_GTiff`, `_COG`, `_VRT`, `_MEM`,
  `GNMRegisterAllInternal` and `OGRRegisterAllInternal`; Android's `libgdal.so` dynamic symbol
  table defines the same eleven. That library is stripped, so go by dynamic symbols, not `nm`.
- **The codec set**, as `strings -a <file> | grep -c <marker>` on `libgdal`. Android's
  `libgdal.so` gives `LZWDecode` 5, `ZIPDecode` 2, `JPEGDecode` 4, `PackBitsDecode` 2,
  `LERCDecode` 1; `ZSTDDecode`, `WebPDecode` and `LZMADecode` must be 0 there and in the iOS
  `libgdal.dylib`.
- **Where the data files are.** `unzip -l` on the gdal and `flet-libgdal` wheels should
  still match nothing under `proj.db`, `gdal_data/`, `proj_data/` or `share/`; the
  `flet-libproj` wheel should carry exactly `opt/share/proj/proj.db` (9,261,056 bytes in the
  iOS build 11 wheels, 9,240,576 in the Android ones). If `GDAL_DATA` starts shipping, or
  `proj.db` moves, **Coordinate systems** needs rewriting.
- **The two PROJ routes.** On iOS, EPSG codes resolving with no app configuration. On
  Android, `assets/extract.zip` in a built APK is 22 bytes when nothing was extracted and
  about 9.6 MB when pyproj's database was — the cheap check that `extract_packages` took,
  before `test_epsg_codes_work_where_proj_db_reached_the_device` says anything.
- **The sizes**, re-measured rather than adjusted by eye. Decimal units — `du -h` will
  disagree.
- **The example is the live regression test.** A bump means bumping
  [`geotiff-roundtrip`](examples/geotiff-roundtrip)'s `gdal==` pin and rebuilding on both
  platforms; its panels are one-to-one with the claims above.

### Coverage gaps

**EPSG resolution through `osgeo.osr` has run on an iPhone simulator and an Android
emulator.** `test_epsg_codes_work_where_proj_db_reached_the_device` decides its branch from
whether `proj.db` is on disk, so a pass alone does not say which branch ran; a run with the
no-database branch made to fail confirmed the database branch on both, with the Android app
reading pyproj's extracted copy through gdal's shim. An app-set `PROJ_DATA` has not run on a
device.

The other tests stay inside `_gdal` and inside the `MEM` driver, so a broken GeoTIFF-on-disk
path, a broken `_gdal_array` or `_ogr` handoff, or a vanished driver would all pass CI green;
only [`geotiff-roundtrip`](examples/geotiff-roundtrip) on a device exercises those. Worth
adding: an assertion over the exact eleven driver short names (so a driver *appearing* is as
red as one disappearing) and a GTiff write-read-compare in `tmp_path`.

Untested anywhere: an app-supplied `PROJ_DATA` on a device, `OF_THREAD_SAFE` on device,
`gdal_array.SaveArray`, the `COG` and `VRT` drivers, and every network-drivers path.
