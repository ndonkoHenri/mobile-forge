import pytest


def test_gdal_version():
    """`rasterio.__gdal_version__` reads from `rasterio._base` (a Cython
    extension that links libgdal). Confirms the native extension loaded
    and libgdal is reachable — the canary for the GDAL_LIBS link
    declared in meta.yaml (mirrors recipes/pyogrio's test_gdal_version).
    """
    import rasterio

    v = rasterio.__gdal_version__
    # `__gdal_version__` is a "MAJOR.MINOR.PATCH" string in modern
    # rasterio. Be tolerant about extra suffixes like "3.10.0e".
    parts = v.split(".")
    assert len(parts) >= 2, f"unexpected GDAL version string: {v!r}"
    assert int(parts[0]) >= 3, f"GDAL major < 3: {v!r}"


def test_drivers_listed():
    """Imports `rasterio.drivers`, which loads `rasterio._base`.

    `is_blacklisted` is a pure-Python dict lookup, so the driver registry
    itself goes untested here; `test_geotiff_round_trip` and
    `test_shutil_sees_and_copies_a_dataset` cover it."""
    import rasterio
    from rasterio.drivers import is_blacklisted

    # Built-in driver — should not be blacklisted.
    assert is_blacklisted("GTiff", "r") is False


def test_geotiff_round_trip(tmp_path):
    """Write a GeoTIFF and read it back — the path listing drivers does not cover.

    Guards the single driver registry, which `test_drivers_listed` cannot: a
    static libgdal gives each extension its own GDAL and its own registry.
    `rasterio.Env()` registers inside `_env`, while `rasterio.open` resolves the
    driver name inside `_base`, whose registry is then empty. The failure is
    `DriverRegistrationError: ('No such driver registered: %s', b'GTiff')`
    raised in a process that lists GTiff as available.

    So this asserts the round trip rather than the registry: write real pixels
    through the GTiff driver, read them back, and compare. A wheel that can
    list drivers but not open a dataset fails here and passes everything else.
    """
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    path = tmp_path / "round-trip.tif"
    data = (np.arange(64 * 64, dtype="float32").reshape(64, 64) / 64.0)

    with rasterio.open(
        path, "w", driver="GTiff", height=64, width=64, count=1,
        dtype="float32", crs="+proj=latlong", transform=from_origin(0, 0, 1, 1),
    ) as dst:
        dst.write(data, 1)

    assert path.exists() and path.stat().st_size > 0

    with rasterio.open(path) as src:
        assert src.driver == "GTiff", src.driver
        assert (src.width, src.height, src.count) == (64, 64, 1)
        read_back = src.read(1)

    assert read_back.dtype == data.dtype
    assert int((read_back != data).sum()) == 0, "pixels differ after a round trip"


def test_shutil_sees_and_copies_a_dataset(tmp_path):
    """`rasterio.shutil` resolves driver names in its own module — cover it too.

    `_base`, `_io` and `shutil` are the three modules whose own code calls
    `GDALGetDriverByName`, so a static libgdal would leave each with a registry
    of its own to populate. `test_geotiff_round_trip` covers the first two.

    `exists` is the interesting half. It identifies a format by asking every
    registered driver, and asking none of them is not an error — so with an
    empty registry it reports False for a file just written, and nothing
    raises. Assert the True, or the bug reads as a normal answer.
    """
    import numpy as np
    import rasterio
    import rasterio.shutil
    from rasterio.transform import from_origin

    source = tmp_path / "source.tif"
    with rasterio.open(
        source, "w", driver="GTiff", height=8, width=8, count=1,
        dtype="uint8", crs="+proj=latlong", transform=from_origin(0, 0, 1, 1),
    ) as dst:
        dst.write(np.full((8, 8), 7, dtype="uint8"), 1)

    assert rasterio.shutil.exists(str(source)), "a dataset just written reads as absent"

    copied = tmp_path / "copied.tif"
    rasterio.shutil.copy(str(source), str(copied), driver="GTiff")
    assert rasterio.shutil.exists(str(copied))

    with rasterio.open(copied) as src:
        assert int((src.read(1) != 7).sum()) == 0, "pixels differ after a copy"


def test_epsg_codes_work_where_proj_db_reached_the_device():
    """EPSG codes resolve iff PROJ's database is on disk — assert whichever holds.

    `flet-libproj` ships `proj.db` in `opt/share/proj`, a real directory on iOS,
    and the preload shim points `PROJ_DATA` at it. On Android that tree never
    arrives, so the shim points at pyproj's extracted copy when there is one and
    leaves the variable unset when there is not. Both outcomes are correct for
    their install; asserting the wrong one is the failure this catches.

    Decide from the shipped artifact, not from what PROJ reports, or the test
    passes in both branches and proves neither. The candidates follow
    `rasterio/env.py`'s own precedence: a set `PROJ_DATA`/`PROJ_LIB` is the only
    place PROJ looks, so a bundled directory elsewhere must not count. A
    proj-string transform is the control and must work either way.
    """
    import os

    import rasterio
    from rasterio.crs import CRS
    from rasterio.errors import CRSError
    from rasterio.warp import transform

    wgs84 = "+proj=longlat +datum=WGS84 +no_defs"
    mercator = "+proj=merc +a=6378137 +b=6378137 +lon_0=0 +units=m +no_defs"
    xs, ys = transform(wgs84, mercator, [4.3517], [50.8503])
    # Closed form: x = a*lon, y = a*ln(tan(pi/4 + lat/2)), radians, a = 6378137.
    assert abs(xs[0] - 484429.03) < 0.01, xs
    assert abs(ys[0] - 6594856.12) < 0.01, ys

    package = os.path.dirname(os.path.abspath(rasterio.__file__))
    env_var = next((v for v in ("PROJ_DATA", "PROJ_LIB") if os.environ.get(v)), None)
    if env_var:
        # The shim's choice (iOS: opt/share/proj; Android: pyproj's extracted
        # copy), or the app's own.
        roots = os.environ[env_var].split(os.pathsep)
    else:
        roots = [
            # where flet-libproj ships it
            os.path.join(os.path.dirname(package), "opt", "share", "proj"),
            # where rasterio's own PyPI wheel bundles one on a desktop
            os.path.join(package, "proj_data"),
        ]
    have_db = any(os.path.exists(os.path.join(r, "proj.db")) for r in roots)

    if have_db:
        assert CRS.from_epsg(4326).to_epsg() == 4326
        # 15E is UTM zone 33's central meridian, so the easting is the 500000
        # false easting exactly — checkable from the definition, not from a run.
        xs, ys = transform("EPSG:4326", "EPSG:32633", [15.0], [60.0])
        assert abs(xs[0] - 500000.0) < 0.01, xs
        assert abs(ys[0] - 6651411.19) < 0.5, ys
    else:
        with pytest.raises(CRSError):
            CRS.from_epsg(4326)
        with pytest.raises(CRSError):
            transform("EPSG:4326", "EPSG:32633", [15.0], [60.0])
