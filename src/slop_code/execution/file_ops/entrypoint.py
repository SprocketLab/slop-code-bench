from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import JsonValue

from slop_code.execution.file_ops import raw_files
from slop_code.execution.file_ops import structured_files
from slop_code.execution.file_ops.models import Compression
from slop_code.execution.file_ops.models import FileContent
from slop_code.execution.file_ops.models import FileHandler
from slop_code.execution.file_ops.models import FileSignature
from slop_code.execution.file_ops.models import FileType
from slop_code.execution.file_ops.models import InputFileReadError
from slop_code.logging import get_logger

logger = get_logger(__name__)


def detect_file_signature(path: Path) -> FileSignature:
    """Determine the file signature (format + compression) from a path."""
    suffixes = path.suffixes

    # Check for compressed files first (e.g., .json.gz, .csv.bz2)
    if len(suffixes) >= 2:
        combined_ext = "".join(suffixes[-2:]).lower()
        signature = _REGISTRY.get_signature_by_extension(combined_ext)
        if signature:
            return signature

    # Check for single extension
    if suffixes:
        single_ext = suffixes[-1].lower()
        signature = _REGISTRY.get_signature_by_extension(single_ext)
        if signature:
            return signature

    # Default to text for unknown types (will fall back to binary if read fails)
    return FileSignature(FileType.TEXT, Compression.NONE)


def read_file_content(path: Path, signature: FileSignature) -> FileContent:
    """Read the content of a file.

    Args:
        path: Path to the file.
        signature: File signature determined for the file.

    Returns:
        JsonValue: The content of the file.

    Raises:
        ExecutionError: If the file cannot be read.
    """
    logger.debug(
        "Reading file content",
        path=path,
        file_type=signature.file_type,
        compression=signature.compression,
        verbose=True,
    )

    # For text files with unknown extensions, try text first, then binary
    if (
        signature.file_type == FileType.TEXT
        and signature.compression == Compression.NONE
    ):
        try:
            handler = _REGISTRY.get_handler(FileType.TEXT, Compression.NONE)
            return handler.read(path)
        except (UnicodeDecodeError, InputFileReadError) as e:
            logger.debug(
                "Failed to read as text, falling back to binary",
                path=path,
                error=str(e),
                verbose=True,
            )
            handler = _REGISTRY.get_handler(FileType.BINARY, Compression.NONE)
            return handler.read(path)
    else:
        handler = _REGISTRY.get_handler(
            signature.file_type, signature.compression
        )
        return handler.read(path)


