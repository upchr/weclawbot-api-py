FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY main.py .

# 创建配置目录
RUN mkdir -p /app/config
VOLUME /app/config

# 暴露端口
EXPOSE 26322

# 启动服务
CMD ["python", "main.py"]
