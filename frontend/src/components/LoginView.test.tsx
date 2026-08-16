import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import LoginView from "./LoginView";
import * as api from "../api/client";

vi.mock("../api/client", () => ({
  login: vi.fn(),
}));

describe("LoginView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders correctly", () => {
    render(<LoginView onLogin={vi.fn()} />);
    expect(screen.getByText("Sign in with your employee credentials.")).toBeInTheDocument();
  });

  it("submits the form successfully", async () => {
    const onLogin = vi.fn();
    const mockIdentity = { username: "12345", fullName: "Test User", employeeId: "12345" };
    vi.mocked(api.login).mockResolvedValue(mockIdentity);

    render(<LoginView onLogin={onLogin} />);
    
    const input = screen.getByPlaceholderText("e.g. 12345");
    fireEvent.change(input, { target: { value: "12345" } });
    
    const submitBtn = screen.getByRole("button", { name: "Sign in" });
    fireEvent.click(submitBtn);

    expect(api.login).toHaveBeenCalledWith("12345", "dummy-password");
    await waitFor(() => {
      expect(onLogin).toHaveBeenCalledWith(mockIdentity);
    });
  });

  it("displays error when login fails", async () => {
    const onLogin = vi.fn();
    vi.mocked(api.login).mockRejectedValue(new Error("Invalid credentials"));

    render(<LoginView onLogin={onLogin} />);
    
    const input = screen.getByPlaceholderText("e.g. 12345");
    fireEvent.change(input, { target: { value: "wrong" } });
    
    const submitBtn = screen.getByRole("button", { name: "Sign in" });
    fireEvent.click(submitBtn);

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
    expect(onLogin).not.toHaveBeenCalled();
  });

  it("displays generic error for unknown errors", async () => {
    const onLogin = vi.fn();
    vi.mocked(api.login).mockRejectedValue("some weird error");

    render(<LoginView onLogin={onLogin} />);
    
    const input = screen.getByPlaceholderText("e.g. 12345");
    fireEvent.change(input, { target: { value: "wrong" } });
    
    const submitBtn = screen.getByRole("button", { name: "Sign in" });
    fireEvent.click(submitBtn);

    expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in failed.");
  });
});
