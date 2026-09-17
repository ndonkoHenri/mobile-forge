import pytest

def test_import_pyproj():
    """`import pyproj` loads `_geod`/`_crs`/`_context` etc., which link the shared
    libproj: `@rpath/libproj.dylib` on iOS, which flet relocates into a framework,
    and `libproj.so` by basename out of jniLibs on Android."""
    import pyproj

    assert hasattr(pyproj, "Geod")
    assert hasattr(pyproj, "CRS")


def test_geod_distance():
    """Geod works on the WGS-84 ellipsoid directly, so it needs no proj.db.
    Paris → London is ~344 km along the geodesic."""
    from pyproj import Geod

    g = Geod(ellps="WGS84")
    _, _, dist = g.inv(2.3522, 48.8566, -0.1276, 51.5074)
    km = dist / 1000.0
    assert 340 < km < 350


def test_geod_forward():
    """The forward problem: given a start point, azimuth, and distance,
    where do you end up? Also database-free."""
    from pyproj import Geod

    g = Geod(ellps="WGS84")
    # Start at the equator/prime meridian, head due east 1000 km.
    lon, lat, back_az = g.fwd(0.0, 0.0, 90.0, 1_000_000)
    # Should still be on the equator (within precision), longitude ~9°.
    assert abs(lat) < 0.01
    assert 8.9 < lon < 9.1


def test_epsg_codes_resolve_where_proj_db_reached_the_device():
    """EPSG codes resolve iff PROJ's database is on disk — assert whichever holds.

    iOS reads flet-libproj's opt/share/proj, a real directory inside the app.
    Android reads the copy bundled in pyproj's own proj_dir, on disk only when the
    app extracts pyproj. Decide from the shipped file, not from what pyproj
    reports, or the test passes in both branches and proves neither.

    Unlike the GDAL consumers, pyproj needs a data directory for ANY transform:
    with none, even a proj-string raises DataDirError (seen on an Android
    emulator). So the proj-string control sits in the database branch only.
    """
    import os

    import pyproj
    from pyproj import CRS, Transformer
    from pyproj.exceptions import CRSError, DataDirError

    package = os.path.dirname(os.path.abspath(pyproj.__file__))
    shipped = [
        path
        for path in (
            os.path.join(os.path.dirname(package), "opt", "share", "proj", "proj.db"),
            os.path.join(package, "proj_dir", "share", "proj", "proj.db"),
        )
        if os.path.exists(path)
    ]

    if not shipped:
        with pytest.raises((CRSError, DataDirError)):
            CRS.from_epsg(4326)
        return

    wgs84 = "+proj=longlat +datum=WGS84 +no_defs"
    mercator = "+proj=merc +a=6378137 +b=6378137 +lon_0=0 +units=m +no_defs"
    x, y = Transformer.from_crs(wgs84, mercator, always_xy=True).transform(4.3517, 50.8503)
    # Spherical Mercator's closed form: x = a*lon, y = a*ln(tan(pi/4 + lat/2)).
    assert abs(x - 484429.03) < 0.01, x
    assert abs(y - 6594856.12) < 0.01, y

    crs = CRS.from_epsg(4326)
    assert crs.to_epsg() == 4326, f"database at {shipped[0]} but EPSG:4326 did not resolve"
    assert "WGS 84" in crs.name, crs.name

    # 15E is UTM zone 33's central meridian, so the easting is its 500000 false
    # easting exactly — checkable from the definition, not copied from a run.
    easting, northing = Transformer.from_crs(
        "EPSG:4326", "EPSG:32633", always_xy=True
    ).transform(15.0, 60.0)
    assert abs(easting - 500000.0) < 0.01, easting
    assert abs(northing - 6651411.19) < 0.5, northing
