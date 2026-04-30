FROM python:3.14-alpine

RUN adduser -D appuser

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
RUN chown -R appuser:appuser /app

USER appuser

CMD ["python", "/app/app.py"]
