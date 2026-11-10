/**
 * Scroll and motion choreography for the marketing page: smooth scrolling (Lenis) driving GSAP ScrollTrigger.
 * Everything is declared with data attributes in the markup and wired here once:
 *   data-loader            intro counter screen          data-intro="header|fade"   hero entrance
 *   data-reveal="words"    words rise out of a mask      data-reveal="fade"         fade + lift on enter
 *   data-scrub="words"     words light up with scroll    data-speed="1.15"          parallax depth
 *   data-marquee[="rev"]   endless row, speeds up with scroll velocity
 *   data-pixels            block transition between a dark and a light section
 *   data-tone="dark|light" header colour while the section is under it
 *   data-magnetic          element leans toward the pointer
 */
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";
import { motionState } from "./state";

let lenis: Lenis | null = null;
export const scroller = {
  stop: () => lenis?.stop(),
  start: () => lenis?.start(),
};

export function setupLanding(root: HTMLElement, reduce: boolean): () => void {
  gsap.registerPlugin(ScrollTrigger);
  const html = document.documentElement;
  const w = window as unknown as { __lxReady?: boolean };
  w.__lxReady = true;
  // Arrived by client-side navigation (the inline boot script did not run): no intro screen.
  if (!html.classList.contains("lx-js")) html.classList.add("lx-js", "lx-seen");
  const cleanups: (() => void)[] = [];
  const fine = window.matchMedia("(pointer: fine)").matches;

  if (!reduce) {
    lenis = new Lenis({ lerp: 0.09, smoothWheel: true });
    lenis.on("scroll", ScrollTrigger.update);
    const tick = (time: number) => lenis?.raf(time * 1000);
    gsap.ticker.add(tick);
    // Default lag smoothing stays on: while the 3D scene compiles, timelines (the intro counter) must not jump ahead.
    cleanups.push(() => {
      gsap.ticker.remove(tick);
      lenis?.destroy();
      lenis = null;
    });
  }

  // In-page links scroll smoothly.
  const onClick = (e: MouseEvent) => {
    const a = (e.target as HTMLElement).closest<HTMLAnchorElement>('a[href^="#"]');
    const id = a?.getAttribute("href");
    if (!a || !id || id.length < 2) return;
    const target = root.querySelector<HTMLElement>(id);
    if (!target) return;
    e.preventDefault();
    if (lenis) {
      lenis.start();
      lenis.scrollTo(target, { offset: 0, duration: 1.5 });
    } else target.scrollIntoView();
  };
  root.addEventListener("click", onClick);
  cleanups.push(() => root.removeEventListener("click", onClick));

  const ctx = gsap.context(() => {
    const q = <T extends Element = HTMLElement>(sel: string) => gsap.utils.toArray<T>(sel, root);
    const header = root.querySelector<HTMLElement>("[data-header]");

    // Header colour follows the section beneath it (works with reduced motion too).
    q("[data-tone]").forEach((sec) => {
      ScrollTrigger.create({
        trigger: sec, start: "top 40px", end: "bottom 40px",
        onToggle: (self) => { if (self.isActive && header) header.dataset.tone = sec.dataset.tone; },
      });
    });

    const hero = root.querySelector<HTMLElement>("[data-hero]");
    if (hero) {
      ScrollTrigger.create({ trigger: hero, start: "top top", end: "bottom top", onUpdate: (s) => { motionState.hero = s.progress; } });
    }

    if (reduce) {
      motionState.introAt = performance.now() - 10_000;
      return;
    }

    // (The hidden starting transforms come from CSS; y: 0 stops GSAP from keeping them as a pixel offset.)
    // ---- hero entrance ------------------------------------------------------------------------
    const intro = gsap.timeline({ paused: true, onStart: () => { motionState.introAt = performance.now(); } });
    intro
      .fromTo("[data-intro='header']", { yPercent: -140, y: 0 }, { yPercent: 0, y: 0, duration: 1.1, ease: "expo.out" }, 0.1)
      .fromTo("[data-hero-title] .lx-wi", { yPercent: 118, y: 0 }, { yPercent: 0, y: 0, duration: 1.25, ease: "expo.out", stagger: 0.05 }, 0.05)
      .fromTo("[data-intro='fade']", { y: 26, autoAlpha: 0 }, { y: 0, autoAlpha: 1, duration: 1, ease: "power3.out", stagger: 0.08 }, 0.45)
      .fromTo("[data-scribble='hero'] path", { strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: 1.7, ease: "power2.inOut" }, 0.7);

    const loader = root.querySelector<HTMLElement>("[data-loader]");
    if (loader && !html.classList.contains("lx-seen")) {
      lenis?.stop();
      const count = loader.querySelector<HTMLElement>("[data-count]");
      const n = { v: 0 };
      gsap.timeline({
        onComplete: () => {
          try { sessionStorage.setItem("lx-seen", "1"); } catch { /* private mode */ }
          html.classList.add("lx-seen");
          lenis?.start();
        },
      })
        .to(n, { v: 100, duration: 1.6, ease: "power2.inOut", onUpdate: () => { if (count) count.textContent = String(Math.round(n.v)).padStart(3, "0"); } })
        .fromTo("[data-bar]", { scaleX: 0 }, { scaleX: 1, duration: 1.6, ease: "power2.inOut" }, 0)
        .to("[data-loader-inner]", { yPercent: -40, autoAlpha: 0, duration: 0.55, ease: "power3.in" })
        .to(loader, { clipPath: "inset(0% 0% 100% 0%)", duration: 0.95, ease: "expo.inOut" }, "-=0.15")
        .add(() => { intro.play(); }, "-=0.6");
    } else {
      intro.play();
    }

    // Hero content drifts up and fades as you leave it.
    if (hero) {
      gsap.to("[data-hero-content]", { yPercent: -14, autoAlpha: 0.15, ease: "none", scrollTrigger: { trigger: hero, start: "top top", end: "bottom top", scrub: true } });
    }

    // ---- reveals ------------------------------------------------------------------------------
    q("[data-reveal='words']").forEach((el) => {
      if (el.closest("[data-hero]")) return;
      gsap.fromTo(el.querySelectorAll(".lx-wi"), { yPercent: 118, y: 0 }, {
        yPercent: 0, y: 0, duration: 1.15, ease: "expo.out", stagger: 0.05,
        scrollTrigger: { trigger: el, start: "top 88%", once: true },
      });
    });
    ScrollTrigger.batch(q("[data-reveal='fade']"), {
      start: "top 90%", once: true,
      onEnter: (els) => gsap.fromTo(els, { y: 44, autoAlpha: 0 }, { y: 0, autoAlpha: 1, duration: 1.1, ease: "power3.out", stagger: 0.09, overwrite: true }),
    });
    q("[data-scribble='line'] path").forEach((p) => {
      gsap.fromTo(p, { strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: 1.4, ease: "power2.inOut", scrollTrigger: { trigger: p, start: "top 85%", once: true } });
    });

    // ---- parallax depth -----------------------------------------------------------------------
    q("[data-speed]").forEach((el) => {
      const s = parseFloat(el.dataset.speed || "1");
      const d = (s - 1) * 420;
      gsap.fromTo(el, { y: d }, { y: -d, ease: "none", scrollTrigger: { trigger: el, start: "top bottom", end: "bottom top", scrub: true } });
    });

    // ---- manifesto: words light up --------------------------------------------------------------
    q("[data-scrub='words']").forEach((el) => {
      gsap.fromTo(el.querySelectorAll(".lx-sw"), { opacity: 0.13 }, {
        opacity: 1, ease: "none", stagger: 0.12,
        scrollTrigger: { trigger: el, start: "top 78%", end: "bottom 42%", scrub: true },
      });
    });

    // ---- block transition dark → light -------------------------------------------------------
    q("[data-pixels]").forEach((band) => {
      gsap.timeline({ scrollTrigger: { trigger: band, start: "top 92%", end: "bottom 40%", scrub: true } })
        .fromTo(band.querySelectorAll(".lx-px-a"), { scaleY: 0 }, { scaleY: 1, ease: "none", duration: 0.3, stagger: { amount: 0.55, from: "random" } }, 0)
        .fromTo(band.querySelectorAll(".lx-px-b"), { scaleY: 0 }, { scaleY: 1, ease: "none", duration: 0.3, stagger: { amount: 0.55, from: "random" } }, 0.3);
    });

    // ---- footer panel grows into place -------------------------------------------------------
    q("[data-grow]").forEach((el) => {
      gsap.fromTo(el, { scale: 0.92, y: 60 }, { scale: 1, y: 0, ease: "none", scrollTrigger: { trigger: el, start: "top bottom", end: "top 35%", scrub: true } });
    });

    // ---- marquees: endless, faster (and reversed) with scroll velocity ------------------------
    const rows = q("[data-marquee]").map((row) => {
      const track = row.querySelector(".lx-mq-track");
      const rev = row.dataset.marquee === "rev";
      return gsap.fromTo(track, { xPercent: rev ? -50 : 0 }, { xPercent: rev ? 0 : -50, duration: Number(row.dataset.duration || 38), ease: "none", repeat: -1 });
    });
    if (rows.length) {
      let boost = 0;
      let dir = 1;
      ScrollTrigger.create({
        trigger: root, start: "top top", end: "bottom bottom",
        onUpdate: (self) => {
          dir = self.direction;
          boost = Math.min(5, Math.abs(self.getVelocity()) / 450);
        },
      });
      const tick = () => {
        boost *= 0.93;
        rows.forEach((tw) => tw.timeScale(dir * (1 + boost)));
      };
      gsap.ticker.add(tick);
      cleanups.push(() => gsap.ticker.remove(tick));
    }

    // ---- magnetic buttons ---------------------------------------------------------------------
    if (fine) {
      q("[data-magnetic]").forEach((el) => {
        const xTo = gsap.quickTo(el, "x", { duration: 0.5, ease: "power3" });
        const yTo = gsap.quickTo(el, "y", { duration: 0.5, ease: "power3" });
        const move = (e: PointerEvent) => {
          const r = el.getBoundingClientRect();
          xTo((e.clientX - (r.left + r.width / 2)) * 0.3);
          yTo((e.clientY - (r.top + r.height / 2)) * 0.4);
        };
        const leave = () => {
          gsap.to(el, { x: 0, y: 0, duration: 1, ease: "elastic.out(1, 0.35)" });
        };
        el.addEventListener("pointermove", move);
        el.addEventListener("pointerleave", leave);
        cleanups.push(() => {
          el.removeEventListener("pointermove", move);
          el.removeEventListener("pointerleave", leave);
        });
      });
    }
  }, root);

  // Layout changes (fonts, prices arriving from the API) move every trigger: re-measure.
  let pending = 0;
  const ro = new ResizeObserver(() => {
    cancelAnimationFrame(pending);
    pending = requestAnimationFrame(() => ScrollTrigger.refresh());
  });
  ro.observe(root);
  document.fonts?.ready.then(() => ScrollTrigger.refresh());

  return () => {
    ro.disconnect();
    cancelAnimationFrame(pending);
    ctx.revert();
    cleanups.forEach((f) => f());
    motionState.hero = 0;
    motionState.introAt = -1;
    html.classList.remove("lx-js", "lx-seen");
    w.__lxReady = false;
  };
}
