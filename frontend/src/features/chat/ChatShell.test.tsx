import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ChatShell from './ChatShell';

function setViewportWidth(width: number): void {
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    writable: true,
    value: width,
  });
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => {
      const min = /\(min-width:\s*(\d+)px\)/.exec(query);
      const max = /\(max-width:\s*(\d+)px\)/.exec(query);
      const matches = min
        ? width >= Number(min[1])
        : max
          ? width <= Number(max[1])
          : false;
      return {
        matches,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      } as unknown as MediaQueryList;
    },
  });
}

function renderShell() {
  return render(
    <ChatShell
      username="Ada"
      viewTab="chat"
      onViewTabChange={vi.fn()}
      voiceOn
      onVoiceToggle={vi.fn()}
      onLogout={vi.fn()}
      onNewConversation={vi.fn()}
      oracleStatus="online"
    >
      <div>Content</div>
    </ChatShell>
  );
}

describe('ChatShell', () => {
  afterEach(() => {
    setViewportWidth(1280);
  });

  it('renders the shell and children in order', () => {
    setViewportWidth(1280);
    const { container } = renderShell();

    const layout = container.firstElementChild;
    expect(layout).toHaveClass('app-layout');
    expect(container.querySelector('.sidebar')).toBeInTheDocument();
    expect(container.querySelector('.workspace')).toBeInTheDocument();
    expect(screen.getByText('OTL Timesheet')).toBeInTheDocument();
    expect(screen.getByText('Oracle Fusion Connected')).toBeInTheDocument();
    expect(screen.getByText('Content')).toBeInTheDocument();
  });

  it('forwards navigation, voice, and logout actions', () => {
    setViewportWidth(1280);
    const onViewTabChange = vi.fn();
    const onVoiceToggle = vi.fn();
    const onLogout = vi.fn();
    const onNewConversation = vi.fn();
    render(
      <ChatShell
        username="Ada"
        viewTab="chat"
        onViewTabChange={onViewTabChange}
        voiceOn
        onVoiceToggle={onVoiceToggle}
        onLogout={onLogout}
        onNewConversation={onNewConversation}
        oracleStatus="checking"
      >
        <div>Content</div>
      </ChatShell>
    );

    fireEvent.click(
      screen.getByRole('button', { name: /Navigate to Projects/i })
    );
    fireEvent.click(
      screen.getByRole('button', { name: /Disable voice responses/i })
    );
    fireEvent.click(screen.getByRole('button', { name: /New conversation/i }));
    fireEvent.click(
      screen.getByRole('button', { name: /Sign out of your account/i })
    );

    expect(onViewTabChange).toHaveBeenCalledWith('projects');
    expect(onVoiceToggle).toHaveBeenCalledTimes(1);
    expect(onNewConversation).toHaveBeenCalledTimes(1);
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it('keeps the full-viewport backdrop out of the tab order', () => {
    setViewportWidth(390);
    const { container } = renderShell();
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));

    const backdrop = container.querySelector('.sidebar-backdrop');
    expect(backdrop).toHaveAttribute('tabindex', '-1');
    expect(backdrop).toHaveAttribute('aria-hidden', 'true');
    // The drawer's own Close control is the keyboard route out.
    expect(
      container.querySelectorAll('#primary-navigation [tabindex="-1"]')
    ).toHaveLength(0);
    expect(
      screen.getByRole('button', { name: 'Close navigation' })
    ).toBeInTheDocument();
  });

  it('moves focus into a modal drawer and restores it on close', () => {
    setViewportWidth(390);
    const { container } = renderShell();
    const toggle = screen.getByRole('button', { name: 'Open navigation' });

    fireEvent.click(toggle);

    const drawer = container.querySelector('#primary-navigation')!;
    expect(drawer).toHaveAttribute('role', 'dialog');
    expect(drawer).toHaveAttribute('aria-modal', 'true');
    expect(drawer.contains(document.activeElement)).toBe(true);
    expect(container.querySelector('.workspace')).toHaveAttribute('inert');

    fireEvent.click(screen.getByRole('button', { name: 'Close navigation' }));

    expect(document.activeElement).toBe(toggle);
    expect(container.querySelector('#primary-navigation')).not.toHaveAttribute(
      'aria-modal'
    );
  });

  it('wraps Tab around inside the modal drawer', () => {
    setViewportWidth(390);
    const { container } = renderShell();
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    const drawer = container.querySelector('#primary-navigation')!;
    const focusable = [
      ...drawer.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ),
    ];
    expect(focusable.length).toBeGreaterThan(2);

    focusable[focusable.length - 1].focus();
    fireEvent.keyDown(drawer, { key: 'Tab' });
    expect(document.activeElement).toBe(focusable[0]);

    fireEvent.keyDown(drawer, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(focusable[focusable.length - 1]);
  });

  it('leaves the desktop sidebar untrapped and part of the page', () => {
    setViewportWidth(1280);
    const { container } = renderShell();

    const drawer = container.querySelector('#primary-navigation')!;
    expect(drawer).not.toHaveAttribute('role', 'dialog');
    expect(container.querySelector('.workspace')).not.toHaveAttribute('inert');
  });
});
