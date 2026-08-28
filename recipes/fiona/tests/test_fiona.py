import pytest


def test_import_fiona():
    """`import fiona` triggers `fiona._env.so`'s dlopen. On iOS, the
    published wheel's _env.so was linked against `libgdal.a` only — GDAL's
    static archive leaks undefined references for symbols GDAL itself uses
    from libproj/libtiff/libcurl/libpsl/openssl. iOS dyld eagerly resolves
    the flat namespace at dlopen and aborts with
    `symbol not found in flat namespace '_geod_init'` (or _TIFFClientOpen
    / _curl_easy_init / _psl_builtin, depending on which gap is hit
    first). Android isn't affected — libproj/libtiff/libcurl/etc. are
    shared libraries there, so their symbols resolve via DT_NEEDED."""
    import fiona

    assert hasattr(fiona, "supported_drivers")
    assert hasattr(fiona, "open")


def test_supported_drivers():
    """fiona binds GDAL's vector I/O (OGR). Listing supported drivers is
    the lightest-weight way to confirm the C lib loaded without needing
    a test shapefile."""
    import fiona

    drivers = list(fiona.supported_drivers.keys())
    # ESRI Shapefile + GeoJSON are universal — if the GDAL lib is loaded
    # at all, these are present.
    assert "ESRI Shapefile" in drivers
    assert "GeoJSON" in drivers


def test_write_read_geojson(tmp_path):
    """Write a Point feature to GeoJSON then read it back — covers OGR's
    writer + reader without depending on bundled test data.

    This used to skip on iOS, on the reasoning that OGR's GeoJSON writer stamps
    a default WGS84 field through PROJ even when the caller supplies no CRS, so
    the missing `proj.db` made a write impossible. Naming the CRS as a
    proj-string avoids that lookup entirely — PROJ needs its database only to
    resolve an authority code — and `pyogrio`, which shares this GDAL, writes
    GeoJSON on an iPhone simulator this way. So the restriction is avoidable
    rather than fundamental, and the test now runs everywhere.

    It also covers the driver registry: `ogrext`, where `fiona.open` works, has
    its own GDAL copy under a static libgdal, and `ios-driver-registry.patch`
    is what populates it. Without that patch this fails at the driver rather
    than at the CRS."""
    import fiona

    schema = {"geometry": "Point", "properties": {"name": "str"}}
    path = tmp_path / "tiny.geojson"

    # proj-string, never an authority code: this chain ships no proj.db.
    with fiona.open(
        path, "w", driver="GeoJSON", schema=schema,
        crs="+proj=longlat +datum=WGS84 +no_defs",
    ) as dst:
        dst.write(
            {
                "geometry": {"type": "Point", "coordinates": (2.35, 48.86)},
                "properties": {"name": "Paris"},
            }
        )

    with fiona.open(path) as src:
        feats = list(src)
        assert len(feats) == 1
        assert feats[0]["properties"]["name"] == "Paris"
        assert tuple(feats[0]["geometry"]["coordinates"]) == (2.35, 48.86)


def test_transform_loads_and_reprojects():
    """`fiona.transform` is the one import that needs `libc++_shared.so`.

    `fiona/_transform.so` is the only extension of the eight whose `DT_NEEDED`
    names it, and plain `import fiona` never loads that module — so a wheel
    missing `flet-libcpp-shared` from its `Requires-Dist` installs cleanly,
    passes every other test here, and fails only when an app reaches for a
    reprojection.

    The CRSs are spelled as proj-strings rather than EPSG codes deliberately.
    `flet-libproj` ships no `proj.db`, so anything naming an authority raises
    `CRSError: PROJ: proj_create_from_database: Cannot find proj.db` — a real
    limitation, covered separately by `test_epsg_codes_need_proj_db`. Using a
    proj-string keeps this test pinned to the thing it is about: that the
    extension loads and computes.
    """
    from fiona.transform import transform

    wgs84 = "+proj=longlat +datum=WGS84 +no_defs"
    mercator = "+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +units=m +no_defs"

    lon, lat = 4.3517, 50.8503
    x, y = transform(wgs84, mercator, [lon], [lat])
    assert 484_000 < x[0] < 485_000, x
    assert 6_593_000 < y[0] < 6_595_000, y

    back_lon, back_lat = transform(mercator, wgs84, x, y)
    assert abs(back_lon[0] - lon) < 1e-6, back_lon
    assert abs(back_lat[0] - lat) < 1e-6, back_lat


def test_epsg_codes_work_where_proj_db_reached_the_device():
    """EPSG codes resolve iff PROJ's database is on disk — assert whichever holds.

    `flet-libproj` ships `proj.db` in `opt/share/proj` and the preload shim points
    `PROJ_DATA` at it. On iOS that directory is real inside the app, so authority
    codes resolve; on Android it never arrives, because Flet's `copyOpt` copies
    only `*.so` out of a `flet-lib*` `opt/` tree. Both are correct answers for
    their platform, and asserting the wrong one is the failure this catches.

    Decide from the shipped artifact rather than from what PROJ reports, or the
    test passes in both branches and proves neither. Proj-strings are the control:
    they need no database and must keep working either way.
    """
    import os

    import fiona
    from fiona.errors import CRSError
    from fiona.transform import transform

    wgs84 = "+proj=longlat +datum=WGS84 +no_defs"
    mercator = "+proj=merc +a=6378137 +b=6378137 +lon_0=0 +units=m +no_defs"
    assert transform(wgs84, mercator, [4.3517], [50.8503])[0]

    package = os.path.dirname(os.path.abspath(fiona.__file__))
    site_packages = os.path.dirname(package)
    roots = [
        # where flet-libproj ships it, and iOS can read it directly
        os.path.join(site_packages, "opt", "share", "proj"),
        # where fiona's own PyPI wheel bundles one on a desktop
        os.path.join(package, "proj_data"),
    ]
    # Whatever the preload shim settled on -- on Android that is pyproj's
    # extracted copy, which is the only route the database has there.
    for var in ("PROJ_DATA", "PROJ_LIB"):
        if os.environ.get(var):
            roots.extend(os.environ[var].split(os.pathsep))
    have_db = any(os.path.exists(os.path.join(r, "proj.db")) for r in roots)

    if have_db:
        # 15E is UTM zone 33's central meridian, so the easting is the 500000
        # false easting exactly — checkable from the definition, not from a run.
        xs, ys = transform("EPSG:4326", "EPSG:32633", [15.0], [60.0])
        assert abs(xs[0] - 500000.0) < 0.01, xs
        assert abs(ys[0] - 6651411.19) < 0.5, ys
    else:
        with pytest.raises(CRSError):
            transform("EPSG:4326", "EPSG:3857", [4.3517], [50.8503])
