"""NeoConverter: lossless metadata editing and safe JAR conversion (standard library)."""
from __future__ import annotations

import codecs
import copy
from dataclasses import dataclass
import errno
import itertools
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

VERSION = "1.0.0"
METADATA = "fabric.mod.json"
MAX_METADATA = 8 * 1024 * 1024


@dataclass(frozen=True)
class ConversionResult:
    source: Path
    success: bool
    reason: str
    output: Path | None = None
    removed_signatures: int = 0
    mod_id: str = ""

    def log_line(self) -> str:
        if self.success:
            return (
                f"[成功] {self.source.name} → {self.output.name} "
                f"（删除 {self.removed_signatures} 个签名文件）"
            )
        return f"[跳过] {self.source.name}：{self.reason}"


class MetadataError(ValueError):
    pass


def _reject_constant(value: str):
    raise MetadataError(f"不支持 JSON 常量 {value}")


def patch_metadata(raw: bytes) -> tuple[bytes, str]:
    """Replace only top-level flag value tokens, preserving every other byte.

    All duplicate top-level neofabric values are replaced, so JSON readers with
    different duplicate-key policies still see a boolean true.
    """
    try:
        bom = raw.startswith(codecs.BOM_UTF8)
        text = raw.decode("utf-8-sig")
        decoder = json.JSONDecoder(parse_constant=_reject_constant)
        start = len(text) - len(text.lstrip(" \t\r\n"))
        document, end = decoder.raw_decode(text, start)
        if text[end:].strip(" \t\r\n") or not isinstance(document, dict):
            raise MetadataError("根节点必须是一个 JSON 对象，且不能有额外内容")
        cursor = start + 1
        members = []
        while True:
            while text[cursor] in " \t\r\n":
                cursor += 1
            if text[cursor] == "}":
                break
            key_start = cursor
            key, cursor = decoder.raw_decode(text, cursor)
            while text[cursor] in " \t\r\n":
                cursor += 1
            if text[cursor] != ":":
                raise MetadataError("字段缺少冒号")
            cursor += 1
            while text[cursor] in " \t\r\n":
                cursor += 1
            value_start = cursor
            _, cursor = decoder.raw_decode(text, cursor)
            members.append((key, key_start, value_start, cursor))
            while text[cursor] in " \t\r\n":
                cursor += 1
            if text[cursor] == "}":
                break
            if text[cursor] != ",":
                raise MetadataError("字段之间缺少逗号")
            cursor += 1

        replacements = [(a, b) for key, _, a, b in members if key == "neofabric"]
        if replacements:
            for a, b in reversed(replacements):
                text = text[:a] + "true" + text[b:]
        elif members:
            _, key_start, _, value_end = members[-1]
            line_start = text.rfind("\n", 0, key_start) + 1
            indent = text[line_start:key_start]
            pretty = line_start > 0 and not indent.strip(" \t")
            newline = "\r\n" if line_start > 1 and text[line_start - 2] == "\r" else "\n"
            addition = (
                "," + newline + indent + '"neofabric": true'
                if pretty else ',"neofabric":true'
            )
            text = text[:value_end] + addition + text[value_end:]
        else:
            addition = '"neofabric":true'
            if "\n" in text[start + 1:cursor]:
                newline = "\r\n" if "\r\n" in text[start + 1:cursor] else "\n"
                addition = newline + '  "neofabric": true'
            text = text[:start + 1] + addition + text[start + 1:]

        result = text.encode("utf-8")
        if bom:
            result = codecs.BOM_UTF8 + result
        return result, str(document.get("id", ""))
    except (UnicodeError, json.JSONDecodeError, IndexError, RecursionError) as exc:
        raise MetadataError(str(exc)) from exc


def is_signature(name: str) -> bool:
    normalized = name.casefold()
    return (
        normalized.startswith("meta-inf/")
        and not normalized.endswith("/")
        and normalized.endswith((".sf", ".rsa", ".dsa"))
    )


def _publish_without_overwrite(temporary: Path, source: Path) -> Path:
    """Publish a complete archive atomically; a collision never overwrites data."""
    for number in itertools.count():
        suffix = "" if number == 0 else f"_{number}"
        candidate = source.with_name(f"{source.stem}_neofabric{suffix}.jar")
        if os.path.lexists(candidate):
            continue
        try:
            if os.name == "nt":
                # Unlike POSIX rename, Windows rename does not replace an existing file.
                os.rename(temporary, candidate)
            else:
                os.link(temporary, candidate)
            return candidate
        except FileExistsError:
            continue
        except OSError as exc:
            # Portable fallback for filesystems without hard links; still exclusive.
            if os.name == "nt" or exc.errno not in (
                errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV
            ):
                raise
            created = False
            try:
                with candidate.open("xb") as destination:
                    created = True
                    with temporary.open("rb") as original:
                        shutil.copyfileobj(original, destination, 1024 * 1024)
                    destination.flush()
                    os.fsync(destination.fileno())
                return candidate
            except FileExistsError:
                continue
            except BaseException:
                if created:
                    candidate.unlink(missing_ok=True)
                raise


