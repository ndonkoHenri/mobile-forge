# fiona

[`fiona`](https://fiona.readthedocs.io/en/stable/) reads and writes **vector** geospatial
data — points, lines and polygons carrying attributes — through
[GDAL/OGR](https://gdal.org/), and hands each feature back as a plain Python mapping with
`geometry` and `properties`, shaped like a GeoJSON feature.
[`fiona.open`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.open) returns a
`Collection`: iterate it to read, hand it records to write. On a phone that is what lets an
app store, edit and exchange real vector data with no database and no network — everything
happens in-process, on files in app storage.

Both platforms read and write. On both this is a deliberately small GDAL: six vector
drivers, no `proj.db`, no `GDAL_DATA`, no GEOS and no libcurl, and none of that announces
itself at import — **Drivers** and **Coordinate systems** below say what it rules out. The
one rule to carry into every call is that a CRS has to be spelled as a proj-string rather
than `EPSG:4326`, because resolving an authority code is a database lookup and no database
ships.

Both platforms resolve one shared GDAL, so the wheels are small and near-identical: an iOS
slice is 1.0 MB compressed and 3.1–3.2 MB unpacked, against 0.84–0.96 MB and 1.8–2.6 MB for
an Android wheel. The GDAL itself is a separate package — `flet-libgdal` — and **App size**
puts the two together, which is the comparison that decides it.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
]

[tool.flet.android]
dependencies = [
    "fiona",
]

[tool.flet.ios]
dependencies = [
    "fiona",
]
```

**fiona goes in the platform tables rather than in `[project] dependencies`.** Flet
[appends](https://flet.dev/docs/publish/#app-dependencies)
`[tool.flet.<platform>].dependencies` to the project list rather than replacing it, so a
top-level `"fiona"` is *also* handed to the host resolve `flet build` runs first. fiona's
PyPI wheels stop at CPython 3.13, and its sdist learns where GDAL is in exactly one way —
by shelling out to `gdal-config` — so on a 3.14 interpreter that resolve either fails with
`A GDAL API version must be specified.` or, on a machine that happens to have a system
GDAL, quietly builds a *host* fiona no device will ever load and then serves it from the
resolver's cache. The tables keep fiona out of that resolve entirely.

The cost is worth stating plainly: **fiona is then absent from `flet run` on your desktop
and from a web build**, because nothing outside a `flet build` for Android or iOS reads
those tables, and `import fiona` raises `ModuleNotFoundError` everywhere you develop. Guard
the import so those runs explain themselves instead of crashing — the
[`feature-roundtrip`](examples/feature-roundtrip) example renders a card naming the missing
module. If you pin fiona to a version whose desktop wheels cover your interpreter, a
top-level entry works too; the platform tables are the shape that keeps working as Python
moves on.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`feature-roundtrip`](examples/feature-roundtrip) — a GeoJSON and a Shapefile written to
  app storage, then read back and compared geometry by geometry and property by property
  against the records they came from.

## Usage in a Flet app

```python
import os

import fiona
import flet as ft

folder = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "tracks")
os.makedirs(folder, exist_ok=True)
path = os.path.join(folder, "tracks.geojson")

schema = {"geometry": "Point", "properties": {"name": "str", "score": "float"}}

# pass driver= explicitly on every write — see Things to know
with fiona.open(path, "w", driver="GeoJSON", schema=schema) as dst:
    dst.write(
        {
            "geometry": {"type": "Point", "coordinates": (2.35, 48.86)},
            "properties": {"name": "Paris", "score": 1.0},
        }
    )

with fiona.open(path) as src:
    features = list(src)

