import axios from "axios";
import { TokenManager } from "@/utils/token-manager";

export interface AuthResponse {
  authenticated?: boolean;
  user?: UserProfile;
}

export interface UserProfile {
  id: string;
  email: string;
  name?: string;
  role: UserRole;
  permissions: string[];
  subscription_plan?: string;
  email_verified?: boolean;
  portal_only?: boolean;
  portal_workspace_id?: number | null;
  avatar_url?: string | null;
  auth_provider?: string | null;
}

export interface LoginCredentials {
  email: string;
  password: string;
  mfa_code?: string;
  remember_me?: boolean;
}

export interface RegisterPayload {
  name?: string;
  email: string;
  password: string;
  trial_token?: string;
}

export enum UserRole {
  USER = "user",
  ADMIN = "admin",
  MODERATOR = "moderator",
}

export type AuthServiceError = Error & {
  mfaRequired?: boolean;
  emailNotVerified?: boolean;
};

const normalizeErrorMessage = (value: string): string =>
  value.replace(/^value error,\s*/i, "").trim();

const collectErrorMessages = (value: unknown): string[] => {
  if (typeof value === "string") {
    const normalized = normalizeErrorMessage(value);
    return normalized ? [normalized] : [];
  }

  if (Array.isArray(value)) {
    return value.flatMap((entry) => collectErrorMessages(entry));
  }

  if (value && typeof value === "object") {
    const payload = value as Record<string, unknown>;
    return [
      ...collectErrorMessages(payload.msg),
      ...collectErrorMessages(payload.message),
      ...collectErrorMessages(payload.detail),
      ...collectErrorMessages(payload.error),
    ];
  }

  return [];
};

const extractApiErrorMessage = (error: unknown, fallback: string): string => {
  const payload = (
    error as { response?: { data?: { detail?: unknown; message?: unknown } } } | undefined
  )?.response?.data;
  const errorMessage = (error as { message?: unknown } | undefined)?.message;
  const candidates = [
    ...collectErrorMessages(payload?.detail),
    ...collectErrorMessages(payload?.message),
    ...collectErrorMessages(errorMessage),
  ];
  const uniqueMessages = Array.from(new Set(candidates));
  return uniqueMessages[0] || fallback;
};

const normalizeRole = (value: unknown): UserRole => {
  const normalized = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (normalized === UserRole.ADMIN) return UserRole.ADMIN;
  if (normalized === UserRole.MODERATOR) return UserRole.MODERATOR;
  return UserRole.USER;
};

const normalizePermissions = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : [];

const normalizeUserProfile = (value: unknown): UserProfile => {
  const payload = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  return {
    id: String(payload.id ?? ""),
    email: String(payload.email ?? ""),
    name: typeof payload.name === "string" ? payload.name : undefined,
    role: normalizeRole(payload.role),
    permissions: normalizePermissions(payload.permissions),
    subscription_plan:
      typeof payload.subscription_plan === "string" ? payload.subscription_plan : undefined,
    email_verified: typeof payload.email_verified === "boolean" ? payload.email_verified : true,
    portal_only: payload.portal_only === true,
    portal_workspace_id:
      typeof payload.portal_workspace_id === "number" ? payload.portal_workspace_id : null,
    avatar_url: typeof payload.avatar_url === "string" ? payload.avatar_url : null,
    auth_provider: typeof payload.auth_provider === "string" ? payload.auth_provider : null,
  };
};

export class AuthService {
  private static instance: AuthService;

  private constructor() {}

  static getInstance(): AuthService {
    if (!AuthService.instance) {
      AuthService.instance = new AuthService();
    }
    return AuthService.instance;
  }

  async register(payload: RegisterPayload): Promise<{ message: string }> {
    try {
      const response = await axios.post("/api/auth/register", payload);
      return { message: response.data?.message || "Registration successful" };
    } catch (error: unknown) {
      throw new Error(extractApiErrorMessage(error, "Registration failed"));
    }
  }

  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    try {
      const body = new URLSearchParams();
      body.set("username", credentials.email);
      body.set("password", credentials.password);
      body.set("remember_me", credentials.remember_me ? "true" : "false");
      if (credentials.mfa_code) {
        body.set("mfa_code", credentials.mfa_code);
      }

      const response = await axios.post("/api/auth/login", body, {
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        withCredentials: true,
      });

      if (response.data?.authenticated !== true) {
        throw new Error("Authenticated session was not established");
      }

      let user: UserProfile | undefined;
      try {
        user = await this.getCurrentUser();
      } catch {
        user = undefined;
      }

      return { authenticated: true, user };
    } catch (error: unknown) {
      const responseData = (
        error as { response?: { data?: { mfa_required?: boolean; detail?: unknown } } } | undefined
      )?.response?.data;
      const detailPayload =
        responseData?.detail && typeof responseData.detail === "object"
          ? (responseData.detail as Record<string, unknown>)
          : null;
      const message = extractApiErrorMessage(error, "Login failed");

      const authError: AuthServiceError = new Error(message);
      if (responseData?.mfa_required || detailPayload?.mfa_required === true) {
        authError.mfaRequired = true;
      }
      if (detailPayload?.code === "email_not_verified") {
        authError.emailNotVerified = true;
      }
      throw authError;
    }
  }

  async logout(): Promise<void> {
    try {
      await axios.post("/api/auth/logout", {}, { withCredentials: true });
    } catch {
      // Always clear local auth state even if logout endpoint fails.
    } finally {
      TokenManager.clearTokens();
      TokenManager.broadcastLogout();
    }
  }

  async getCurrentUser(): Promise<UserProfile> {
    try {
      const response = await axios.get("/api/auth/me", { withCredentials: true });
      return normalizeUserProfile(response.data);
    } catch (error: unknown) {
      throw new Error(extractApiErrorMessage(error, "Failed to get user profile"));
    }
  }

  async forgotPassword(email: string): Promise<void> {
    try {
      await axios.post("/api/auth/forgot-password", { email });
    } catch (error: unknown) {
      throw new Error(extractApiErrorMessage(error, "Failed to send reset email"));
    }
  }

  async resetPassword(token: string, newPassword: string): Promise<void> {
    try {
      await axios.post("/api/auth/reset-password", {
        token,
        password: newPassword,
      });
    } catch (error: unknown) {
      throw new Error(extractApiErrorMessage(error, "Password reset failed"));
    }
  }

  async verifyEmail(token: string): Promise<void> {
    try {
      await axios.post("/api/auth/verify-email", { token });
    } catch (error: unknown) {
      throw new Error(extractApiErrorMessage(error, "Email verification failed"));
    }
  }

  async resendVerificationEmail(email: string): Promise<void> {
    try {
      await axios.post("/api/auth/resend-verification", { email });
    } catch (error: unknown) {
      throw new Error(extractApiErrorMessage(error, "Failed to resend verification email"));
    }
  }
}

export default AuthService.getInstance();
