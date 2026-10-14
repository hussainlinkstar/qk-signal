import { describe, expect, it } from "vitest";

import manifest from "@/app/manifest";
import { BASE_PATH } from "@/lib/basePath";

describe("Signal manifest", () => {
  it("uses one base path for scope, start URL, and every icon", () => {
    const value = manifest();

    expect(value.name).toBe("Qiko Signal");
    expect(value.start_url).toBe(`${BASE_PATH}/dashboard`);
    expect(value.scope).toBe(`${BASE_PATH}/`);
    expect(value.icons).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ src: `${BASE_PATH}/icon-192.png` }),
        expect.objectContaining({ src: `${BASE_PATH}/icon-512.png` }),
        expect.objectContaining({ src: `${BASE_PATH}/icon.svg` }),
      ])
    );
    expect(JSON.parse(JSON.stringify(value))).toEqual(value);
  });
});
