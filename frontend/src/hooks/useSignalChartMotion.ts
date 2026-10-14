"use client";

import { useEffect, useRef, useState } from "react";

const ENTRY_MS = 450;
const UPDATE_MS = 250;
const GRID_MS = 200;
const STAG_MS = 50;
const EASE_OUT = "cubic-bezier(.22,1,.36,1)";
const OBSERVER_OPTIONS = { threshold: 0.2, rootMargin: "0px 0px -8% 0px" };

export function useSignalScoreEntrance(score: number | null) {
  const ref = useRef<HTMLDivElement | null>(null);
  const played = useRef(false);
  const [progress, setProgress] = useState(1);

  useEffect(() => {
    const element = ref.current;
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (
      !element ||
      score === null ||
      media?.matches ||
      typeof IntersectionObserver === "undefined"
    ) {
      setProgress(1);
      return;
    }
    let frame = 0;
    const play = (duration: number) => {
      played.current = true;
      const start = performance.now();
      setProgress(0);
      const step = (now: number) => {
        const elapsed = Math.min(1, Math.max(0, (now - start) / duration));
        setProgress(1 - Math.pow(1 - elapsed, 3));
        if (elapsed < 1) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    };
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      play(ENTRY_MS);
    }, OBSERVER_OPTIONS);
    if (played.current) play(UPDATE_MS);
    else observer.observe(element);
    const reduce = () => {
      if (!media?.matches) return;
      observer.disconnect();
      cancelAnimationFrame(frame);
      setProgress(1);
    };
    media?.addEventListener("change", reduce);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      media?.removeEventListener("change", reduce);
    };
  }, [score]);

  return { ref, progress };
}

export function useSignalBarEntrance(revision: string) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = ref.current;
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!element || media?.matches || typeof IntersectionObserver === "undefined") return;
    const animations: Animation[] = [];
    const observer = new IntersectionObserver((entries) => {
      entries
        .filter((entry) => entry.isIntersecting)
        .forEach((entry, index) => {
          observer.unobserve(entry.target);
          if (typeof entry.target.animate !== "function") return;
          animations.push(
            entry.target.animate([{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], {
              duration: ENTRY_MS,
              delay: index * 50,
              easing: "cubic-bezier(.22,1,.36,1)",
              fill: "backwards",
            })
          );
        });
    }, OBSERVER_OPTIONS);
    element.querySelectorAll("[data-signal-bar]").forEach((bar) => observer.observe(bar));
    const reduce = () => {
      if (!media?.matches) return;
      observer.disconnect();
      animations.forEach((animation) => animation.cancel());
    };
    media?.addEventListener("change", reduce);
    return () => {
      observer.disconnect();
      animations.forEach((animation) => animation.cancel());
      media?.removeEventListener("change", reduce);
    };
  }, [revision]);

  return ref;
}

/**
 * Generic MVP entry engine (signal-mvp-motion-spec §2). One IntersectionObserver
 * per container; descendants marked `data-signal-enter` play once in registration
 * order with `i * 50ms` stagger. Kinds:
 *  - "bar":       transform scaleX(0 -> 1), 450ms EASE_OUT        (`[data-w]`)
 *  - "ring":      stroke-dashoffset C -> final, 450ms EASE_OUT    (`.ring-fill`)
 *  - "path":      polyline/path draw via dashoffset, 450ms        (`.spark`)
 *  - "donut":     dasharray 0 C -> seg C, 450ms, staggered        (`.chan-donut`)
 *  - "sparkfill": opacity 0 -> 1, 200ms at delay 350 + stagger    (spark fill/dot)
 *  - "fade":      opacity 0 -> 1, 200ms at stagger                (grids/legends)
 *  - "count":     rAF count-up 450ms, format kept from
 *                 `data-signal-count` ("62" int, "4.8k" decimal+suffix)
 * `data-signal-delay="<ms>"` overrides the stagger delay for chart sequences.
 * With no IntersectionObserver / reduced motion nothing is prepared, so the
 * DOM keeps its finished state - final values are always the fallback.
 */
