#!/bin/bash
set -eu

# SQLite3 discovery for Android:
#   - 3.12/3.13: sqlite3.h is bundled inside the python install dir,
#     so $HOST_PYTHON_HOME/include/sqlite3.h works.
#   - 3.14+: sqlite3.h lives in a sibling dir alongside the python
#     install (.../install/android/<abi>/sqlite-X.Y.Z/include/).
# The .so library itself stays inside $HOST_PYTHON_HOME/lib/ on both.
SQLITE3_INC="$HOST_PYTHON_HOME/include"
if [ ! -f "$SQLITE3_INC/sqlite3.h" ]; then
    for candidate in "$HOST_PYTHON_HOME"/../sqlite-*; do
        if [ -f "$candidate/include/sqlite3.h" ]; then
            SQLITE3_INC="$candidate/include"
            break
        fi
    done
fi

# Libraries the SHARED libgdal must resolve for itself on iOS.
#
# GDAL_USE_EXTERNAL_LIBS=OFF makes GDAL use its own internal libtiff/libjpeg/
# zlib/etc, so GDAL proper needs nothing here. libproj.a is the reason: it calls
# into libtiff (reading GTiff grid files), libcurl (fetching grids over the
# network) and sqlite3 (opening proj.db), and flet-libproj builds for iOS with
# `-undefined dynamic_lookup`, so its archive leaves all of them unresolved.
#
# Under a static libgdal that debt was paid much later, at each consumer's
# extension link, which is what the long `GDAL_LIBS: gdal,proj,tiff,curl,psl,
# sqlite3,jpeg,ssl,crypto,z` chain in gdal/fiona/rasterio/pyogrio is for. A real
# dylib has to settle it once, here -- which is the point: linked once instead
# of once per extension per package.
#
# libtiff in turn needs libjpeg, including its 12-bit entry points -- GDAL's
# INTERNAL libjpeg cannot satisfy those, because GDAL renames its symbols to
# avoid exactly this kind of collision, so the external flet-libjpeg is what
# resolves them. libcurl is configured --with-openssl, hence ssl/crypto (and
# psl, its public suffix list). sqlite3 and z are iOS system libraries and
# resolve from the SDK. Ordered by dependency, since these are static archives.
#
# This list is closed, not guessed: every symbol the archives reference and do
# not define between them is libc++, libSystem, sqlite3, z or compiler-rt.
IOS_GDAL_LINK_LIBS="-L$PLATLIB/opt/lib -ltiff -ljpeg -lcurl -lssl -lcrypto -lpsl -lsqlite3 -lz"

mkdir build
cd build

if [ $CROSS_VENV_SDK == "android" ]; then
    cmake .. \
        -DCMAKE_SYSTEM_NAME=Android \
        -DANDROID_PLATFORM=$SDK_VERSION \
        -DANDROID_ABI=$ANDROID_ABI \
        -DCMAKE_TOOLCHAIN_FILE=$NDK_ROOT/build/cmake/android.toolchain.cmake \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_SHARED_LINKER_FLAGS="$LDFLAGS" \
        -DCMAKE_INSTALL_PREFIX="$PREFIX" \
        -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=NEVER \
        -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=NEVER \
        -DCMAKE_FIND_USE_CMAKE_SYSTEM_PATH=NO \
        -DPROJ_LIBRARY=$PLATLIB/opt/lib/libproj.so \
        -DPROJ_INCLUDE_DIR=$PLATLIB/opt/include \
        -DSQLite3_LIBRARY=$HOST_PYTHON_HOME/lib/libsqlite3_python.so \
        -DSQLite3_INCLUDE_DIR=$SQLITE3_INC \
        -DGDAL_BUILD_OPTIONAL_DRIVERS=OFF \
        -DOGR_BUILD_OPTIONAL_DRIVERS=OFF \
        -DGDAL_USE_EXPAT=OFF \
        -DGDAL_USE_OPENSSL=OFF \
        -DGDAL_USE_CURL=OFF \
        -DGDAL_USE_LIBXML2=OFF \
        -DGDAL_USE_OPENMP=OFF \
        -DBUILD_APPS=OFF \
        -DBUILD_TESTING=OFF \
        -DBUILD_PYTHON_BINDINGS=OFF
