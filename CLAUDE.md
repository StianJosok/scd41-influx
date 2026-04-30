# scd41-influx

## Running tests

```bash
docker run --rm -v "$(pwd)":/app -w /app python:3.14-alpine sh -c "pip install -q -r requirements-dev.txt && pytest tests/ -v"
```

## Building and pushing

```bash
docker buildx build --builder multiarch --platform linux/amd64,linux/arm64 --push -t stianjosok/scd41-influx:latest .
```

The `multiarch` builder uses the `docker-container` driver with QEMU binfmt for cross-compilation.

## Design rules

- Secrets (`INFLUX_*`, `I2C_GID`) go in `.env` only
- All tuning lives in `docker-compose.yaml` with inline comments
- `tests/` and `requirements-dev.txt` are excluded from the Docker image via `.dockerignore`
