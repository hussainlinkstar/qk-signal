import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup, configure } from "@testing-library/react";
import * as React from "react";

// findBy* and waitFor give up after 1s by default, well before the test's own
// budget. Under parallel load an element can legitimately take longer than that
// to appear, which showed up as "unable to find" in whichever file happened to
// be unlucky. See the note in vitest.config.ts.
configure({ asyncUtilTimeout: 5_000 });

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const TEST_CHART_WIDTH = 800;
const TEST_CHART_HEIGHT = 320;

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");

  return {
    ...actual,
    ResponsiveContainer: ({
      children,
      width,
      height,
      minWidth,
      minHeight,
    }: {
      children?: React.ReactNode;
      width?: number | string;
      height?: number | string;
      minWidth?: number | string;
      minHeight?: number | string;
    }) => {
      const resolvedWidth = typeof width === "number" ? width : TEST_CHART_WIDTH;
      const resolvedHeight = typeof height === "number" ? height : TEST_CHART_HEIGHT;
      const containerStyle = {
        width: typeof width === "number" ? `${width}px` : (width ?? `${resolvedWidth}px`),
        height: typeof height === "number" ? `${height}px` : (height ?? `${resolvedHeight}px`),
        minWidth: typeof minWidth === "number" ? `${minWidth}px` : minWidth,
        minHeight: typeof minHeight === "number" ? `${minHeight}px` : minHeight,
      };

      const child = React.isValidElement(children)
        ? React.cloneElement(children as React.ReactElement<Record<string, unknown>>, {
            width: resolvedWidth,
            height: resolvedHeight,
          })
        : children;

      return React.createElement(
        "div",
        { style: containerStyle, "data-testid": "recharts-responsive-container" },
        child
      );
    },
  };
});

vi.stubGlobal("ResizeObserver", ResizeObserverMock);

// jsdom has no layout engine, so `scrollIntoView` is absent. cmdk (the shell
// command palette) calls it on every selection change.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

/**
 * Node 24 added a native `localStorage` global that is `undefined` unless the
 * process is started with `--localstorage-file`. On Node 26 it shadows the one
 * jsdom installs, so `window.localStorage.setItem(...)` throws
 * "Cannot read properties of undefined" in any component that persists state.
 * That was the single largest cause of failures in this suite.
 *
 * An in-memory implementation is installed on both `globalThis` and `window`,
 * and cleared between tests so nothing leaks from one test into the next.
 */
class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

const localStorageMock = new MemoryStorage();
const sessionStorageMock = new MemoryStorage();

const installStorage = (key: "localStorage" | "sessionStorage", value: Storage) => {
  vi.stubGlobal(key, value);
  if (typeof window !== "undefined") {
    Object.defineProperty(window, key, { value, configurable: true, writable: true });
  }
};

installStorage("localStorage", localStorageMock);
installStorage("sessionStorage", sessionStorageMock);

afterEach(() => {
  cleanup();
  localStorageMock.clear();
  sessionStorageMock.clear();
});
