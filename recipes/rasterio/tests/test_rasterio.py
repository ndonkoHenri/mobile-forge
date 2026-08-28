def test_gdal_version():
    """`rasterio.__gdal_version__` reads from `rasterio._base` (a Cython
    extension that links libgdal). Confirms the native extension loaded
    and libgdal is reachable — the canary for the GDAL_LIBS chain
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
    """Touches `rasterio._env` (driver registration) + `rasterio.drivers`.
    Asks for the registered raster driver count to confirm GDAL's
    driver registry initialised inside the Cython binding."""
    import rasterio

    # `rasterio.drivers` is the public driver-management module; the
    # `is_blacklisted` predicate is the cheapest call that round-trips
    # through `rasterio._env.GDALEnv` and proves the driver registry
    # initialised. GTiff is universal in any GDAL build with raster
    # support.
    from rasterio.drivers import is_blacklisted

    # Built-in driver — should not be blacklisted.
    assert is_blacklisted("GTiff", "r") is False


def test_geotiff_round_trip(tmp_path):
    """Write a GeoTIFF and read it back — the path listing drivers does not cover.

    This is the test that would have caught the iOS driver-registry split, and
    the reason `test_drivers_listed` above cannot: with a static libgdal each
    extension links its own GDAL and gets its own registry. `rasterio.Env()`
    registers inside `_env`, which is what makes the listing succeed, while
    `rasterio.open` resolves the driver name inside `_base` — a registry nobody
    had populated. The failure is
    `DriverRegistrationError: ('No such driver registered: %s', b'GTiff')`
    raised in the same process that has just listed GTiff as available.

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
    `GDALGetDriverByName`, so under a static libgdal each needs its registry
    populated. `test_geotiff_round_trip` covers the first two and stops there.

    `exists` is the interesting half. It identifies a format by asking every
    registered driver, and asking none of them is not an error — so on an
    unregistered `shutil` it reports False for a file it just failed to open,
    and nothing raises. Assert the True, or the bug reads as a normal answer.
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
