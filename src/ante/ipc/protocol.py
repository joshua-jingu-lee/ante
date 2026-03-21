"""길이 접두사 프레이밍 프로토콜.

메시지 형식: [4바이트 빅엔디안 길이][JSON 페이로드]
최대 메시지 크기: 1MB (1_048_576 바이트)
"""

import asyncio
import json
import struct

from ante.ipc.exceptions import MessageTooLargeError

MAX_MESSAGE_SIZE = 1_048_576  # 1MB


async def encode(data: dict) -> bytes:
    """dict를 길이 접두사 + JSON 바이트로 직렬화."""
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_MESSAGE_SIZE:
        raise MessageTooLargeError(
            f"메시지 크기({len(payload)} bytes)가 "
            f"최대 제한({MAX_MESSAGE_SIZE} bytes)을 초과"
        )
    length_prefix = struct.pack("!I", len(payload))
    return length_prefix + payload


async def decode(reader: asyncio.StreamReader) -> dict:
    """StreamReader에서 길이 접두사 프레이밍 메시지를 읽어 dict로 역직렬화."""
    raw_length = await reader.readexactly(4)
    (length,) = struct.unpack("!I", raw_length)

    if length > MAX_MESSAGE_SIZE:
        raise MessageTooLargeError(
            f"메시지 크기({length} bytes)가 최대 제한({MAX_MESSAGE_SIZE} bytes)을 초과"
        )

    payload = await reader.readexactly(length)
    return json.loads(payload.decode("utf-8"))
