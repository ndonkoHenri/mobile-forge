import pytest


def test_in_memory_raster():
    """GDAL's MEM driver creates an in-memory raster — no disk I/O,
    no test data file. Touches the C++ raster band API."""
    from osgeo import gdal

    drv = gdal.GetDriverByName("MEM")
    assert drv is not None
    ds = drv.Create("", 4, 3, 1, gdal.GDT_Byte)
    assert ds.RasterXSize == 4
    assert ds.RasterYSize == 3

    band = ds.GetRasterBand(1)
    band.Fill(7)
    raw = band.ReadRaster(0, 0, 4, 3)  # 4*3*1 byte = 12 bytes
    assert raw == bytes([7] * 12)


def test_version_loaded():
    """Confirms the libgdal C++ runtime is wired through SWIG."""
    from osgeo import gdal

    assert gdal.VersionInfo()


def test_epsg_codes_work_where_proj_db_reached_the_device():
    """EPSG codes resolve iff PROJ's database is on disk — assert whichever holds.

    On iOS `flet-libproj` ships `proj.db` in `opt/share/proj` and the preload shim
    points `PROJ_DATA` at it. On Android that tree never arrives, so the shim
    points at pyproj's extracted copy instead, and with no pyproj there is none.
    Both outcomes are correct for their setup; asserting the wrong one is the
    failure this catches.

    Decide from the shipped artifact rather than from whether PROJ found it, or
    the test passes in both branches and proves neither. A proj-string is the
    control: it needs no database and must work either way.
    """
    import os

    from osgeo import osr

    def srs(definition):
        ref = osr.SpatialReference()
        # GDAL 3 honours EPSG:4326's lat/lon authority order; force lon/lat.
        ref.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        definition(ref)
        return ref

    # Scoped, so no other test inherits exception mode.
    with osr.ExceptionMgr():
        wgs84 = srs(lambda r: r.SetFromUserInput("+proj=longlat +datum=WGS84 +no_defs"))
        mercator = srs(
            lambda r: r.SetFromUserInput(
                "+proj=merc +a=6378137 +b=6378137 +lon_0=0 +units=m +no_defs"
            )
        )
        x, y, _ = osr.CoordinateTransformation(wgs84, mercator).TransformPoint(4.3517, 50.8503)
        assert abs(x - 484409.0) < 5000, x
        assert abs(y - 6593200.0) < 5000, y

        # osgeo/osr.py -> osgeo -> site-packages.
        site_packages = os.path.dirname(os.path.dirname(os.path.abspath(osr.__file__)))
        # Where flet-libproj ships it (iOS reads it in place).
        roots = [os.path.join(site_packages, "opt", "share", "proj")]
        # Whatever the preload shim settled on: pyproj's extracted copy on Android.
        for var in ("PROJ_DATA", "PROJ_LIB"):
            if os.environ.get(var):
                roots.extend(os.environ[var].split(os.pathsep))
        # PROJ's own search directories: on a desktop GDAL (Homebrew, conda) its
        # database lives here. Only the paths are taken; existence is checked below.
        roots.extend(osr.GetPROJSearchPaths() or [])
        have_db = any(os.path.exists(os.path.join(r, "proj.db")) for r in roots)

        if have_db:
            # 15E is UTM zone 33's central meridian, so the easting is the 500000
            # false easting exactly, checkable from the definition.
            utm33 = srs(lambda r: r.ImportFromEPSG(32633))
            geographic = srs(lambda r: r.ImportFromEPSG(4326))
            e, n, _ = osr.CoordinateTransformation(geographic, utm33).TransformPoint(15.0, 60.0)
            assert abs(e - 500000.0) < 0.01, e
            assert abs(n - 6651411.19) < 0.5, n
        else:
            # PROJ: proj_create_from_database: Cannot find proj.db
            with pytest.raises(RuntimeError, match="proj.db"):
                osr.SpatialReference().ImportFromEPSG(4326)
