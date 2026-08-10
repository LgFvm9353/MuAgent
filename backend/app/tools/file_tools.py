import asyncio
import difflib
import hashlib
from pathlib import Path

from pydantic import Field

from app.contracts.base import ContractModel
from app.workspace.paths import Workspace, iter_workspace_files


class PathInput(ContractModel):
    path: str = Field(min_length=1, max_length=1_000)


class ListFilesInput(ContractModel):
    path: str = Field(min_length=1, max_length=1_000)


class FileListOutput(ContractModel):
    files: tuple[str, ...]


class SearchFilesInput(ContractModel):
    query: str = Field(min_length=1, max_length=500)
    path: str = Field(default=".", min_length=1, max_length=1_000)
    limit: int = Field(default=100, ge=1, le=500)


class SearchMatch(ContractModel):
    path: str
    line: int
    text: str


class SearchFilesOutput(ContractModel):
    matches: tuple[SearchMatch, ...]


class FileContentOutput(ContractModel):
    path: str
    content: str
    size: int
    sha256: str


class WriteFileInput(PathInput):
    content: str = Field(max_length=5 * 1024 * 1024)


class WriteFileOutput(ContractModel):
    path: str
    size: int
    sha256: str
    diff: str


class FileTools:
    def __init__(self, workspace: Workspace, *, max_read_bytes: int = 1024 * 1024) -> None:
        self._workspace = workspace
        self._max_read_bytes = max_read_bytes

    async def list_files(self, request: ListFilesInput) -> FileListOutput:
        base = (
            self._workspace.root
            if request.path == "."
            else self._workspace.resolve(request.path, must_exist=True)
        )
        if not base.is_dir():
            raise ValueError("list path must be a directory")
        files = await asyncio.to_thread(self._list_files, base)
        return FileListOutput(files=files[: self._workspace.max_files])

    def _list_files(self, base: Path) -> tuple[str, ...]:
        return tuple(
            sorted(
                path.relative_to(self._workspace.root).as_posix()
                for path in iter_workspace_files(base)
            )
        )

    async def search_files(self, request: SearchFilesInput) -> SearchFilesOutput:
        base = (
            self._workspace.root
            if request.path == "."
            else self._workspace.resolve(request.path, must_exist=True)
        )
        if not base.is_dir():
            raise ValueError("search path must be a directory")
        matches = await asyncio.to_thread(self._search_files, base, request)
        return SearchFilesOutput(matches=matches)

    def _search_files(self, base: Path, request: SearchFilesInput) -> tuple[SearchMatch, ...]:
        matches: list[SearchMatch] = []
        for path in iter_workspace_files(base):
            if len(matches) >= request.limit:
                break
            relative = path.relative_to(self._workspace.root)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if request.query.casefold() in line.casefold():
                    matches.append(
                        SearchMatch(
                            path=relative.as_posix(), line=line_number, text=line[:1_000]
                        )
                    )
                    if len(matches) >= request.limit:
                        break
        return tuple(matches)

    async def read_file(self, request: PathInput) -> FileContentOutput:
        path = self._workspace.resolve(request.path, must_exist=True)
        if not path.is_file() or path.is_symlink():
            raise ValueError("read path must be a regular file")
        size = path.stat().st_size
        if size > self._max_read_bytes:
            raise ValueError("read size limit exceeded")
        data = await asyncio.to_thread(path.read_bytes)
        return FileContentOutput(
            path=request.path,
            content=data.decode("utf-8"),
            size=size,
            sha256=hashlib.sha256(data).hexdigest(),
        )

    async def create_file(self, request: WriteFileInput) -> WriteFileOutput:
        data = request.content.encode()
        self._workspace.validate_capacity(len(data))
        path = self._workspace.resolve(request.path, must_exist=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._exclusive_write, path, data)
        return self._result(request.path, data, "", request.content)

    async def modify_file(self, request: WriteFileInput) -> WriteFileOutput:
        data = request.content.encode()
        path = self._workspace.resolve(request.path, must_exist=True)
        self._workspace.validate_capacity(len(data), replacing=path)
        old = await asyncio.to_thread(path.read_text, encoding="utf-8")
        await asyncio.to_thread(path.write_bytes, data)
        return self._result(request.path, data, old, request.content)

    @staticmethod
    def _exclusive_write(path: Path, data: bytes) -> None:
        with path.open("xb") as stream:
            stream.write(data)

    @staticmethod
    def _result(path: str, data: bytes, old: str, new: str) -> WriteFileOutput:
        diff = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        return WriteFileOutput(
            path=path, size=len(data), sha256=hashlib.sha256(data).hexdigest(), diff=diff
        )
