import pytest


def test_list_drivers():
    """pyogrio is a Cython wrapper for GDAL/OGR's vector I/O. Listing
    drivers is the smallest C-call we can make to confirm libgdal is
    loaded; it runs through the `_ogr` extension, so it says nothing
    about whether `_io` can actually open a dataset."""
    import pyogrio

    drivers = pyogrio.list_drivers()
    assert isinstance(drivers, dict)
    # Universal drivers — present in any GDAL build with vector support.
    assert "ESRI Shapefile" in drivers
    assert "GeoJSON" in drivers


def test_gdal_version():
    """Confirms the GDAL C library version is reported. `get_gdal_version`
    lives in `_ogr`, so this reaches the same extension as the driver
    list, not a separate one."""
    import pyogrio

    v = pyogrio.__gdal_version__
    # `__gdal_version__` is a 3-tuple of ints.
    assert isinstance(v, tuple)
    assert len(v) == 3
    assert all(isinstance(x, int) for x in v)


def test_vector_round_trip(tmp_path):
    """Write features and read them back — the path listing drivers does not cover.

    The two tests above touch `pyogrio._ogr`, which calls `GDALAllRegister()`
    itself. `_io`, where a read or a write actually happens, is a different
    extension that neither of them calls into, so a wheel can list every driver
    and still be unable to open a dataset.

    This asserts the round trip instead: two Points out through the GeoJSON
    driver, both back with their attribute intact.
    """
    import struct

    import numpy as np
    from pyogrio.raw import read, write

    def wkb_point(x, y):
        return struct.pack("<BI2d", 1, 1, x, y)

    path = tmp_path / "round-trip.geojson"
    geometry = np.array([wkb_point(4.35, 50.85), wkb_point(2.35, 48.85)], dtype=object)
    names = np.array(["brussels", "paris"], dtype=object)

    write(
        str(path),
        geometry=geometry,
        field_data=[names],
        fields=["name"],
        driver="GeoJSON",
        geometry_type="Point",
        # A proj-string needs no database, so this checks I/O alone. Whether
        # PROJ's database arrived is the EPSG test's job.
        crs="+proj=longlat +datum=WGS84 +no_defs",
    )
    assert path.exists() and path.stat().st_size > 0

    _meta, _fids, read_geometry, read_fields = read(str(path))

    assert len(read_geometry) == 2, len(read_geometry)
    assert list(read_fields[0]) == ["brussels", "paris"], read_fields[0]


def test_epsg_codes_work_where_proj_db_reached_the_device(tmp_path):
    """An EPSG CRS survives a GeoJSON round trip iff PROJ's database is on disk.

    On iOS `flet-libproj`'s `opt/share/proj` is a real directory and the preload
    shim points `PROJ_DATA` at it. On Android that tree never arrives, so the
    shim points at pyproj's extracted copy, which exists only if pyproj is
    installed and extracted. Without a database it is the write that fails:
    `OSRSetFromUserInput` cannot resolve the code and pyogrio raises `CRSError`.

    Decide from the shipped artifact rather than from what PROJ reports, or the
    test passes in both branches and proves neither. A proj-string write is the
    control: it needs no database and must work either way.
    """
    import os
    import struct

    import numpy as np
    import pyogrio
    from pyogrio.errors import CRSError
    from pyogrio.raw import read, write

    def write_point(path, crs, **kwargs):
        # 15E, 60N in UTM zone 33 — the easting is the zone's false easting.
        geometry = np.array([struct.pack("<BI2d", 1, 1, 500000.0, 6651411.19)], dtype=object)
        write(
            str(path),
            geometry=geometry,
            field_data=[],
            fields=[],
            driver="GeoJSON",
            geometry_type="Point",
            crs=crs,
            **kwargs,
        )

    control = tmp_path / "control.geojson"
    write_point(control, "+proj=utm +zone=33 +datum=WGS84 +units=m +no_defs")
    assert len(read(str(control))[2]) == 1

    package = os.path.dirname(os.path.abspath(pyogrio.__file__))
    roots = [
        # where flet-libproj ships it, and iOS can read it directly
        os.path.join(os.path.dirname(package), "opt", "share", "proj"),
        # where pyogrio's own PyPI wheel bundles one on a desktop
        os.path.join(package, "proj_data"),
    ]
    # Whatever the preload shim settled on -- on Android that is pyproj's
    # extracted copy, which is the only route the database has there.
    for var in ("PROJ_DATA", "PROJ_LIB"):
        if os.environ.get(var):
            roots.extend(os.environ[var].split(os.pathsep))
    have_db = any(os.path.exists(os.path.join(r, "proj.db")) for r in roots)

    path = tmp_path / "utm33.geojson"
    if have_db:
        write_point(path, "EPSG:32633")
        meta, _fids, geometry, _fields = read(str(path))
        assert meta["crs"] == "EPSG:32633", meta["crs"]
        # The driver stores coordinates as given; nothing reprojects.
        x, y = struct.unpack_from("<2d", geometry[0], 5)
        assert abs(x - 500000.0) < 0.01, x
        assert abs(y - 6651411.19) < 0.01, y
        # RFC7946 output is lon/lat, so GDAL reprojects through PROJ on write:
        # the EPSG operation itself, checked against the definition.
        wgs84 = tmp_path / "rfc7946.geojson"
        write_point(wgs84, "EPSG:32633", layer_options={"RFC7946": "YES"})
        lon, lat = struct.unpack_from("<2d", read(str(wgs84))[2][0], 5)
        assert abs(lon - 15.0) < 1e-6, lon
        assert abs(lat - 60.0) < 1e-6, lat
    else:
        with pytest.raises(CRSError):
            write_point(path, "EPSG:32633")
