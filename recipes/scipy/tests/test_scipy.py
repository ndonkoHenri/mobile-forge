import numpy as np


def test_linalg_solve():
    """linalg.solve -> LAPACK getrf/getrs through OpenBLAS."""
    from scipy import linalg

    a = np.array([[3.0, 1.0], [1.0, 2.0]])
    b = np.array([9.0, 8.0])
    x = linalg.solve(a, b)
    assert np.allclose(a @ x, b)
    assert np.allclose(x, [2.0, 3.0])


def test_linalg_svd():
    """linalg.svd -> LAPACK gesdd; reconstruct the matrix from U S Vt."""
    from scipy import linalg

    m = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    u, s, vt = linalg.svd(m, full_matrices=False)
    assert np.allclose(u @ np.diag(s) @ vt, m)
    assert s[0] > s[1] > 0


def test_linalg_eigh():
    """eigvalsh -> symmetric eigensolver (LAPACK syevd) through OpenBLAS."""
    from scipy import linalg

    a = np.array([[2.0, 1.0], [1.0, 2.0]])
    w = np.sort(linalg.eigvalsh(a))
    assert np.allclose(w, [1.0, 3.0])


def test_linalg_cholesky():
    """cholesky -> LAPACK potrf of an SPD matrix; L @ L.T reconstructs it."""
    from scipy import linalg

    a = np.array([[4.0, 2.0], [2.0, 3.0]])
    L = linalg.cholesky(a, lower=True)
    assert np.allclose(L @ L.T, a)


def test_fft():
    """scipy.fft (vendored ducc) -> fft/ifft roundtrip; DC term equals the sum."""
    from scipy import fft

    x = np.array([1.0, 2.0, 1.0, -1.0, 1.5, 0.0, 0.0, 0.0])
    y = fft.fft(x)
    assert np.allclose(y[0].real, x.sum())
    assert np.allclose(fft.ifft(y).real, x)


def test_special_real():
    """special.gamma(0.5) == sqrt(pi); gamma(5) == 4!; erf(0) == 0."""
    import math
    from scipy import special

    assert abs(special.gamma(0.5) - math.sqrt(math.pi)) < 1e-12
    assert abs(special.gamma(5.0) - 24.0) < 1e-9
    assert abs(special.erf(0.0)) < 1e-15


def test_special_complex():
    """Complex special function -> exercises scipy.special's C99 complex math
    (clog/cpow in _complexstuff.h). loggamma(1) == 0; loggamma(1+1j) is finite."""
    from scipy import special

    assert abs(special.loggamma(1.0)) < 1e-12
    z = special.loggamma(1 + 1j)
    assert np.isfinite(z.real) and np.isfinite(z.imag)


def test_sparse_spsolve():
    """sparse CSC matrix + sparse.linalg.spsolve (SuperLU)."""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve

    a = sparse.csc_matrix([[3.0, 1.0], [1.0, 2.0]])
    b = np.array([9.0, 8.0])
    x = spsolve(a, b)
    assert np.allclose(x, [2.0, 3.0])


def test_optimize():
    """optimize.minimize (BFGS) on a quadratic -> minimum at (1, 2.5)."""
    from scipy import optimize

    res = optimize.minimize(
        lambda p: (p[0] - 1.0) ** 2 + (p[1] - 2.5) ** 2, [0.0, 0.0], method="BFGS"
    )
    assert res.success
    assert np.allclose(res.x, [1.0, 2.5], atol=1e-4)


def test_integrate():
    """integrate.quad of x^2 over [0, 1] == 1/3 (QUADPACK, f2c)."""
    from scipy import integrate

    val, _ = integrate.quad(lambda x: x**2, 0.0, 1.0)
    assert abs(val - 1.0 / 3.0) < 1e-10


def test_interpolate():
    """interpolate.interp1d -> linear interp of a known line (FITPACK, f2c)."""
    from scipy import interpolate

    x = np.array([0.0, 1.0, 2.0])
    f = interpolate.interp1d(x, 2.0 * x + 1.0)
    assert abs(float(f(0.5)) - 2.0) < 1e-12


def test_stats():
    """stats.norm -> standard-normal cdf(0) == 0.5, pdf(0) == 1/sqrt(2*pi)."""
    from scipy import stats

    assert abs(stats.norm.cdf(0.0) - 0.5) < 1e-12
    assert abs(stats.norm.pdf(0.0) - 1.0 / np.sqrt(2.0 * np.pi)) < 1e-12


