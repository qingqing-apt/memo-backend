FROM python:3.13-slim

WORKDIR /app

# 先复制依赖清单，利用 Docker 层缓存
COPY requirements.txt .
# 国内环境可用清华镜像加速；海外可去掉 -i 参数
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 复制应用代码
COPY app ./app
COPY run.py .

EXPOSE 8000

# 模型密钥等通过环境变量注入，不写入镜像
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
