# pyproj control points

One screen of coordinate maths that checks its own answers. Every projected coordinate is
differenced against arithmetic written in `src/coordinates.py`, so what you read on the
device is a residual in millimetres rather than a claim. `src/main.py` is the Flet layer
and nothing else.

It carries no data file of its own. PROJ's database ships with the wheels: iOS finds it
automatically, and on Android the app's `pyproject.toml` extracts pyproj so the database is
on disk rather than inside Flet's `sitepackages.zip`:

```toml
[tool.flet.android]
extract_packages = ["pyproj"]
```

Leave that out and pyproj has no data directory on Android, so every row below except the
version strings and the geodesics reports `DataDirError`.

What it demonstrates:

- **Geodesics that need no projection** —
  [`Geod`](https://pyproj4.github.io/pyproj/stable/api/geod.html) distances checked against
  a Vincenty inverse implemented in the app, and `Geod.fwd` walking back the azimuth
  `Geod.inv` returned to see how far it misses.
- **Projections from `+proj=` strings** — Web Mercator differenced
  against its closed form, UTM 33N and the British National Grid against a transverse
  Mercator series written in the app. A round trip is deliberately *not* the check: a
  string with the wrong zone, ellipsoid or unit inverts as cleanly as the right one and
  still reads 0.0000 mm. The round trips are printed on their own line, where all they
  measure is whether the National Grid's `+towgs84` Helmert reverses — it does, to a
  millimetre.
- **The [`always_xy`](https://pyproj4.github.io/pyproj/stable/api/transformer.html) trap,
  shown rather than described** — a latitude-first CRS transformed twice from the same
  argument pair, so the swap is visible on screen.
- **An authority code** — `CRS.from_epsg(4326)`, which needs the database rather than a
  projection's parameters. It prints `WGS 84` on both platforms, and reports the error on
  screen instead of swallowing it, so a build that lost the database says so.
- **A vectorised round trip on a [`ft.Slider`](https://flet.dev/docs/controls/slider/)**
  — up to 200,000 points through `array('d')` buffers with no numpy, run in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread).

Nothing here reaches the network. The app pins `PROJ_NETWORK=OFF` before importing pyproj
and prints the switch back to you, and no other download path is touched.

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

On a desktop run (`uv run flet run`) the version row shows the PROJ release the PyPI wheel
bundles, the data-directory row points into that wheel's own database, and the timings move
on every run.
