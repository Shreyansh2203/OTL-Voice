class PCMRecorderProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.inputSampleRate = options?.processorOptions?.sampleRate || 16000;
    this.targetSampleRate = 16000;
    this.ratio = this.inputSampleRate / this.targetSampleRate;
    this.sampleAcc = 0;
    this.lastVal = 0;
    const fc = this.targetSampleRate / 2;
    this.alpha = 1 / (1 + (2 * Math.PI * fc) / this.inputSampleRate);
    this.buffer = [];

    // Voice Activity Energy Gate & Zero Crossing Rate
    this.noiseThreshold = 0.005;
    this.hangoverFrames = 0;
    this.maxHangover = Math.ceil(0.3 * (this.inputSampleRate / 128)); // 300ms hangover

    this.port.onmessage = (event) => {
      if (event.data?.type === "flush" && this.buffer.length > 0) {
        const out = new Int16Array(this.buffer);
        this.port.postMessage(
          {
            type: "audio",
            buffer: out.buffer,
            rms: 0,
            zcr: 0,
            isVoiceActive: false,
          },
          [out.buffer]
        );
        this.buffer = [];
      }
    };
  }

  process(inputs) {
    const input = inputs[0];
    if (input && input.length > 0) {
      const channelData = input[0];
      if (!channelData) return true;

      // Calculate RMS energy & Zero-Crossing Rate
      let sumSq = 0;
      let zeroCrossings = 0;
      for (let i = 0; i < channelData.length; i++) {
        sumSq += channelData[i] * channelData[i];
        if (i > 0 && ((channelData[i] >= 0 && channelData[i - 1] < 0) || (channelData[i] < 0 && channelData[i - 1] >= 0))) {
          zeroCrossings++;
        }
      }
      const rms = Math.sqrt(sumSq / channelData.length);
      const zcr = zeroCrossings / channelData.length;

      // Vocal onset detection (human voice has typical ZCR between 0.02 and 0.45)
      const isVoiceLike = rms >= this.noiseThreshold && zcr >= 0.01 && zcr <= 0.55;

      if (isVoiceLike) {
        this.hangoverFrames = this.maxHangover;
      } else if (this.hangoverFrames > 0) {
        this.hangoverFrames--;
      }

      const isVoiceActive = this.hangoverFrames > 0;

      // Resample and convert to 16-bit Linear PCM
      if (this.inputSampleRate === 16000) {
        const out = new Int16Array(channelData.length);
        for (let i = 0; i < channelData.length; i++) {
          if (isVoiceActive) {
            const s = Math.max(-1, Math.min(1, channelData[i]));
            out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          } else {
            out[i] = 0;
          }
        }
        this.port.postMessage({
          type: "audio",
          buffer: out.buffer,
          rms,
          zcr,
          isVoiceActive,
        }, [out.buffer]);
      } else {
        for (let i = 0; i < channelData.length; i++) {
          this.lastVal = this.lastVal + this.alpha * (channelData[i] - this.lastVal);
          this.sampleAcc += 1;
          if (this.sampleAcc >= this.ratio) {
            this.sampleAcc -= this.ratio;
            if (isVoiceActive) {
              const s = Math.max(-1, Math.min(1, this.lastVal));
              this.buffer.push(s < 0 ? s * 0x8000 : s * 0x7fff);
            } else {
              this.buffer.push(0);
            }
          }
        }
        if (this.buffer.length >= 1024) {
          const out = new Int16Array(this.buffer);
          this.port.postMessage({
            type: "audio",
            buffer: out.buffer,
            rms,
            zcr,
            isVoiceActive,
          }, [out.buffer]);
          this.buffer = [];
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-recorder-processor", PCMRecorderProcessor);
