FROM python:3.12-slim
WORKDIR /app
RUN groupadd --system casepilot && useradd --system --gid casepilot casepilot && mkdir /data && chown casepilot:casepilot /data
COPY main.py index.html ./
COPY static/ ./static/
EXPOSE 8765
ENV CASEPILOT_DB=/data/casepilot.sqlite3
ENV CASEPILOT_HOST=0.0.0.0
USER casepilot
CMD ["python","main.py"]
