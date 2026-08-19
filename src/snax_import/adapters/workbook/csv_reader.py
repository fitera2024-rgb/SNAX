from __future__ import annotations

import codecs
import csv
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from io import TextIOWrapper
from tempfile import TemporaryFile
from typing import BinaryIO, Literal, Protocol, cast
from uuid import uuid4

from snax_import.domain.raw_workbook import (
    Cell,
    CellCoordinate,
    FilenameMetadata,
    Row,
    Sheet,
    SheetVisibility,
    ValueType,
    Workbook,
    WorkbookFormat,
)
from snax_import.ports.workbook_reader import (
    IssueSeverity,
    ReaderIssue,
    ReaderIssueCode,
    ReaderOptions,
    ReaderResult,
    ReaderStatistics,
)


@dataclass(frozen=True, slots=True)
class _DialectSettings:
    delimiter: str
    quotechar: str | None
    escapechar: str | None
    doublequote: bool
    skipinitialspace: bool
    quoting: Literal[0, 1, 2, 3, 4, 5]


class _DialectSource(Protocol):
    delimiter: str
    quotechar: str | None
    escapechar: str | None
    doublequote: bool
    quoting: Literal[0, 1, 2, 3, 4, 5]


class _EncodingError(Exception):
    pass


class _DialectError(Exception):
    pass