class InputFile(BaseModel):
    """Input file for an execution request.

    Attributes:
        path: Path to the file.
        content: Content of the file.
        file_type: Type of the file.
        compression: Compression codec used for the file.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path
    content: FileContent
    file_type: FileType
    compression: Compression = Compression.NONE

    @classmethod
    def from_absolute(
        cls,
        path: Path,
        save_path: Path,
        content: FileContent | None = None,
        file_type: FileType | None = None,
        compression: Compression | None = None,
    ) -> InputFile:
        logger.debug(
            "Creating InputFile from path",
            path=path,
            save_path=save_path,
            has_content=content is not None,
            file_type=file_type,
            compression=compression,
            verbose=True,
        )

        file_type, compression = cls.resolve_suffix(
            path, file_type, compression
        )

        signature = FileSignature(file_type=file_type, compression=compression)

        if content is None:
            actual_content: FileContent = cls._read_content_from_file(
                path, signature
            )
        else:
            actual_content: FileContent = content

        return cls(
            path=save_path,
            content=actual_content,
            file_type=file_type,
            compression=compression,
        )

    @classmethod
    def from_path(
        cls,
        path: Path,
        content: JsonValue = None,
        file_type: FileType | str | None = None,
        compression: Compression | str | None = None,
        relative_to: Path | None = None,
    ) -> InputFile:
        """Create an InputFile from a path."""
        logger.debug(
            "Creating InputFile from path",
            path=path,
            relative_to=relative_to,
            has_content=content is not None,
            file_type=file_type,
            compression=compression,
            verbose=True,
        )

        file_type, compression = cls.resolve_suffix(
            path, file_type, compression
        )

        signature = FileSignature(file_type=file_type, compression=compression)

        if content is None:
            actual_content: FileContent = cls._read_content_from_file(
                path, signature, relative_to=relative_to
            )
        else:
            actual_content: FileContent = content

        path = cls._normalize_path(relative_to, path)

        return cls(
            path=path,
            content=actual_content,
            file_type=file_type,
            compression=compression,
        )

    @classmethod
    def resolve_suffix(
        cls,
        path: Path,
        file_type: FileType | str | None = None,
        compression: Compression | str | None = None,
    ) -> tuple[FileType, Compression]:
        """Detect and normalize file_type and compression."""
        detected_signature: FileSignature | None = None
        if file_type is None or compression is None:
            detected_signature = detect_file_signature(path)

        if file_type is None and detected_signature is not None:
            file_type = detected_signature.file_type

        if compression is None and detected_signature is not None:
            compression = detected_signature.compression

        if file_type is not None and not isinstance(file_type, FileType):
            file_type = FileType(file_type)

        if not isinstance(compression, Compression):
            if compression is None:
                compression = Compression.NONE
            else:
                compression = Compression(compression)

        if file_type is None:
            raise ValueError("file_type and compression are required")

        return file_type, compression

    @classmethod
    def _read_content_from_file(
        cls,
        path: Path,
        signature: FileSignature,
        relative_to: Path | None = None,
    ) -> FileContent:
        use_path = path
        if not use_path.exists():
            if relative_to is None:
                raise ValueError(
                    "relative_to is required if path does not exist"
                )
            use_path = relative_to / use_path
        return read_file_content(use_path, signature)

    @classmethod
    def _normalize_path(cls, relative_to: Path, path: Path) -> Path:
        if path.is_absolute():
            return path.relative_to(relative_to)
        return path


class FileHandlerRegistry:
    """Registry for file handlers with decorator support."""

    def __init__(self) -> None:
        self._handlers: dict[FileSignature, type[FileHandler]] = {}
        self._instances: dict[FileSignature, FileHandler] = {}
        self._extensions: dict[str, FileSignature] = {}
        self._register_handlers()

    def register(
        self,
        handler_class: type[FileHandler],
        file_type: FileType,
        extensions: set[str],
        compression: Compression,
    ) -> None:
        """Decorator to register a handler for a file type."""

        signature = FileSignature(file_type=file_type, compression=compression)

        self._handlers[signature] = handler_class

        for ext in extensions:
            self._extensions[ext.lower()] = signature

    def get_handler(
        self, file_type: FileType, compression: Compression = Compression.NONE
    ) -> FileHandler:
        """Get handler instance for a file signature."""

        signature = FileSignature(file_type=file_type, compression=compression)

        if signature not in self._handlers:
            raise ValueError(
                f"No handler registered for file signature: {signature}"
            )

        # Create instance lazily
        if signature not in self._instances:
            self._instances[signature] = self._handlers[signature](
                compression=compression,
                file_type=file_type,
            )

        return self._instances[signature]

    def list_handlers(self) -> dict[FileSignature, type[FileHandler]]:
        """List all registered handler classes."""
        return self._handlers.copy()

    def get_signature_by_extension(
        self, extension: str
    ) -> FileSignature | None:
        """Get file signature by extension."""
        return self._extensions.get(extension.lower())

    def _register_handlers(self):
        # Register all handlers from structured_files and raw_files
        for modules in [structured_files, raw_files]:
            for (handle_cls, file_type), setups in modules.SETUPS.items():
                for compression, extensions in setups.items():
                    self.register(
                        handle_cls,
                        file_type=file_type,
                        compression=compression,
                        extensions=extensions,
                    )


_REGISTRY = FileHandlerRegistry()


def materialize_input_files(files: list[InputFile], cwd: Path) -> None:
    """Materializes the input files into the working directory.

    Args:
        files: List of InputFile objects.
        cwd: Working directory.

    Returns:
        None

    Raises:
        InputFileWriteError: If an input file cannot be written.
    """
    logger.debug(
        "Materializing input files",
        files=[f.path for f in files],
        verbose=True,
        cwd=cwd,
    )

    for input_file in files:
        handler = _REGISTRY.get_handler(
            input_file.file_type, input_file.compression
        )
        file_path = cwd / input_file.path
        logger.debug(
            "Writing input file",
            path=input_file.path,
            file_type=input_file.file_type,
            compression=input_file.compression,
            target_path=file_path,
            verbose=True,
        )
        # Ensure the parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        handler.write(file_path, input_file.content)
        logger.debug(
            "Successfully materialized input file",
            path=input_file.path,
            file_type=input_file.file_type,
            compression=input_file.compression,
        )
