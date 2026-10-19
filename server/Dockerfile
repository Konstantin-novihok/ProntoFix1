FROM python:3.12-slim
WORKDIR /srv
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/*.py ./
COPY web ./web
ENV WEB_DIR=/srv/web
ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
