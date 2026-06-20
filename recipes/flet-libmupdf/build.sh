#!/bin/bash
# Cross-compile the MuPDF C library (libmupdf.a + libmupdf-third.a) for Flet's
# mobile targets. MuPDF uses its own GNU Makefile (not autotools/CMake).
#
# Mechanism (see MuPDF's Makerules / Makefile):
#   - Toolchain is overridden on the command line: CC=/CXX=/AR= take precedence
#     over Makerules' `CC = xcrun cc` Darwin defaults (make ranks command-line
#     assignments above makefile `=` assignments).
#   - forge's SDK flags must be *appended*, never assigned: a bare `CFLAGS=` on
#     the command line would clobber MuPDF's internal `CFLAGS += -O2 -DNDEBUG ...`
#     and the per-feature `-D` defines. MuPDF's documented hook is the X-prefixed
#     vars — `CFLAGS += $(XCFLAGS) -Iinclude`, `LDFLAGS += $(XLDFLAGS)`, and the
#     C++ compile line uses `$(CFLAGS) $(XCXXFLAGS)`.
#   - OS selects platform conventions. The host is macOS, so the default
#     `uname` gives Darwin (correct for iOS: clang/dylib/-dead_strip). For
#     Android we force OS=Linux so we don't inherit the Darwin xcrun/framework
#     bits, and pin HAVE_OBJCOPY=no so embedded fonts use the portable hexdump
#     codegen instead of objcopy (which the Linux branch would otherwise enable).
#   - Optional features that would drag in host libraries are switched off
#     (libcrypto/glut/x11/curl), leaving the core engine plus the bundled
#     thirdparty deps. HTML/EPUB stays on (harfbuzz+gumbo) — PyMuPDF needs it.
set -eu

if [ "$CROSS_VENV_SDK" = "android" ]; then
    MUPDF_OS="Linux"
else
    MUPDF_OS="Darwin"
fi

# Knobs shared by every make pass. Keeping them identical guarantees the
# generate / build / install passes all resolve the same OUT=build/release dir
# and the same set of generated font sources.
COMMON="OS=$MUPDF_OS build=release \
    HAVE_LIBCRYPTO=no HAVE_GLUT=no HAVE_X11=no HAVE_CURL=no HAVE_OBJCOPY=no \
    barcode=no tesseract=no \
    CC=$CC CXX=$CXX AR=$AR RANLIB=$RANLIB LD=$CC"

# Embedded resources (fonts, CMaps, ICC profiles) are produced by HOST-only
# tooling — `bash scripts/hexdump.sh`, `python3 scripts/cmapdump.py`, `sed` — and
# never invoke the cross compiler, so it is safe to generate them up front. Pass
# the same HAVE_OBJCOPY=no so the .c font sources are actually emitted (the
# objcopy path would skip them, then the cross compile would fail to find them).
# shellcheck disable=SC2086  # COMMON must word-split into separate make args.
make $COMMON generate

# shellcheck disable=SC2086
make -j "$CPU_COUNT" $COMMON \
    XCFLAGS="$CFLAGS $CPPFLAGS -fPIC" \
    XCXXFLAGS="-std=c++14" \
    XLDFLAGS="$LDFLAGS" \
    libs

# install-libs (not `install`, which also runs install-apps for the unbuilt
# mutool/muraster CLIs) copies include/mupdf/** + libmupdf.a + libmupdf-third.a.
# shellcheck disable=SC2086
make $COMMON \
    XCFLAGS="$CFLAGS $CPPFLAGS -fPIC" \
    XLDFLAGS="$LDFLAGS" \
    prefix="$PREFIX" \
    install-libs

shopt -s nullglob
rm -rf "$PREFIX"/lib/pkgconfig
