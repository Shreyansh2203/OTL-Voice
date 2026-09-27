/**
 * `@testing-library/jest-dom@7.0.1` only augments the legacy single-parameter
 * `vitest.Assertion<T>` interface. Vitest 5 declares `Assertion<R, T>` with two
 * type parameters and introduced `interface Matchers<R, T>` as the supported
 * augmentation target, so jest-dom's declaration merge is silently dropped and
 * every DOM matcher (`toBeInTheDocument`, ...) disappears from `expect()`.
 *
 * Re-declaring the matchers against the Vitest 5 target restores the types.
 * Remove this file once jest-dom ships Vitest 5 support.
 */
import 'vitest';
import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers';

declare module 'vitest' {
  interface Matchers<
    R extends void | Promise<void> = void | Promise<void>,
    T = unknown,
  > extends TestingLibraryMatchers<any, R> {}

  interface AsymmetricMatchersContaining
    extends TestingLibraryMatchers<any, void> {}
}
