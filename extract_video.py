
from mcap.reader import make_reader
from pathlib import Path
import statistics

source = Path(
    r"D:\TST\HumanEgo_Videos\20261019_SPA-20261020T023851Z-1-002"
    r"\20261019_SPA\20261019_044407\part_00017.mcap"
)
topic = "/top-left-camera/image-raw"
output = Path(r"D:\MCAPConverter\top_left.h265")


def read_varint(data, pos):
    value = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        value |= (b & 0x7f) << shift
        if b < 0x80:
            return value, pos
        shift += 7
    raise ValueError("Invalid varint")


def fields(data):
    pos = 0
    while pos < len(data):
        key, pos = read_varint(data, pos)
        number, wire = key >> 3, key & 7

        if wire == 0:
            value, pos = read_varint(data, pos)
        elif wire == 1:
            value = data[pos:pos + 8]
            pos += 8
        elif wire == 2:
            size, pos = read_varint(data, pos)
            value = data[pos:pos + size]
            pos += size
        elif wire == 5:
            value = data[pos:pos + 4]
            pos += 4
        else:
            raise ValueError(f"Unsupported wire type: {wire}")

        yield number, wire, value


def timestamp_ns(data):
    # foxglove.CompressedVideo field 1 is google.protobuf.Timestamp
    seconds = nanos = 0
    for number, wire, value in fields(data):
        if number == 1 and wire == 0:
            seconds = value
        elif number == 2 and wire == 0:
            nanos = value
    return seconds * 1_000_000_000 + nanos


times = []
count = 0

with source.open("rb") as f, output.open("wb") as out:
    reader = make_reader(f)

    for schema, channel, msg in reader.iter_messages(topics=[topic]):
        if schema is None or schema.name != "foxglove.CompressedVideo":
            raise ValueError("Unexpected schema")

        message_fields = list(fields(msg.data))
        ts_field = next(
            (value for number, wire, value in message_fields
             if number == 1 and wire == 2),
            None,
        )
        data_field = next(
            (value for number, wire, value in message_fields
             if number == 3 and wire == 2),
            None,
        )
        format_field = next(
            (value for number, wire, value in message_fields
             if number == 4 and wire == 2),
            b"",
        )

        if format_field != b"h265":
            raise ValueError(f"Unexpected codec: {format_field!r}")
        if data_field is None:
            raise ValueError("Missing compressed data")

        out.write(data_field)
        if ts_field is not None:
            times.append(timestamp_ns(ts_field))
        count += 1

print(f"Messages extracted: {count}")
print(f"Output file: {output}")
print(f"File size: {output.stat().st_size:,} bytes")

valid_deltas = [
    (b - a) / 1e9
    for a, b in zip(times, times[1:])
    if b > a
]
if valid_deltas:
    median_dt = statistics.median(valid_deltas)
    print(f"Median frame interval: {median_dt:.6f} seconds")
    print(f"Estimated FPS: {1 / median_dt:.3f}")
    print(f"Timestamp duration: {(times[-1] - times[0]) / 1e9:.3f} seconds")
else:
    print("Could not estimate FPS from message timestamps.")
