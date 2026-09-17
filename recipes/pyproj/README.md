# pyproj

[`pyproj`](https://pyproj4.github.io/pyproj/stable/) is the Python interface to
[PROJ](https://proj.org/), the library underneath every GIS: it turns latitude and longitude
into metres on a map, converts one datum into another, and answers distance-and-bearing
questions on the WGS-84 ellipsoid. On a phone that is what stands between a GPS fix and a
coordinate anyone else can use — plotting a track on a national grid, showing metres rather
than degrees, or consuming survey data published in a projection your device knows nothing
about. It computes all of that in-process, with no network. PROJ's database, `proj.db`, ships
with these wheels, so EPSG codes resolve on iOS with no configuration and on Android once the
app extracts pyproj — the one line under **Install**.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pyproj",
]

[tool.flet.android]
extract_packages = ["pyproj"]   # without this the database stays in the zip
```

On Android the database travels inside pyproj, and a file inside Flet's `sitepackages.zip` is
not a path PROJ can open, so the package has to be extracted to disk. `extract_packages` is
read from **your** pyproject and is never inherited from a dependency, so nothing sets it on
your behalf. Miss it and `import pyproj` still succeeds, then every `CRS` and `Transformer`
call raises `DataDirError` — proj-strings included. iOS ignores the table.

pyproj needs **Python 3.11 or newer**, so set the app's `requires-python` to at least
`>=3.11`. Leaving it at the `>=3.10` that `flet create` writes does not fail the resolve —
which is what makes it worth saying. uv simply splits, taking an older pyproj for the
`<3.11` range and the current one above it. The older one has no wheel on this index, so
what you get is a build that resolves cleanly and then cannot find a mobile wheel for the
low split.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`control-points`](examples/control-points) — geodesics, proj-string projections and an EPSG
  lookup, each printing its own residual.

## Usage in a Flet app

Build a transformer once and put its result on screen:

```python
import flet as ft
import pyproj

# always_xy=True, and feed it (lon, lat) — see Things to know
to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32633", always_xy=True)
easting, northing = to_utm.transform(15.0, 60.0)

position = ft.Text(f"{easting:,.1f} m E   {northing:,.1f} m N")
```

### The PROJ database

PROJ refuses to build a *context* until it finds a directory holding a file called `proj.db`,
and every
[`CRS`](https://pyproj4.github.io/pyproj/stable/api/crs/crs.html#pyproj.crs.CRS),
[`Proj`](https://pyproj4.github.io/pyproj/stable/api/proj.html#pyproj.Proj),
[`Transformer`](https://pyproj4.github.io/pyproj/stable/api/transformer.html#pyproj.transformer.Transformer),
`database` and `network` call goes through one.
[`Geod`](https://pyproj4.github.io/pyproj/stable/api/geod.html#pyproj.Geod) does not, and works
with no data directory at all (Paris → London measured 343,915.771 m). The database reaches
that directory differently on each platform:

- **iOS:** `flet-libproj` ships it in `opt/share/proj`, a real directory inside the app, and
  `pyproj/__init__.py` sets `PROJ_DATA` and `PROJ_LIB` to it before the first extension
  import — unless either is already set.
- **Android:** that `opt/` tree never reaches site-packages, so the database ships inside
  pyproj itself, at `pyproj/proj_dir/share/proj/proj.db`. pyproj looks there before
  `PROJ_DATA`, so once **Install**'s `extract_packages` has put it on disk it is found with
  no code.

The same shared PROJ is what [`gdal`](../gdal), [`fiona`](../fiona), [`rasterio`](../rasterio)
and [`pyogrio`](../pyogrio) link, so one database serves the whole app. On Android those
packages find pyproj's extracted copy without importing pyproj, which is why an app using them
there needs pyproj installed and extracted to resolve EPSG codes.

**With no database on disk** — Android without extraction — `import pyproj` still succeeds,
emitting `UserWarning: Valid PROJ data directory not found…`, and everything but `Geod` raises
[`pyproj.exceptions.DataDirError`](https://pyproj4.github.io/pyproj/stable/api/exceptions.html#pyproj.exceptions.DataDirError):
`CRS.from_epsg`, `CRS("EPSG:3857")`, `CRS("+proj=utm …")`, `Proj`, `Transformer.from_crs`,
`Transformer.from_pipeline`, `database.get_authorities()`, `datadir.get_data_dir()`,
`network.is_network_enabled()` and `show_versions()`. It fails loudly, but at the *first* CRS
call rather than at import — typically inside an event handler, where an unhandled exception
ends the session with a crash screen.

**Proj-strings and WKT need no database content.** They name a projection by its parameters,
so wherever pyproj has a data directory they behave identically on both platforms, and they are
the portable choice for code that must run on both. The accuracy cost is nil, because a
proj-string reproduces the authority definition exactly: `+proj=merc` against EPSG:3857 at Paris, `+proj=utm +zone=33` against
EPSG:32633 at 15°E 60°N and `+proj=tmerc …` against EPSG:27700 at London each agreed **bit for
bit** with the same transform run against the full database. What you give up is discovery —
you have to know the parameters, and `CRS(code).name`, `.area_of_use` and the `database` module
are closed to you. The [`control-points`](examples/control-points) example projects this way
and keeps authority codes to a single row.

**An empty `proj.db` is only for an Android app that skips extraction** — one that uses
proj-strings alone and does not want the database extracted to disk. `get_data_dir()` checks
only that a file of that name exists, so a zero-byte one clears `DataDirError` for the
proj-string API, at a cost of one `UserWarning: pyproj unable to set PROJ database path.` per
context; authority codes then raise `CRSError: … no database context specified`. Plant it only
when no database was found:

```python
import os

import pyproj
from pyproj.exceptions import DataDirError

try:
    pyproj.datadir.get_data_dir()
except DataDirError:  # Android without extract_packages
    stub = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "proj")
    os.makedirs(stub, exist_ok=True)
    open(os.path.join(stub, "proj.db"), "ab").close()
    pyproj.datadir.set_data_dir(stub)
