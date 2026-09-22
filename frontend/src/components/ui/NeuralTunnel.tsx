import { useEffect, useRef } from 'react';
import { Renderer, Program, Mesh, Triangle } from 'ogl';

const vertex = `
  attribute vec2 position;
  attribute vec2 uv;
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position, 0.0, 1.0);
  }
`;

const fragment = `
  precision highp float;
  varying vec2 vUv;
  uniform float uTime;
  uniform vec2 uResolution;
  uniform float uSpeed;

  // Simple pseudo-random and noise functions
  float hash(float n) { return fract(sin(n) * 43758.5453123); }
  float noise(vec2 x) {
    vec2 p = floor(x);
    vec2 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    float n = p.x + p.y * 57.0;
    return mix(mix(hash(n +  0.0), hash(n +  1.0), f.x),
               mix(hash(n + 57.0), hash(n + 58.0), f.x), f.y);
  }
  
  float fbm(vec2 p) {
    float f = 0.0;
    f += 0.5000 * noise(p); p = p * 2.02;
    f += 0.2500 * noise(p); p = p * 2.03;
    f += 0.1250 * noise(p); p = p * 2.01;
    f += 0.0625 * noise(p);
    return f / 0.9375;
  }

  void main() {
    // Normalize coordinates to -1.0 to 1.0, adjusted for aspect ratio
    vec2 p = -1.0 + 2.0 * vUv;
    p.x *= uResolution.x / uResolution.y;

    // Convert to polar coordinates for the tunnel effect
    float a = atan(p.y, p.x);
    float r = length(p);

    // Tunnel geometry: u and v are cylindrical coordinates mapped to 2D
    // Adding uTime makes you fly forward
    vec2 uv = vec2(3.0 / r + uTime * uSpeed, a / 3.1415926 * 4.0);

    // Generate neural strands using layered fbm
    float n1 = fbm(uv * 2.0 - vec2(uTime * 0.2, 0.0));
    float n2 = fbm(uv * 4.0 + vec2(0.0, uTime * 0.3));
    
    // Create strand structures by thresholding and smoothing noise
    float strands = smoothstep(0.4, 0.6, n1) * smoothstep(0.4, 0.6, n2);
    
    // Add glowing synapses
    float synapses = smoothstep(0.7, 0.9, noise(uv * 10.0 + uTime)) * strands;

    // Depth fading (darker towards the center of the screen/tunnel)
    float depthFade = smoothstep(0.0, 0.5, r);

    // Colors: base dark purple/blue, strands are cyan/magenta, synapses are bright white/cyan
    vec3 baseColor = vec3(0.05, 0.0, 0.1);
    vec3 strandColor = mix(vec3(0.2, 0.0, 0.8), vec3(0.0, 0.8, 1.0), n1);
    
    vec3 color = baseColor;
    color += strandColor * strands * 2.0 * depthFade;
    color += vec3(1.0, 1.0, 1.0) * synapses * 4.0 * depthFade;

    gl_FragColor = vec4(color, 1.0);
  }
`;

interface NeuralTunnelProps {
  speed?: number;
}

export default function NeuralTunnel({ speed = 1.0 }: NeuralTunnelProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;

    const renderer = new Renderer({ alpha: true, dpr: window.devicePixelRatio || 1 });
    const gl = renderer.gl;
    container.appendChild(gl.canvas);
    gl.clearColor(0, 0, 0, 0);

    const geometry = new Triangle(gl);
    const program = new Program(gl, {
      vertex,
      fragment,
      uniforms: {
        uTime: { value: 0 },
        uResolution: { value: new Float32Array([1, 1]) },
        uSpeed: { value: speed },
      },
    });

    const mesh = new Mesh(gl, { geometry, program });

    let requestID: number;
    const resize = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      renderer.setSize(width, height);
      program.uniforms.uResolution.value[0] = width;
      program.uniforms.uResolution.value[1] = height;
    };
    window.addEventListener('resize', resize);
    resize();

    const loop = (t: number) => {
      requestID = requestAnimationFrame(loop);
      program.uniforms.uTime.value = t * 0.001;
      renderer.render({ scene: mesh });
    };
    requestID = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(requestID);
      window.removeEventListener('resize', resize);
      container.removeChild(gl.canvas);
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    };
  }, [speed]);

  return <div ref={ref} style={{ width: '100%', height: '100%' }} />;
}