export function useSignalEntrance<T extends HTMLElement = HTMLDivElement>(revision: string) {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    const element = ref.current;
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!element || media?.matches || typeof IntersectionObserver === "undefined") return;
    const animations: Animation[] = [];
    const frames: number[] = [];

    const playCount = (target: HTMLElement) => {
      const spec = (target.getAttribute("data-signal-count") ?? target.textContent ?? "").trim();
      const match = spec.match(/^([\d.,]+)(.*)$/);
      if (!match) return;
      const raw = match[1].replace(/,/g, "");
      const final = Number.parseFloat(raw);
      if (!Number.isFinite(final)) return;
      const decimals = raw.includes(".") ? raw.split(".")[1].length : 0;
      const suffix = match[2] ?? "";
      const start = performance.now();
      const step = (now: number) => {
        const p = Math.min(1, Math.max(0, (now - start) / ENTRY_MS));
        const e = 1 - Math.pow(1 - p, 3);
        target.textContent = `${(final * e).toFixed(decimals)}${suffix}`;
        if (p < 1) frames.push(requestAnimationFrame(step));
      };
      frames.push(requestAnimationFrame(step));
    };

    const animate = (target: Element, index: number) => {
      const kind = target.getAttribute("data-signal-enter") ?? "bar";
      const explicitDelay = target.getAttribute("data-signal-delay");
      const delay = explicitDelay !== null ? Number.parseFloat(explicitDelay) : index * STAG_MS;
      if (kind === "count") {
        if (target instanceof HTMLElement) playCount(target);
        return;
      }
      if (typeof target.animate !== "function") return;
      if (kind === "path" || kind === "ring") {
        const geometry = target as SVGGeometryElement;
        if (typeof geometry.getTotalLength !== "function") return;
        const length = geometry.getTotalLength();
        const final =
          kind === "ring" ? Number.parseFloat(getComputedStyle(target).strokeDashoffset) || 0 : 0;
        if (kind === "path") {
          (target as SVGElement).style.strokeDasharray = `${length}`;
        }
        animations.push(
          target.animate([{ strokeDashoffset: length }, { strokeDashoffset: final }], {
            duration: ENTRY_MS,
            delay,
            easing: EASE_OUT,
            fill: "backwards",
          })
        );
        return;
      }
      if (kind === "donut") {
        const geometry = target as SVGGeometryElement;
        if (typeof geometry.getTotalLength !== "function") return;
        const length = geometry.getTotalLength();
        const computed = getComputedStyle(target).strokeDasharray;
        animations.push(
          target.animate([{ strokeDasharray: `0 ${length}` }, { strokeDasharray: computed }], {
            duration: ENTRY_MS,
            delay,
            easing: EASE_OUT,
            fill: "backwards",
          })
        );
        return;
      }
      if (kind === "sparkfill") {
        animations.push(
          target.animate([{ opacity: 0 }, { opacity: 1 }], {
            duration: GRID_MS,
            delay: explicitDelay !== null ? delay : ENTRY_MS - 100 + index * STAG_MS,
            easing: "ease",
            fill: "backwards",
          })
        );
        return;
      }
      if (kind === "fade") {
        animations.push(
          target.animate([{ opacity: 0 }, { opacity: 1 }], {
            duration: GRID_MS,
            delay,
            easing: "ease",
            fill: "backwards",
          })
        );
        return;
      }
      animations.push(
        target.animate([{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], {
          duration: ENTRY_MS,
          delay,
          easing: EASE_OUT,
          fill: "backwards",
        })
      );
    };

    const observer = new IntersectionObserver((entries) => {
      entries
        .filter((entry) => entry.isIntersecting)
        .forEach((entry, index) => {
          observer.unobserve(entry.target);
          animate(entry.target, index);
        });
    }, OBSERVER_OPTIONS);
    element.querySelectorAll("[data-signal-enter]").forEach((node) => observer.observe(node));

    const reduce = () => {
      if (!media?.matches) return;
      observer.disconnect();
      animations.forEach((animation) => animation.cancel());
      frames.forEach((frame) => cancelAnimationFrame(frame));
      element.querySelectorAll('[data-signal-enter="count"]').forEach((node) => {
        const spec = node.getAttribute("data-signal-count");
        if (spec !== null) node.textContent = spec;
      });
    };
    media?.addEventListener("change", reduce);
    return () => {
      observer.disconnect();
      animations.forEach((animation) => animation.cancel());
      frames.forEach((frame) => cancelAnimationFrame(frame));
      media?.removeEventListener("change", reduce);
    };
  }, [revision]);

  return ref;
}
