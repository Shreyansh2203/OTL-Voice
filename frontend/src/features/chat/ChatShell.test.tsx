import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ChatShell from "./ChatShell";

describe("ChatShell", () => {
  it("renders the shell and children in order", () => {
    const { container } = render(
      <ChatShell
        username="Ada"
        viewTab="chat"
        onViewTabChange={vi.fn()}
        voiceOn
        onVoiceToggle={vi.fn()}
        onLogout={vi.fn()}
        oracleStatus="online"
      >
        <div data-testid="content">Content</div>
      </ChatShell>
    );

    const layout = container.firstElementChild;
    expect(layout).toHaveClass("app-layout");
    expect(layout?.children[0]).toHaveClass("sidebar");
    expect(layout?.children[1]).toHaveClass("workspace");
    expect(screen.getByText("OTL Timesheet")).toBeInTheDocument();
    expect(screen.getByText("Oracle Fusion Connected")).toBeInTheDocument();
    expect(screen.getByTestId("content")).toBeInTheDocument();
  });

  it("forwards navigation, voice, and logout actions", () => {
    const onViewTabChange = vi.fn();
    const onVoiceToggle = vi.fn();
    const onLogout = vi.fn();
    render(
      <ChatShell
        username="Ada"
        viewTab="chat"
        onViewTabChange={onViewTabChange}
        voiceOn
        onVoiceToggle={onVoiceToggle}
        onLogout={onLogout}
        oracleStatus="checking"
      >
        <div>Content</div>
      </ChatShell>
    );

    fireEvent.click(screen.getByRole("button", { name: /Navigate to Project Assignments/i }));
    fireEvent.click(screen.getByRole("button", { name: /Disable voice responses/i }));
    fireEvent.click(screen.getByRole("button", { name: /Sign out of your account/i }));

    expect(onViewTabChange).toHaveBeenCalledWith("projects");
    expect(onVoiceToggle).toHaveBeenCalledTimes(1);
    expect(onLogout).toHaveBeenCalledTimes(1);
  });
});
