from concurrent.futures import ThreadPoolExecutor
import codecs
import errno
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from converter import collect_jars, convert_jar, patch_metadata


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def jar(self, name="example.jar", metadata=b'{"schemaVersion":1,"id":"sample","version":"1.0"}', extra=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.comment = "原始归档注释".encode()
            if metadata is not None:
                archive.writestr("fabric.mod.json", metadata)
            archive.writestr("assets/中文/unchanged.bin", bytes(range(256)) * 9)
            archive.writestr("META-INF/MANIFEST.MF", b"Manifest-Version: 1.0\r\n\r\n")
            archive.writestr("LICENSE", b"Original author and license")
            for name, data in (extra or {}).items():
                archive.writestr(name, data)
        return path

    def test_other_json_bytes_are_unchanged(self):
        raw = b'{\r\n  "id": "a", "ratio":1.000e+05, "big":999999999999999999999,\r\n  "custom":{"neofabric":false,"escaped":"\\u4e2d"}\r\n}\n'
        out, mod_id = patch_metadata(raw)
        self.assertEqual(mod_id, "a")
        self.assertEqual(out.replace(b',\r\n  "neofabric": true', b""), raw)
        self.assertIs(json.loads(out)["neofabric"], True)

    def test_replace_only_top_level_value(self):
        raw = b'{"neofabric" : { "old": [false] }, "custom":{"neofabric":false}}'
        out, _ = patch_metadata(raw)
        self.assertEqual(out, b'{"neofabric" : true, "custom":{"neofabric":false}}')

    def test_duplicate_flags_all_become_true(self):
        out, _ = patch_metadata(b'{"neofabric":false,"neofabric":"true"}')
        self.assertEqual(out, b'{"neofabric":true,"neofabric":true}')

    def test_empty_json_objects_and_bom(self):
        for raw in (b"{}", b"{  }", b"{\n}", b"{\r\n  }", codecs.BOM_UTF8 + b'{"id":"bom"}'):
            with self.subTest(raw=raw):
                output, _ = patch_metadata(raw)
                self.assertIs(json.loads(output)["neofabric"], True)
                self.assertEqual(output.startswith(codecs.BOM_UTF8), raw.startswith(codecs.BOM_UTF8))

    def test_repeated_metadata_patch_is_byte_idempotent(self):
        output, _ = patch_metadata(b'{"id":"x"}')
        self.assertEqual(patch_metadata(output)[0], output)

    def test_raw_metadata_whitespace_and_utf8(self):
        raw = ' \t{\n  "id": "中文",\n  "neofabric": false\n}\r\n'.encode()
        self.assertEqual(patch_metadata(raw)[0], raw.replace(b"false", b"true"))

    def test_non_fabric_is_skipped(self):
        source = self.jar(metadata=None)
        result = convert_jar(source)
        self.assertFalse(result.success)
        self.assertIn("非 Fabric 模组", result.reason)
        self.assertIsNone(result.output)
        self.assertEqual(list(self.root.glob("*_neofabric*.jar")), [])

    def test_nested_metadata_is_not_root_metadata(self):
        source = self.jar(metadata=None, extra={"nested/fabric.mod.json": b'{"id":"x"}'})
        self.assertIn("非 Fabric 模组", convert_jar(source).reason)

    def test_malformed_json_variants(self):
        for index, raw in enumerate((b"{", b"[]", b"null", b"{}", b'{"n":NaN}', b'{"x":1}[]', b"\xff")):
            if raw == b"{}":
                continue
            with self.subTest(raw=raw):
                result = convert_jar(self.jar(f"bad-{index}.jar", metadata=raw))
                self.assertFalse(result.success)
                self.assertIn("JSON 损坏", result.reason)

    def test_duplicate_metadata_entry_is_rejected(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            path = self.jar(extra={"fabric.mod.json": b'{"id":"other"}'})
        result = convert_jar(path)
        self.assertFalse(result.success)
        self.assertIn("重复", result.reason)

    def test_broken_archive_is_skipped(self):
        source = self.root / "broken.jar"
        source.write_bytes(b"not a ZIP archive")
        self.assertIn("jar 损坏", convert_jar(source).reason)

    def test_remove_only_specified_meta_inf_signatures(self):
        contents = {
            "META-INF/ONE.SF": b"sig", "META-INF/ONE.RSA": b"sig",
            "meta-inf/sub/two.dsa": b"sig", "META-INF/three.sF": b"sig",
            "OTHER/keep.SF": b"must stay", "META-INF/keep.txt": b"must stay",
            "META-INF/services/a": b"service", "META-INF/jars/child.jar": b"unchanged nested bytes",
        }
        source = self.jar(extra=contents)
        before_bytes = source.read_bytes()
        result = convert_jar(source)
        self.assertTrue(result.success, result.reason)
        self.assertEqual(result.removed_signatures, 4)
        self.assertEqual(before_bytes, source.read_bytes())
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(result.output) as output:
            self.assertEqual(output.comment, original.comment)
            expected = {x for x in original.namelist() if x not in {
                "META-INF/ONE.SF", "META-INF/ONE.RSA", "meta-inf/sub/two.dsa", "META-INF/three.sF"
            }}
            self.assertEqual(set(output.namelist()), expected)
            for entry in output.infolist():
                if entry.filename != "fabric.mod.json":
                    self.assertEqual(output.read(entry), original.read(entry.filename))
                    self.assertEqual(entry.CRC, original.getinfo(entry.filename).CRC)
            self.assertIs(json.loads(output.read("fabric.mod.json"))["neofabric"], True)

    def test_zip_attributes_and_directories_are_preserved(self):
        path = self.root / "attrs.jar"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("fabric.mod.json", b"{}")
            info = zipfile.ZipInfo("lib/中文.class", (2020, 3, 4, 5, 6, 8))
            info.comment = b"entry comment"
            info.external_attr = 0o755 << 16
            info.extra = b"\xfe\xca\x02\x00ab"
            archive.writestr(info, b"class bytes")
            archive.writestr("empty/", b"")
        result = convert_jar(path)
        with zipfile.ZipFile(path) as a, zipfile.ZipFile(result.output) as b:
            for name in ("lib/中文.class", "empty/"):
                for field in ("date_time", "comment", "external_attr", "extra", "compress_type"):
                    self.assertEqual(getattr(a.getinfo(name), field), getattr(b.getinfo(name), field))

    def test_collision_adds_number_without_overwriting(self):
        source = self.jar()
        existing = self.root / "example_neofabric.jar"
        existing.write_bytes(b"existing output")
        result = convert_jar(source)
        self.assertTrue(result.success, result.reason)
        self.assertEqual(result.output.name, "example_neofabric_1.jar")
        self.assertEqual(existing.read_bytes(), b"existing output")

    def test_directory_name_collision_also_gets_a_suffix(self):
        source = self.jar()
        (self.root / "example_neofabric.jar").mkdir()
        result = convert_jar(source)
        self.assertTrue(result.success, result.reason)
        self.assertEqual(result.output.name, "example_neofabric_1.jar")
        self.assertTrue((self.root / "example_neofabric.jar").is_dir())

    def test_converted_jar_can_be_converted_again(self):
        first = convert_jar(self.jar())
        second = convert_jar(first.output)
        self.assertTrue(second.success, second.reason)
        self.assertNotEqual(first.output, second.output)
        with zipfile.ZipFile(second.output) as archive:
            self.assertIs(json.loads(archive.read("fabric.mod.json"))["neofabric"], True)

    def test_chinese_and_uppercase_extension(self):
        result = convert_jar(self.jar("中文 文件夹/你好 世界.JAR"))
        self.assertTrue(result.success, result.reason)
        self.assertEqual(result.output.parent.name, "中文 文件夹")
        self.assertEqual(result.output.name, "你好 世界_neofabric.jar")

    def test_parallel_conversion_never_overwrites(self):
        source = self.jar()
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(convert_jar, [source] * 4))
        self.assertTrue(all(x.success for x in results), results)
        self.assertEqual(len({x.output for x in results}), 4)
        self.assertEqual(list(self.root.glob(".neoconverter-*")), [])
        for result in results:
            with zipfile.ZipFile(result.output) as archive:
                self.assertIs(json.loads(archive.read("fabric.mod.json"))["neofabric"], True)

    def test_permission_error_does_not_create_output(self):
        source = self.jar()
        with patch("converter.tempfile.NamedTemporaryFile", side_effect=PermissionError("denied")):
            result = convert_jar(source)
        self.assertFalse(result.success)
        self.assertIn("权限不足", result.reason)
        self.assertEqual(list(self.root.glob("*_neofabric*.jar")), [])

    def test_disk_full_cleans_temporary_file(self):
        source = self.jar()
        original = source.read_bytes()
        with patch("converter.shutil.copyfileobj", side_effect=OSError(errno.ENOSPC, "full")):
            result = convert_jar(source)
        self.assertFalse(result.success)
        self.assertIn("磁盘空间不足", result.reason)
        self.assertEqual(list(self.root.glob(".neoconverter-*")), [])
        self.assertEqual(list(self.root.glob("*_neofabric*.jar")), [])
        self.assertEqual(source.read_bytes(), original)

    def test_flush_failure_is_caught(self):
        source = self.jar()
        with patch("converter.os.fsync", side_effect=OSError(errno.ENOSPC, "full")):
            result = convert_jar(source)
        self.assertFalse(result.success)
        self.assertIn("磁盘空间不足", result.reason)
        self.assertEqual(list(self.root.glob(".neoconverter-*")), [])

    def test_publish_failure_cleans_temporary_file(self):
        source = self.jar()
        with patch("converter._publish_without_overwrite", side_effect=PermissionError("locked")):
            result = convert_jar(source)
        self.assertFalse(result.success)
        self.assertIn("权限不足", result.reason)
        self.assertEqual(list(self.root.glob(".neoconverter-*")), [])

    def test_crc_error_does_not_publish_partial_archive(self):
        path = self.jar()
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("assets/中文/unchanged.bin")
            offset = info.header_offset
        data = bytearray(path.read_bytes())
        name_size = int.from_bytes(data[offset + 26:offset + 28], "little")
        extra_size = int.from_bytes(data[offset + 28:offset + 30], "little")
        data[offset + 30 + name_size + extra_size + 3] ^= 0x40
        path.write_bytes(data)
        result = convert_jar(path)
        self.assertFalse(result.success)
        self.assertEqual(list(self.root.glob("*_neofabric*.jar")), [])
        self.assertEqual(list(self.root.glob(".neoconverter-*")), [])

    def test_missing_file_and_non_jar(self):
        self.assertIn("文件不存在", convert_jar(self.root / "gone.jar").reason)
        self.assertIn("不是 .jar", convert_jar(self.root / "readme.txt").reason)

    def test_collector_deduplicates_and_handles_case(self):
        a = self.jar("a.JAR")
        self.jar("sub/b.jar")
        (self.root / "readme.txt").write_text("text")
        found, notes = collect_jars([self.root, a, self.root / "readme.txt"])
        self.assertEqual(found, [a])
        self.assertTrue(any("非 jar" in n for n in notes))

    def test_recursive_folder_and_snapshot(self):
        self.jar("a.jar")
        self.jar("sub/b.jar")
        found, _ = collect_jars([self.root], recursive=True)
        self.assertEqual(len(found), 2)
        for path in found:
            self.assertTrue(convert_jar(path).success)
        self.assertEqual(len(found), 2)
        self.assertEqual(len(collect_jars([self.root], recursive=True)[0]), 4)

    def test_metadata_limit(self):
        source = self.jar()
        with patch("converter.MAX_METADATA", 2):
            result = convert_jar(source)
        self.assertIn("安全上限", result.reason)

    def test_cli_batch_report(self):
        import NeoConverter
        original = self.jar("normal.jar")
        other = self.jar("non-fabric.jar", metadata=None)
        report = self.root / "汇总.json"
        with patch("sys.argv", ["NeoConverter", "--batch", str(original), str(other), "--report", str(report)]), patch("sys.stdout", new=io.StringIO()):
            NeoConverter.main()
        value = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual((value["success"], value["skipped"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
