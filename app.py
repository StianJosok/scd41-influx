import os
import signal
import threading
import time
import logging
from datetime import datetime, timezone

from sensirion_i2c_driver import LinuxI2cTransceiver, I2cConnection
from sensirion_i2c_scd import Scd4xI2cDevice

from influxdb_client import InfluxDBClient, Point, WriteOptions


def _optional_float(name):
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else None


def _optional_int(name):
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None


def _optional_bool(name):
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return None
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise ValueError(f"{name}: expected true/false, got {raw!r}")


# --- config ---
I2C_DEV = "/dev/i2c-1"

INFLUX_URL = os.environ["INFLUX_URL"]
INFLUX_TOKEN = os.environ["INFLUX_TOKEN"]
INFLUX_ORG = os.environ["INFLUX_ORG"]
INFLUX_BUCKET = os.environ["INFLUX_BUCKET"]

INTERVAL_SEC = int(os.getenv("INTERVAL_SEC", "10"))
MEASUREMENT = os.getenv("MEASUREMENT", "scd41")

# Optional tags (keep minimal)
LOCATION = os.getenv("LOCATION", "")  # empty => omit

# Sensor calibration — unset means leave the sensor's current setting
# untouched. See README "Sensor calibration" for defaults and guidance.
TEMP_OFFSET_C = _optional_float("TEMP_OFFSET_C")
ALTITUDE_M = _optional_int("ALTITUDE_M")
ASC_ENABLED = _optional_bool("ASC_ENABLED")

# Logging behavior
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DAILY_LOG_SEC = 86400   # heartbeat log interval: once per day
ERROR_LOG_MIN_INTERVAL_SEC = 300  # suppress repeated error logs: max once per 5 min

# Influx batching (reduce HTTP requests)
INFLUX_BATCH_SIZE = int(os.getenv("INFLUX_BATCH_SIZE", "6"))   # ~1 minute at 10s interval
INFLUX_FLUSH_MS = int(os.getenv("INFLUX_FLUSH_MS", "60000"))   # flush at least every minute

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scd41")


def utc_now():
    return datetime.now(timezone.utc)


class ThrottledWarn:
    """Rate-limited warning logger; thread-safe so the Influx background
    write thread and the main loop can share the pattern."""

    def __init__(self, min_interval_sec):
        self._min_interval = min_interval_sec
        self._last = 0.0
        self._lock = threading.Lock()

    def __call__(self, msg, *args):
        with self._lock:
            now = time.monotonic()
            if now - self._last < self._min_interval:
                return
            self._last = now
        log.warning(msg, *args)


def main():
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _sig, _frame: stop.set())
    signal.signal(signal.SIGINT, lambda _sig, _frame: stop.set())

    warn_sensor = ThrottledWarn(ERROR_LOG_MIN_INTERVAL_SEC)
    warn_influx = ThrottledWarn(ERROR_LOG_MIN_INTERVAL_SEC)

    last_daily_log = 0.0
    first_ok_logged = False
    last_values = None  # (co2_ppm, temp_c, rh)

    write_opts = WriteOptions(
        batch_size=INFLUX_BATCH_SIZE,
        flush_interval=INFLUX_FLUSH_MS,
    )

    with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
        if not client.ping():
            log.error("cannot reach InfluxDB at %s — check INFLUX_URL and that the instance is up", INFLUX_URL)
            return

        # Batching mode writes happen on a background thread; without this
        # callback a bad token/org/bucket would drop every point silently.
        write_api = client.write_api(
            write_options=write_opts,
            error_callback=lambda _conf, _data, exc: warn_influx("influx write failed: %r", exc),
        )

        try:
            with LinuxI2cTransceiver(I2C_DEV) as i2c_transceiver:
                scd4x = Scd4xI2cDevice(I2cConnection(i2c_transceiver))

                # Clean start (ignore if already stopped)
                try:
                    scd4x.stop_periodic_measurement()
                except Exception:
                    pass

                serial = scd4x.read_serial_number()

                # Calibration commands only work in idle mode, i.e. here
                # between stop and start. The sensor holds them in RAM, so
                # they are reapplied on every start — deliberately not
                # persisted to EEPROM (limited write endurance).
                if TEMP_OFFSET_C is not None:
                    scd4x.set_temperature_offset(TEMP_OFFSET_C)
                if ALTITUDE_M is not None:
                    scd4x.set_sensor_altitude(ALTITUDE_M)
                if ASC_ENABLED is not None:
                    scd4x.set_automatic_self_calibration(ASC_ENABLED)
                if (TEMP_OFFSET_C, ALTITUDE_M, ASC_ENABLED) != (None, None, None):
                    log.info(
                        "calibration applied: temp_offset_c=%s altitude_m=%s asc=%s",
                        TEMP_OFFSET_C, ALTITUDE_M, ASC_ENABLED,
                    )

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
                        warn_sensor("sensor error: %r", e)

                # Stopped via SIGTERM/SIGINT — leave the sensor idle
                try:
                    scd4x.stop_periodic_measurement()
                except Exception:
                    pass

        except FileNotFoundError:
            log.error("device not found: %s — check the devices: bind mount in your compose file", I2C_DEV)
            return
        except PermissionError:
            log.error("permission denied: %s — check that group_add GID matches the i2c group on your host (stat /dev/i2c-1 | grep Gid)", I2C_DEV)
            return
        finally:
            # close() flushes remaining points and stops the background
            # write thread; flush() alone leaves the thread running
            try:
                write_api.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