class CsvWorkbookReader:
    """Stream a CSV source into the common raw-workbook model."""

    MEDIA_TYPES = frozenset({"text/csv", "application/csv"})
    EXTENSIONS = frozenset({".csv"})
    _CHUNK_SIZE = 64 * 1024
    _SAMPLE_SIZE = 128 * 1024
    _DETECTABLE_DELIMITERS = ",;\t|"

    def supports(self, media_type: str | None = None, extension: str | None = None) -> bool:
        normalized_media_type = media_type.lower().split(";", 1)[0] if media_type else None
        normalized_extension = extension.lower() if extension else None
        media_matches = normalized_media_type is None or normalized_media_type in self.MEDIA_TYPES
        extension_matches = normalized_extension is None or normalized_extension in self.EXTENSIONS
        return (
            (media_type is not None or extension is not None)
            and media_matches
            and extension_matches
        )

    def read(self, source: BinaryIO, options: ReaderOptions) -> ReaderResult:
        started = time.monotonic()
        issues: list[ReaderIssue] = []
        issue_number = 0
        bytes_read = 0

        def add_issue(
            code: ReaderIssueCode,
            severity: IssueSeverity,
            message: str,
            *,
            row_index: int | None = None,
            details: dict[str, str] | None = None,
            retryable: bool = False,
        ) -> None:
            nonlocal issue_number
            issue_number += 1
            issues.append(
                ReaderIssue(
                    issue_id=f"csv-reader-{issue_number:04d}",
                    code=code,
                    severity=severity,
                    message=message,
                    sheet_name="CSV" if row_index is not None else None,
                    row_index=row_index,
                    retryable=retryable,
                    details=details or {},
                )
            )

        def statistics(
            *,
            sheets_read: int = 0,
            rows_read: int = 0,
            cells_read: int = 0,
        ) -> ReaderStatistics:
            return ReaderStatistics(
                sheets_read=sheets_read,
                rows_read=rows_read,
                cells_read=cells_read,
                bytes_read=bytes_read,
                duration_seconds=time.monotonic() - started,
            )

        with TemporaryFile(mode="w+b") as temporary:
            binary_temporary = cast(BinaryIO, temporary)
            try:
                while chunk := source.read(self._CHUNK_SIZE):
                    if not isinstance(chunk, bytes):
                        raise TypeError("CSV source must return bytes")
                    bytes_read += len(chunk)
                    if bytes_read > options.max_file_size:
                        add_issue(
                            ReaderIssueCode.FILE_TOO_LARGE,
                            IssueSeverity.CRITICAL,
                            "CSV source exceeded max_file_size",
                            details={"limitBytes": str(options.max_file_size)},
                        )
                        return ReaderResult(
                            workbook=None,
                            issues=tuple(issues),
                            statistics=statistics(),
                        )
                    if time.monotonic() - started > options.timeout_seconds:
                        add_issue(
                            ReaderIssueCode.TIMEOUT_EXCEEDED,
                            IssueSeverity.CRITICAL,
                            "CSV reader timeout exceeded while copying the source",
                            retryable=True,
                        )
                        return ReaderResult(
                            workbook=None,
                            issues=tuple(issues),
                            statistics=statistics(),
                        )
                    binary_temporary.write(chunk)
            except (OSError, TypeError, ValueError) as exc:
                add_issue(
                    ReaderIssueCode.MALFORMED_STRUCTURE,
                    IssueSeverity.ERROR,
                    "CSV source could not be read",
                    details={"error": type(exc).__name__},
                )
                return ReaderResult(
                    workbook=None,
                    issues=tuple(issues),
                    statistics=statistics(),
                )

            try:
                encoding = self._detect_encoding(binary_temporary, options.csv_encoding)
            except _EncodingError as exc:
                add_issue(
                    ReaderIssueCode.UNSUPPORTED_FORMAT,
                    IssueSeverity.ERROR,
                    "CSV encoding could not be resolved",
                    details={"reason": str(exc)},
                )
                return ReaderResult(
                    workbook=None,
                    issues=tuple(issues),
                    statistics=statistics(),
                )

            text_source = TextIOWrapper(
                binary_temporary,
                encoding=encoding,
                errors="strict",
                newline="",
            )
            rows: list[Row] = []
            cells_read = 0
            estimated_memory = 0
            max_column = 0
            stopped = False
            dialect: _DialectSettings | None = None

            try:
                sample = text_source.read(self._SAMPLE_SIZE)
                text_source.seek(0)
                dialect = self._resolve_dialect(sample, options)
                reader = csv.reader(
                    text_source,
                    delimiter=dialect.delimiter,
                    quotechar=dialect.quotechar,
                    escapechar=dialect.escapechar,
                    doublequote=dialect.doublequote,
                    skipinitialspace=dialect.skipinitialspace,
                    quoting=dialect.quoting,
                    strict=True,
                )
                expected_columns: int | None = None

                for values in reader:
                    row_index = len(rows) + 1
                    if time.monotonic() - started > options.timeout_seconds:
                        add_issue(
                            ReaderIssueCode.TIMEOUT_EXCEEDED,
                            IssueSeverity.CRITICAL,
                            "CSV reader timeout exceeded",
                            row_index=row_index,
                            retryable=True,
                        )
                        break
                    if row_index > options.max_rows:
                        add_issue(
                            ReaderIssueCode.ROW_LIMIT_EXCEEDED,
                            IssueSeverity.CRITICAL,
                            "CSV source exceeded max_rows",
                            row_index=row_index,
                            details={"limitRows": str(options.max_rows)},
                        )
                        break

                    if expected_columns is None:
                        expected_columns = len(values)
                    elif len(values) != expected_columns:
                        add_issue(
                            ReaderIssueCode.MALFORMED_STRUCTURE,
                            IssueSeverity.ERROR,
                            "CSV row has an unexpected number of columns",
                            row_index=row_index,
                            details={
                                "expectedColumns": str(expected_columns),
                                "actualColumns": str(len(values)),
                                "physicalLine": str(reader.line_num),
                            },
                        )

                    row_memory = 128
                    if estimated_memory + row_memory > options.memory_limit:
                        add_issue(
                            ReaderIssueCode.MEMORY_LIMIT_EXCEEDED,
                            IssueSeverity.CRITICAL,
                            "CSV reader memory budget exceeded",
                            row_index=row_index,
                            details={"limitBytes": str(options.memory_limit)},
                        )
                        break
                    estimated_memory += row_memory
                    cells: list[Cell] = []

                    for column_index, value in enumerate(values, start=1):
                        if column_index > options.max_columns:
                            add_issue(
                                ReaderIssueCode.WORKBOOK_TOO_MANY_COLUMNS,
                                IssueSeverity.CRITICAL,
                                "CSV source exceeded max_columns",
                                row_index=row_index,
                                details={"limitColumns": str(options.max_columns)},
                            )
                            stopped = True
                            break
                        if cells_read >= options.max_cells:
                            add_issue(
                                ReaderIssueCode.CELL_LIMIT_EXCEEDED,
                                IssueSeverity.CRITICAL,
                                "CSV source exceeded max_cells",
                                row_index=row_index,
                                details={"limitCells": str(options.max_cells)},
                            )
                            stopped = True
                            break

                        cell_memory = 256 + len(value) * 2
                        if estimated_memory + cell_memory > options.memory_limit:
                            add_issue(
                                ReaderIssueCode.MEMORY_LIMIT_EXCEEDED,
                                IssueSeverity.CRITICAL,
                                "CSV reader memory budget exceeded",
                                row_index=row_index,
                                details={"limitBytes": str(options.memory_limit)},
                            )
                            stopped = True
                            break
                        estimated_memory += cell_memory
                        cells.append(
                            Cell(
                                coordinate=CellCoordinate(row_index, column_index),
                                row_index=row_index,
                                column_index=column_index,
                                value_type=ValueType.STRING,
                                raw_value=value,
                                display_value=value,
                            )
                        )
                        cells_read += 1

                    if cells or not values:
                        rows.append(Row(index=row_index, cells=tuple(cells)))
                        max_column = max(max_column, len(cells))
                    if stopped:
                        break
            except _DialectError as exc:
                add_issue(
                    ReaderIssueCode.UNSUPPORTED_FORMAT,
                    IssueSeverity.ERROR,
                    "CSV dialect override is not available",
                    details={"reason": str(exc)},
                )
            except (csv.Error, UnicodeDecodeError) as exc:
                add_issue(
                    ReaderIssueCode.MALFORMED_STRUCTURE,
                    IssueSeverity.ERROR,
                    "CSV record is malformed",
                    row_index=len(rows) + 1,
                    details={"error": type(exc).__name__},
                )
            finally:
                text_source.detach()

        if dialect is None:
            return ReaderResult(
                workbook=None,
                issues=tuple(issues),
                statistics=statistics(cells_read=cells_read),
            )

        sheet = Sheet(
            name="CSV",
            index=0,
            visibility=SheetVisibility.VISIBLE,
            max_row=len(rows),
            max_column=max_column,
            rows=tuple(rows),
        )
        workbook = Workbook(
            id=uuid4(),
            source_file_id=uuid4(),
            filename=FilenameMetadata(
                name="source.csv",
                media_type="text/csv",
                size_bytes=bytes_read,
            ),
            format=WorkbookFormat.CSV,
            created_at=datetime.now(UTC),
            sheets=(sheet,),
            workbook_metadata={
                "parser": "python-csv",
                "encoding": encoding,
                "delimiter": dialect.delimiter,
                "quotechar": dialect.quotechar or "",
            },
        )
        return ReaderResult(
            workbook=workbook,
            issues=tuple(issues),
            statistics=statistics(
                sheets_read=1,
                rows_read=len(rows),
                cells_read=cells_read,
            ),
        )

    @classmethod
    def _detect_encoding(cls, source: BinaryIO, override: str | None) -> str:
        if override is not None:
            try:
                encoding = codecs.lookup(override).name
            except LookupError as exc:
                raise _EncodingError(f"unknown encoding: {override}") from exc
            if not cls._can_decode(source, encoding):
                raise _EncodingError(f"source is not valid {encoding}")
            return encoding

        source.seek(0)
        prefix = source.read(4)
        source.seek(0)
        if prefix.startswith(codecs.BOM_UTF8):
            return "utf-8-sig"
        if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return "utf-16"
        if cls._can_decode(source, "utf-8"):
            return "utf-8"
        if cls._can_decode(source, "cp1251"):
            return "cp1251"
        raise _EncodingError("supported encodings are UTF-8, UTF-16 and Windows-1251")

    @classmethod
    def _can_decode(cls, source: BinaryIO, encoding: str) -> bool:
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
        source.seek(0)
        try:
            while chunk := source.read(cls._CHUNK_SIZE):
                decoder.decode(chunk, final=False)
            decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            return False
        finally:
            source.seek(0)
        return True

    @classmethod
    def _resolve_dialect(cls, sample: str, options: ReaderOptions) -> _DialectSettings:
        detected: _DialectSource
        if options.csv_dialect is not None:
            try:
                detected = cast(_DialectSource, csv.get_dialect(options.csv_dialect))
            except csv.Error as exc:
                raise _DialectError(f"unknown dialect: {options.csv_dialect}") from exc
        elif sample:
            try:
                detected = cast(
                    _DialectSource,
                    csv.Sniffer().sniff(
                        sample,
                        delimiters=cls._DETECTABLE_DELIMITERS,
                    ),
                )
            except csv.Error:
                detected = cast(_DialectSource, csv.get_dialect("excel"))
        else:
            detected = cast(_DialectSource, csv.get_dialect("excel"))

        return _DialectSettings(
            delimiter=options.csv_delimiter or detected.delimiter,
            quotechar=(
                options.csv_quotechar if options.csv_quotechar is not None else detected.quotechar
            ),
            escapechar=detected.escapechar,
            doublequote=detected.doublequote,
            # Whitespace is source data. Sniffer may otherwise enable trimming
            # merely because every delimiter in its sample is followed by a space.
            skipinitialspace=False,
            quoting=detected.quoting,
        )


__all__ = ["CsvWorkbookReader"]
