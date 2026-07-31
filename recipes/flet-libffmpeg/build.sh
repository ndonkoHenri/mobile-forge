#!/bin/bash
# Cross-compile FFmpeg for iOS and Android as a mobile-forge flet-lib* recipe.
#
# Environment (set by forge):
#   CC, CXX, AR, STRIP, RANLIB       -- cross-compile toolchain
#   CFLAGS, CPPFLAGS, LDFLAGS        -- pre-configured flags
#   HOST_TRIPLET, HOST_ARCH          -- e.g. aarch64-linux-android, arm64-v8a
#   SDK, SDK_VERSION, SDK_ROOT       -- platform info
#   NDK_ROOT, NDK_SYSROOT,
#   ANDROID_ABI, ANDROID_API_LEVEL   -- Android-only
#   PREFIX                           -- install here (= <build>/wheel/opt)
#   CPU_COUNT                        -- parallelism

set -eu

# ---------------------------------------------------------------------------
# Map forge arch names to FFmpeg --arch values
# ---------------------------------------------------------------------------
case "$HOST_ARCH" in
    arm64-v8a|arm64)   ff_arch="aarch64" ;;
    armeabi-v7a)       ff_arch="arm"     ;;
    x86_64)            ff_arch="x86_64"  ;;
    x86)               ff_arch="x86"     ;;
    *)                 echo "ERROR: unknown arch $HOST_ARCH"; exit 1 ;;
esac

# ---------------------------------------------------------------------------
# Platform-specific configure args
# ---------------------------------------------------------------------------
if [ "$CROSS_VENV_SDK" = "android" ]; then
    # Android: system=linux, shared libs (bundled in APK)
    target_os="linux"
    sysroot="$NDK_SYSROOT"
    lib_args="--enable-shared --disable-static"

    # Strip quotes from CFLAGS/LDFLAGS that may contain paths with spaces
    # (FFmpeg's configure handles flags differently from autotools)
    extra_cflags="$CFLAGS"
    extra_ldflags="$LDFLAGS"

    # Android 16KB page alignment
    extra_ldflags="$extra_ldflags -Wl,-z,max-page-size=16384"
else
    # iOS: system=darwin, static libs (linked into Python .so/.framework)
    target_os="darwin"
    sysroot="$SDK_ROOT"
    lib_args="--enable-static --disable-shared"

    # On iOS, disable asm to avoid gas-preprocessor / Apple assembler issues.
    # FFmpeg's ARM64 asm uses GNU as syntax; Apple's integrated assembler
    # rejects it. Recent FFmpeg 8.x handles clang better, but disable asm
    # for safety on a first build.
    asm_arg="--disable-asm"

    # iOS: minimum deployment target
    extra_cflags="$CFLAGS -mios-version-min=$SDK_VERSION"
    # Strip literal quotes from LDFLAGS that break FFmpeg's configure
    extra_ldflags=$(printf '%s' "$LDFLAGS" | tr -d '"')
    extra_ldflags="$extra_ldflags -mios-version-min=$SDK_VERSION"
fi

# ---------------------------------------------------------------------------
# Configure FFmpeg
# ---------------------------------------------------------------------------
./configure \
    --prefix="$PREFIX" \
    --cc="$CC" \
    --cxx="$CXX" \
    --ar="$AR" \
    --ranlib="$RANLIB" \
    --strip="$STRIP" \
    --enable-cross-compile \
    --target-os="$target_os" \
    --arch="$ff_arch" \
    --sysroot="$sysroot" \
    --extra-cflags="$extra_cflags" \
    --extra-ldflags="$extra_ldflags" \
    --pkg-config=false \
    $lib_args \
    ${asm_arg:-} \
    --disable-doc \
    --disable-programs \
    --disable-ffmpeg \
    --disable-ffplay \
    --disable-ffprobe \
    --disable-htmlpages \
    --disable-manpages \
    --disable-podpages \
    --disable-txtpages \
    --disable-debug \
    --disable-stripping \
    --disable-vaapi \
    --disable-vdpau \
    --disable-videotoolbox \
    --disable-audiotoolbox \
    --disable-appkit \
    --disable-coreimage \
    --disable-avfoundation \
    --disable-securetransport \
    --disable-cuda-llvm \
    --disable-cuvid \
    --disable-nvenc \
    --disable-nvdec \
    --disable-vulkan

# ---------------------------------------------------------------------------
# Build & install
# ---------------------------------------------------------------------------
make -j "$CPU_COUNT"
make install

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
shopt -s nullglob

rm -rf "$PREFIX/share"
rm -rf "$PREFIX/lib/"*.la
rm -rf "$PREFIX/bin"

# Keep pkgconfig .pc files so downstream pkg-config-based recipes can find FFmpeg.
# (forge sets PKG_CONFIG_PATH to include $PREFIX/lib/pkgconfig at build time.)

# On Android, delete static libs — only shared .so matters for APK bundling.
if [ "$CROSS_VENV_SDK" = "android" ]; then
    rm -rf "$PREFIX/lib/"*.a
fi
