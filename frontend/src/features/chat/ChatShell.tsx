import type { ReactNode } from "react";
import { motion } from "motion/react";
import {
  SpeakerIcon,
  FolderIcon,
  HistoryIcon,
  MessageSquareIcon,
} from "../../components/ui/icons";
import ShinyText from "../../components/ui/ShinyText";

export type ChatTab = "chat" | "history" | "projects";
export type OracleStatus = "checking" | "online" | "offline";

export interface ChatShellProps {
  username: string;
  viewTab: ChatTab;
  onViewTabChange: (tab: ChatTab) => void;
  voiceOn: boolean;
  onVoiceToggle: () => void;
  onLogout: () => void;
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
  oracleStatus,
  children,
}: ChatShellProps) {
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="brand-logo">
            <img src="/favicon.svg" alt="" width={24} height={24} />
          </div>
          <span className="brand-title">OTL Timesheet</span>
        </div>
        <nav className="sidebar-nav">
          <div className="nav-group-title">Menu</div>
          {(["chat", "projects", "history"] as const).map((tab) => {
            const isActive = viewTab === tab;
            return (
              <button
                key={tab}
                className="nav-item"
                onClick={() => onViewTabChange(tab)}
                aria-label={`Navigate to ${tab === "chat" ? "Assistant chat" : tab === "projects" ? "Project Assignments" : "Timecard History"}`}
                aria-current={isActive ? "page" : undefined}
                style={{
                  position: "relative",
                  color: isActive ? "#ffffff" : undefined,
                  border: "1px solid transparent",
                  background: "transparent",
                }}
              >
                {isActive && (
                  <motion.div
                    layoutId="active-nav-tab"
                    initial={false}
                    transition={{ type: "spring", stiffness: 500, damping: 30 }}
                    style={{
                      position: "absolute",
                      inset: 0,
                      background: "rgba(83, 58, 253, 0.16)",
                      borderRadius: "8px",
                      border: "1px solid rgba(83, 58, 253, 0.35)",
                      boxShadow: "0 1px 2px 0 rgba(0, 0, 0, 0.1)",
                      zIndex: 0,
                    }}
                  />
                )}
                <span style={{ position: "relative", zIndex: 1, display: "flex", alignItems: "center", gap: "10px" }}>
                  {tab === "chat" && <MessageSquareIcon size={16} />}
                  {tab === "projects" && <FolderIcon size={16} />}
                  {tab === "history" && <HistoryIcon size={16} />}
                  <span>{tab === "chat" ? "Assistant" : tab === "projects" ? "Projects" : "History"}</span>
                </span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <div className="nav-group-title">Settings</div>
          <button
            className="nav-item"
            style={{ display: "flex", justifyContent: "space-between", width: "100%" }}
            onClick={onVoiceToggle}
            aria-label={voiceOn ? "Disable voice responses" : "Enable voice responses"}
            aria-pressed={voiceOn}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <SpeakerIcon size={16} />
              <span>Voice</span>
            </div>
            <div
              style={{
                width: "32px",
                height: "18px",
                borderRadius: "999px",
                background: voiceOn ? "var(--color-accent-primary)" : "rgba(255, 255, 255, 0.2)",
                display: "flex",
                alignItems: "center",
                padding: "2px",
                cursor: "pointer",
                transition: "background 0.2s",
              }}
            >
              <motion.div
                layout
                transition={{ type: "spring", stiffness: 700, damping: 30 }}
                style={{
                  width: "14px",
                  height: "14px",
                  borderRadius: "50%",
                  background: "#fff",
                  boxShadow: "0 1px 2px rgba(0,0,0,0.1)",
                  marginLeft: voiceOn ? "14px" : "0px",
                }}
              />
            </div>
          </button>
          <div className="user-profile">
            <div className="avatar">{username.charAt(0).toUpperCase()}</div>
            <div className="user-info">
              <span className="user-name" title={username}>
                {username}
              </span>
              <button className="sign-out-btn" onClick={onLogout} aria-label="Sign out of your account">
                Sign out
              </button>
            </div>
          </div>
        </div>
      </aside>
      <main className="workspace" style={{ position: "relative" }}>
        <header
          className="workspace-header"
          style={{
            zIndex: 1,
            position: "relative",
            background: "rgba(18, 15, 23, 0.65)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.1)",
          }}
        >
          <h2 style={{ color: "white" }}>
            {viewTab === "chat"
              ? "Assistant"
              : viewTab === "projects"
                ? "Project Assignments"
                : "Timecard History"}
          </h2>
          <div
            className="workspace-header-meta"
            style={{ color: "rgba(255, 255, 255, 0.7)" }}
          >
            <span className="status-heartbeat">
              <span className="status-heartbeat-dot" />
              <ShinyText
                text={
                  oracleStatus === "online"
                    ? "Oracle Fusion Connected"
                    : oracleStatus === "offline"
                      ? "Oracle Fusion Unavailable"
                      : "Checking Oracle Fusion"
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