def test_odr_is_the_only_missing_module():
    """The wheels are built without a Fortran compiler, which drops scipy.odr
    and nothing else. Pin both halves of that claim: odr is gone, and every
    other public submodule the README implies is present still imports."""
    import importlib

    import pytest

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("scipy.odr")

    for name in (
        "cluster",
        "constants",
        "datasets",
        "fft",
        "fftpack",
        "integrate",
        "interpolate",
        "io",
        "linalg",
        "ndimage",
        "optimize",
        "signal",
        "sparse",
        "spatial",
        "special",
        "stats",
    ):
        importlib.import_module(f"scipy.{name}")


def test_blas_is_openblas_on_both_platforms():
    """BLAS/LAPACK come from flet-libopenblas on iOS as well as Android — iOS
    deliberately does NOT fall back to Accelerate, so numerical results do not
    drift between platforms or across iOS releases."""
    import scipy

    blas = scipy.show_config(mode="dicts")["Build Dependencies"]["blas"]
    assert "openblas" in blas["name"].lower(), blas


def test_pythran_fallback_modules_are_correct():
    """pythran is disabled on Android, so three modules ship as .py instead of
    .so. The fallbacks are never exercised by the rest of this suite, so a
    broken one would ship green. Keep the arrays tiny — RBFInterpolator is the
    slowest of the fallback paths."""
    import numpy as np
    from scipy import interpolate, linalg

    points = np.array([[0.0], [1.0], [2.0], [3.0]])
    values = np.array([0.0, 1.0, 4.0, 9.0])
    interpolated = interpolate.RBFInterpolator(points, values)(np.array([[1.5]]))
    assert 1.0 < float(interpolated[0]) < 4.0, interpolated

    matrix = np.array([[4.0, 0.0], [0.0, 9.0]])
    root = linalg.funm(matrix, np.sqrt)
    assert np.allclose(root @ root, matrix), root


def test_sobol_data_file_loads_from_the_zip():
    """scipy's one runtime data file is read through importlib.resources, which
    is why no extract_packages entry is needed. Force that read."""
    from scipy.stats import qmc

    sample = qmc.Sobol(d=2, scramble=False).random(4)
    assert sample.shape == (4, 2), sample


def test_ode_solver_lsoda():
    """solve_ivp(method="LSODA") -> the _odepack extension, which nothing else reaches.

    There is no `_lsoda` extension — LSODA is `from ._odepack import lsoda`,
    reached through `scipy.integrate._ode`. Check the module list before
    retargeting this at a name that sounds right.

    `test_integrate` covers QUADPACK via `quad`, a different compiled unit. On
    iOS each of scipy's OpenBLAS-carrying extensions absorbs its own copy of
    the library, so "scipy works" is never per-extension evidence — thirteen
    extensions carry one and the suite reached three. Exponential decay has a
    closed form to check the answer against.
    """
    import numpy as np
    from scipy.integrate import solve_ivp

    result = solve_ivp(lambda t, y: -0.5 * y, (0.0, 4.0), [2.0],
                       method="LSODA", rtol=1e-8, atol=1e-10)
    assert result.success, result.message
    assert np.allclose(result.y[0, -1], 2.0 * np.exp(-0.5 * 4.0), rtol=1e-5)


def test_optimize_lbfgsb_and_slsqp():
    """L-BFGS-B and SLSQP -> the _lbfgsb and _slsqplib extensions.

    `test_optimize` uses BFGS, which is pure Python over numpy and touches
    neither. Both minimise the same quadratic so the expected answer is shared;
    SLSQP additionally carries a constraint, which is its own code path.
    """
    import numpy as np
    from scipy.optimize import minimize

    def quadratic(v):
        return (v[0] - 1.0) ** 2 + (v[1] - 2.5) ** 2

    bounded = minimize(quadratic, [0.0, 0.0], method="L-BFGS-B")
    assert bounded.success, bounded.message
    assert np.allclose(bounded.x, [1.0, 2.5], atol=1e-5)

    constrained = minimize(
        quadratic, [0.0, 0.0], method="SLSQP",
        constraints=[{"type": "ineq", "fun": lambda v: 2.0 - v[0]}],
    )
    assert constrained.success, constrained.message
    assert np.allclose(constrained.x, [1.0, 2.5], atol=1e-5)


def test_sparse_eigsh_arpack():
    """sparse.linalg.eigsh -> the ARPACK extension, another OpenBLAS carrier.

    `test_sparse_spsolve` covers SuperLU; ARPACK is separate. A diagonal matrix
    makes the eigenvalues exactly the diagonal, so the assertion needs no
    tolerance argument about which eigenvector convention came back.
    """
    import numpy as np
    from scipy.sparse import diags
    from scipy.sparse.linalg import eigsh

    matrix = diags(np.array([1.0, 2.0, 3.0, 4.0, 9.0]), format="csr")
    values = eigsh(matrix, k=2, which="LM", return_eigenvectors=False)
    assert np.allclose(np.sort(values), [4.0, 9.0], atol=1e-8)
