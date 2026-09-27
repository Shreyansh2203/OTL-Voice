import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * WCAG 1.4.11 (non-text contrast) and 2.4.7 (focus visible) both require a focus
 * indicator at 3:1 against the colours next to it. The previous ring was
 * `--color-accent-soft` (#d6d9fc), which is 1.38:1 on white, so this asserts the
 * real numbers from the stylesheet rather than trusting a token's name.
 */

const candidates = [
  resolve(process.cwd(), 'src', 'index.css'),
  resolve(process.cwd(), 'frontend', 'src', 'index.css'),
];
const cssPath = candidates.find((candidate) => existsSync(candidate));
if (!cssPath) {
  throw new Error(`index.css not found; looked in ${candidates.join(', ')}`);
}
const css = readFileSync(cssPath, 'utf8');

const MINIMUM_FOCUS_CONTRAST = 3;

function token(name: string): string {
  const match = new RegExp(`${name}:\\s*([^;]+);`).exec(css);
  if (!match) throw new Error(`${name} is not defined in index.css`);
  return match[1].trim();
}

function hex(red: number, green: number, blue: number): number {
  const channel = (value: number) => {
    const scaled = value / 255;
    return scaled <= 0.03928
      ? scaled / 12.92
      : Math.pow((scaled + 0.055) / 1.055, 2.4);
  };
  return (
    0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)
  );
}

function luminance(colour: string): number {
  const value = colour.trim().replace('#', '');
  const full =
    value.length === 3
      ? value
          .split('')
          .map((character) => character + character)
          .join('')
      : value;
  if (!/^[0-9a-f]{6}$/i.test(full)) {
    throw new Error(`Expected a hex colour, received ${colour}`);
  }
  return hex(
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16)
  );
}

function contrast(first: string, second: string): number {
  const a = luminance(first);
  const b = luminance(second);
  const [light, dark] = a > b ? [a, b] : [b, a];
  return (light + 0.05) / (dark + 0.05);
}

/** Resolves the colours a box-shadow layer list paints, outermost last. */
function shadowLayers(declaration: string): string[] {
  return [...declaration.matchAll(/var\((--[a-z-]+)\)/g)].map((match) =>
    token(match[1])
  );
}

function ruleBody(selector: string): string {
  const index = css.indexOf(`${selector} {`);
  if (index === -1) throw new Error(`${selector} is not styled in index.css`);
  const start = css.indexOf('{', index) + 1;
  return css.slice(start, css.indexOf('}', start));
}

describe('focus indicator contrast', () => {
  const focusRing = shadowLayers(token('--shadow-focus'));
  const outer = focusRing[focusRing.length - 1];

  it.each([
    ['the page background', '--color-bg-primary'],
    ['the secondary surface', '--color-bg-secondary'],
    ['the tertiary surface', '--color-bg-tertiary'],
  ])('clears 3:1 against %s', (_label, surface) => {
    expect(contrast(outer, token(surface))).toBeGreaterThanOrEqual(
      MINIMUM_FOCUS_CONTRAST
    );
  });

  it('clears 3:1 against a control filled with the accent colour', () => {
    // Without the inner light layer the ring would vanish into a purple button.
    expect(focusRing.length).toBeGreaterThanOrEqual(2);
    const inner = focusRing[0];
    expect(
      contrast(inner, token('--color-accent-primary'))
    ).toBeGreaterThanOrEqual(MINIMUM_FOCUS_CONTRAST);
  });

  it('gives the approve button the same compliant ring', () => {
    const declaration = ruleBody('.btn-approve:focus-visible');
    expect(declaration).toContain('var(--shadow-focus)');
    expect(contrast(outer, token('--color-bg-primary'))).toBeGreaterThanOrEqual(
      MINIMUM_FOCUS_CONTRAST
    );
  });

  it('gives the hours input a borderless focus ring that is still visible', () => {
    const declaration = ruleBody('.review-field .hour-stepper input:focus');
    const layers = shadowLayers(declaration);
    expect(layers.length).toBeGreaterThan(0);
    layers.forEach((colour) => {
      expect(
        contrast(colour, token('--color-bg-primary'))
      ).toBeGreaterThanOrEqual(MINIMUM_FOCUS_CONTRAST);
    });
  });

  it('rejects the old low-contrast soft ring so it cannot come back', () => {
    expect(contrast(token('--color-accent-soft'), '#ffffff')).toBeLessThan(
      MINIMUM_FOCUS_CONTRAST
    );
  });
});

describe('visually hidden text helper', () => {
  it('keeps speaker labels available to assistive technology', () => {
    const body = ruleBody('.sr-only');
    expect(body).toContain('position: absolute');
    expect(body).toContain('overflow: hidden');
    expect(body).toMatch(/width:\s*1px/);
    expect(body).toMatch(/clip|clip-path/);
  });
});
