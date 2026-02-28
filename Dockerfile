FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY flask_bridge_final.py .
EXPOSE 8012
CMD gunicorn --bind 0.0.0.0:${PORT:-8012} --timeout 310 --workers 2 flask_bridge_final:app
