class STTProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.buffer = [];
    this.lastVal = 0;
    this.inputSampleRate = options?.processorOptions?.sampleRate || 48000;
    this.targetSampleRate = 16000;
    this.ratio = this.inputSampleRate / this.targetSampleRate;
    this.sampleAcc = 0;
    const fc = this.targetSampleRate / 2;
    this.alpha = 1 / (1 + 2 * Math.PI * fc / this.inputSampleRate);
  }
  process(inputs) {
    const input = inputs[0];
    if (input && input.length > 0) {
      const channelData = input[0];
      if (!channelData) return true;
      for (let i = 0; i < channelData.length; i++) {
        this.lastVal = this.lastVal + this.alpha * (channelData[i] - this.lastVal);
        this.sampleAcc += 1;
        if (this.sampleAcc >= this.ratio) {
          this.sampleAcc -= this.ratio;
          const val = Math.max(-1, Math.min(1, this.lastVal));
          this.buffer.push(val * 0x7FFF);
        }
      }
      if (this.buffer.length >= 2048) {
        const out = new Int16Array(this.buffer);
        this.port.postMessage(out.buffer, [out.buffer]);
        this.buffer = [];
      }
    }
    return true;
  }
}
registerProcessor("stt-processor", STTProcessor);
