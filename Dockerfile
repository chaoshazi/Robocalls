# 外呼系统：镜像构建与编排（交付物，本机无 docker 未验证）
FROM python:3.11-slim

WORKDIR /srv/wahu
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY sql ./sql
COPY scripts ./scripts
COPY pyproject.toml README.md ./
COPY web/dist ./web/dist

EXPOSE 9300
# 说明：生产请通过环境变量注入 WAHU_SECRET_KEY / WAHU_BOOTSTRAP_ADMIN_PASSWORD 等，
# 并把 WAHU_ENV 设为 prod；启动守卫会拒绝默认密钥与模拟能力。
CMD ["python", "-X", "utf8", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9300"]