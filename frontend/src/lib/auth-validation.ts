import { z } from "zod";

const specialCharacterPattern = /[!@#$%^&*()_\-+=\[\]{};:'",.<>?/\\|`~]/;

export const passwordSchema = z
  .string()
  .min(8, "Password must be at least 8 characters")
  .regex(/[A-Z]/, "Must contain an uppercase letter")
  .regex(/[a-z]/, "Must contain a lowercase letter")
  .regex(/[0-9]/, "Must contain a number")
  .regex(specialCharacterPattern, "Must contain a special character");

export const PASSWORD_REQUIREMENTS = [
  {
    id: "min_length",
    label: "At least 8 characters",
    test: (value: string) => value.length >= 8,
  },
  {
    id: "uppercase",
    label: "Uppercase letter",
    test: (value: string) => /[A-Z]/.test(value),
  },
  {
    id: "lowercase",
    label: "Lowercase letter",
    test: (value: string) => /[a-z]/.test(value),
  },
  {
    id: "number",
    label: "Number",
    test: (value: string) => /[0-9]/.test(value),
  },
  {
    id: "special_character",
    label: "Special character",
    test: (value: string) => specialCharacterPattern.test(value),
  },
] as const;

export type PasswordRequirement = (typeof PASSWORD_REQUIREMENTS)[number];
export type PasswordStrength = "weak" | "fair" | "strong";

export function getPasswordStrength(password: string): PasswordStrength {
  const metRequirements = PASSWORD_REQUIREMENTS.filter((requirement) =>
    requirement.test(password)
  ).length;

  if (metRequirements >= 5) {
    return "strong";
  }
  if (metRequirements >= 3) {
    return "fair";
  }
  return "weak";
}
