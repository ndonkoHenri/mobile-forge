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

    # Ask pyproj where PROJ will actually look, rather than reading PROJ_DATA:
    # on a desktop the answer is the directory bundled inside the wheel, which
    # takes precedence over the variable and would make an env-var check lie.
    try:
        from pyproj.datadir import get_data_dir

        data_dir = get_data_dir()
    except Exception:
        data_dir = ""
    have_db = bool(data_dir) and any(
        os.path.exists(os.path.join(d, "proj.db")) for d in data_dir.split(os.pathsep)
    )

    if have_db:
        crs = CRS.from_epsg(4326)
        assert crs.to_epsg() == 4326
        assert "WGS 84" in crs.name, crs.name
    else:
        with pytest.raises(CRSError):
            CRS.from_epsg(4326)
