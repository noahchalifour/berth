# syntax=docker/dockerfile:1.7
FROM eclipse-temurin:21-jre-noble

ARG CMDLINE_TOOLS=13114758
ENV ANDROID_SDK_ROOT=/opt/android \
    ANDROID_AVD_HOME=/avd \
    ANDROID_EMULATOR_HOME=/avd/.android \
    PATH=/opt/android/cmdline-tools/latest/bin:/opt/android/emulator:/opt/android/platform-tools:$PATH

# HTTPS mirror: plain-HTTP apt through some proxies/emulated networks yields
# intermittent 'Hash Sum mismatch'.
RUN sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g; s|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=5 update && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
      unzip curl socat ca-certificates libpulse0 libnss3 libxcomposite1 libxcursor1 libxdamage1 \
      libxi6 libxtst6 libasound2t64 libgl1 libegl1 libxkbfile1 libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/android/cmdline-tools && cd /tmp \
    && curl -fsSLo clt.zip "https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS}_latest.zip" \
    && unzip -q clt.zip -d /opt/android/cmdline-tools && mv /opt/android/cmdline-tools/cmdline-tools /opt/android/cmdline-tools/latest \
    && rm clt.zip \
    && yes | sdkmanager --licenses >/dev/null \
    && sdkmanager --install "platform-tools" "emulator" >/dev/null

# System images: keep in sync with emulator_hub/catalog.py (tests/test_catalog.py enforces it).
RUN sdkmanager --install \
      "system-images;android-35;google_apis;x86_64" \
      "system-images;android-36;android-tv;x86_64" >/dev/null

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && useradd --uid 10010 --create-home emu && mkdir -p /avd && chown emu:emu /avd
USER 10010
EXPOSE 5557 8554
ENTRYPOINT ["/entrypoint.sh"]