else
    cmake .. \
        -DCMAKE_SYSTEM_NAME=iOS \
        -DCMAKE_OSX_SYSROOT=$SDK \
        -DCMAKE_OSX_ARCHITECTURES=$HOST_ARCH \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=$PREFIX \
        -DBUILD_SHARED_LIBS=ON \
        -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=NEVER \
        -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=NEVER \
        -DCMAKE_FIND_USE_CMAKE_SYSTEM_PATH=NO \
        -DCMAKE_CXX_FLAGS="$CFLAGS" \
        -DCMAKE_SHARED_LINKER_FLAGS="$IOS_GDAL_LINK_LIBS" \
        -DGDAL_USE_EXTERNAL_LIBS=OFF \
        -DPROJ_LIBRARY=$PLATLIB/opt/lib/libproj.a \
        -DPROJ_INCLUDE_DIR=$PLATLIB/opt/include \
        -DSQLite3_LIBRARY=$SDK_ROOT/usr/lib/libsqlite3.tbd \
        -DSQLite3_INCLUDE_DIR=$SDK_ROOT/usr/include \
        -DGDAL_BUILD_OPTIONAL_DRIVERS=OFF \
        -DOGR_BUILD_OPTIONAL_DRIVERS=OFF \
        -DGDAL_USE_OPENMP=OFF \
        -DBUILD_APPS=OFF \
        -DBUILD_TESTING=OFF \
        -DBUILD_PYTHON_BINDINGS=OFF
fi

cmake --build . -j $CPU_COUNT
cmake --build . --target install

# iOS ships libgdal SHARED so that every extension of a consumer resolves ONE
# image, and therefore one driver registry. A static libgdal is copied into each
# extension that links it, which gives each its own copy of GDAL's process
# globals -- the driver table among them -- and that is a real bug, not just
# bytes: the module that registers is not the module that looks up.
#
# Two fixups are required before the dylib is usable under flet:
#
#  1. DE-VERSION it. CMake installs libgdal.<soversion>.dylib plus unversioned
#     and major-version symlinks. serious_python's per-slice framework
#     relocation globs both "libgdal.*.dylib" and "libgdal.dylib", so it matches
#     the real file AND both symlinks and then runs `lipo -create` on three
#     copies of one arch, which fails with "duplicate architecture". The
#     framework is then silently never built and a consumer's @rpath link cannot
#     resolve at runtime. Same fixup, same reason, as recipes/flet-libarrow.
#  2. Give it an @rpath install id, so a consumer that links it records
#     @rpath/libgdal.dylib rather than this build directory.
#
# Android is untouched: it already builds shared and ships a plain versionless
# .so through jniLibs.
if [ $CROSS_VENV_SDK != "android" ]; then
    echo "=== de-versioning libgdal.dylib for iOS ==="
    _real="$(find "$PREFIX/lib" -maxdepth 1 -type f -name "libgdal.*.dylib" | head -1)"
    if [ -n "$_real" ]; then
        mv "$_real" "$PREFIX/lib/libgdal.dylib.tmp"
        find "$PREFIX/lib" -maxdepth 1 -name "libgdal.*.dylib" -delete  # version symlinks
        rm -f "$PREFIX/lib/libgdal.dylib"                               # unversioned symlink
        mv "$PREFIX/lib/libgdal.dylib.tmp" "$PREFIX/lib/libgdal.dylib"
    fi
    install_name_tool -id "@rpath/libgdal.dylib" "$PREFIX/lib/libgdal.dylib"
    echo "=== install id: $(otool -D "$PREFIX/lib/libgdal.dylib" | tail -1) ==="
    otool -L "$PREFIX/lib/libgdal.dylib"
fi

rm -rf $PREFIX/{bin,share}
rm -rf $PREFIX/lib/{cmake,pkgconfig}