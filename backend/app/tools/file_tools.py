import asyncio
import difflib
import hashlib
from pathlib import Path

from pydantic import Field

from app.contracts.base import ContractModel
from app.workspace.paths import Workspace


class PathInput(ContractModel):
    path: str = Field(min_length=1, max_length=1_000)


class ListFilesInput(ContractModel):
    path: str = "."


class FileListOutput(ContractModel):
    files: tuple[str, ...]


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
        base = self._workspace.root if request.path == "." else self._workspace.resolve(request.path, must_exist=True)
        if not base.is_dir():
            raise ValueError("list path must be a directory")
        files = await asyncio.to_thread(lambda: tuple(sorted(path.relative_to(self._workspace.root).as_posix() for path in base.rglob("*") if path.is_file() and not path.is_symlink())))
        return FileListOutput(files=files[: self._workspace.max_files])

    async def read_file(self, request: PathInput) -> FileContentOutput:
        path = self._workspace.resolve(request.path, must_exist=True)
        if not path.is_file() or path.is_symlink():
            raise ValueError("read path must be a regular file")
        size = path.stat().st_size
        if size > self._max_read_bytes:
            raise ValueError("read size limit exceeded")
        data = await asyncio.to_thread(path.read_bytes)
        return FileContentOutput(path=request.path, content=data.decode("utf-8"), size=size, sha256=hashlib.sha256(data).hexdigest())

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
        diff = "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}"))
        return WriteFileOutput(path=path, size=len(data), sha256=hashlib.sha256(data).hexdigest(), diff=diff)