page.add(
    ft.Column([ft.Text(f["properties"]["name"]) for f in features])
)
```

### Storage

Vector files belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, durable and included in backups. It has to be a **writable** directory rather
than a bundled asset: OGR writes the dataset in place. Avoid
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it) and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) for anything you want to keep.

**Give each dataset its own subdirectory**, because a Shapefile is not one file. Writing a
point layer with no CRS left `layer.shp`, `layer.shx`, `layer.dbf` and `layer.cpg`, and a
fifth file `layer.prj` appeared as soon as a CRS was supplied. Copy, move, back up and
delete them as a unit — and note that losing one **does not raise**: with the `.dbf`
deleted, `fiona.open(path)` still opened the layer and still returned the right geometry,
but the schema came back `{'properties': {}, 'geometry': 'Point'}` and every feature's
`properties` was empty. A half-copied Shapefile reads as a layer with no attributes rather
than as an error.

### Drivers

This GDAL registers eleven drivers in all: `GTiff`, `COG` and `VRT` (raster only), `MEM`
(raster *and* vector), the five vector drivers `ESRI Shapefile`, `GeoJSON`, `GeoJSONSeq`,
`ESRIJSON` and `TopoJSON`, and `GNMFile` and `GNMDatabase`, which are network drivers and
are not vector-capable. fiona keeps the five, and its mode table marks `ESRI Shapefile`,
`GeoJSON` and `GeoJSONSeq` as read/append/write and `ESRIJSON` and `TopoJSON` as read-only.
**No GPKG, no SQLite, no GML, no GPX, no CSV, no FlatGeobuf, no DXF, no OpenFileGDB, no
MapInfo, no DGN and no S57** — convert those off-device.

Ask both lists rather than trusting either alone.
[`fiona.supported_drivers`](https://fiona.readthedocs.io/en/stable/fiona.html#module-fiona.drvsupport)
is what `fiona.open` will accept; `with fiona.Env() as env: env.drivers()` is OGR's
vector-capable subset of the registry, and it returns **six** names, not five. The sixth is
`MEM`, which registers with `DCAP_VECTOR` — but fiona's static table has no `MEM` entry, so
`fiona.open(..., driver="MEM")` raises `DriverError: unsupported driver: 'MEM'` before any
native call.

### Coordinate systems

There is no `proj.db` and no `GDAL_DATA` on either platform, so **spell CRSes as
proj-strings or WKT** and everything works with nothing supplied:

```python
from fiona.crs import CRS

