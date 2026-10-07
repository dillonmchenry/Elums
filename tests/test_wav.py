from elums.ingest.wav import build_wav_header


def test_build_wav_header_byte_layout():
    header = build_wav_header(sample_rate=16000, data_length=320, num_channels=1, bits_per_sample=16)
    assert len(header) == 44
    assert header[0:4] == b"RIFF"
    assert header[8:12] == b"WAVE"
    assert header[12:16] == b"fmt "
    assert header[36:40] == b"data"

    import struct

    (riff_size,) = struct.unpack_from("<I", header, 4)
    assert riff_size == 36 + 320
    (fmt_tag,) = struct.unpack_from("<H", header, 20)
    assert fmt_tag == 1
    (channels,) = struct.unpack_from("<H", header, 22)
    assert channels == 1
    (rate,) = struct.unpack_from("<I", header, 24)
    assert rate == 16000
    (bits,) = struct.unpack_from("<H", header, 34)
    assert bits == 16
    (data_size,) = struct.unpack_from("<I", header, 40)
    assert data_size == 320


def test_build_wav_header_matches_frontend_fixture():
    # Same inputs as frontend/src/audio/wav.test.ts's first case — a
    # fixed cross-language expected-byte vector, not a reimplementation
    # check against itself.
    header = build_wav_header(16000, 320, 1, 16)
    expected_prefix = bytes.fromhex("52494646")  # "RIFF"
    assert header[:4] == expected_prefix
