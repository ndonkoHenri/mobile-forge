# rasterio elevation tile

A GeoTIFF written, read back and differenced against the array it came from. Every panel
prints a count of mismatched elements and a worst absolute residual, so what you read is a
measurement rather than a claim.

A 1024×1024 float32 elevation surface is generated in numpy from a formula in
`src/elevation.py`, written into
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
as a tiled DEFLATE GeoTIFF, and read back several ways. It ships no data file and reaches
no network — everything is generated at runtime. `src/elevation.py` holds every rasterio and
numpy call; `src/main.py` is Flet and the threading around them.

It runs on both platforms: an arm64 Android emulator and an iPhone simulator each wrote and
read the raster back with 0 of 1,048,576 pixels differing. The [recipe page](../..) has the
size breakdown.

What it demonstrates:

- **A GeoTIFF round trip that checks itself** — a full
  [`read`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetReader.read)
  differenced element-wise against the source array, a
  [`Window`](https://rasterio.readthedocs.io/en/stable/topics/windowed-rw.html) read
  differenced against the equivalent numpy slice, and
  [`ds.stats(approx=False)`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetReader.stats)
  against `min`/`max`/`mean`/`std` computed in float64. All three residuals are zero or a
  few times 1e-13.
- **A CRS that needs no database** — the raster is tagged with a `+proj=` string, which PROJ
  parses itself. The profile row prints the CRS as it survived the round trip, and
  `to_epsg()`, which identifies it against the database: `4326` where one reached the device,
  `None` where none did.
- **Georeferencing, which needs no database at all** — a longitude/latitude pair goes
  through [`ds.index`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetReader.index)
  to a row and column and through
  [`ds.sample`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetReader.sample)
  to an elevation, differenced against the same element of the source array. That is the
  affine transform, not the CRS, so it works with or without a database.
- **What the device actually supports**, read from the live registry rather than described:
  `env.drivers()` inside a
  [`rasterio.Env`](https://rasterio.readthedocs.io/en/stable/api/rasterio.env.html#rasterio.env.Env)
  names 147 drivers on a desktop and eleven on a phone, where GDAL was built with four
  raster drivers, five vector ones and the two GNM network ones.
- **An EPSG code** —
  [`CRS.from_epsg(4326)`](https://rasterio.readthedocs.io/en/stable/api/rasterio.crs.html#rasterio.crs.CRS.from_epsg)
  needs PROJ's database. iOS reads the one `flet-libproj` ships; Android reads pyproj's, which
  is why `pyproject.toml` depends on `pyproj` and lists it in `extract_packages`. Drop either
  and that row prints a `CRSError` on Android.
- **Why a window is worth having** — a
  [`ft.Slider`](https://flet.dev/docs/controls/slider/) picks the window side and drives a
  re-read from [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread).
  The worker opens **its own** dataset, because handing one dataset object to several
  threads takes the process down rather than raising.

The `ds.stats(approx=False)` call also leaves an `elevation.tif.aux.xml` beside the raster —
GDAL's statistics sidecar, 385 bytes here — which is why the file has to live in writable
app storage and not in assets.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

A desktop run (`uv run flet run`) uses rasterio's PyPI wheel, a different GDAL with its own
`proj_data`: the version line differs, and the driver line reads `147 drivers` rather than
the eleven a phone registers. Every residual is identical.
