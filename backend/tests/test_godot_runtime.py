from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runners.godot_runtime import (
    GodotRuntime,
    GodotRuntimeError,
    _CA_INTERPOSER_SOURCE,
    _SYSTEM_CA_BUNDLE,
    _canonicalize_certificate_blocks,
    _read_and_validate_system_ca_bundle,
    sandboxed_godot_argv,
)


class GodotRuntimeCATests(unittest.TestCase):
    def test_graphics_drawable_grant_is_narrow_and_not_given_to_headless_roles(self):
        from runners.common import strict_sandbox_rules
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            def profile(graphics):
                return "".join(strict_sandbox_rules(project, read_roots=[project], write_roots=[project],
                                                    protected_paths=[], allow_graphics=graphics))
            headless, graphics = profile(False), profile(True)
            self.assertNotIn("iokit-open", headless)
            self.assertIn('(iokit-user-client-class "IOGPUGLDrawableUserClient")', graphics)
            self.assertNotIn('(allow iokit-open)', graphics)
            self.assertNotIn('(allow network', graphics)
            self.assertIn('(deny default)', graphics)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = GodotRuntime.create(self.root / "runtime")

    def tearDown(self):
        self.temp.cleanup()

    def test_fixed_system_bundle_is_root_owned_and_contains_parseable_pem_certificates(self):
        if not _SYSTEM_CA_BUNDLE.is_file():
            self.skipTest("fixed macOS public CA bundle is unavailable")
        metadata = _SYSTEM_CA_BUNDLE.stat(follow_symlinks=False)
        if metadata.st_uid != 0:
            self.skipTest("fixed CA bundle is not root-owned on this test host")
        contents = _read_and_validate_system_ca_bundle()
        self.assertGreater(contents.count(b"-----BEGIN CERTIFICATE-----"), 0)
        raw_source = _SYSTEM_CA_BUNDLE.read_bytes()
        self.assertEqual(
            _canonicalize_certificate_blocks(raw_source).count(b"-----BEGIN CERTIFICATE-----"),
            contents.count(b"-----BEGIN CERTIFICATE-----"),
        )
        self.assertNotIn(b"Certificate: Data:", contents)

    def test_invalid_fixed_ca_bundle_fails_closed(self):
        with tempfile.NamedTemporaryFile() as invalid:
            invalid.write(b"not a PEM CA bundle")
            invalid.flush()
            with mock.patch("runners.godot_runtime._SYSTEM_CA_BUNDLE", Path(invalid.name)):
                real_fstat = os.fstat

                def root_owned_fstat(descriptor):
                    result = real_fstat(descriptor)
                    values = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
                    values["st_uid"] = 0
                    return type("StatResult", (), values)()

                with mock.patch("runners.godot_runtime.os.fstat", side_effect=root_owned_fstat):
                    with self.assertRaisesRegex(GodotRuntimeError, "PEM markers"):
                        _read_and_validate_system_ca_bundle()

    @mock.patch("runners.godot_runtime.sys.platform", "darwin")
    def test_interposer_uses_host_source_and_compile_time_bundle_binding(self):
        bundle_bytes = b"trusted test bundle"
        fake_clang = self.root / "clang"
        fake_clang.touch()
        fake_clang.chmod(0o700)
        fake_sdk = self.root / "MacOSX.sdk"
        fake_sdk.mkdir()
        with mock.patch("runners.godot_runtime._CLANG", fake_clang), \
             mock.patch("runners.godot_runtime._MACOS_SDK", fake_sdk), \
             mock.patch("runners.godot_runtime._read_and_validate_system_ca_bundle", return_value=bundle_bytes), \
             mock.patch("runners.godot_runtime.subprocess.run") as run:
            def compile_fake(argv, **kwargs):
                output = Path(argv[argv.index("-o") + 1])
                output.write_bytes(b"fake compiled dylib")
                return subprocess.CompletedProcess(argv, 0, "", "")

            run.side_effect = compile_fake
            support, bundle, library = self.runtime.prepare_trusted_ca_interposer()
            self.assertEqual(support, (self.root / "runtime" / "trusted-ca").resolve())
            self.assertEqual(bundle.read_bytes(), bundle_bytes)
            self.assertEqual(library.read_bytes(), b"fake compiled dylib")
            self.assertEqual(library.stat().st_mode & 0o777, 0o700)
            argv = run.call_args.args[0]
            self.assertEqual(Path(argv[-1]), _CA_INTERPOSER_SOURCE)
            binding = next(item for item in argv if item.startswith("-DSTUDIO_GODOT_CA_BUNDLE_PATH="))
            self.assertIn(str(bundle), binding)
            self.assertEqual(self.runtime._ca_assets.get("compile_binding"), bundle)
            self.runtime.prepare_trusted_ca_interposer()
            self.assertEqual(run.call_count, 1)

    @mock.patch("runners.godot_runtime.sys.platform", "darwin")
    def test_missing_command_line_tools_raises_a_controlled_error(self):
        with mock.patch("runners.godot_runtime._read_and_validate_system_ca_bundle", return_value=b"CA"), \
             mock.patch("runners.godot_runtime._CLANG", self.root / "missing-clang"):
            with self.assertRaisesRegex(GodotRuntimeError, "Command Line Tools"):
                self.runtime.prepare_trusted_ca_interposer()

    @mock.patch("runners.godot_runtime.sys.platform", "darwin")
    def test_compile_failure_raises_instead_of_launching_without_anchors(self):
        fake_clang = self.root / "clang"
        fake_clang.touch()
        fake_clang.chmod(0o700)
        fake_sdk = self.root / "MacOSX.sdk"
        fake_sdk.mkdir()
        with mock.patch("runners.godot_runtime._CLANG", fake_clang), \
             mock.patch("runners.godot_runtime._MACOS_SDK", fake_sdk), \
             mock.patch("runners.godot_runtime._read_and_validate_system_ca_bundle", return_value=b"CA"), \
             mock.patch("runners.godot_runtime.subprocess.run",
                        return_value=subprocess.CompletedProcess([], 1, "", "compile failed")):
            with self.assertRaisesRegex(GodotRuntimeError, "interposer compilation failed"):
                self.runtime.prepare_trusted_ca_interposer()

    @unittest.skipUnless(
        sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file(),
        "macOS seatbelt is required to inspect the production argv",
    )
    def test_central_sandbox_injects_dyld_only_through_env_and_denies_support_writes(self):
        project = self.root / "project"
        project.mkdir()
        fake_engine = self.root / "fake-godot"
        fake_engine.write_text("engine mock", encoding="utf-8")
        fake_engine.chmod(0o700)
        support = self.root / "runtime" / "trusted-ca"
        support.mkdir()
        bundle = support / "system-ca.pem"
        bundle.write_text("private CA copy", encoding="ascii")
        bundle.chmod(0o600)
        library = support / "libgodot_trusted_ca.dylib"
        library.write_text("private library", encoding="ascii")
        library.chmod(0o700)
        with mock.patch.object(
            GodotRuntime,
            "prepare_trusted_ca_interposer",
            return_value=(support, bundle, library),
        ):
            argv = sandboxed_godot_argv(
                fake_engine,
                ["--version"],
                project_root=project,
                runtime=self.runtime,
            )

        self.assertEqual(argv[3], "/usr/bin/env")
        self.assertEqual(argv[4], f"DYLD_INSERT_LIBRARIES={library}")
        self.assertEqual(argv[5], str(fake_engine.resolve()))
        profile = argv[2]
        self.assertIn(f'(deny file-write* (subpath "{support.resolve()}")', profile)
        self.assertIn(f'(deny file-write* (literal "{bundle.resolve()}")', profile)
        self.assertIn(f'(deny file-write* (literal "{library.resolve()}")', profile)
        self.assertIn("(deny file-link)", profile)
        self.assertIn('(allow process-exec (literal "/usr/bin/env"))', profile)
        self.assertNotIn("(allow network-outbound", profile)
        self.assertNotIn("user-preference-read", profile)

    def test_interposer_has_no_experiment_environment_override_or_runtime_log_probe(self):
        source = _CA_INTERPOSER_SOURCE.read_text(encoding="utf-8")
        self.assertIn("STUDIO_GODOT_CA_BUNDLE_PATH", source)
        self.assertNotIn("getenv(", source)
        self.assertNotIn("STUDIO_CA_INTERPOSE_LOG", source)
        self.assertNotIn("write_open", source)
        self.assertIn("CFArrayGetCount(g_anchors) == 0", source)
        self.assertIn("return g_initialization_status", source)


if __name__ == "__main__":
    unittest.main()
