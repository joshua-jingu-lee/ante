"""프레이밍 프로토콜 테스트."""

import asyncio
import struct

import pytest

from ante.ipc.exceptions import MessageTooLargeError
from ante.ipc.protocol import MAX_MESSAGE_SIZE, decode, encode


@pytest.mark.asyncio
async def test_encode_decode_roundtrip() -> None:
    """encode → decode 라운드트립 검증."""
    original = {"command": "system.halt", "args": {"reason": "test"}, "id": "abc-123"}
    encoded = await encode(original)

    # 길이 접두사 확인
    (length,) = struct.unpack("!I", encoded[:4])
    assert length == len(encoded) - 4

    # decode
    reader = asyncio.StreamReader()
    reader.feed_data(encoded)
    decoded = await decode(reader)
    assert decoded == original


@pytest.mark.asyncio
async def test_encode_decode_unicode() -> None:
    """한글 등 유니코드 메시지 라운드트립."""
    original = {"message": "한글 테스트 메시지", "value": 42}
    encoded = await encode(original)

    reader = asyncio.StreamReader()
    reader.feed_data(encoded)
    decoded = await decode(reader)
    assert decoded == original


@pytest.mark.asyncio
async def test_encode_too_large() -> None:
    """최대 크기 초과 시 MessageTooLargeError."""
    large_data = {"data": "x" * (MAX_MESSAGE_SIZE + 1)}
    with pytest.raises(MessageTooLargeError):
        await encode(large_data)


@pytest.mark.asyncio
async def test_decode_too_large_length_prefix() -> None:
    """길이 접두사가 최대 크기를 초과하면 MessageTooLargeError."""
    fake_length = struct.pack("!I", MAX_MESSAGE_SIZE + 1)
    reader = asyncio.StreamReader()
    reader.feed_data(fake_length + b"\x00" * 100)
    with pytest.raises(MessageTooLargeError):
        await decode(reader)


@pytest.mark.asyncio
async def test_decode_incomplete_read() -> None:
    """불완전한 데이터 시 IncompleteReadError."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x00\x00")  # 4바이트 미만
    reader.feed_eof()
    with pytest.raises(asyncio.IncompleteReadError):
        await decode(reader)


_ONE_MIB = 1_048_576


def _dict_with_payload_size(size: int) -> dict:
    """JSON 직렬화 결과가 정확히 ``size`` 바이트인 dict."""
    overhead = len(b'{"d": ""}')
    return {"d": "x" * (size - overhead)}


@pytest.mark.asyncio
async def test_encode_accepts_exactly_one_mib_and_rejects_one_more_byte() -> None:
    """페이로드 1_048_576 바이트까지는 보내고, 1 바이트만 넘어도 거부한다."""
    encoded = await encode(_dict_with_payload_size(_ONE_MIB))
    (length,) = struct.unpack("!I", encoded[:4])
    assert length == _ONE_MIB

    with pytest.raises(MessageTooLargeError):
        await encode(_dict_with_payload_size(_ONE_MIB + 1))


@pytest.mark.asyncio
async def test_decode_accepts_one_mib_prefix_and_rejects_one_more_byte() -> None:
    """수신 길이 접두사도 1_048_576 까지 받고 그 위는 본문을 읽기 전에 거부한다."""
    payload = b'{"d": "' + b"x" * (_ONE_MIB - len(b'{"d": ""}')) + b'"}'
    reader = asyncio.StreamReader()
    reader.feed_data(struct.pack("!I", _ONE_MIB) + payload)
    decoded = await decode(reader)
    assert len(decoded["d"]) == _ONE_MIB - len(b'{"d": ""}')

    reader = asyncio.StreamReader()
    reader.feed_data(struct.pack("!I", _ONE_MIB + 1))
    reader.feed_eof()
    with pytest.raises(MessageTooLargeError):
        await decode(reader)


@pytest.mark.asyncio
async def test_encode_empty_dict() -> None:
    """빈 dict 인코딩/디코딩."""
    original: dict = {}
    encoded = await encode(original)

    reader = asyncio.StreamReader()
    reader.feed_data(encoded)
    decoded = await decode(reader)
    assert decoded == original
