import asyncio
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings


class ScannerUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    engine: str
    signature: str | None = None


class MalwareScanner(Protocol):
    async def scan(self, data: bytes) -> ScanResult: ...


class MarkerScanner:
    """Deterministic development scanner that recognizes the standard EICAR marker."""

    async def scan(self, data: bytes) -> ScanResult:
        infected = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in data
        return ScanResult(
            clean=not infected,
            engine="marker-v1",
            signature="EICAR-Test-Signature" if infected else None,
        )


class ClamAVScanner:
    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    async def scan(self, data: bytes) -> ScanResult:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=self.timeout
            )
            writer.write(b"zINSTREAM\0")
            for offset in range(0, len(data), 64 * 1024):
                chunk = data[offset : offset + 64 * 1024]
                writer.write(len(chunk).to_bytes(4, "big") + chunk)
            writer.write((0).to_bytes(4, "big"))
            await writer.drain()
            response = await asyncio.wait_for(reader.read(4096), timeout=self.timeout)
            writer.close()
            await writer.wait_closed()
        except (OSError, TimeoutError) as error:
            raise ScannerUnavailableError("resume_scan_unavailable") from error
        result = response.decode("utf-8", errors="replace").strip("\0\r\n")
        if result.endswith(" OK"):
            return ScanResult(clean=True, engine="clamav")
        if " FOUND" in result:
            signature = result.rsplit(":", maxsplit=1)[-1].removesuffix(" FOUND").strip()
            return ScanResult(clean=False, engine="clamav", signature=signature[:120])
        raise ScannerUnavailableError("resume_scan_unavailable")


def build_scanner(settings: Settings) -> MalwareScanner:
    if settings.malware_scanner == "clamav":
        return ClamAVScanner(
            settings.clamav_host,
            settings.clamav_port,
            settings.clamav_timeout_seconds,
        )
    return MarkerScanner()
