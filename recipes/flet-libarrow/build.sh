#!/bin/bash
# flet-libarrow: Apache Arrow C++ as a shared libarrow, cross-compiled via CMake,
# for the pyarrow recipe. MINIMAL CORE config (IPC only; no compute/parquet/
# compression) — the proven feasibility set. Arrow's own CMake has no iOS/Android
# awareness, so we drive the toolchain.
#
# Key cross fixes:
#   * ARROW_CPU_FLAG=<aarch64|aarch32|x86> — Arrow's SetupCxxFlags FATAL_ERRORs on
#     an unknown CMAKE_SYSTEM_PROCESSOR; under CMAKE_SYSTEM_NAME=iOS CMake leaves
#     it empty, so set the flag directly.
#   * iOS link: -framework CoreFoundation — Arrow's vendored `date` lib compiles
#     ios.mm (Obj-C++) using CoreFoundation for the tzdata.
#   * ARROW_SIMD_LEVEL=NONE — avoids -march=armv8-a (Apple clang dislikes it).
set -eu

# Locate the Arrow C++ source (cpp/), whether or not forge stripped the tarball top dir.
if [ -d cpp ]; then
    CPP="$PWD/cpp"
else
    CPP="$(find "$PWD" -maxdepth 3 -type d -name cpp -path '*/cpp' | head -1)"
fi
[ -n "${CPP:-}" ] && [ -d "$CPP" ] || { echo "ERROR: cannot find Arrow cpp/ source under $PWD"; exit 1; }
echo "Arrow C++ source: $CPP"

# Map the target arch to Arrow's CPU flag.
case "${HOST_ARCH:-${ANDROID_ABI:-}}" in
    arm64*|aarch64) CPU=aarch64 ;;
    armeabi*|armv7*) CPU=aarch32 ;;
    x86_64|x86)      CPU=x86 ;;
    *)               CPU=aarch64 ;;
esac

# CMake drives the cross toolchain itself (NDK file / iOS), so keep forge's host
# compiler flags out of the way.
unset CC CXX CFLAGS CPPFLAGS LDFLAGS AR RANLIB STRIP || true

COMMON_ARGS=(
    -G Ninja
    -DCMAKE_BUILD_TYPE=Release
    -DCMAKE_INSTALL_PREFIX="$PREFIX"
    -DCMAKE_INSTALL_LIBDIR=lib
    -DARROW_CPU_FLAG="$CPU"
    -DARROW_SIMD_LEVEL=NONE
    -DARROW_BUILD_SHARED=ON -DARROW_BUILD_STATIC=OFF
    -DARROW_IPC=ON
    # pyarrow 24 builds 7 UNCONDITIONAL Cython modules (lib, _compute, _csv,
    # _feather, _fs, _json, _pyarrow_cpp_tests) and FATAL_ERRORs unless Arrow C++
    # was built with COMPUTE + CSV; it also can't link _json/_fs/_feather without
    # JSON + FILESYSTEM + IPC(feather). So COMPUTE+CSV+JSON+FILESYSTEM+IPC is
    # pyarrow's true irreducible floor. Feather rides ARROW_IPC; JSON pulls only
    # header-only RapidJSON (bundled). Heavy optional deps stay OFF: re2/utf8proc
    # (compute string kernels → abseil), parquet/dataset/acero/flight/orc/gandiva,
    # and all cloud filesystems (S3/GCS/Azure/HDFS).
    -DARROW_COMPUTE=ON -DARROW_CSV=ON -DARROW_JSON=ON -DARROW_PARQUET=OFF
    -DARROW_DATASET=OFF -DARROW_ACERO=OFF -DARROW_FLIGHT=OFF -DARROW_GANDIVA=OFF
    -DARROW_FILESYSTEM=ON
    -DARROW_WITH_BROTLI=OFF -DARROW_WITH_BZ2=OFF -DARROW_WITH_LZ4=OFF
    -DARROW_WITH_SNAPPY=OFF -DARROW_WITH_ZLIB=OFF -DARROW_WITH_ZSTD=OFF
    -DARROW_WITH_UTF8PROC=OFF -DARROW_WITH_RE2=OFF
    -DARROW_MIMALLOC=OFF -DARROW_JEMALLOC=OFF -DARROW_WITH_BACKTRACE=OFF
    -DARROW_DEPENDENCY_SOURCE=BUNDLED
    # zlib can't actually be turned off here: Arrow force-enables it on Apple
    # because the vendored `date` lib decompresses the system tzdata via zlib in
    # ios.mm (GZipCodec also pulls it). The BUNDLED zlib_ep builds for the HOST
    # arch — fine when host==target, but on an arm64 mac it produces an arm64
    # libz.a that fails to link the x86_64 simulator slice. Use the platform's
    # SYSTEM zlib instead: the iOS SDK ships libz.tbd and the Android NDK ships
    # libz.so — both correct-arch and present on-device at runtime (no bundling).
    -DZLIB_SOURCE=SYSTEM
    -DARROW_BUILD_TESTS=OFF -DARROW_BUILD_BENCHMARKS=OFF
    -DARROW_BUILD_EXAMPLES=OFF -DARROW_BUILD_UTILITIES=OFF -DARROW_CUDA=OFF
)

mkdir -p _build && cd _build

if [ -n "${NDK_ROOT:-}" ]; then
    echo "=== configure (Android $ANDROID_ABI) ==="
    cmake "$CPP" "${COMMON_ARGS[@]}" \
        -DCMAKE_TOOLCHAIN_FILE="$NDK_ROOT/build/cmake/android.toolchain.cmake" \
        -DANDROID_ABI="$ANDROID_ABI" \
        -DANDROID_PLATFORM="android-$ANDROID_API_LEVEL" \
        -DANDROID_STL=c++_shared \
        -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384"
else
    echo "=== configure (iOS $HOST_ARCH, sysroot $SDK_ROOT) ==="
    cmake "$CPP" "${COMMON_ARGS[@]}" \
        -DCMAKE_SYSTEM_NAME=iOS \
        -DCMAKE_SYSTEM_PROCESSOR="$HOST_ARCH" \
        -DCMAKE_OSX_SYSROOT="$SDK_ROOT" \
        -DCMAKE_OSX_ARCHITECTURES="$HOST_ARCH" \
        -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0 \
        -DZLIB_INCLUDE_DIR="$SDK_ROOT/usr/include" \
        -DZLIB_LIBRARY="$SDK_ROOT/usr/lib/libz.tbd" \
        -DCMAKE_SHARED_LINKER_FLAGS="-framework CoreFoundation"
fi

echo "=== build + install libarrow (+ libarrow_compute) ==="
# No --target: build the default ALL target so both arrow_shared and
# arrow_compute_shared (ARROW_COMPUTE=ON) get built. Components are OFF, so ALL
# is just the two Arrow libs + bundled xsimd.
cmake --build . -j "${CPU_COUNT:-4}"
cmake --install .

# (pyarrow ships its own arrow_python C++ sources — its CMake sets
# PYARROW_CPP_ROOT_DIR=pyarrow/src — so flet-libarrow only needs to provide the
# built libarrow + headers, installed above.)

echo "=== installed ==="
ls -la "$PREFIX/lib" | grep -i arrow || true
