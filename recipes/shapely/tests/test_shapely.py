def test_import_shapely():
    """`import shapely` triggers `_geos.so` + `lib.so` + `_geometry_helpers.so`,
    and shapely 2.x does `import numpy` during package __init__. Whether the
    libc++_shared gap fires depends on arch: on x86_64 numpy's
    `_multiarray_umath.so` requires libcpp and bombs at dlopen; on arm64
    multiarray is fine but `_pocketfft_umath.so` (used by `np.fft.*`) still
    needs libcpp. Either way the recipe's `flet-libcpp-shared` host dep is
    defensive — surface it via Requires-Dist so libc++_shared.so is bundled
    even when the only mobile dep is shapely."""
    import shapely

    assert hasattr(shapely, "Point")
    assert hasattr(shapely, "points")  # vectorized API


def test_numpy_fft():
    """libcpp_shared canary that fires on every Android arch via
    `_pocketfft_umath.so` (DT_NEEDED=[libc++_shared.so] on both arm64
    AND x86_64). shapely doesn't reach into fft naturally, but this
    surfaces the libcpp gap the recipe's defensive
    `flet-libcpp-shared` host dep closes. Same canary added in blis's
    test file."""
    import numpy as np

    x = np.cos(2 * np.pi * 2 * np.arange(8) / 8)
    spectrum = np.fft.fft(x)
    magnitudes = np.abs(spectrum)
    assert magnitudes[2] > 3.9
    assert magnitudes[6] > 3.9


def test_geometry_ops():
    """shapely wraps GEOS (the C++ computational-geometry library). Cover
    geometry construction + a non-trivial spatial predicate."""
    from shapely.geometry import Point, Polygon

    triangle = Polygon([(0, 0), (4, 0), (0, 3)])
    assert abs(triangle.area - 6.0) < 1e-9  # ½ × base × height

    inside = Point(1, 1)
    outside = Point(5, 5)
    assert triangle.contains(inside)
    assert not triangle.contains(outside)


def test_buffer_and_intersection():
    """Buffer + intersect exercises GEOS's harder operations."""
    from shapely.geometry import Point

    circle = Point(0, 0).buffer(1.0)
    # `buffer(1)` approximates a unit circle; area ≈ π.
    assert 3.0 < circle.area < 3.2

    far = Point(10, 10).buffer(1.0)
    assert circle.intersection(far).is_empty


def test_numpy_vectorized():
    """The shapely 2.x numpy bridge — the reason the recipe has `numpy`
    as a host dep (and, transitively on Android, `flet-libcpp-shared`).

    Shapely's per-geometry API (Point/Polygon/.area) goes straight to
    GEOS and never touches numpy. The vectorized `shapely.*` calls below
    DO — they accept numpy arrays in and return numpy arrays out, with
    shapely's `_lib`/`_geometry` C extensions handling the buffer-level
    marshaling. If numpy ever fails to load on the device (e.g.
    libc++_shared missing on Android) this test surfaces the gap
    directly; the scalar tests above would still pass."""
    import numpy as np
    import shapely

    # numpy → shapely: vectorized Point construction from coord arrays.
    xs = np.array([0.0, 3.0, 0.0])
    ys = np.array([0.0, 0.0, 4.0])
    pts = shapely.points(xs, ys)
    assert isinstance(pts, np.ndarray)
    assert pts.shape == (3,)

    # shapely → numpy: vectorized .area over an object-dtype array of
    # geometries. Triangle (0,0)-(3,0)-(0,4) has area = ½·3·4 = 6.
    triangle = shapely.polygons([list(zip(xs, ys))])
    areas = shapely.area(triangle)
    assert isinstance(areas, np.ndarray)
    np.testing.assert_allclose(areas, [6.0], atol=1e-9)

    # shapely → numpy: extract coordinates as a 2-D array. Closing the
    # ring adds the first vertex again, so we expect 4 rows × 2 cols.
    coords = shapely.get_coordinates(triangle)
    assert isinstance(coords, np.ndarray)
    assert coords.shape == (4, 2)
    np.testing.assert_array_equal(coords[0], coords[-1])  # ring closed


def test_ragged_array_round_trip():
    """Cross from `lib` into `_geometry_helpers`, which on iOS is a second GEOS.

    `flet-libgeos` is a static archive there, so `lib`, `_geos` and
    `_geometry_helpers` each link their own copy — all three *define*
    `GEOS_init_r` and none imports it. Geometries built by one and read by
    another therefore cross library instances. Every other test here stays
    inside `lib`, so nothing exercised that until now.

    `to_ragged_array`/`from_ragged_array` are the cheapest path that does:
    they live in `_geometry_helpers` and take geometries `lib` allocated.
    """
    import numpy as np
    from shapely import from_ragged_array, to_ragged_array
    from shapely.geometry import Polygon

    original = [
        Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
        Polygon([(4, 4), (6, 4), (6, 6), (4, 6)]),
    ]
    geometry_type, coords, offsets = to_ragged_array(original)
    restored = from_ragged_array(geometry_type, coords, offsets)

    assert len(restored) == 2
    for before, after in zip(original, restored):
        assert after.equals(before), f"{after.wkt} != {before.wkt}"
        assert np.isclose(after.area, before.area)


def test_strtree_queries_geometries_built_elsewhere():
    """An STRtree indexes geometries it did not create — another instance cross.

    The index holds pointers to geometries `lib` allocated and runs predicates
    against them. On one shared libgeos that is unremarkable; with a static one
    per extension it is the kind of hand-off that has nowhere to go wrong until
    it does, and no test covered it.
    """
    from shapely import STRtree
    from shapely.geometry import Point

    points = [Point(x, 0) for x in range(10)]
    tree = STRtree(points)

    hits = tree.query(Point(4, 0).buffer(1.5))
    assert len(hits) >= 3, f"expected the neighbours of x=4, got {sorted(hits)}"
    assert 4 in list(hits)

    nearest = tree.nearest(Point(7.4, 0))
    assert points[int(nearest)].equals(Point(7, 0))
