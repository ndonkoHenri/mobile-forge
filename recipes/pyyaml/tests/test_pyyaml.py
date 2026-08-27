DOC = {
    "name": "mobile-forge",
    "components": ["recipes", "tests", "ci"],
    "android": {"api": 24, "abi": ["arm64-v8a", "x86_64"]},
    "iOS": {"min": "13.0"},
}


def test_basic():
    """Round-trip a small document through PyYAML's pure-Python path."""
    import yaml

    text = yaml.safe_dump(DOC, sort_keys=True)
    assert yaml.safe_load(text) == DOC


def test_libyaml_parses_and_emits():
    """Round-trip through the C loader and dumper — the reason this recipe exists.

    `safe_load` and `safe_dump` resolve `SafeLoader`/`SafeDumper` from
    `yaml.loader`, which is pure Python; the C classes live in `yaml.cyaml` and
    are only used when passed explicitly. So the rest of this file proves the
    extension imports and exports `CParser`, and never runs libyaml over a
    document — a libyaml that loads but cannot parse passes all of it.

    Naming the classes is the whole point, so assert the module they came from
    too: if a future PyYAML makes the C path the default, this keeps testing
    the C path rather than quietly retesting `test_basic`.
    """
    import yaml

    assert yaml.CSafeLoader.__module__ == "yaml.cyaml"
    assert yaml.CSafeDumper.__module__ == "yaml.cyaml"

    text = yaml.dump(DOC, Dumper=yaml.CSafeDumper, sort_keys=True)
    assert yaml.load(text, Loader=yaml.CSafeLoader) == DOC

    # Cross the implementations: libyaml emits, pure Python reads, and back.
    assert yaml.safe_load(text) == DOC
    assert yaml.load(yaml.safe_dump(DOC), Loader=yaml.CSafeLoader) == DOC


def test_libyaml_reports_a_syntax_error():
    """A malformed document must raise through the C parser, not crash.

    libyaml reports errors by filling a struct the binding turns into a Python
    exception. That path is compiled code too, and it is the one a bad build is
    most likely to take on a device, so cover it rather than only the happy one.
    """
    import pytest
    import yaml

    with pytest.raises(yaml.YAMLError):
        yaml.load("key: [unterminated, list\n", Loader=yaml.CSafeLoader)


def test_c_extension():
    """The C accelerator (_yaml) is what this recipe primarily exists for.

    PyYAML exposes `CSafeDumper`/`CSafeLoader` only when the C extension
    successfully imports — otherwise they're simply absent from the `yaml`
    package namespace (no exception, no None — just missing names). Probe by
    importing the extension and checking it carries the Cython-emitted
    `CParser` class. That assertion fires both when the .so was never shipped
    AND when libyaml fails to load at import time on the device.

    Import it as `yaml._yaml`, which is where the extension actually lives.
    The top-level `_yaml` is a shim package that warns on import and whose
    location upstream calls subject to change, so testing it tests the shim."""
    import yaml._yaml

    assert hasattr(yaml._yaml, "CParser"), (
        "PyYAML's yaml._yaml C extension loaded but is missing CParser — "
        "libyaml probably failed to load at import time"
    )


def test_csafedumper_binding():
    """The user-facing surface: `from yaml import CSafeDumper, CSafeLoader`.

    Functionally subsumed by test_c_extension (cyaml.py exposes these
    classes iff `_yaml.CParser` exists), but kept as a separate test
    because (a) this is the import shape real apps break on and (b) a
    clean ImportError here points a future debugger straight at the
    `_yaml`/libyaml chain instead of an obscure attribute-missing
    surprise downstream."""
    from yaml import CSafeDumper, CSafeLoader  # noqa: F401
