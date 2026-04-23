FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get upgrade -y

RUN apt-get install -y \
    build-essential automake libtool \
    libzmq3-dev libzmq5 \
    libasound2-dev libsoapysdr-dev\
    libjack-jackd2-dev libbladerf-dev\
    libvlc-dev liblimesuite-dev\
    libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    libcurl4-openssl-dev libboost-system-dev libmagickwand-dev\
    git libuhd-dev\
    autoconf ffmpeg\
    pkg-config \
    libfftw3-dev \
    libcurl4-openssl-dev \
    wget hackrf supervisor python3 python3-pip socat tzdata\
    && rm -rf /var/lib/apt/lists/*

RUN ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone && \
    dpkg-reconfigure --frontend noninteractive tzdata

WORKDIR /app

RUN git clone --depth 1 https://github.com/Opendigitalradio/ODR-AudioEnc.git
RUN git clone --depth 1 https://github.com/Opendigitalradio/ODR-DabMux.git
RUN git clone --depth 1 https://github.com/Opendigitalradio/ODR-PadEnc.git
RUN git clone --depth 1 https://github.com/Opendigitalradio/ODR-DabMod.git

RUN cd ODR-AudioEnc \
    && ./bootstrap \
    && ./configure\
    && make -j$(nproc) \
    && make install

RUN cd ODR-DabMux \
    && ./bootstrap.sh \
    && ./configure \
    && make -j$(nproc) \
    && make install

RUN cd ODR-PadEnc \
    && ./bootstrap \
    && ./configure \
    && make -j$(nproc) \
    && make install

RUN cd ODR-DabMod \
    && ./bootstrap.sh \
    && ./configure \
    && make -j$(nproc) \
    && make install

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages --ignore-installed -r requirements.txt

USER root

COPY . .

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]