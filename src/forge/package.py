from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import jinja2
import jsonschema
import yaml

from forge.build import Builder, PythonPackageBuilder, SimplePackageBuilder
from forge.cross import CrossVEnv


def _same_version(left: str, right: str) -> bool:
    """Compare two version strings, tolerating spelling differences.

    Falls back to a string compare when either side will not parse, so an
    unusual recipe version can never raise here.
    """
    try:
        from packaging.version import InvalidVersion, Version

        try:
            return Version(left) == Version(right)
        except InvalidVersion:
            return left == right
    except ImportError:  # pragma: no cover - packaging ships with pip/build
        return left == right


class Package:
    def __init__(
        self,
        package_name_or_recipe: str,
        version: str | None,
        build_number: int | None,
        sdk: str,
        sdk_version: str,
        arch: str,
    ):
        self.sdk = sdk
        self.sdk_version = sdk_version
        self.arch = arch

        if "/" in package_name_or_recipe:
            self.recipe_path = Path(package_name_or_recipe)
        else:
            self.recipe_path = Path.cwd() / "recipes" / package_name_or_recipe

        if not (self.recipe_path / "meta.yaml").exists():
            raise ValueError(
                f"{package_name_or_recipe} does not appear to be a valid recipe."
            )

        self.meta = self.load_meta(
            override_version=version, override_build=build_number
        )

        # Extract some useful properties from the metadata
        self.name = self.meta["package"]["name"]
        self.version = self.meta["package"]["version"]

    def __str__(self):
        return f"{self.name} {self.version}"

    def load_meta(self, override_version, override_build):
        # http://python-jsonschema.readthedocs.io/en/latest/faq/
        def with_defaults(validator_cls):
            def set_defaults(validator, properties, instance, schema):
                for name, subschema in properties.items():
                    if "default" in subschema:
                        instance.setdefault(name, deepcopy(subschema["default"]))
                yield from validator_cls.VALIDATORS["properties"](
                    validator, properties, instance, schema
                )

            return jsonschema.validators.extend(
                validator_cls, {"properties": set_defaults}
            )

        # Validate the meta-schema
        Validator = jsonschema.Draft4Validator
        with (Path(__file__).parent / "schema" / "meta-schema.yaml").open(
            encoding="utf-8"
        ) as f:
            schema = yaml.safe_load(f)
        Validator.check_schema(schema)

        with (self.recipe_path / "meta.yaml").open(encoding="utf-8") as f:
            meta_template = f.read()

        # Render the meta template.
        meta_str = jinja2.Template(meta_template).render(
            sdk=self.sdk,
            sdk_version=self.sdk_version,
            arch=self.arch,
            version=(
                tuple(int(v) for v in override_version.split("."))
                if override_version
                else None
            ),
            py_version=sys.version_info,
        )

        # Parse the rendered meta template
        meta = yaml.safe_load(meta_str)

        # If there's a version override, set it in the package metadata.
        # An explicit build number wins. Otherwise the recipe's build number
        # survives unless the override names a DIFFERENT version, where it
        # would describe a build of something else.
        #
        # Only purging on a genuine version change matters because the schema
        # defaults `build.number` to 1, so purging it is a silent downgrade:
        # `forge <pkg>:<same version>` -- the form CI uses when it pins a
        # version -- would relabel a build 13 wheel as build 1, which then
        # LOSES the PEP 427 tie-break against whatever is already published at
        # that version, and the rebuild it was meant to ship becomes invisible.
        if override_version:
            try:
                recipe_version = str(meta["package"]["version"])
                meta["package"]["version"] = override_version
                if override_build:
                    meta.setdefault("build", {})["number"] = override_build
                elif not _same_version(recipe_version, override_version):
                    del meta["build"]["number"]
            except KeyError:
                pass

        # Validate the metadata against the schema.
        with_defaults(Validator)(schema).validate(meta)

        return meta

    def builder(self, cross_venv: CrossVEnv) -> Builder:
        """Return a builder for this package in the given cross-platform environment.

        :param cross_venv: The cross-platform environment to use for the build
        :returns: A builder for the package.
        """
        if (self.recipe_path / "build.sh").exists():
            return SimplePackageBuilder(cross_venv=cross_venv, package=self)
        else:
            return PythonPackageBuilder(cross_venv=cross_venv, package=self)
