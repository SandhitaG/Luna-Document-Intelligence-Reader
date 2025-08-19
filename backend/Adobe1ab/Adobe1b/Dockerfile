FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

RUN apt-get update && apt-get install -y gcc g++ build-essential && apt-get clean

RUN pip install --no-cache-dir torch==1.13.1+cpu -f https://download.pytorch.org/whl/torch_stable.html

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["bash", "run.sh"]
