import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { motion } from 'motion/react';
import {
  SpeakerIcon,
  FolderIcon,
  HistoryIcon,
  MessageSquareIcon,
} from '../../components/ui/icons';
import ShinyText from '../../components/ui/ShinyText';

export type ChatTab = 'chat' | 'history' | 'projects';
export type OracleStatus = 'checking' | 'online' | 'offline';

const NARROW_VIEWPORT = 800;
const NARROW_QUERY = `(max-width: ${NARROW_VIEWPORT}px)`;
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

function isNarrowViewport(): boolean {
  if (typeof window === 'undefined') return false;
  if (typeof window.matchMedia !== 'function') {
    return window.innerWidth <= NARROW_VIEWPORT;
  }
  return window.matchMedia(NARROW_QUERY).matches;
}

export interface ChatShellProps {
  username: string;
  viewTab: ChatTab;
  onViewTabChange: (tab: ChatTab) => void;
  voiceOn: boolean;
  onVoiceToggle: () => void;
  onLogout: () => void;
  onNewConversation: () => void;
  oracleStatus: OracleStatus;
  children: ReactNode;
}

export default function ChatShell({
  username,
  viewTab,
  onViewTabChange,
  voiceOn,
  onVoiceToggle,
  onLogout,
  onNewConversation,
  oracleStatus,
  children,
}: ChatShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(
    () => typeof window === 'undefined' || window.innerWidth > NARROW_VIEWPORT
  );
  const [narrow, setNarrow] = useState(isNarrowViewport);
  const sidebarRef = useRef<HTMLElement | null>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  // The drawer only behaves modally on a narrow viewport; on desktop the sidebar
  // is part of the page and must not trap focus.
  const drawerModal = sidebarOpen && narrow;

  const closeSidebar = useCallback(() => {
    setSidebarOpen(false);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSidebarOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const narrowMedia = window.matchMedia(NARROW_QUERY);
    const onChange = (event: MediaQueryListEvent) => {
      setNarrow(event.matches);
      if (!event.matches) setSidebarOpen(false);
    };
    narrowMedia.addEventListener('change', onChange);
    return () => narrowMedia.removeEventListener('change', onChange);
  }, []);

  useEffect(() => {
    if (!drawerModal) return;
    const sidebar = sidebarRef.current;
    const toggle = toggleRef.current;
    if (!sidebar) return;
    // Move focus into the drawer and keep it there: a modal drawer that leaks
    // focus behind it is unusable with a screen reader or a keyboard.
    const first = sidebar.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const focusable = [...sidebar.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (focusable.length === 0) return;
      const firstItem = focusable[0];
      const lastItem = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (
        event.shiftKey &&
        (active === firstItem || !sidebar.contains(active))
      ) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && active === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    };
    sidebar.addEventListener('keydown', onKeyDown);
    return () => {
      sidebar.removeEventListener('keydown', onKeyDown);
      toggle?.focus();
    };
  }, [drawerModal]);

  const navigate = (tab: ChatTab) => {
    onViewTabChange(tab);
    if (narrow) setSidebarOpen(false);
  };

  return (
    <div className={`app-layout ${sidebarOpen ? 'sidebar-is-open' : ''}`}>
      {sidebarOpen && (
        <button
          type="button"
          className="sidebar-backdrop"
          // A redundant pointer target: it must not be a tab stop, and the
          // drawer's own Close control and Escape are the announced routes out.
          tabIndex={-1}
          aria-hidden="true"
          onClick={closeSidebar}
        />
      )}
      <aside
        className="sidebar"
        id="primary-navigation"
        ref={sidebarRef}
        {...(drawerModal ? { 'aria-modal': true, role: 'dialog' } : {})}
      >
        <div className="sidebar-header">
          <div className="brand-logo">
            <img src="/favicon.svg" alt="" width={24} height={24} />
          </div>
          <span className="brand-title">OTL Timesheet</span>
          <button
            type="button"
            className="sidebar-close"
            aria-label="Close navigation"
            onClick={closeSidebar}
          >
            Close
          </button>
        </div>
        <nav className="sidebar-nav" aria-label="Primary navigation">
          <div className="nav-group-title">Menu</div>
          {(['chat', 'projects', 'history'] as const).map((tab) => {
            const isActive = viewTab === tab;
            const label =
              tab === 'chat'
                ? 'Assistant'
                : tab === 'projects'
                  ? 'Projects'
                  : 'History';
            return (
              <button
                key={tab}
                className="nav-item"
                onClick={() => navigate(tab)}
                aria-label={`Navigate to ${label}`}
                aria-current={isActive ? 'page' : undefined}
              >
                {isActive && (
                  <motion.span
                    layoutId="active-nav-tab"
                    className="active-nav-background"
                    initial={false}
                    transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                  />
                )}
                <span className="nav-item-content">
                  {tab === 'chat' && <MessageSquareIcon size={16} />}
                  {tab === 'projects' && <FolderIcon size={16} />}
                  {tab === 'history' && <HistoryIcon size={16} />}
                  <span>{label}</span>
                </span>
              </button>
            );
          })}
          <button
            type="button"
            className="nav-item new-conversation-button"
            onClick={() => {
              onNewConversation();
              if (narrow) setSidebarOpen(false);
            }}
          >
            <span className="nav-item-content">
              <span>New conversation</span>
            </span>
          </button>
        </nav>
        <div className="sidebar-footer">
          <div className="nav-group-title">Settings</div>
          <button
            className="nav-item"
            onClick={onVoiceToggle}
            aria-label={
              voiceOn ? 'Disable voice responses' : 'Enable voice responses'
            }
            aria-pressed={voiceOn}
          >
            <span className="nav-item-content">
              <SpeakerIcon size={16} />
              <span>Voice</span>
            </span>
            <span className="voice-toggle" aria-hidden="true">
              <motion.span
                layout
                transition={{ type: 'spring', stiffness: 700, damping: 30 }}
                className={voiceOn ? 'on' : ''}
              />
            </span>
          </button>
          <div className="user-profile">
            <div className="avatar">{username.charAt(0).toUpperCase()}</div>
            <div className="user-info">
              <span className="user-name" title={username}>
                {username}
              </span>
              <button
                className="sign-out-btn"
                onClick={onLogout}
                aria-label="Sign out of your account"
              >
                Sign out
              </button>
            </div>
          </div>
        </div>
      </aside>
      <main
        className="workspace"
        style={{ position: 'relative' }}
        {...(drawerModal ? { inert: '' } : {})}
      >
        <header className="workspace-header">
          <div className="workspace-title-group">
            <button
              type="button"
              className="sidebar-toggle"
              aria-label="Open navigation"
              aria-controls="primary-navigation"
              aria-expanded={sidebarOpen}
              ref={toggleRef}
              onClick={() => setSidebarOpen((current) => !current)}
            >
              Menu
            </button>
            <h2>
              {viewTab === 'chat'
                ? 'Assistant'
                : viewTab === 'projects'
                  ? 'Project Assignments'
                  : 'Timecard History'}
            </h2>
          </div>
          <div className="workspace-header-meta">
            <span className="status-heartbeat">
              <span className="status-heartbeat-dot" />
              <ShinyText
                text={
                  oracleStatus === 'online'
                    ? 'Oracle Fusion Connected'
                    : oracleStatus === 'offline'
                      ? 'Oracle Fusion Unavailable'
                      : 'Checking Oracle Fusion'
                }
                disabled={false}
                speed={3}
                className="shiny-heartbeat"
              />
            </span>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
