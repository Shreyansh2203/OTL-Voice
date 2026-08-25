class STTProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.buffer = [];
    this.inputSampleRate = options?.processorOptions?.sampleRate || 16000;
    this.targetSampleRate = 16000;
    this.ratio = this.inputSampleRate / this.targetSampleRate;
    this.sampleAcc = 0;
    this.lastVal = 0;
    const fc = this.targetSampleRate / 2;
    this.alpha = 1 / (1 + (2 * Math.PI * fc) / this.inputSampleRate);
    // Voice Activity Noise Gate
    this.noiseThreshold = 0.008;
    this.hangoverFrames = 0;
    this.maxHangover = Math.ceil(0.25 * (this.inputSampleRate / 128)); // 250ms hold
  }
  process(inputs) {
    const input = inputs[0];
    if (input && input.length > 0) {
      const channelData = input[0];
      if (!channelData) return true;

      // Calculate RMS energy of current audio block
      let sumSq = 0;
      for (let i = 0; i < channelData.length; i++) {
        sumSq += channelData[i] * channelData[i];
      }
      const rms = Math.sqrt(sumSq / channelData.length);
      if (rms >= this.noiseThreshold) {
        this.hangoverFrames = this.maxHangover;
      } else if (this.hangoverFrames > 0) {
        this.hangoverFrames--;
      }

      const isVoiceActive = this.hangoverFrames > 0;

      if (this.inputSampleRate === 16000) {
        const out = new Int16Array(channelData.length);
        for (let i = 0; i < channelData.length; i++) {
          if (isVoiceActive) {
            const s = Math.max(-1, Math.min(1, channelData[i]));
            out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          } else {
            out[i] = 0; // Clean silence - prevents ASR hallucinations on background fan/room noise
          }
        }
        this.port.postMessage(out.buffer, [out.buffer]);
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
          this.port.postMessage(out.buffer, [out.buffer]);
          this.buffer = [];
        }
      }
    }
    return true;
  }
}
registerProcessor("stt-processor", STTProcessor);
