class PCMPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // Circular / ring buffer for incoming Float32 samples
    this.bufferSize = 96000; // ~2 seconds buffer at 48kHz
    this.buffer = new Float32Array(this.bufferSize);
    this.readIndex = 0;
    this.writeIndex = 0;
    this.samplesAvailable = 0;
    this.totalSamplesPlayed = 0;
    this.lastReportFrame = 0;

    this.port.onmessage = (event) => {
      const data = event.data;
      if (data.type === "push") {
        const incoming = new Float32Array(data.buffer);
        for (let i = 0; i < incoming.length; i++) {
          if (this.samplesAvailable < this.bufferSize) {
            this.buffer[this.writeIndex] = incoming[i];
            this.writeIndex = (this.writeIndex + 1) % this.bufferSize;
            this.samplesAvailable++;
          }
        }
      } else if (data.type === "flush") {
        // Instant barge-in cutoff: report truncation point
        const playedMs = Math.round((this.totalSamplesPlayed / sampleRate) * 1000);
        this.port.postMessage({ type: "truncated", playedMs });
        this.readIndex = 0;
        this.writeIndex = 0;
        this.samplesAvailable = 0;
      }
    };
  }

  process(inputs, outputs) {
    const output = outputs[0];
    if (!output || output.length === 0) return true;

    const channelLeft = output[0];
    const channelRight = output[1] || output[0];
    const frameCount = channelLeft.length;

    for (let i = 0; i < frameCount; i++) {
      if (this.samplesAvailable > 0) {
        const sample = this.buffer[this.readIndex];
        this.readIndex = (this.readIndex + 1) % this.bufferSize;
        this.samplesAvailable--;
        this.totalSamplesPlayed++;

        channelLeft[i] = sample;
        if (channelRight !== channelLeft) {
          channelRight[i] = sample;
        }
      } else {
        channelLeft[i] = 0;
        if (channelRight !== channelLeft) {
          channelRight[i] = 0;
        }
      }
    }

    this.lastReportFrame += frameCount;
    if (this.lastReportFrame >= 1024) {
      this.lastReportFrame = 0;
      const playedMs = Math.round((this.totalSamplesPlayed / sampleRate) * 1000);
      this.port.postMessage({
        type: "progress",
        playedMs,
        isPlaying: this.samplesAvailable > 0,
      });
    }

    if (this.samplesAvailable === 0 && this.totalSamplesPlayed > 0) {
      this.port.postMessage({ type: "empty" });
    }

    return true;
  }
}

registerProcessor("pcm-player-processor", PCMPlayerProcessor);