```

Setting `PROJ_DATA` to a stub unconditionally instead would displace the real database on iOS,
where the shim leaves an existing value alone.

**Your own database — a newer PROJ data release — or datum grids** ship as an asset. Point
both mechanisms at the directory holding them:

```python
proj_dir = os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "proj")
os.environ["PROJ_DATA"] = proj_dir        # before `import pyproj`; the GDAL packages read it
pyproj.datadir.set_data_dir(proj_dir)     # after it
```

`set_data_dir` is the one that matters for pyproj on Android:
[`get_data_dir`](https://pyproj4.github.io/pyproj/stable/api/datadir.html#pyproj.datadir.get_data_dir)
prefers it, then pyproj's own `proj_dir`, and only then `PROJ_DATA`, so the extracted copy
outranks the variable. The variable is still worth setting, because it is the only one that
applies before any import — PROJ reads it when a context is first created — and the GDAL
packages' shims leave a value you set alone. Both mechanisms were verified in the main thread
and in worker threads, which build their own PROJ context.
[`append_data_dir`](https://pyproj4.github.io/pyproj/stable/api/datadir.html#pyproj.datadir.append_data_dir)
adds a directory without displacing the first, which is how you add grid files and keep the
shipped database: PROJ takes the *database* from the first entry and treats the rest as search
paths.

**A database from another PROJ release has to match its layout version.** PROJ validates
`DATABASE.LAYOUT.VERSION.MAJOR`/`MINOR` and rejects a mismatch with *"It comes from another
PROJ installation"*. The database in the same-version PyPI wheel declares layout 1.4 and
`PROJ.VERSION 9.5.1`, and PROJ 9.5.0, which `flet-libproj` builds, wants layout 1.4 as well and
accepted that exact file. Confirm any other database on the device you ship.

### Storage

The shipped database needs no storage decision. An empty stub is app-private state rather than
an asset, which is why the snippet above creates it under
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— durable, and a real filesystem path on both platforms.

A database of your own, and any grid file, ships with the application instead: put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and read
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir) for
the absolute path to hand `set_data_dir` or `append_data_dir`. Keep a 9 MB database out of app
storage unless the app downloads it itself — an asset costs nothing to install and nothing to
keep current.

### Grids and the network

No transformation grid ships beside the database, and most transforms do not need one. Where
one *is* wanted — datum shifts like OSTN15 for the British National Grid, or NADCON for NAD27 — PROJ
silently falls back to a lower-accuracy operation instead of failing, which is the trap under
[Things to know](#things-to-know). Bundle the grid as an asset and `append_data_dir` its
directory, or use one of the two independent download paths, **both of which are off unless you
turn them on**:

- **PROJ's own fetcher** (libcurl, endpoint `https://cdn.proj.org`) is compiled in on both
  platforms and defaults to off: `_context.pyx` reads
  `strtobool(os.environ.get("PROJ_NETWORK", "OFF"))` at import, and
  [`set_network_enabled`](https://pyproj4.github.io/pyproj/stable/api/network.html#pyproj.network.set_network_enabled)
  flips it afterwards.
- **pyproj's own downloader** —
  [`TransformerGroup.download_grids`](https://pyproj4.github.io/pyproj/stable/api/transformer.html#pyproj.transformer.TransformerGroup.download_grids)
  over `urllib.request.urlretrieve` in `sync.py` — ignores `PROJ_NETWORK` entirely.

Turning the fetcher on is not a safety net either: when a fetch failed, the transform returned
`(inf, inf)` rather than falling back. Assume no signal.

To prove an app really is offline, a Python `socket` stub is no help — PROJ's fetcher is
libcurl, underneath Python entirely. Point `PROJ_NETWORK_ENDPOINT` at a local HTTP server that
logs every hit, and cover the Python half separately with a `sys.addaudithook` watching
`socket.connect`, `getaddrinfo` and `urllib.Request`, where `sync.py`'s `urlretrieve` would
show up. Importing pyproj, building `Transformer.from_crs("EPSG:4326", "EPSG:27700")`,
transforming and reading `TransformerGroup(...).best_available` made **zero requests** and
recorded zero events that way, while the same sequence with `PROJ_NETWORK=ON` made one —
`GET /uk_os_OSTN15_NTv2_OSGBtoETRS.tif` — which is what says the probe would have caught a leak.

### Threading

**`Transformer` and `CRS` objects are safe to share across threads, by design.** Both hold a
`threading.local` and rebuild their Cython object per thread on first use, and PROJ contexts
are thread-local too. Eight threads driving one shared `Transformer`, one shared `CRS` and one
shared `Geod`, each over its own disjoint slice of points so a shared-state bug could not hide
behind identical inputs, matched a single-threaded reference element for element across 48,000
calls, with zero exceptions.

**The transform loop releases the GIL**, so a projection in a worker thread genuinely runs
beside the UI. Clocked against a pure-Python counter thread, `Transformer.transform` let that
counter keep 93–99% of the rate an idle main thread allows — the same band as `hashlib.sha256`,
which also releases the GIL, and three to thirteen times what GIL-holding `math.factorial`
leaves it.

Two objects are explicitly *not* thread-safe, and pyproj's own docstrings say so: the
`Transformer`s and `CoordinateOperation`s handed out by
[`TransformerGroup`](https://pyproj4.github.io/pyproj/stable/api/transformer.html#pyproj.transformer.TransformerGroup)
(they wrap `TransformerUnsafe`, which skips the per-thread rebuild), and the one returned by
[`get_last_used_operation`](https://pyproj4.github.io/pyproj/stable/api/transformer.html#pyproj.transformer.Transformer.get_last_used_operation).
Use those on the thread that made them.

The standing Flet caveats apply on top:
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) never
retrieves the worker's future, so an exception inside one surfaces nowhere — wrap the body —
and auto-update does not reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### App size

Everything in the wheel except the extensions is about 545 KB on every slice. On Android:

| slice | wheel | unpacked | the ten extensions |
| --- | --- | --- | --- |
| Android arm64-v8a | 0.49 MB | 1.6 MB | 1.04 MB |
| Android armeabi-v7a | 0.46 MB | 1.3 MB | 0.72 MB |
| Android x86_64 | 0.52 MB | 1.6 MB | 1.02 MB |

On iOS the extensions link the shared `libproj.dylib` rather than carrying PROJ, and the wheels
are 0.55–0.58 MB.

Those are decimal MB; `du -h` and the Finder report binary units and read about 5% lower for
the same bytes. The Android table excludes `proj.db`, which only the Android wheel carries: it is
9.26 MB unpacked and brings that wheel to about 2.3 MB. Extracting pyproj adds
`assets/extract.zip`, about 9.6 MB, to the APK.

Both platforms load PROJ from a separate shared library on top of that — on Android a chain of
about 7.5 MB on arm64-v8a, 5.2 MB on armeabi-v7a and 8.3 MB on x86_64; on iOS a single
`libproj.dylib`, 9.9–10.4 MB unpacked, which absorbs libtiff, libjpeg, libcurl, libpsl and
OpenSSL rather than chaining to them, shipped beside the 9.26 MB `proj.db` in a `flet-libproj`
wheel of about 5.4 MB per slice. So on Android, use an app bundle, split APKs, or
narrow [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
when the app does not need every ABI; that lever is worth more here than the wheel column
suggests, since the native chain is carried once per ABI. On iOS the same shared
`libproj.dylib` serves every GDAL consumer in the app as well, so a project using pyproj
beside [`rasterio`](../rasterio) or [`fiona`](../fiona) pays for PROJ and its database once;
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) cannot reach
it. Budget for it. These figures describe the package payload, not the exact amount added to
the final APK or IPA; packaging and compression determine that.

### Other considerations

**Your desktop cannot show you a missing `extract_packages`.** `flet run` resolves pyproj from
PyPI, whose wheel bundles `proj_dir/share/proj/proj.db`, so EPSG codes work on your Mac whatever
your pyproject says, and raise on an Android phone when the table is missing. Test the CRS half
on an Android device or emulator, or temporarily move `site-packages/pyproj/proj_dir` aside to
reproduce an unextracted install locally — with no system PROJ on `PATH`, which `get_data_dir`
also searches.

## Things to know

- **`import pyproj` succeeding proves nothing.** On Android without `extract_packages` it
  succeeds with no data directory, with only a `UserWarning` to show for it, and nothing in your
  UI displays that. The failure surfaces at the first `CRS`/`Transformer` call, which is
  typically inside an event handler, where an unhandled exception gives you a crash screen
  rather than a message. Declare the table and wrap the first transform in
  `try/except Exception`.
- **[`pyproj.show_versions()`](https://pyproj4.github.io/pyproj/stable/api/show_versions.html#pyproj.show_versions)
  raises without a data directory** — Android without `extract_packages`. It prints
  `pyproj info:` and then reaches for the database. For a header line that survives that, use
  `pyproj.__version__`, `pyproj.__proj_version__`, `pyproj.__proj_compiled_version__` and `pyproj.geod.geodesic_version_str` — all of which work
  with no data at all — plus `datadir.get_data_dir()` and `network.is_network_enabled()` in
  their own `try/except`.
- **`always_xy=True` on every `Transformer.from_crs`, and feed it `(lon, lat)`.** EPSG:4326's
  authority axis order is latitude-first
  ([`CRS("EPSG:4326").axis_info`](https://pyproj4.github.io/pyproj/stable/api/crs/crs.html#pyproj.crs.CRS.axis_info)
  → `[('Lat','north'), ('Lon','east')]`), so a default transformer reads Paris's `(2.3522,
  48.8566)` as latitude 2.35. It does not raise — to EPSG:3857 it returns
  `(5438691.83, 261919.29)`, a perfectly well-formed Web Mercator pair that is simply wrong.
  `+proj=longlat` strings are longitude-first and unaffected, which is exactly why testing
  against one proves nothing about the EPSG path.
- **A missing grid downgrades the transform silently — this is the one that will hurt you.**
  With the full database present and no grid files (which is every device: the database ships,
  grids do not), `Transformer.from_crs("EPSG:4326", "EPSG:27700")` and the transform that
  follows raise **zero warnings** and return coordinates that look completely normal. PROJ has
  quietly picked *"Inverse of OSGB36 to WGS 84 (6)"*, declared accuracy **2.0 m**, in place of
  the *"(9)"* operation it wanted at **1.0 m**, which needs `uk_os_OSTN15_NTv2_OSGBtoETRS.tif`
  (about 3.0 MB). Run the same points with and without that grid and the error it really costs
  is Edinburgh 0.550 m, London 1.753 m, Cape Wrath 2.171 m, Norwich 3.152 m, Land's End
  4.270 m. Two diagnostics work, both offline: `TransformerGroup(src, dst)` *does* warn, and
  exposes `.best_available` (`False` here), `.unavailable_operations` — each with `.accuracy`
  and `.grids[i].short_name` / `.available` / `.url` — and `.transformers`; and
  `get_last_used_operation()`, once a transform has run, names what actually ran and carries
  its `.accuracy`. Do not reach for the transformer's own `.description` and `.accuracy`
  instead: where PROJ picks the operation lazily they read
  `unavailable until proj_trans is called` and `-1.0` for the object's whole life — after the
  transform exactly as before it.
- **`allow_ballpark=False` and `only_best=True` do not turn that into an error.** Both were
  passed to the same `EPSG:4326 → EPSG:27700` transformer, singly and together, with
  `errcheck=True` on the transform: it built without raising and returned the *same*
  lower-accuracy coordinates. pyproj does forward the flags to PROJ; the fallback here is a
  genuine Helmert operation rather than a ballpark, and `ONLY_BEST` did not fire. Gate on
  `TransformerGroup(...).best_available` instead.
- **`errcheck=True` does not catch an out-of-area point either.** Sydney (151.2093, −33.8688)
  through `EPSG:4326 → EPSG:27700` returns `(2910514.15, −21431829.56)` with and without it —
  large, finite and meaningless. `errcheck` catches PROJ errors (`inf`/`HUGE_VAL`), not
  nonsense. Compare your input against `CRS(code).area_of_use` (EPSG:27700's bounds are
  `(-9.01, 49.75, 2.01, 61.01)`) and range-check the output.
- **A `+towgs84` round trip is not exact, and that is the datum, not a bug.** London out to the
  British National Grid and back landed 1.0080 mm from where it started, Edinburgh 0.7904 mm;
  drop the seven-parameter shift from the same projection string and both go to 0.0000 mm, as
  does UTM 33N, which has no shift. Millimetres, but do not expect a bit-exact round trip
  through a datum transformation.
- **The vectorised path needs no numpy.** pyproj never imports it — `numpy` is absent from
  `sys.modules` after `import pyproj` — so `Transformer.transform` takes lists, tuples and
  `array('d')` buffers through the Python buffer protocol, and `inplace=True` writes back into
  the buffer you passed. Use it: 100,000 points took 3.2 ms against 6.8 ms for 20,000 through a
  scalar loop, about 10× per point. Building the transformer is the expensive part (8.8 ms
  first, 1.8 ms warm) — hoist it out of the loop.
- **`import pyproj` calls `certifi.where()` on every launch.** `pyproj/__init__.py` ends with
  `pyproj.network.set_ca_bundle_path()`, which takes the certifi branch unless
  `PROJ_CURL_CA_BUNDLE`, `CURL_CA_BUNDLE` or `SSL_CERT_FILE` is set — and does so *before* the
  call that can raise `DataDirError`. certifi's Python ≥3.11 branch resolves the path through
  `importlib.resources.as_file`, which materialises a temp copy of the 240 KB `cacert.pem` with
  an `atexit` cleanup when the package lives inside a zip, as it does in Android's
  `sitepackages.zip`. Set one of those environment variables to skip it; leaving it alone is
  only a cost if you are counting launch milliseconds.

## Build notes (maintainers)

### Recipe shape

Two recipes: `flet-libproj` builds PROJ, `recipes/pyproj` consumes it. The three patches explain
themselves in their preambles and `meta.yaml` comments its `script_env` next to it, so what is
left here is shape, the linkage evidence the consumer sections rest on, and
the bump checklist.

**The database lives in a different wheel on each platform, because only iOS can reach
`opt/`.** `flet-libproj` keeps `opt/share/proj/proj.db` and deletes the rest of `share/`. On iOS
that tree is a real directory in the app, so `ios-libproj-preload.patch` sets `PROJ_DATA` and
`PROJ_LIB` to it. On Android the tree never reaches site-packages — an APK's
`sitepackages.zip` has no `opt/` entries, and `copyOpt` lifts only `*.so` into `jniLibs` — so no
`extract_packages` entry can put it on disk. It has to live in a real Python package, and
pyproj's own `PROJ_WHEEL` switch is that route: `stage-proj-db.patch` copies the database from
`PROJ_DIR` into `pyproj/proj_dir` so `get_package_data` has something to package. `PROJ_WHEEL`
is Android-only because iOS already has the file in `flet-libproj`, and a second copy would
add 9 MB for nothing. pyproj is also the carrier for the GDAL consumers on Android, whose shims
look for `pyproj/proj_dir/share/proj` through `find_spec`, so moving the database means
changing all five shims together.

**`flet-libproj` is `requirements.host`, so it lands in `Requires-Dist` on both platforms**,
and both need it at runtime: on Android `libproj.so` must reach `jniLibs`, and on iOS the wheel
carries `libproj.dylib` and `opt/share/proj/proj.db`.

**Android: a chain of shared libraries, resolved by bare soname.** All ten extensions list
exactly `libm.so`, `libproj.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` in
`DT_NEEDED` — no `libc++_shared.so` — with a `RUNPATH` pointing at a build-host directory that
exists on no phone. Harmless: serious_python's Gradle `copyOpt` task flattens every `.so` under
a wheel's `opt/` into `jniLibs/<abi>/` under its plain basename, and `libproj.so` carries
`SONAME libproj.so`. `libproj.so` in turn names `libsqlite3_python.so` (from Flet's Python
bundle), `libtiff.so` and `libcurl.so`; `libtiff.so` names `libjpeg.so` and `libz.so`;
`libcurl.so` names `libpsl.so`, `libssl_python.so`, `libcrypto_python.so` and `libz.so`. That
chain is **7,513,872 bytes of `.so` on arm64-v8a** — `libproj.so` 4,640,656, `libturbojpeg.so`
748,184, `libtiff.so` 744,048, `libcurl.so` 723,712, `libjpeg.so` 589,784, `libpsl.so` 67,488 —
against 5,227,468 on armeabi-v7a and 8,347,680 on x86_64, on top of pyproj's own 1,039,288.
Every `LOAD` segment in all of them, across all three ABIs, reports `align 0x4000`.

**iOS: one shared `libproj.dylib`, the same shape as Android.** `flet-libproj` ships a real
shared library, so all ten extensions name `@rpath/libproj.dylib` in `otool -L` and none of
them carries PROJ itself — check with `nm -a <ext> | grep " [tT] _proj_create"`, which must be
empty for every one. The extensions are 71 KB–535 KB as a result, against a 550–580 KB wheel.

What the dylib absorbs is PROJ's own dependency tree — libtiff (GTiff grids), libjpeg (which
libtiff needs), libcurl (network grids), libpsl and OpenSSL (which libcurl needs) — because
none of those ships as a shared library for iOS. That is why `flet-libproj`'s licence
expression is a composite there and plain MIT on Android, where they are linked by
`DT_NEEDED` instead; the reasoning is written out in that recipe's `meta.yaml`. Verify with
`nm -a` that `_TIFFClientOpen`, `_curl_easy_init`, `_psl_builtin` and `_SSL_CTX_new` are
defined inside `libproj.dylib`, not inside any extension.

SQLite differs across the platforms — Android's `libproj.so` links `libsqlite3_python.so` from
Flet's Python bundle, iOS binds the system `/usr/lib/libsqlite3.dylib` — and either way it is
that SQLite which opens whatever `proj.db` the app supplies.

**`meta.yaml`'s `extract_packages` reaches the recipe's own on-device tests only.** The
recipe-tester passes it to `flet build`; a consumer's build never reads it, which is why
**Install** asks the app to declare it. Beyond `proj.db` in the Android wheel, the wheel ships
no data file, and outside the preload shim in `__init__.py` there is exactly one occurrence of
`__file__`, `importlib.resources`, `pkgutil`, `pkg_resources`, `ctypes`, `find_library`,
`sys.platform`, `platform.system()` or `os.name`: `datadir.py:73`, the probe for
`proj_dir/share/proj` that finds the extracted Android database. All ten extension filenames
carry a full CPython ABI tag, which is what Android's relocation needs. Nothing reads its own
source, so `.pyc` compilation is safe; Flet's default cleanup takes 26 files and 202,508 bytes
of `.pyx`, `.pxd`, `.pyi` and `py.typed`, and leaves two unused `.pxi` at 23,144 bytes.
`certifi` is pure Python and absent from this index, so it resolves from PyPI.

Nineteen wheels come out of one build number: Python 3.12, 3.13 and 3.14 × three Android ABIs
and three iOS slices, plus a legacy 32-bit `android_24_x86` slice on 3.12, which flet-cli
0.86.5 cannot target — its `ANDROID_ARCH_TO_FLUTTER_TARGET_PLATFORM` holds only `armeabi-v7a`,
`arm64-v8a` and `x86_64`. No arch is excluded.

### Upgrade hazards

- **Both halves of the database route fail silently.** `flet-libproj`'s `build.sh` keeps
  `proj.db` only if `make install` wrote it, and `stage-proj-db.patch` returns quietly when
  `PROJ_WHEEL`, `PROJ_DIR` or the source file is missing, or when `proj_dir` already exists. A
  PROJ bump that moves the file, or a pyproj bump that renames `INTERNAL_PROJ_DIR` or reworks
  `get_package_data`, still builds green and ships no database. The checklist below is what
  catches it.
- **The empty-`proj.db` stub lives in pyproj's Python layer, not in PROJ**, so a `flet-libproj`
  bump cannot break it on its own. The file only has to satisfy `datadir.py`'s
  `Path(dir, "proj.db").exists()`. PROJ then *rejects* it — `proj_context_set_database_path`
  returns false and `_context.pyx` warns *"pyproj unable to set PROJ database path"*, which is
  the tell that the stub is in play — and the proj-string API keeps working because it never
  wanted a database. What can break it is a **pyproj** bump that tightens `valid_data_dir`.
- **The behavioural claims in [Things to know](#things-to-know) are PROJ's, not pyproj's**, so a
  `flet-libproj` bump can move any of them without the Python half changing: the silent grid
  downgrade — both the declared accuracies (2.0 m versus 1.0 m for EPSG:27700) and the
  0.55–4.27 m it costs across Great Britain — the inertness of `allow_ballpark`/`only_best`, and
  the `+towgs84` round-trip residual. They are the most consumer-visible claims here and nothing
  asserts them.

### Re-verification checklist

- **The three control points behind "bit for bit".** That claim is the reason the page can tell
  a reader the proj-string route costs no accuracy, so a bump has to re-run it rather than
  re-read it. Against the same transforms with the full database present, all three agreed
  exactly: `+proj=merc +a=6378137 +b=6378137` vs EPSG:3857 at Paris
  `(261845.70624393807, 6250564.349543124)`; `+proj=utm +zone=33 +datum=WGS84` vs EPSG:32633 at
  15°E 60°N `(500000.0000000009, 6651411.190362714)`; and
  `+proj=tmerc +lat_0=49 +lon_0=-2 +k=0.9996012717 +x_0=400000 +y_0=-100000 +ellps=airy
  +towgs84=446.448,-125.157,542.06,0.15,0.247,0.842,-20.489` vs EPSG:27700 at London
  `(530042.625993872, 180380.44930295716)`. A PROJ bump that moves any digit means the
  accuracy sentence in Usage no longer holds.

- **The PROJ version** comes from `flet-libproj`'s `libproj.so` / `libproj.dylib` on both
  platforms, so `strings` on that one file answers it. The version belongs on the
  example's header line, not in an assertion.
- **That PROJ is still SHARED on both platforms, first.** Android: `DT_NEEDED` still naming
  `libproj.so` with no `libc++_shared`, `SONAME libproj.so`, the
  `libtiff`/`libcurl`/`libjpeg`/`libpsl` chain intact, and 16 KB `PT_LOAD` alignment on all ten
  extensions and on `libproj.so`. iOS: ten `MH_DYLIB`s each naming `@rpath/libproj.dylib`, and
  `nm -a <ext> | grep " [tT] _proj_create"` EMPTY for every one. A definition there means the
  link absorbed a static PROJ, which gives each extension a private database search path and
  makes `set_data_dir` configure one of them. The wheel size is the cheap tell:
  it should stay well under a megabyte.
- **A device run of the [`control-points`](examples/control-points) example.** If a pyproj bump
  tightened the data-directory check, every panel becomes a `DataDirError` row — visibly rather
  than silently.
- **The database is present where each platform reads it.** `unzip -l` every `flet-libproj`
  wheel for `opt/share/proj/proj.db` (9,261,056 bytes at PROJ 9.5.0; about 5.4 MB of iOS
  wheel), and every Android pyproj wheel for `pyproj/proj_dir/share/proj/proj.db` (about
  2.3 MB of wheel), which the build log announces as `mobile-forge: staged …`. The iOS pyproj
  wheels should carry none.
- **The Android extraction tell.** In an APK built with `extract_packages = ["pyproj"]`,
  `assets/extract.zip` is about 9.6 MB; 22 bytes means nothing was extracted and EPSG codes will
  raise.
- **The sizes and timings are measured.** Re-measure rather than adjusting by eye, and quote
  decimal.

### Coverage gaps

`tests/test_pyproj.py` covers `import pyproj`, two `Geod` calls, and
`test_epsg_codes_resolve_where_proj_db_reached_the_device`. That test decides from the shipped
file, not from PROJ, whether a database is present; with one, it requires `CRS.from_epsg(4326)`
and an `EPSG:4326 → EPSG:32633` transform landing on the 500000.0 easting at 15°E, 60°N, after
a proj-string control; without one it requires `CRS.from_epsg(4326)` to raise `CRSError` or
`DataDirError`, and runs no control, because pyproj needs a data directory for any transform.
The database branch has passed on an iOS simulator and on an Android emulator.

Not covered on a device:

- **The Android no-extraction shape and the empty stub.** The recipe-tester always extracts
  pyproj, so the test's no-database branch has not run on a device, and the `DataDirError` list
  and the stub's boundary are desktop measurements.
- **A database or grid supplied as an asset**, including the layout-version acceptance of a
  database from another PROJ release.
- **Grids.** The grid-downgrade figures were measured on a desktop PROJ 9.5.1 with a
  downloaded grid; no device has run them, because no grid file ships.
- **The network**: PROJ's fetcher, `download_grids` and the offline probe.
- **Threading and timings**, and the three "bit for bit" control points.
