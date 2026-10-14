import en from "@/i18n/en.json";

const lookup = (key: string): unknown =>
  key.split(".").reduce<unknown>((acc, part) => {
    if (acc && typeof acc === "object") {
      return (acc as Record<string, unknown>)[part];
    }
    return undefined;
  }, en);

export const tEn = (key: string, options?: Record<string, unknown>): string => {
  let value = lookup(key);
  if (value === undefined && options && typeof options.count === "number") {
    value = lookup(`${key}_${options.count === 1 ? "one" : "other"}`);
  }
  if (typeof value !== "string") return key;
  return value.replace(/\{\{(\w+)\}\}/g, (raw, name: string) =>
    options && name in options ? String(options[name]) : raw
  );
};
