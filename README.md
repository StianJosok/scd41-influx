# scd41-influx

Reads CO2, temperature, and humidity from an SCD41 sensor over I2C and writes the data to InfluxDB v2.

Supports `linux/amd64` and `linux/arm64` (Raspberry Pi 4/5).

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
    devices:
      - /dev/i2c-1:/dev/i2c-1
    environment:
      I2C_DEV: /dev/i2c-1
      INFLUX_URL: ${INFLUX_URL}
      INFLUX_TOKEN: ${INFLUX_TOKEN}
      INFLUX_ORG: ${INFLUX_ORG}
      INFLUX_BUCKET: ${INFLUX_BUCKET}
      INTERVAL_SEC: "10"
      MEASUREMENT: "scd41"
    group_add:
      - "${I2C_GID:-994}"
    restart: unless-stopped
```

Create a `.env` file next to it:

```env
INFLUX_URL=https://your-influxdb-host
INFLUX_TOKEN=your-token-here
INFLUX_ORG=your-org
INFLUX_BUCKET=scd41
```

Find your I2C GID with `stat /dev/i2c-1 | grep Gid` and set `I2C_GID` in `.env` if it differs from 994.

Then run:

```bash
docker compose up -d
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `INFLUX_URL` | yes | — | InfluxDB v2 URL |
| `INFLUX_TOKEN` | yes | — | API token |
| `INFLUX_ORG` | yes | — | Organisation name |
| `INFLUX_BUCKET` | yes | — | Bucket name |
| `I2C_GID` | no | `994` | Host GID for `/dev/i2c-1` |
| `I2C_DEV` | no | `/dev/i2c-1` | I2C device path |
| `INTERVAL_SEC` | no | `10` | Seconds between readings |
| `MEASUREMENT` | no | `scd41` | InfluxDB measurement name |
| `LOCATION` | no | — | Optional location tag on data points |
| `LOG_LEVEL` | no | `INFO` | Logging level |