CRS.from_string("+proj=longlat +datum=WGS84 +no_defs")  # works
CRS.from_epsg(4326)  # CRSError: ... Cannot find proj.db
```

[`CRS.from_string("EPSG:4326")`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.crs.CRS.from_string)
fails the same way; the string form is not a way around it. What you give up is discovery —
`to_string()` on a CRS built from a proj-string returns `GEOGCS["unknown", …]` rather than
`"EPSG:4326"`, because naming a CRS means identifying it against the authority database, so
you have to know the projection parameters yourself.

Writing a layer with **no** CRS at all is fine, and is what the example does: on an
arm64-v8a emulator at 200 features per layer, GeoJSON and Shapefile round trips came back
with 0 geometry-type, integer and string mismatches, and worst coordinate residuals of
1.4e-14 through GeoJSON (a text format) against exactly 0 through the Shapefile.

[`fiona.transform`](https://fiona.readthedocs.io/en/stable/fiona.html#module-fiona.transform)
reprojects between proj-string CRSes on both platforms. It is the one module a plain
`import fiona` does not load, so reaching for it is a decision rather than a side effect —
see **App size** for what that costs on iOS.

To get EPSG codes back you would ship a `proj.db` as an app asset and point fiona at it —
`GDALEnv.start` honours `PROJ_DATA` from the environment, and
`fiona._env.set_proj_data_search_path(path)` is in the shipped wheel, with
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir)
naming where a bundled `src/assets/` lands on device. **That has not been run on a device
for this recipe**, and on iOS `fiona._env` and `fiona.crs` carry separate statically linked
copies of PROJ, so a database supplied through one is not the one the other reads.
[`pyproj`](../pyproj), [`gdal`](../gdal) and [`rasterio`](../rasterio) sit on the same
native chain and lose the same files.

### Threading

**Two threads must not share one `Collection`, and getting it wrong loses data without
raising anything.** Measured on a desktop fiona: eight threads each iterating the same open
`Collection` five times returned the correct feature count on only 15, 18 and 20 of 40
iterations across three runs — and raised **zero** exceptions. Giving each thread its own
`fiona.open` returned 40 of 40 correct on each of three runs.

That is worse than it sounds under
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), which
submits to a shared pool, so two taps really do overlap — and which never retrieves the
worker's future, so even a raised exception would surface nowhere. Open one `Collection` per
thread, or hold a `threading.Lock` around the whole use **including consuming the
iterator**: a half-read `Collection` is still an open handle.

There is no per-thread environment to enter by hand: `fiona.open` carries the
`@ensure_env_with_credentials` decorator and `fiona/env.py` keeps its `GDALEnv` in a
`threading.local`, so a worker thread gets its own environment and its drivers with no
preamble, and an explicit
[`fiona.Env()`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.env.Env) adds
nothing. Auto-update does not reach background threads either, so end a `run_thread` handler
with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### App size

Android: 0.84–0.96 MB of compressed wheel and 1.8–2.6 MB unpacked per ABI, on top of roughly
21–23 MB of shared native libraries per ABI that come with GDAL. iOS: 1.0 MB compressed and
3.1–3.2 MB unpacked per slice, on top of `flet-libgdal`'s own 9.6–10.4 MB compressed
(27.6–29.3 MB unpacked), which is one shared `libgdal.dylib` for every consumer in the app.
Plain `import fiona` maps seven of the eight, and the two platforms are now within a factor
of two of each other for the same work — about 2 MB of native code on Android arm64-v8a
against about 2.9 MB on the iOS device slice, plus the one shared `libgdal` each.

There is nothing here worth naming to
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) — the payload
is extensions and a little Python, with no test suite or data directory to drop. On Android,
use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI; that lever is worth more here than the wheel figures
suggest, because the 21–23 MB of native library is carried once per ABI. These numbers
describe the package payload, not the amount added to the final APK or IPA; packaging and
compression determine that.

Budget build-machine time and disk too. Each iOS slice pulls a roughly 113 MB GDAL wheel
that is one half-gigabyte static archive plus headers, and Flet's cleanup then deletes all
of it, so expect a slow first `ipa` or `ios-simulator` build.

### Android

Everything imports, `fiona.transform` included, and there is one GDAL: all eight extensions
resolve every `GDAL*` and `OGR*` entry point out of a single shared `libgdal.so` at load
time, so the driver table `fiona.Env()` registers into is the one `fiona.open` reads and the
two lists agree. Verified on an arm64-v8a Android 14 emulator with `fiona` as the only
dependency: GeoJSON and ESRI Shapefile, each carrying 200 Point and 200 Polygon features out
and back, all four layers reading back 200 of 200 with 0 type, integer and string
mismatches.

Android logs `Cannot find header.dxf (GDAL_DATA is not defined)` to logcat at startup. It is
expected here and stops nothing.

### iOS

All eight extensions link one `libgdal.dylib`, the same way Android's link one `libgdal.so`,
so there is a single driver registry and a single configuration:
[`fiona.Env()`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.Env) options reach
the code doing the I/O, and nothing on this page needs a platform caveat.

The delivery is the only iOS-specific part, and it is invisible from Python. flet relocates
each extension into its own `*.framework` bundle while the dylib stays a plain file in
`opt/lib`, so `fiona/__init__.py` loads it `RTLD_GLOBAL` before the first extension import —
without that, the import fails with `Library not loaded: @rpath/libgdal.dylib`. The shim is
inert on Android and on a desktop.

### Other considerations

**Your desktop is not a preview of the device.** `flet run` cannot see fiona at all with the
install shape above, and a desktop fiona installed by hand is a different package: PyPI's
macOS wheel bundles its own — older — GDAL and its own `proj_data`, and reported 17 entries
in `supported_drivers`, 55 from `Env().drivers()` and a working `CRS.from_epsg(4326)`.
Twelve of those 17, including `CSV`, `GML`, `GPKG`, `GPX`, `OpenFileGDB` and `SQLite`, are
absent from the mobile registry. To approximate the device's *data* situation locally,
run with `GDAL_DATA`, `PROJ_DATA` and `PROJ_LIB` pointed at an empty directory. That proxy is
worth trusting because it was checked: the device reproduced those numbers exactly. It is how the
CRS findings above were established. It will not show you the driver set, and on iOS it will
not show you the split.

Leave Flet's
[compilation and cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) on.
Nothing in the package reads its own source and it carries no data file of its own, so
compiling to `.pyc` is safe and the default cleanup only takes Cython headers.

## Things to know

- **`FionaNullPointerError` is not a `FionaError`.** `fiona/_err.pyx` defines
  `class FionaNullPointerError(CPLE_BaseError)` and `class CPLE_BaseError(Exception)`, with
  no relation to anything in `fiona/errors.py` — the measured MRO is
  `FionaNullPointerError → CPLE_BaseError → Exception`, and
  `isinstance(err, fiona.errors.FionaError)` is `False`. So
  `except fiona.errors.FionaError` will not catch it, and an uncaught exception in a Flet
  handler ends the session with a crash screen. Catch bare `Exception` around fiona calls
  and render `type(err).__name__` alongside `str(err)`.

- **Always pass `driver=` explicitly when writing.** Left out,
  [`fiona.open`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.open) calls
  [`driver_from_extension`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.drvsupport.driver_from_extension),
  which builds its extension map by asking every driver in `supported_drivers` for its
  metadata and raises `FionaValueError: Could not find driver '<name>'` the moment
  `GDALGetDriverByName` returns NULL — so on iOS the convenient form fails inside the empty
  table before it ever reaches your file. On a working platform the same omission gives
  `ValueError: Unable to detect driver. Please specify driver.` for an extension it does not
  recognise, so the two failures look nothing alike.

- **`fiona.supported_drivers` is filtered at import — against the wrong table on iOS.**
  `fiona/drvsupport.py` runs `_filter_supported_drivers()` at module scope, intersecting
  fiona's static table with `Env().drivers()`, which loops `OGRGetDriverCount()` inside
  `fiona._env`. On Android that is the same registry `fiona.open` uses. On iOS it is not, so
  an app that checks the driver list before writing gets a green light from a table
  `fiona.open` never consults.

- **`fiona.driver_count()` is not the number of drivers you can use.** It is
  `GDALGetDriverCount() + OGRGetDriverCount()` evaluated inside `fiona._env`, so it counts
  every registered driver plus the vector-capable ones a second time. It read 124 on a
  desktop where `fiona.supported_drivers` held 17 names and `Env().drivers()` held 55. Read
  it off a device rather than reasoning from it.

- **A round-tripped schema is not the schema you wrote**, so `src.schema == schema` is the
  wrong check. Writing `{"name": "str", "n": "int", "v": "float"}` read back as
  `{"name": "str", "n": "int32", "v": "float"}` from GeoJSON and
  `{"name": "str:80", "n": "int:18", "v": "float:24.15"}` from a Shapefile. The *values*
  round-tripped in both — worst residual 4.44e-16 on the floats — and coordinates came back
  as `tuple`, not `list`. Compare feature values element by element and treat the schema as
  information.

- **A Shapefile holds one geometry type and rewinds your rings.** A layer declared `Unknown`
  whose first feature is a Point becomes a point shapefile, and the next feature raises
  `RuntimeError: GDAL Error: Attempt to write non-point (LINESTRING) geometry to point
  shapefile.`; GeoJSON takes the mixture happily. Separately, an outer ring written
  counter-clockwise comes back with its vertices reversed, because the format fixes the
  winding order; GeoJSON leaves it alone. Keep field names to ten characters or fewer while
  you are at it: DBF truncates silently, and a property written as `a_very_long_name` came
  back keyed `a_very_lon`.

- **GEOS is not compiled in, and neither is libcurl.** Both platforms carry the diagnostics
  *GEOS support not enabled.* and *GDAL/OGR not compiled with libcurl support, remote
  requests not supported.*, and the Android `libgdal.so` holds no `GEOS*` and no `curl_*`
  symbol at all, defined or undefined. So OGR geometry predicates and operations are
  unavailable — use [`shapely`](../shapely) for those — and `/vsicurl/`, `/vsis3/`,
  `/vsigs/` and `/vsiaz/` are dead, which leaves fiona's `session` module nothing to drive.

- **`certifi` is imported on every `import fiona`, from compiled code.** The call is in no
  `.py`: `fiona/_env` does `import certifi` at module scope and puts `certifi.where()` into
  `GDAL_CURL_CA_BUNDLE` and `PROJ_CURL_CA_BUNDLE`. So `certifi/cacert.pem` needs a real
  filesystem path and is unpacked to a temporary file if your site-packages are zipped — and
  do not drop `certifi` from a lockfile on the theory that fiona only declares it, because
  the `try/except` around that import catches `ImportError` only. (`click`, `click-plugins`
  and `cligj` arrive the same way and really are unused here: they exist for the `fio`
  console script, which `fiona/__init__.py` never imports.)

## Build notes (maintainers)

### Recipe shape

Two recipes: `flet-libgdal` builds GDAL, this one consumes it. `patches/mobile.patch`
explains its own hunks and `meta.yaml` comments the Android/iOS `GDAL_LIBS` split next to
it, so what is left here is shape and the bump checklist.

**Almost everything this page warns about is a `flet-libgdal` decision, not a fiona one.**
The eleven-driver registry, the missing `GDAL_DATA` and `proj.db`, the absent GEOS and
libcurl and the iOS static-only link all come from that recipe and from `flet-libproj`. A
`flet-libgdal` bump can invalidate most of this README without a line changing here, which
is why the pin in `meta.yaml` is exact.

`flet-libgdal` is `requirements.host` rather than `requirements.host_build`, so it ships and
lands in `Requires-Dist` on both platforms. That is load-bearing on Android, where the
extensions resolve `libgdal.so` by bare soname at load, and redundant but harmless on iOS,
where the wheel's payload is a static archive plus headers that Flet's cleanup deletes.

**`flet-libgdal` must stay SHARED on iOS, and `GDAL_LIBS` must stay `gdal`.** A static
`libgdal.a` is copied into every extension that links it, giving each its own GDAL — its own
driver registry and its own configuration. fiona registers in `_env` and resolves driver
names in `ogrext`, so those would stop being the same table: `Env().drivers()` lists a full
registry while every `fiona.open` fails. The shared library is what makes them one table, and
it is also why `GDAL_LIBS` is a single entry — the dylib resolves proj, tiff, jpeg, curl,
ssl, crypto and psl internally, so naming that chain here would link it again per extension.

`-undefined dynamic_lookup` must stay off for the same reason: with a real dylib an
unresolved symbol is a defect that has to fail at link, not at `dlopen` on a device.
[`rasterio`](../rasterio), [`pyogrio`](../pyogrio) and [`gdal`](../gdal) share all of this;
change one and re-check the other three.

### Upgrade hazards

- **Bump `flet-libgdal` and this recipe together**, and re-read every claim above off the
  built wheels rather than assuming the Python layer moved alone.
- **The Android C++ runtime declaration is one line from being lost.** `_transform.so` is
  the only extension whose `DT_NEEDED` names `libc++_shared.so`; `libgdal.so` itself does
  not need it, because its undefined C++ symbols are covered by `libproj.so`'s statically
  linked libc++ and by bionic. So the `flet-libcpp-shared` entry buys exactly
  `import fiona.transform`, and losing it costs exactly that one import — silently, because
  every other test still passes.
- **`serious_python`'s junk-file globs list `**.pxd` and not `**.pxi`**, so `fiona/gdal.pxi`
  (about 36 KB) ships to the device for nothing. That is a claim about another project's
  current source; recheck it before repeating it, and drop this note if the glob gains
  `**.pxi`.
- **The example is the live regression test.** Bumping this recipe means bumping
  [`feature-roundtrip`](examples/feature-roundtrip)'s `fiona==` pin and rebuilding it on both
  platforms; its sections map one-to-one onto the claims above.

### Re-verification checklist

- **`Requires-Dist` in the built Android wheel** still names `flet-libcpp-shared`, and
  `test_transform_loads_and_reprojects` still exists — it is the only test that would go red.
- **The linkage split.** Android: `DT_NEEDED` still naming `libgdal.so` by bare soname,
  `libc++_shared.so` on `_transform` and nowhere else, `ogrext` still defining zero GDAL
  symbols, and 16 KB `PT_LOAD` alignment everywhere. iOS: still eight `MH_DYLIB`, still
  exactly five carrying GDAL, and `_env` still the only image with a `RegisterOGR*` in it.
  If iOS ever links dynamically, the **iOS** section and every size figure change together.
- **The driver set**, from the symbol tables on both platforms — Android's `libgdal.so` is
  stripped, so read it from dynamic symbols rather than `nm`. Two traps. The exported
  `GDALRegister_*`/`RegisterOGR*` names are a superset of what is actually called: follow
  the `BL` targets out of `GDALAllRegister` instead, which is how the eleven above were
  fixed. And a name says nothing about vector capability — `MEM` registers with
  `DCAP_VECTOR` and shows up in `env.drivers()` — so read each registration function's
  `DCAP_*` strings, not its name.
- **Nothing reads its own source and the wheel ships no data file**, which is what makes
  the no-`extract_packages` and leave-compilation-on advice safe. Re-grep every `.py` for
  `__file__`, `importlib.resources`, `pkgutil`, `pkg_resources`, `ctypes`, `find_library`
  and `inspect.getsource`; today the hits are Windows guards in `_path.py`, `vfs.py` and
  `__init__.py` plus a `platform.system()` in `_show_versions.py`'s printout, all inert.
- **The sizes are measured.** Re-measure rather than adjusting by eye. They are also the
  cheapest regression signal there is: an iOS slice that comes back tens of MB means
  `flet-libgdal` went back to a static archive and every extension absorbed its own copy.

### Coverage gaps

- **`test_supported_drivers` asks the wrong table.** It checks two names in a dict
  `_filter_supported_drivers()` builds from `_env`'s registry — exactly the table that is
  *not* the one in question on iOS. `test_write_read_geojson` is what covers `ogrext`, and it
  must keep writing with a proj-string CRS: an authority code fails at the CRS before it
  reaches the driver, which is how the write looked impossible on iOS for so long. Worth
  adding: an assertion over the exact six names `fiona.Env().drivers()` returns, so a driver
  appearing is as red as one vanishing.
- **Nothing covers whether an `Env()` option reaches `ogrext` on iOS.** The limit stated
  under **iOS** follows from the linkage, not from a run.
- **The `proj.db`-as-asset lever has never been run on a device.** It is also the claim most
  likely to be wrong as written: [`pyproj`](../pyproj) carries eight separate PROJ copies on
  iOS, so an API call that sets a data directory configures whichever copy it lands in, while
  an environment variable is read by every copy. Prefer `PROJ_DATA` if anyone tries it.
