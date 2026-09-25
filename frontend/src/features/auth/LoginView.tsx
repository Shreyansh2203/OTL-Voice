import { useState, type FormEvent } from 'react';
import { motion } from 'motion/react';
import * as api from '../../api/client';
import type { Identity } from '../../types';
import styles from './LoginView.module.css';

export default function LoginView({
  onLogin,
}: {
  onLogin: (identity: Identity) => void;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      onLogin(await api.login(username.trim(), password));
    } catch (submitError: unknown) {
      setError(
        submitError instanceof Error && submitError.message
          ? submitError.message
          : 'Sign-in failed.'
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={styles.container}>
      <div className={styles.innerLayout}>
        <section className={styles.fluffSection} aria-labelledby="login-heading">
          <div className={styles.brandMark} aria-hidden="true">
            <span>OTL</span>
          </div>
          <h1 className={styles.heading} id="login-heading">
            Welcome back
          </h1>
          <p className={styles.footerText}>
            Sign in with your employee credentials to review and approve your
            Oracle timecard entries.
          </p>
          <form className={styles.formContainer} onSubmit={submit}>
            <div className={styles.inputGroup}>
              <label htmlFor="person-number">Person number</label>
              <input
                id="person-number"
                type="text"
                inputMode="numeric"
                autoComplete="username"
                className={styles.input}
                placeholder="For example, 7"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
                autoFocus
              />
            </div>
            <div className={styles.inputGroup}>
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                className={styles.input}
                placeholder="Enter your password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>
            {error && (
              <div role="alert" className={styles.error} id="login-error">
                {error}
              </div>
            )}
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              className={styles.submitBtn}
              type="submit"
              disabled={busy}
              aria-describedby={error ? 'login-error' : undefined}
            >
              {busy ? 'Signing in…' : 'Sign in'}
            </motion.button>
            <p className={styles.securityNote}>
              Authentication uses a secure, HttpOnly session cookie. No access
              token is stored in this browser.
            </p>
          </form>
        </section>
        <section className={styles.artSection} aria-hidden="true">
          <div className={styles.artGlow} />
          <div className={`${styles.timeCard} ${styles.timeCardPrimary}`}>
            <span className={styles.cardLabel}>VOICE CAPTURE</span>
            <strong>“I worked four hours on Apollo testing.”</strong>
            <span className={styles.cardStatus}>Ready for review</span>
          </div>
          <div className={`${styles.timeCard} ${styles.timeCardSecondary}`}>
            <span className={styles.cardLabel}>REVIEW CHECK</span>
            <div className={styles.fieldLine}>Date <span>25 Sep 2026</span></div>
            <div className={styles.fieldLine}>Hours <span>4.0</span></div>
            <div className={styles.fieldLine}>Project <span>Apollo</span></div>
          </div>
          <div className={styles.artCaption}>
            <span>Speak naturally</span>
            <span>Review every field</span>
            <span>Approve once</span>
          </div>
        </section>
      </div>
    </main>
  );
}
