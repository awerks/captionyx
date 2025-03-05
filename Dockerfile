FROM ubuntu:22.04
FROM nginx:latest
RUN apt-get update && apt-get install -y \
    ffmpeg \
    zlib1g-dev \
    libpq-dev \
    libssl-dev \
    libc++abi-dev \
    libc++-dev \
    python3 \
    python3-pip \
    gperf \
    fontconfig 

COPY . /app
WORKDIR /app

COPY fonts/*.ttf /usr/share/fonts/
COPY fonts/*.otf /usr/share/fonts/
RUN fc-cache -f -v

RUN pip3 install -r requirements.txt --break-system-packages

RUN chmod +x ./telegram-bot-api/telegram-bot-api

EXPOSE 8081

CMD ["bash", "-c", "./telegram-bot-api/telegram-bot-api --api-id=$apiid --api-hash=$apihash --local & python3 bot.py"]