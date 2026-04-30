# scd41-influx

Reads CO2, temperature, and humidity from an SCD41 sensor over I2C and writes the data to InfluxDB v2.

Supports `linux/amd64` and `linux/arm64`.

## Prerequisites

- Docker with Compose
- SCD41 wired to I2C and the bus enabled on the host
- A running InfluxDB v2 instance with a bucket and API token

## Quick start

Create a `docker-compose.yaml`:

```yaml
services:
  scd41_influx:
    image: stianjosok/scd41-influx:latest
    container_name: scd41-influx
    devices:
      - /dev/i2c-1:/dev/i2c-1      # left side is the host device — change if your sensor is on a different bus (e.g. /dev/i2c-0:/dev/i2c-1)
    environment:
      INFLUX_URL: ${INFLUX_URL}
      INFLUX_TOKEN: ${INFLUX_TOKEN}
      INFLUX_ORG: ${INFLUX_ORG}
      INFLUX_BUCKET: ${INFLUX_BUCKET}
      INTERVAL_SEC: "10"            # seconds between readings (min: 5, sensor limitation)
      MEASUREMENT: "scd41"          # InfluxDB measurement name
      LOG_LEVEL: INFO               # DEBUG | INFO | WARNING | ERROR
      INFLUX_BATCH_SIZE: "6"        # number of points to buffer before writing to InfluxDB
      INFLUX_FLUSH_MS: "60000"      # max milliseconds before force flush
      # LOCATION: ""               # optional tag added to every data point e.g. livingRoom
    group_add:
      - "${I2C_GID:-994}"
    restart: unless-stopped
```

Create a `.env` file next to it:

```env
INFLUX_URL=https://your-influxdb-host
INFLUX_TOKEN=your-token-here
INFLUX_ORG=your-org
INFLUX_BUCKET=your-bucket
```

Find your I2C GID with `stat /dev/i2c-1 | grep Gid` and set `I2C_GID` in `.env` if it differs from 994.

Then run:

```bash
docker compose up -d
```

## Logging

On a healthy start you will see two log lines and then silence:

```
INFO init ok: i2c=/dev/i2c-1 serial=... interval=10s ...
INFO first reading ok: co2=530ppm temp=24.27C rh=37.6%
```

Silence after that is normal — readings are written to InfluxDB every interval without being logged. After that the only expected output is:

| Log line | When |
|---|---|
| `INFO daily ok: co2=...` | Once every 24 hours |
| `WARNING error: ...` | On read/write failure — at most once per 5 minutes |

Set `LOG_LEVEL` to `DEBUG` in `docker-compose.yaml` to log every reading as it is written.

## Environment variables

| Variable | Description |
|---|---|
| `INFLUX_URL` | InfluxDB v2 URL |
| `INFLUX_TOKEN` | API token |
| `INFLUX_ORG` | Organisation name |
| `INFLUX_BUCKET` | Bucket name |
| `I2C_GID` | Host GID for the i2c device (default: `994`) |
| `INTERVAL_SEC` | Seconds between readings — min 5, sensor limitation (default: `10`) |
| `MEASUREMENT` | InfluxDB measurement name (default: `scd41`) |
| `INFLUX_BATCH_SIZE` | Points to buffer before writing to InfluxDB (default: `6`) |
| `INFLUX_FLUSH_MS` | Max milliseconds before force flush (default: `60000`) |
| `LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` (default: `INFO`) |
| `LOCATION` | Optional tag added to every data point |
