import { act, render, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSignalEntrance, useSignalScoreEntrance } from "./useSignalChartMotion";

afterEach(() => vi.unstubAllGlobals());

describe("MVP score entrance", () => {
  it("keeps the final score when reduced motion is requested", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    const observer = vi.fn();
    vi.stubGlobal("IntersectionObserver", observer);
    const { result } = renderHook(() => useSignalScoreEntrance(61));
    expect(result.current.progress).toBe(1);
    expect(observer).not.toHaveBeenCalled();
  });

  it("uses the approved 450ms cubic ease-out without overshoot", () => {
    let intersect: IntersectionObserverCallback = () => {};
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("matchMedia", () => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: IntersectionObserverCallback) {
          intersect = callback;
        }
        observe() {}
        disconnect() {}
      }
    );
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      frames.push(callback);
      return frames.length;
    });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.spyOn(performance, "now").mockReturnValue(0);
    const target = document.createElement("div");
    const { result } = renderHook(() => {
      const motion = useSignalScoreEntrance(61);
      motion.ref.current = target;
      return motion;
    });
    act(() =>
      intersect(
        [{ isIntersecting: true, target } as IntersectionObserverEntry],
        {} as IntersectionObserver
      )
    );
    expect(result.current.progress).toBe(0);
    act(() => frames.shift()?.(225));
    expect(result.current.progress).toBe(0.875);
    act(() => frames.shift()?.(450));
    expect(result.current.progress).toBe(1);
    vi.restoreAllMocks();
  });
});

function stubMotionGlobals({ reduced = false } = {}) {
  let intersect: IntersectionObserverCallback = () => {};
  let observerInstance: {
    observe: (el: Element) => void;
    unobserve: (el: Element) => void;
    disconnect: () => void;
  } | null = null;
  const observed: Element[] = [];
  const frames: FrameRequestCallback[] = [];
  vi.stubGlobal("matchMedia", () => ({
    matches: reduced,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  vi.stubGlobal(
    "IntersectionObserver",
    class FakeIntersectionObserver {
      constructor(callback: IntersectionObserverCallback) {
        intersect = callback;
        observerInstance = this as unknown as typeof observerInstance;
      }
      observe(el: Element) {
        observed.push(el);
      }
      unobserve() {}
      disconnect() {}
    }
  );
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.push(callback);
    return frames.length;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  return {
    get intersect() {
      return intersect;
    },
    observed,
    frames,
    trigger(elements: Element[]) {
      intersect(
        elements.map((target) => ({ isIntersecting: true, target }) as IntersectionObserverEntry),
        observerInstance as unknown as IntersectionObserver
      );
    },
  };
}

describe("MVP generic entrance engine", () => {
  it("animates bars with scaleX over 450ms at a 50ms stagger", () => {
    const globals = stubMotionGlobals();
    const animate = vi.fn().mockReturnValue({ cancel: vi.fn() });
    function Bars() {
      const ref = useSignalEntrance("r1");
      return (
        <div ref={ref}>
          <span data-signal-enter="bar" />
          <span data-signal-enter="bar" />
        </div>
      );
    }
    const { container } = render(<Bars />);
    container.querySelectorAll("[data-signal-enter]").forEach((el) => {
      (el as HTMLElement).animate = animate;
    });
    const targets = Array.from(container.querySelectorAll("[data-signal-enter]"));
    act(() => globals.trigger(targets));
    expect(animate).toHaveBeenCalledTimes(2);
    const [firstFrames, firstOpts] = animate.mock.calls[0];
    expect(firstFrames).toEqual([{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }]);
    expect(firstOpts).toMatchObject({
      duration: 450,
      delay: 0,
      easing: "cubic-bezier(.22,1,.36,1)",
      fill: "backwards",
    });
    expect(animate.mock.calls[1][1]).toMatchObject({ delay: 50 });
  });

  it("counts up over 450ms preserving the markup's format", () => {
    const globals = stubMotionGlobals();
    function Counter() {
      const ref = useSignalEntrance("r2");
      return (
        <div ref={ref}>
          <b data-signal-enter="count" data-signal-count="4.8k">
            4.8k
          </b>
        </div>
      );
    }
    const { container } = render(<Counter />);
    const el = container.querySelector("[data-signal-count]") as HTMLElement;
    vi.spyOn(performance, "now").mockReturnValue(0);
    act(() => globals.trigger([el]));
    act(() => globals.frames.shift()?.(225));
    expect(el.textContent).toBe("4.2k"); // 4.8 * 0.875
    act(() => globals.frames.shift()?.(450));
    expect(el.textContent).toBe("4.8k");
    vi.restoreAllMocks();
  });

  it("draws sparkline paths via dashoffset and rings from full circumference", () => {
    const globals = stubMotionGlobals();
    const animate = vi.fn().mockReturnValue({ cancel: vi.fn() });
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    (path as unknown as SVGGeometryElement).getTotalLength = () => 200;
    (ring as unknown as SVGGeometryElement).getTotalLength = () => 300;
    path.animate = animate;
    ring.animate = animate;
    ring.style.strokeDashoffset = "90";
    function Svg() {
      const ref = useSignalEntrance<HTMLDivElement>("r3");
      return <div ref={ref} />;
    }
    const { container } = render(<Svg />);
    const host = container.firstChild as HTMLElement;
    path.setAttribute("data-signal-enter", "path");
    ring.setAttribute("data-signal-enter", "ring");
    host.append(path, ring);
    act(() => globals.trigger([path, ring]));
    // observed at mount happens before nodes are appended; trigger manually is enough
    const pathCall = animate.mock.calls.find((c) => c[0][0].strokeDashoffset === 200);
    expect(pathCall).toBeTruthy();
    const ringCall = animate.mock.calls.find((c) => c[0][0].strokeDashoffset === 300);
    expect(ringCall?.[0][1].strokeDashoffset).toBe(90);
  });

  it("renders final state immediately under reduced motion", () => {
    const globals = stubMotionGlobals({ reduced: true });
    function Bars() {
      const ref = useSignalEntrance("r4");
      return (
        <div ref={ref}>
          <span data-signal-enter="bar" />
        </div>
      );
    }
    render(<Bars />);
    expect(globals.observed).toHaveLength(0);
  });
});