def convert_jar(source: str | os.PathLike) -> ConversionResult:
    source = Path(os.path.abspath(os.fspath(source)))
    temporary = None
    cleanup_error = ""
    try:
        if source.suffix.casefold() != ".jar":
            return ConversionResult(source, False, "不是 .jar 文件")
        with zipfile.ZipFile(source, "r") as archive:
            entries = archive.infolist()
            metadata_entries = [entry for entry in entries if entry.filename == METADATA and not entry.is_dir()]
            if not metadata_entries:
                return ConversionResult(source, False, "非 Fabric 模组（根目录没有 fabric.mod.json）")
            if len(metadata_entries) != 1:
                return ConversionResult(source, False, "JSON 损坏（存在重复的 fabric.mod.json）")
            if metadata_entries[0].file_size > MAX_METADATA:
                return ConversionResult(source, False, "JSON 损坏（元数据超过 8 MiB 安全上限）")
            patched, mod_id = patch_metadata(archive.read(metadata_entries[0]))
            removed = 0
            with tempfile.NamedTemporaryFile(
                mode="w+b", prefix=".neoconverter-", suffix=".tmp", dir=source.parent, delete=False
            ) as raw_output:
                temporary = Path(raw_output.name)
                with zipfile.ZipFile(raw_output, "w", allowZip64=True) as output:
                    output.comment = archive.comment
                    for entry in entries:
                        if is_signature(entry.filename):
                            removed += 1
                            continue
                        info = copy.copy(entry)
                        if entry.filename == METADATA:
                            output.writestr(info, patched)
                        elif entry.is_dir():
                            output.writestr(info, b"")
                        else:
                            with archive.open(entry, "r") as reader, output.open(
                                info, "w", force_zip64=entry.file_size >= zipfile.ZIP64_LIMIT
                            ) as writer:
                                shutil.copyfileobj(reader, writer, 1024 * 1024)
                raw_output.flush()
                os.fsync(raw_output.fileno())
        destination = _publish_without_overwrite(temporary, source)
        result = ConversionResult(source, True, "转换完成", destination, removed, mod_id)
    except MetadataError as exc:
        result = ConversionResult(source, False, f"JSON 损坏：{exc}")
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError) as exc:
        result = ConversionResult(source, False, f"jar 损坏：{exc}")
    except PermissionError as exc:
        result = ConversionResult(source, False, f"权限不足或文件被占用：{exc}")
    except FileNotFoundError as exc:
        result = ConversionResult(source, False, f"文件不存在或路径不可用：{exc}")
    except OSError as exc:
        reason = "磁盘空间不足" if exc.errno == errno.ENOSPC else "文件读写失败"
        result = ConversionResult(source, False, f"{reason}：{exc}")
    except Exception as exc:
        # A bad archive must not terminate the GUI or the remainder of a batch.
        result = ConversionResult(source, False, f"处理失败（{type(exc).__name__}）：{exc}")
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_error = f"；临时文件未能清理：{temporary}（{exc}）"
    if cleanup_error:
        result = ConversionResult(
            result.source, result.success, result.reason + cleanup_error,
            result.output, result.removed_signatures, result.mod_id
        )
    return result


def collect_jars(paths, recursive: bool = False) -> tuple[list[Path], list[str]]:
    """Snapshot input files before a batch; newly created outputs are never rescanned."""
    found = []
    notes = []
    seen = set()
    for raw_path in paths:
        path = Path(os.path.abspath(os.fspath(raw_path)))
        try:
            if path.is_dir():
                candidates = []
                # os.walk reports inaccessible subfolders rather than silently skipping.
                def walk_error(exc):
                    notes.append(f"无法读取文件夹：{exc}")
                if recursive:
                    for folder, _, names in os.walk(path, onerror=walk_error):
                        candidates.extend(Path(folder) / name for name in names if name.casefold().endswith(".jar"))
                else:
                    candidates = [item for item in path.iterdir() if item.suffix.casefold() == ".jar" and item.is_file()]
                candidates.sort(key=lambda item: str(item).casefold())
                if not candidates:
                    notes.append(f"文件夹中没有 jar：{path}")
            else:
                candidates = [path]
            for candidate in candidates:
                if candidate.suffix.casefold() != ".jar":
                    notes.append(f"忽略非 jar 文件：{candidate}")
                    continue
                identity = os.path.normcase(str(candidate.resolve()))
                if identity not in seen:
                    seen.add(identity)
                    found.append(candidate)
        except OSError as exc:
            notes.append(f"无法读取路径 {path}：{exc}")
    return found, notes
