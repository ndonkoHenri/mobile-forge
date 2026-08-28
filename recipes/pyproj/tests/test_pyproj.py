import pytest

def test_import_pyproj():
    """`import pyproj` triggers `_geod`/`_crs`/`_context` etc.'s dlopen.
    On iOS, the published wheel's extensions were linked against
    `libproj.a` only — and libproj's static archive has internal
    references to libtiff (grid file support) and libcurl + libpsl
    (network grid fetcher) that are left undefined. iOS dyld eagerly
    resolves the flat namespace at dlopen and aborts with
    `symbol not found in flat namespace '_TIFFClientOpen'` (or
    _curl_easy_init / _psl_builtin). Android isn't affected — libproj
    is shared there, its deps resolve transparently via DT_NEEDED."""
    import pyproj

    assert hasattr(pyproj, "Geod")
    assert hasattr(pyproj, "CRS")


def test_geod_distance():
    """pyproj wraps PROJ (the C cartographic projection library). The
    Geod (geodesic) API operates directly on the WGS-84 ellipsoid and
    doesn't need PROJ's database (proj.db) — perfect for mobile, where
    the recipe doesn't bundle that ~9 MB sqlite file. Paris → London is
    ~344 km along the WGS-84 geodesic."""
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
    """EPSG codes work iff PROJ's database is on disk — assert whichever holds.

    `flet-libproj` ships `proj.db` in `opt/share/proj`, and the preload shim
    points `PROJ_DATA` at it. On iOS that directory is real inside the app, so
    authority codes resolve. On Android it never lands: Flet's `copyOpt` copies
    only `*.so` out of a `flet-lib*` `opt/` tree, so the database is dropped and
    a code lookup raises. Both are correct answers; asserting the wrong one for
    the platform is the failure.

    Proj-strings need no database and must work either way — that is the
    control, and the thing every consumer's docs tell people to use.
    """
    import os

    from pyproj import CRS, Transformer
    from pyproj.exceptions import CRSError

    # Control: a proj-string round trip, database or not.
    wgs84 = "+proj=longlat +datum=WGS84 +no_defs"
    mercator = "+proj=merc +a=6378137 +b=6378137 +lon_0=0 +units=m +no_defs"
    x, y = Transformer.from_crs(wgs84, mercator, always_xy=True).transform(4.3517, 50.8503)
    assert abs(x - 484409.0) < 5000, x
    assert abs(y - 6593200.0) < 5000, y

    # Decide the expectation from the SHIPPED ARTIFACT, not from what PROJ
    # reports. A test that asks the library whether it found a database, then
    # asserts whichever answer it gave, passes in both branches and so proves
    # nothing about either. Look for the file where flet-libproj puts it —
    # site-packages/opt/share/proj — and where pyproj bundles its own on a
    # desktop, then require the corresponding behaviour.
    import pyproj

    site_packages = os.path.dirname(os.path.dirname(os.path.abspath(pyproj.__file__)))
    candidates = [
        os.path.join(site_packages, "opt", "share", "proj", "proj.db"),
        os.path.join(
            os.path.dirname(os.path.abspath(pyproj.__file__)),
            "proj_dir", "share", "proj", "proj.db",
        ),
    ]
    shipped = [c for c in candidates if os.path.exists(c)]
    have_db = bool(shipped)

    if have_db:
        crs = CRS.from_epsg(4326)
        assert crs.to_epsg() == 4326, f"database at {shipped[0]} but EPSG:4326 did not resolve"
        assert "WGS 84" in crs.name, crs.name
        # And a real authority-to-authority transform, which is the whole point
        # of having the database. 15E is UTM zone 33's central meridian, so the
        # easting lands on the 500000 false easting exactly — a value that is
        # checkable by hand rather than copied from a run.
        easting, northing = Transformer.from_crs(
            "EPSG:4326", "EPSG:32633", always_xy=True
        ).transform(15.0, 60.0)
        assert abs(easting - 500000.0) < 0.01, easting
        assert abs(northing - 6651411.19) < 0.5, northing
    else:
        with pytest.raises(CRSError):
            CRS.from_epsg(4326)
