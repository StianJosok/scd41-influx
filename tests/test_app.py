import os

import pytest
from unittest.mock import patch, MagicMock

import app


def _mock_sensor(co2=550.0, temp=22.5, rh=45.0):
    sensor = MagicMock()
    co2_val = MagicMock(); co2_val.co2 = co2
    temp_val = MagicMock(); temp_val.degrees_celsius = temp
    rh_val = MagicMock(); rh_val.percent_rh = rh
    sensor.read_measurement.return_value = (co2_val, temp_val, rh_val)
    return sensor


def _mock_stop_event(iterations=1):
    stop = MagicMock()
    stop.wait.side_effect = [False] * iterations + [True]
    return stop


def test_device_not_found(caplog):
    with patch("app.LinuxI2cTransceiver", side_effect=FileNotFoundError), \
         patch("app.InfluxDBClient"), \
         patch("app.signal.signal"):
        with caplog.at_level("ERROR", logger="scd41"):
            app.main()
    assert "device not found" in caplog.text


def test_device_permission_denied(caplog):
    with patch("app.LinuxI2cTransceiver", side_effect=PermissionError), \
         patch("app.InfluxDBClient"), \
         patch("app.signal.signal"):
        with caplog.at_level("ERROR", logger="scd41"):
            app.main()
    assert "permission denied" in caplog.text


def test_influx_unreachable(caplog):
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.ping.return_value = False

    with patch("app.InfluxDBClient", return_value=mock_client), \
         patch("app.LinuxI2cTransceiver") as mock_i2c, \
         patch("app.signal.signal"):
        with caplog.at_level("ERROR", logger="scd41"):
            app.main()

    assert "cannot reach InfluxDB" in caplog.text
    mock_i2c.assert_not_called()
    mock_client.write_api.assert_not_called()


def test_throttled_warn_suppresses_repeats(caplog):
    warn = app.ThrottledWarn(min_interval_sec=300)
    with caplog.at_level("WARNING", logger="scd41"):
        warn("first: %s", "a")
        warn("second: %s", "b")
    assert "first: a" in caplog.text
    assert "second: b" not in caplog.text


def test_happy_path_one_reading(caplog):
    mock_stop = _mock_stop_event(iterations=1)
    mock_scd4x = _mock_sensor()
    mock_write_api = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.write_api.return_value = mock_write_api

    with patch("app.LinuxI2cTransceiver"), \
         patch("app.I2cConnection"), \
         patch("app.Scd4xI2cDevice", return_value=mock_scd4x), \
         patch("app.InfluxDBClient", return_value=mock_client), \
         patch("app.threading.Event", return_value=mock_stop), \
         patch("app.signal.signal"):
        with caplog.at_level("INFO", logger="scd41"):
            app.main()

    mock_write_api.write.assert_called_once()
    assert "first reading ok" in caplog.text


def test_signal_stops_loop(caplog):
    mock_stop = _mock_stop_event(iterations=0)
    mock_scd4x = _mock_sensor()
    mock_write_api = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.write_api.return_value = mock_write_api

    with patch("app.LinuxI2cTransceiver"), \
         patch("app.I2cConnection"), \
         patch("app.Scd4xI2cDevice", return_value=mock_scd4x), \
         patch("app.InfluxDBClient", return_value=mock_client), \
         patch("app.threading.Event", return_value=mock_stop), \
         patch("app.signal.signal"):
        app.main()

    mock_write_api.write.assert_not_called()
    mock_stop.set.assert_not_called()
    # once for the clean start, once on shutdown
    assert mock_scd4x.stop_periodic_measurement.call_count == 2
    mock_write_api.close.assert_called_once()


def test_calibration_applied_when_set():
    mock_stop = _mock_stop_event(iterations=0)
    mock_scd4x = _mock_sensor()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("app.LinuxI2cTransceiver"), \
         patch("app.I2cConnection"), \
         patch("app.Scd4xI2cDevice", return_value=mock_scd4x), \
         patch("app.InfluxDBClient", return_value=mock_client), \
         patch("app.threading.Event", return_value=mock_stop), \
         patch("app.signal.signal"), \
         patch("app.TEMP_OFFSET_C", 5.5), \
         patch("app.ALTITUDE_M", 120), \
         patch("app.ASC_ENABLED", False):
        app.main()

    mock_scd4x.set_temperature_offset.assert_called_once_with(5.5)
    mock_scd4x.set_sensor_altitude.assert_called_once_with(120)
    mock_scd4x.set_automatic_self_calibration.assert_called_once_with(False)


def test_calibration_unset_leaves_sensor_untouched():
    mock_stop = _mock_stop_event(iterations=0)
    mock_scd4x = _mock_sensor()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("app.LinuxI2cTransceiver"), \
         patch("app.I2cConnection"), \
         patch("app.Scd4xI2cDevice", return_value=mock_scd4x), \
         patch("app.InfluxDBClient", return_value=mock_client), \
         patch("app.threading.Event", return_value=mock_stop), \
         patch("app.signal.signal"):
        app.main()

    mock_scd4x.set_temperature_offset.assert_not_called()
    mock_scd4x.set_sensor_altitude.assert_not_called()
    mock_scd4x.set_automatic_self_calibration.assert_not_called()


def test_optional_bool_rejects_invalid_value():
    with patch.dict(os.environ, {"ASC_ENABLED": "maybe"}):
        with pytest.raises(ValueError):
            app._optional_bool("ASC_ENABLED")
