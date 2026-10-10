ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

# 默认走清华镜像（境内构建稳定）；官方源构建可加 --build-arg PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PYTHONPATH=/app \
    TZ=Asia/Shanghai

WORKDIR /app
USER root

# 系统库：onnxruntime 需要 libxcb/libgomp，opencv 需要 libGL/libglib（slim 镜像默认缺失）
# apt 源：默认 Debian 官方源（2026-10 起清华源间歇 403，官方源经实测可达）；镜像加速可 --build-arg APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG APT_MIRROR=
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}/debian-security|g" \
            /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list 2>/dev/null || true; \
    fi; \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 libglib2.0-0 libxcb1 libgl1 libxext6 libx11-6 \
    && rm -rf /var/lib/apt/lists/*

# 依赖层：只复制 pyproject + 空包占位，使依赖安装结果可被构建缓存复用（改业务代码不重装依赖）
COPY pyproject.toml ./
RUN mkdir -p app \
    && printf '' > app/__init__.py \
    && pip install --no-cache-dir ".[dev]" \
    && rm -rf app

# 业务代码与迁移
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY entrypoint.sh ./entrypoint.sh
COPY tests ./tests

RUN sed -i 's/\r$//' ./entrypoint.sh \
    && chmod +x ./entrypoint.sh \
    && (id -u appuser >/dev/null 2>&1 || useradd -m -u 10001 appuser) \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
