import os
import signal
import threading
import time
import logging
from datetime import datetime, timezone

from sensirion_i2c_driver import LinuxI2cTransceiver, I2cConnection
from sensirion_i2c_scd import Scd4xI2cDevice

from influxdb_client import InfluxDBClient, Point, WriteOptions


# --- config ---
I2C_DEV = os.getenv("I2C_DEV", "/dev/i2c-1")

INFLUX_URL = os.environ["INFLUX_URL"]
INFLUX_TOKEN = os.environ["INFLUX_TOKEN"]
INFLUX_ORG = os.environ["INFLUX_ORG"]
INFLUX_BUCKET = os.environ["INFLUX_BUCKET"]

INTERVAL_SEC = int(os.getenv("INTERVAL_SEC", "10"))
MEASUREMENT = os.getenv("MEASUREMENT", "scd41")

# Optional tags (keep minimal)
LOCATION = os.getenv("LOCATION", "")  # empty => omit

# Logging behavior
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DAILY_LOG_SEC = int(os.getenv("DAILY_LOG_SEC", "86400"))  # once/day
ERROR_LOG_MIN_INTERVAL_SEC = int(os.getenv("ERROR_LOG_MIN_INTERVAL_SEC", "300"))  # max once/5 min

# Influx batching (reduce HTTP requests)
INFLUX_BATCH_SIZE = int(os.getenv("INFLUX_BATCH_SIZE", "6"))   # ~1 minute at 10s interval
INFLUX_FLUSH_MS = int(os.getenv("INFLUX_FLUSH_MS", "60000"))   # flush at least every minute

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scd41")


def utc_now():
    return datetime.now(timezone.utc)


def main():
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _sig, _frame: stop.set())
    signal.signal(signal.SIGINT, lambda _sig, _frame: stop.set())

    last_daily_log = 0.0
    last_error_log = 0.0
    first_ok_logged = False
    last_values = None  # (co2_ppm, temp_c, rh)

    write_opts = WriteOptions(
        batch_size=INFLUX_BATCH_SIZE,
        flush_interval=INFLUX_FLUSH_MS,
    )

    with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
        write_api = client.write_api(write_options=write_opts)

        try:
            with LinuxI2cTransceiver(I2C_DEV) as i2c_transceiver:
                scd4x = Scd4xI2cDevice(I2cConnection(i2c_transceiver))

                # Clean start (ignore if already stopped)
                try:
                    scd4x.stop_periodic_measurement()
                except Exception:
                    pass

                serial = scd4x.read_serial_number()
                scd4x.start_periodic_measurement()

                log.info(
                    "init ok: i2c=%s serial=%s interval=%ss influx=%s bucket=%s batch=%s flush_ms=%s",
                    I2C_DEV, serial, INTERVAL_SEC, INFLUX_URL, INFLUX_BUCKET, INFLUX_BATCH_SIZE, INFLUX_FLUSH_MS,
                )

                last_daily_log = time.monotonic()

                while not stop.wait(INTERVAL_SEC):

                    try:
                        co2, temperature, humidity = scd4x.read_measurement()
                        co2_ppm = int(round(co2.co2))
                        temp_c = float(temperature.degrees_celsius)
                        rh = float(humidity.percent_rh)
                        last_values = (co2_ppm, temp_c, rh)

                        ts = utc_now()

                        p = (
                            Point(MEASUREMENT)
                            .field("co2_ppm", co2_ppm)
                            .field("temperature_c", temp_c)
                            .field("humidity_rh", rh)
                            .time(ts)
                        )

                        if LOCATION:
                            p = p.tag("location", LOCATION)

                        p = p.tag("serial", str(serial))

                        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=p)

                        log.debug("reading: co2=%dppm temp=%.2fC rh=%.1f%%", co2_ppm, temp_c, rh)

                        if not first_ok_logged:
                            first_ok_logged = True
                            log.info(
                                "first reading ok: co2=%dppm temp=%.2fC rh=%.1f%%",
                                co2_ppm, temp_c, rh,
                            )

                        now_mono = time.monotonic()
                        if now_mono - last_daily_log >= DAILY_LOG_SEC and last_values is not None:
                            last_daily_log = now_mono
                            log.info(
                                "daily ok: co2=%dppm temp=%.2fC rh=%.1f%%",
                                *last_values,
                            )

                    except Exception as e:
                        now_mono = time.monotonic()
                        if now_mono - last_error_log >= ERROR_LOG_MIN_INTERVAL_SEC:
                            last_error_log = now_mono
                            log.warning("error: %s", e)

        finally:
            # Best-effort flush to reduce risk of losing the last partial batch on shutdown
            try:
                write_api.flush()
            except Exception:
                pass


if __name__ == "__main__":
    main()
