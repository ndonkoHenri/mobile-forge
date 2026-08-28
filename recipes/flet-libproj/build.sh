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

# Libraries the SHARED libproj must resolve for itself on iOS. PROJ calls into
# libtiff (reading GTiff grid files), libcurl (fetching grids over the network)
# and sqlite3 (opening proj.db); libtiff in turn needs libjpeg, and libcurl is
# configured --with-openssl, hence ssl/crypto and psl. sqlite3 and z are iOS
# system libraries and resolve from the SDK. Ordered by dependency, since these
# are static archives.
#
# Under a static libproj these stayed undefined and every consumer's extension
# link paid for them -- which is what the PROJ_LIBS chain in recipes/pyproj was
# for. A real dylib settles it once, here.
IOS_PROJ_LINK_LIBS="-L$PLATLIB/opt/lib -ltiff -ljpeg -lcurl -lssl -lcrypto -lpsl -lsqlite3 -lz"

if [ $CROSS_VENV_SDK == "android" ]; then
    cmake \
        -DCMAKE_SYSTEM_NAME=Android \
        -DANDROID_PLATFORM=$SDK_VERSION \
        -DANDROID_ABI=$ANDROID_ABI \
        -DCMAKE_TOOLCHAIN_FILE=$NDK_ROOT/build/cmake/android.toolchain.cmake \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_SHARED_LINKER_FLAGS="$LDFLAGS" \
        -DCMAKE_INSTALL_PREFIX="$PREFIX" \
        -DBUILD_TESTING=0 \
        -DTIFF_LIBRARY="$PLATLIB/opt/lib/libtiff.so" \
        -DTIFF_INCLUDE_DIR="$PLATLIB/opt/include" \
        -DCURL_LIBRARY="$PLATLIB/opt/lib/libcurl.so" \
        -DCURL_INCLUDE_DIR="$PLATLIB/opt/include" \
        -DSQLite3_LIBRARY=$HOST_PYTHON_HOME/lib/libsqlite3_python.so \
        -DSQLite3_INCLUDE_DIR=$SQLITE3_INC
else
    cmake \
        -DCMAKE_SYSTEM_NAME=iOS \
        -DCMAKE_OSX_SYSROOT=$SDK \
        -DCMAKE_OSX_ARCHITECTURES=$HOST_ARCH \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=$PREFIX \
        -DBUILD_SHARED_LIBS=ON \
        -DCMAKE_SHARED_LINKER_FLAGS="$IOS_PROJ_LINK_LIBS" \
        -DBUILD_TESTING=0 \
        -DTIFF_LIBRARY="$PLATLIB/opt/lib/libtiff.a" \
        -DTIFF_INCLUDE_DIR="$PLATLIB/opt/include" \
        -DCURL_LIBRARY="$PLATLIB/opt/lib/libcurl.a" \
        -DCURL_INCLUDE_DIR="$PLATLIB/opt/include" \
        -DSQLite3_LIBRARY=$SDK_ROOT/usr/lib/libsqlite3.tbd \
        -DSQLite3_INCLUDE_DIR=$SDK_ROOT/usr/include
fi

cmake --build . -j $CPU_COUNT
cmake --build . --target install

# iOS ships libproj SHARED so that every extension of a consumer resolves ONE
# image -- pyproj has eight extensions that use PROJ, and a static archive gives
# each its own copy of PROJ's globals, including the proj.db search path a
# `set_data_dir()` writes to. Shared also means libgdal and pyproj share one
# PROJ, so configuring the database once configures it for both.
#
# De-version and stamp an @rpath install id, for the same reasons as
# recipes/flet-libgdal: serious_python's framework relocation globs both
# "libproj.*.dylib" and "libproj.dylib", so a versioned dylib plus its symlinks
# makes `lipo -create` fail ("duplicate architecture") and the simulator
# framework is silently never built.
if [ $CROSS_VENV_SDK != "android" ]; then
    echo "=== de-versioning libproj.dylib for iOS ==="
    _real="$(find "$PREFIX/lib" -maxdepth 1 -type f -name "libproj.*.dylib" | head -1)"
    if [ -n "$_real" ]; then
        mv "$_real" "$PREFIX/lib/libproj.dylib.tmp"
        find "$PREFIX/lib" -maxdepth 1 -name "libproj.*.dylib" -delete
        rm -f "$PREFIX/lib/libproj.dylib"
        mv "$PREFIX/lib/libproj.dylib.tmp" "$PREFIX/lib/libproj.dylib"
    fi
    install_name_tool -id "@rpath/libproj.dylib" "$PREFIX/lib/libproj.dylib"
    echo "=== install id: $(otool -D "$PREFIX/lib/libproj.dylib" | tail -1) ==="
    otool -L "$PREFIX/lib/libproj.dylib"
fi

# Keep share/proj/proj.db -- PROJ's CRS database, the file that makes EPSG codes
# resolve. Everything else under share/ (and all of bin/) goes: the init files,
# JSON schemas and proj.ini are unused without the grids they reference, and
# get_data_dir() looks for proj.db alone.
_projdb="$PREFIX/share/proj/proj.db"
if [ -f "$_projdb" ]; then
    _keep="$(mktemp -d)"
    mv "$_projdb" "$_keep/proj.db"
    rm -rf $PREFIX/{bin,share}
    mkdir -p "$PREFIX/share/proj"
    mv "$_keep/proj.db" "$_projdb"
    rmdir "$_keep"
    echo "=== kept $(du -h "$_projdb" | cut -f1) proj.db ==="
else
    rm -rf $PREFIX/{bin,share}
fi
rm -rf $PREFIX/lib/{cmake,pkgconfig}