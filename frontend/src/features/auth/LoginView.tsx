import { FormEvent, useState, useRef } from 'react';
import { motion } from 'motion/react';
import * as api from '../../api/client';
import type { Identity } from '../../types';
import SimpleMarquee from '../../components/fancy/blocks/simple-marquee';
import styles from './LoginView.module.css';

const exampleImages = [
  "https://cdn.cosmos.so/4b771c5c-d1eb-4948-b839-255dbeb931ba?format=jpeg",
  "https://cdn.cosmos.so/a8d82afd-2293-43ad-bac3-887683d85b44?format=jpeg",
  "https://cdn.cosmos.so/49206ba5-c174-4cd5-aee8-5b744842e6c2?format=jpeg",
  "https://cdn.cosmos.so/b29bd150-6477-420f-8efb-65ed99694421?format=jpeg",
  "https://cdn.cosmos.so/e1a0313e-7617-431d-b7f1-f1b169e6bcb4?format=jpeg",
  "https://cdn.cosmos.so/ad640c12-69fb-4186-bc3d-b1cc93986a37?format=jpeg",
  "https://cdn.cosmos.so/5cf0c3d2-e785-41a3-b0c8-a073ee2f2862?format=jpeg",
  "https://cdn.cosmos.so/938ab21c-a975-41b3-b303-418290343b09?format=jpeg",
  "https://cdn.cosmos.so/2e14a9bb-27e3-40fd-b940-cfb797a1224c?format=jpeg",
  "https://cdn.cosmos.so/81841d9f-e164-4770-aebc-cfc97d72f3ab?format=jpeg",
  "https://cdn.cosmos.so/49b81db0-37ea-4569-b0d6-04afa5115a10?format=jpeg",
  "https://cdn.cosmos.so/ade1834b-9317-44fb-8dc3-b43d29acd409?format=jpeg",
  "https://cdn.cosmos.so/621c250c-3833-45f9-862a-3f400aaf8f28?format=jpeg",
  "https://cdn.cosmos.so/f9b7eae8-e5a6-4ce6-b6e1-9ef125ba7f8e?format=jpeg",
  "https://cdn.cosmos.so/bd56ed6d-1bbd-44a4-b1a1-79b7199bbebb?format=jpeg",
];

const MarqueeItem = ({ children }: { children: React.ReactNode }) => (
  <div className={styles.marqueeItem}>
    {children}
  </div>
);

export default function LoginView({
  onLogin,
}: {
  onLogin: (identity: Identity) => void;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);

  const firstThird = exampleImages.slice(
    0,
    Math.floor(exampleImages.length / 3)
  );
  const secondThird = exampleImages.slice(
    Math.floor(exampleImages.length / 3),
    Math.floor((2 * exampleImages.length) / 3)
  );
  const lastThird = exampleImages.slice(
    Math.floor((2 * exampleImages.length) / 3)
  );

  const easeFn = (x: number) => {
    return x === 0
      ? 0
      : x === 1
        ? 1
        : x < 0.5
          ? Math.pow(2, 20 * x - 10) / 2
          : (2 - Math.pow(2, -20 * x + 10)) / 2;
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      onLogin(await api.login(username.trim(), password));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.container} ref={containerRef}>
      <div className={styles.innerLayout}>
        <div className={styles.fluffSection}>
          <h1 className={styles.heading}>
            Welcome Back!
          </h1>
          <p className={styles.footerText} style={{ marginBottom: "1rem" }}>
            Sign in with your employee credentials.
          </p>

          <form className={styles.formContainer} onSubmit={submit}>
            <div className={styles.inputGroup}>
              <input
                type="text"
                autoComplete="username"
                className={styles.input}
                placeholder="Person Number (e.g. 7)"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
              />
            </div>
            
            <div className={styles.inputGroup} style={{ marginTop: "0.5rem" }}>
              <input
                type="password"
                autoComplete="current-password"
                className={styles.input}
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            {error && (
              <div role="alert" style={{ color: '#ef4444', fontSize: '0.875rem', marginTop: "0.5rem" }}>
                {error}
              </div>
            )}

            <motion.button 
              whileHover={{ scale: 1.02 }} 
              whileTap={{ scale: 0.98 }} 
              className={styles.submitBtn} 
              style={{ marginTop: "1rem" }} 
              type="submit" 
              disabled={busy}
            >
              {busy ? 'Signing in...' : 'Sign In'}
            </motion.button>

            <p className={styles.footerText} style={{ marginTop: "1rem", fontSize: "0.75rem" }}>
              Your Person Number is checked securely against Oracle Fusion Cloud.
            </p>
          </form>
        </div>

        {/* Marquee section - this is the main content */}
        <div className={styles.marqueeSection}>
          <SimpleMarquee
            className={styles.fullHeight}
            baseVelocity={25}
            repeat={4}
            easing={easeFn}
            direction="up"
          >
            {firstThird.map((src, i) => (
              <MarqueeItem key={i}>
                <img
                  src={src}
                  alt={`Image ${i + 1}`}
                  draggable={false}
                  className={styles.marqueeImage}
                />
              </MarqueeItem>
            ))}
          </SimpleMarquee>

          <SimpleMarquee
            className={styles.fullHeight}
            baseVelocity={25}
            repeat={4}
            easing={easeFn}
            direction="down"
          >
            {secondThird.map((src, i) => (
              <MarqueeItem key={i}>
                <img
                  src={src}
                  draggable={false}
                  alt={`Image ${i + firstThird.length}`}
                  className={styles.marqueeImage}
                />
              </MarqueeItem>
            ))}
          </SimpleMarquee>

          <SimpleMarquee
            className={styles.fullHeight}
            baseVelocity={25}
            repeat={4}
            easing={easeFn}
            direction="up"
          >
            {lastThird.map((src, i) => (
              <MarqueeItem key={i}>
                <img
                  src={src}
                  draggable={false}
                  alt={`Image ${i + firstThird.length + secondThird.length}`}
                  className={styles.marqueeImage}
                />
              </MarqueeItem>
            ))}
          </SimpleMarquee>
        </div>
      </div>
    </div>
  );
}
