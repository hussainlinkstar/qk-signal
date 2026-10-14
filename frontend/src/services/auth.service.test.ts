import { beforeEach, describe, expect, it, vi } from "vitest";
import axios from "axios";

import { AuthService } from "./auth.service";
import { TokenManager } from "@/utils/token-manager";

vi.mock("axios", () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}));

describe("AuthService", () => {
  const service = AuthService.getInstance();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(TokenManager, "clearTokens").mockImplementation(() => undefined);
    vi.spyOn(TokenManager, "broadcastLogout").mockImplementation(() => undefined);
  });

  it("register succeeds with JSON payload", async () => {
    const successResponse = {
      message: "If this email is not already registered, a verification link has been sent.",
    };
    vi.mocked(axios.post).mockResolvedValueOnce({ data: successResponse });

    const result = await service.register({
      name: "User",
      email: "user@example.com",
      password: "Passw0rd!",
    });

    expect(axios.post).toHaveBeenCalledWith(expect.stringContaining("/auth/register"), {
      name: "User",
      email: "user@example.com",
      password: "Passw0rd!",
    });
    expect(result).toEqual({
      message: "If this email is not already registered, a verification link has been sent.",
    });
  });

  it("register surfaces backend failure", async () => {
    vi.mocked(axios.post).mockRejectedValueOnce({
      response: { data: { detail: "Email already registered" } },
    });

    await expect(
      service.register({ email: "user@example.com", password: "Passw0rd!" })
    ).rejects.toThrow("Email already registered");
  });

  it("register unwraps FastAPI validation errors instead of showing object payloads", async () => {
    vi.mocked(axios.post).mockRejectedValueOnce({
      response: {
        data: {
          detail: [
            {
              type: "value_error",
              loc: ["body", "password"],
              msg: "Value error, Password must contain at least one special character",
            },
          ],
        },
      },
    });

    await expect(
      service.register({ email: "user@example.com", password: "Passw0rd1" })
    ).rejects.toThrow("Password must contain at least one special character");
  });

  it("login sends x-www-form-urlencoded through the BFF and loads the cookie-backed user session", async () => {
    vi.mocked(axios.post).mockResolvedValueOnce({
      data: { authenticated: true },
    });
    vi.mocked(axios.get).mockResolvedValueOnce({
      data: { id: "1", email: "user@example.com", role: "user", permissions: [] },
    });

    const result = await service.login({
      email: "user@example.com",
      password: "Passw0rd!",
      remember_me: true,
    });

    expect(axios.post).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.any(URLSearchParams),
      expect.objectContaining({
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        withCredentials: true,
      })
    );
    const payload = vi.mocked(axios.post).mock.calls[0][1] as URLSearchParams;
    expect(payload.get("username")).toBe("user@example.com");
    expect(payload.get("password")).toBe("Passw0rd!");
    expect(payload.get("remember_me")).toBe("true");
    expect(vi.mocked(axios.get).mock.calls[0]).toEqual(["/api/auth/me", { withCredentials: true }]);
    expect(result).toEqual({
      authenticated: true,
      user: expect.objectContaining({ email: "user@example.com" }),
    });
  });

  it("login fails when the BFF does not establish an authenticated session", async () => {
    vi.mocked(axios.post).mockResolvedValueOnce({ data: { authenticated: false } });

    await expect(
      service.login({ email: "user@example.com", password: "Passw0rd!" })
    ).rejects.toThrow("Authenticated session was not established");
  });

  it("login failure throws normalized message", async () => {
    vi.mocked(axios.post).mockRejectedValueOnce({
      response: { data: { detail: "Incorrect email or password" } },
    });

    await expect(service.login({ email: "user@example.com", password: "wrong" })).rejects.toThrow(
      "Incorrect email or password"
    );
  });

  it("login marks MFA-required errors so UI can prompt for one-time code", async () => {
    vi.mocked(axios.post).mockRejectedValueOnce({
      response: { data: { detail: "MFA code required", mfa_required: true } },
    });

    await expect(
      service.login({ email: "user@example.com", password: "Passw0rd!" })
    ).rejects.toMatchObject({
      message: "MFA code required",
      mfaRequired: true,
    });
  });

  it("resetPassword unwraps structured backend errors", async () => {
    vi.mocked(axios.post).mockRejectedValueOnce({
      response: {
        data: {
          detail: {
            message: "Invalid or expired reset token",
          },
        },
      },
    });

    await expect(service.resetPassword("bad-token", "Passw0rd!")).rejects.toThrow(
      "Invalid or expired reset token"
    );
  });

  it("logout calls the BFF endpoint and clears local state", async () => {
    vi.mocked(axios.post).mockResolvedValueOnce({ data: {} });

    await service.logout();

    expect(axios.post).toHaveBeenCalledWith("/api/auth/logout", {}, { withCredentials: true });
    expect(TokenManager.clearTokens).toHaveBeenCalledTimes(1);
    expect(TokenManager.broadcastLogout).toHaveBeenCalledTimes(1);
  });

  it("logout still clears local state when the backend call fails", async () => {
    vi.mocked(axios.post).mockRejectedValueOnce(new Error("network down"));

    await service.logout();

    expect(TokenManager.clearTokens).toHaveBeenCalledTimes(1);
    expect(TokenManager.broadcastLogout).toHaveBeenCalledTimes(1);
  });
});
