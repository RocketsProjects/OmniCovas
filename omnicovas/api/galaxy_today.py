"""Public-news presentation; external reads remain explicitly opt-in."""

from typing import Any

from fastapi import APIRouter, HTTPException

from omnicovas.features.galnet import GalnetReader

router = APIRouter(prefix="/galaxy-today", tags=["galaxy-today"])
_reader: GalnetReader | None = None


def set_reader(reader: GalnetReader) -> None:
    global _reader  # noqa: PLW0603
    _reader = reader


def reader() -> GalnetReader:
    if _reader is None:
        raise HTTPException(503, "Public news reader unavailable")
    return _reader


@router.get("")
async def snapshot() -> dict[str, Any]:
    service = reader()
    # Never wait on an external source before returning the local snapshot.
    service.start_update()
    return service.snapshot()


@router.post("/update")
async def update() -> dict[str, Any]:
    service = reader()
    task = service.start_update()
    if task:
        await task
    return service.snapshot()
