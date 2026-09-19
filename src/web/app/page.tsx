"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  motion,
  AnimatePresence,
  useScroll,
  useTransform,
  useMotionValue,
  useMotionTemplate,
  useMotionValueEvent,
  useInView,
  animate,
  type Variants,
} from "framer-motion";

/* ------------------------------------------------------------------ */
/*  Data                                                               */
/* ------------------------------------------------------------------ */

const NAV_LINKS = [
  { label: "Features", href: "#features" },
  { label: "How it works", href: "#how" },
  { label: "Showcase", href: "#showcase" },
  { label: "Testimonials", href: "#testimonials" },
];

const LOGOS = [
  "Nimbus",
  "Vector Labs",
  "Hyperloop",
  "Ferrous",
  "Octane",
  "Moonbase",
  "Parallax",
  "Statler",
];

type Line = { t: "text" | "edit" | "ok" | "dim"; v: string };

const TERMINAL_SCREENS: { cmd: string; out: Line[] }[] = [
  {
    cmd: 'jimmy "fix the flaky auth test"',
    out: [
      { t: "dim", v: "✻ Reading codebase … 42 files indexed" },
      { t: "text", v: "✻ Found race condition in auth/session.ts" },
      { t: "edit", v: "M  src/auth/session.ts" },
      { t: "edit", v: "M  src/auth/session.test.ts" },
      { t: "ok", v: "✔ 2 files changed · tests passing · 1.8s" },
    ],
  },
  {
    cmd: "jimmy plan 'migrate billing to usage-based'",
    out: [
      { t: "dim", v: "✻ Analyzing 118 files · 3 services affected" },
      { t: "text", v: "  1. Add usage_meter table + backfill job" },
      { t: "text", v: "  2. Swap Stripe webhook to metered events" },
      { t: "text", v: "  3. Feature-flag rollout with shadow mode" },
      { t: "ok", v: "✔ Plan ready — approve to start coding" },
    ],
  },
  {
    cmd: "jimmy ship",
    out: [
      { t: "dim", v: "✻ Running lint · typecheck · tests" },
      { t: "text", v: "✻ Writing conventional commit …" },
      { t: "text", v: "✻ Opening pull request against main" },
      { t: "edit", v: "↗  PR #128 — fix: resolve session refresh race" },
      { t: "ok", v: "✔ Shipped · 34s end to end" },
    ],
  },
];

const FEATURES = [
  {
    icon: "terminal",
    title: "Terminal-native, zero config",
    desc: "No new IDE, no browser tab. Jimmy lives where you already work and understands your repo the moment you cd into it.",
  },
  {
    icon: "shield",
    title: "Guardrails & approvals",
    desc: "Every edit is diffed, sandboxed and reversible. You approve each step — or let Jimmy run on a long leash with full audit logs.",
  },
  {
    icon: "sparkles",
    title: "Deep codebase context",
    desc: "Whole-repo semantic indexing means Jimmy reasons about your architecture, conventions and tests — not just the open file.",
  },
  {
    icon: "pr",
    title: "One-command pull requests",
    desc: "From ticket to reviewed PR: it branches, codes, commits with clean messages and shepherds CI until it's green.",
  },
  {
    icon: "zap",
    title: "Local-first & blazing fast",
    desc: "Runs on your machine, respects your .gitignore, and never trains on your code. Median task latency: 800ms.",
  },
];

const DIFF = [
  { type: "ctx", code: "async function refreshAll(sessions: Session[]) {" },
  { type: "del", code: "  await Promise.all(sessions.map(refresh))" },
  { type: "add", code: "  await Promise.all(sessions.map((s) => refresh(s.token)))" },
  { type: "add", code: "  await invalidateStaleTokens(sessions)" },
  { type: "ctx", code: "}" },
];

const STEPS = [
  {
    n: "01",
    title: "Describe the task",
    desc: "Plain English, a GitHub issue, or a failing test — Jimmy turns it into a concrete, reviewable plan.",
    cmd: 'jimmy "add rate limiting to /api/auth"',
  },
  {
    n: "02",
    title: "Jimmy plans & codes",
    desc: "It explores the repo, proposes a step-by-step plan, then writes the code and the tests in a sandbox.",
    cmd: "✻ planning across 42 files …",
  },
  {
    n: "03",
    title: "Review & merge",
    desc: "Approve diffs inline, run checks, and ship. Jimmy opens the PR and babysits CI until it's green.",
    cmd: "jimmy ship  →  PR #128 opened",
  },
];

const TESTIMONIALS = [
  {
    quote:
      "Jimmy closed 11 tickets on our backlog in an afternoon. The diffs were so clean our staff engineer thought a human wrote them.",
    name: "Maya Chen",
    role: "CTO, Ferrous",
    initials: "MC",
    grad: "from-violet-500 to-fuchsia-600",
  },
  {
    quote:
      "It's the first AI tool that actually understands a monorepo. Context that used to take me 20 minutes of spelunking is just… there.",
    name: "Diego Ramírez",
    role: "Staff Engineer, Octane",
    initials: "DR",
    grad: "from-cyan-500 to-blue-600",
  },
  {
    quote:
      "We onboarded three juniors last quarter. With Jimmy reviewing and pair-coding, they shipped like mid-levels. Wild.",
    name: "Priya Nair",
    role: "VP Engineering, Moonbase",
    initials: "PN",
    grad: "from-amber-500 to-orange-600",
  },
];

const STATS = [
  { to: 12400, suffix: "+", label: "developers shipping daily" },
  { to: 1.4, suffix: "M", decimals: 1, label: "commits written by Jimmy" },
  { to: 38, suffix: "%", label: "faster code review cycles" },
  { to: 99.9, suffix: "%", decimals: 1, label: "uptime, local-first" },
];

/* ------------------------------------------------------------------ */
/*  Icons                                                              */
/* ------------------------------------------------------------------ */

function Icon({ name, className = "h-5 w-5" }: { name: string; className?: string }) {
  const paths: Record<string, ReactNode> = {
    terminal: (
      <>
        <polyline points="4 17 10 11 4 5" />
        <line x1="12" y1="19" x2="20" y2="19" />
      </>
    ),
    sparkles: (
      <>
        <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" />
        <path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z" />
      </>
    ),
    shield: (
      <>
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        <polyline points="9 12 11 14 15 10" />
      </>
    ),
    pr: (
      <>
        <circle cx="6" cy="6" r="3" />
        <circle cx="18" cy="18" r="3" />
        <path d="M6 9v12" />
        <path d="M13 6h3a2 2 0 0 1 2 2v7" />
        <line x1="6" y1="18" x2="6" y2="18" />
      </>
    ),
    zap: <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />,
    arrow: (
      <>
        <line x1="5" y1="12" x2="19" y2="12" />
        <polyline points="12 5 19 12 12 19" />
      </>
    ),
    menu: (
      <>
        <line x1="4" y1="7" x2="20" y2="7" />
        <line x1="4" y1="12" x2="20" y2="12" />
        <line x1="4" y1="17" x2="20" y2="17" />
      </>
    ),
    close: (
      <>
        <line x1="6" y1="6" x2="18" y2="18" />
        <line x1="18" y1="6" x2="6" y2="18" />
      </>
    ),
    chevron: <polyline points="6 9 12 15 18 9" />,
  };
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

function GithubIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.56 0-.27-.01-1.17-.02-2.12-3.2.7-3.88-1.36-3.88-1.36-.52-1.33-1.28-1.68-1.28-1.68-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.03 1.76 2.69 1.25 3.35.96.1-.75.4-1.25.72-1.54-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.18-3.09-.12-.29-.51-1.46.11-3.05 0 0 .96-.31 3.15 1.18a10.9 10.9 0 0 1 2.87-.39c.97 0 1.95.13 2.87.39 2.19-1.49 3.15-1.18 3.15-1.18.62 1.59.23 2.76.11 3.05.74.81 1.18 1.83 1.18 3.09 0 4.41-2.69 5.38-5.26 5.66.41.36.78 1.06.78 2.14 0 1.55-.01 2.79-.01 3.17 0 .31.21.68.8.56A10.52 10.52 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5z" />
    </svg>
  );
}

function XIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
      <path d="M18.24 2.25h3.31l-7.23 8.26 8.5 11.24h-6.66l-5.21-6.82-5.97 6.82H1.67l7.73-8.84L1.25 2.25h6.83l4.71 6.23 5.45-6.23zm-1.16 17.52h1.83L7.08 4.13H5.12l11.96 15.64z" />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Primitives                                                         */
/* ------------------------------------------------------------------ */

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 28 },
  show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: [0.21, 0.47, 0.32, 0.98] } },
};

function Reveal({
  children,
  className,
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <motion.div
      className={className}
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: "-80px" }}
      transition={{ delay }}
    >
      {children}
    </motion.div>
  );
}

function SpotlightCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const bg = useMotionTemplate`radial-gradient(280px circle at ${mx}px ${my}px, rgba(167,139,250,0.13), transparent 75%)`;
  return (
    <div
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        mx.set(e.clientX - r.left);
        my.set(e.clientY - r.top);
      }}
      className={`group relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03] transition-colors duration-300 hover:border-white/20 ${className}`}
    >
      <motion.div
        style={{ background: bg }}
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
      />
      <div className="relative h-full">{children}</div>
    </div>
  );
}

function Counter({
  to,
  suffix = "",
  decimals = 0,
}: {
  to: number;
  suffix?: string;
  decimals?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const mv = useMotionValue(0);
  const text = useTransform(mv, (v) =>
    (decimals > 0 ? v.toFixed(decimals) : Math.round(v).toLocaleString("en-US")) + suffix
  );
  useEffect(() => {
    if (!inView) return;
    const controls = animate(mv, to, { duration: 1.8, ease: [0.16, 1, 0.3, 1] });
    return () => controls.stop();
  }, [inView, mv, to]);
  return (
    <span ref={ref} className="tabular-nums">
      <motion.span>{text}</motion.span>
    </span>
  );
}

function SectionHeading({
  kicker,
  title,
  sub,
}: {
  kicker: string;
  title: ReactNode;
  sub?: string;
}) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <Reveal>
        <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3.5 py-1.5 font-mono text-[11px] uppercase tracking-[0.2em] text-violet-300">
          {kicker}
        </span>
      </Reveal>
      <Reveal delay={0.08}>
        <h2 className="mt-5 text-balance text-3xl font-semibold tracking-tight text-white sm:text-4xl md:text-[44px] md:leading-[1.1]">
          {title}
        </h2>
      </Reveal>
      {sub && (
        <Reveal delay={0.16}>
          <p className="mt-4 text-pretty text-base leading-relaxed text-zinc-400 md:text-lg">{sub}</p>
        </Reveal>
      )}
    </div>
  );
}

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <a href="#" className="flex items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-600 font-mono text-[13px] font-bold text-white shadow-lg shadow-fuchsia-500/25">
        &gt;_
      </span>
      {!compact && (
        <span className="text-[15px] font-semibold tracking-tight text-white">
          Jimmy<span className="text-zinc-500"> Code</span>
        </span>
      )}
    </a>
  );
}

function PrimaryButton({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <a
      href="#"
      className={`group inline-flex items-center gap-2 rounded-full bg-white px-6 py-3 text-sm font-semibold text-zinc-950 shadow-[0_0_40px_-10px_rgba(255,255,255,0.45)] transition-all duration-300 hover:shadow-[0_0_60px_-8px_rgba(255,255,255,0.55)] ${className}`}
    >
      {children}
      <Icon
        name="arrow"
        className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5"
      />
    </a>
  );
}

function GhostButton({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <a
      href="#"
      className={`inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-6 py-3 text-sm font-medium text-zinc-200 backdrop-blur transition-colors duration-300 hover:bg-white/10 ${className}`}
    >
      {children}
    </a>
  );
}

/* ------------------------------------------------------------------ */
/*  Terminal                                                           */
/* ------------------------------------------------------------------ */

function Cursor() {
  return (
    <motion.span
      animate={{ opacity: [1, 1, 0, 0] }}
      transition={{ duration: 1.1, repeat: Infinity, times: [0, 0.5, 0.5, 1], ease: "linear" }}
      className="ml-0.5 inline-block h-[15px] w-[7px] translate-y-[2px] bg-emerald-400/90"
    />
  );
}

function Terminal() {
  const [screen, setScreen] = useState(0);
  const [typed, setTyped] = useState("");
  const [showOut, setShowOut] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let t: ReturnType<typeof setTimeout>;
    const cmd = TERMINAL_SCREENS[screen].cmd;
    setTyped("");
    setShowOut(false);
    let i = 0;
    const step = () => {
      if (cancelled) return;
      if (i <= cmd.length) {
        setTyped(cmd.slice(0, i));
        i += 1;
        t = setTimeout(step, 26 + Math.random() * 44);
      } else {
        t = setTimeout(() => {
          if (!cancelled) setShowOut(true);
        }, 450);
        t = setTimeout(() => {
          if (!cancelled) setScreen((s) => (s + 1) % TERMINAL_SCREENS.length);
        }, 3800);
      }
    };
    t = setTimeout(step, 500);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [screen]);

  const lineColor = (t: Line["t"]) =>
    t === "ok"
      ? "text-emerald-400"
      : t === "edit"
        ? "text-violet-300"
        : t === "dim"
          ? "text-zinc-500"
          : "text-zinc-300";

  return (
    <div className="relative w-full overflow-hidden rounded-2xl border border-white/10 bg-zinc-900/70 shadow-2xl shadow-black/50 backdrop-blur-xl">
      <div className="flex items-center gap-2 border-b border-white/5 px-4 py-3">
        <span className="h-3 w-3 rounded-full bg-[#ff5f57]" />
        <span className="h-3 w-3 rounded-full bg-[#febc2e]" />
        <span className="h-3 w-3 rounded-full bg-[#28c840]" />
        <span className="ml-3 font-mono text-xs text-zinc-500">jimmy — zsh</span>
      </div>
      <div className="h-[220px] p-5 font-mono text-[13px] leading-7 sm:text-sm">
        <div className="flex flex-wrap items-center">
          <span className="mr-2 text-emerald-400">➜</span>
          <span className="mr-2 text-violet-400">~/app</span>
          <span className="text-zinc-100">{typed}</span>
          <Cursor />
        </div>
        <AnimatePresence mode="wait">
          {showOut && (
            <motion.div
              key={screen}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
              className="mt-2 space-y-0.5"
            >
              {TERMINAL_SCREENS[screen].out.map((l, idx) => (
                <motion.p
                  key={idx}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.12 * idx, duration: 0.3 }}
                  className={lineColor(l.t)}
                >
                  {l.v}
                </motion.p>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Nav                                                                */
/* ------------------------------------------------------------------ */

function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const { scrollY } = useScroll();
  useMotionValueEvent(scrollY, "change", (v) => setScrolled(v > 16));

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-all duration-300 ${
        scrolled ? "border-b border-white/10 bg-zinc-950/80 backdrop-blur-xl" : "bg-transparent"
      }`}
    >
      <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
        <Logo />
        <div className="hidden items-center gap-8 md:flex">
          {NAV_LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="text-sm text-zinc-400 transition-colors hover:text-white"
            >
              {l.label}
            </a>
          ))}
        </div>
        <div className="hidden items-center gap-3 md:flex">
          <a
            href="#"
            className="flex items-center gap-2 text-sm text-zinc-400 transition-colors hover:text-white"
          >
            <GithubIcon />
            <span>Star</span>
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 font-mono text-[11px] text-zinc-300">
              24.1k
            </span>
          </a>
          <a
            href="#"
            className="rounded-full bg-white px-4 py-2 text-sm font-semibold text-zinc-950 transition-shadow hover:shadow-[0_0_30px_-6px_rgba(255,255,255,0.5)]"
          >
            Get started
          </a>
        </div>
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-zinc-300 md:hidden"
          aria-label="Toggle menu"
        >
          <Icon name={open ? "close" : "menu"} />
        </button>
      </nav>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden border-b border-white/10 bg-zinc-950/95 backdrop-blur-xl md:hidden"
          >
            <div className="space-y-1 px-6 py-4">
              {NAV_LINKS.map((l) => (
                <a
                  key={l.href}
                  href={l.href}
                  onClick={() => setOpen(false)}
                  className="block rounded-lg px-3 py-2.5 text-sm text-zinc-300 hover:bg-white/5"
                >
                  {l.label}
                </a>
              ))}
              <a
                href="#"
                className="mt-2 block rounded-full bg-white px-4 py-2.5 text-center text-sm font-semibold text-zinc-950"
              >
                Get started
              </a>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}

/* ------------------------------------------------------------------ */
/*  Sections                                                           */
/* ------------------------------------------------------------------ */

function Hero() {
  return (
    <section className="relative overflow-hidden pt-36 pb-24 md:pt-44 md:pb-32">
      {/* background */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px)",
          backgroundSize: "72px 72px",
          maskImage: "radial-gradient(ellipse 90% 60% at 50% 0%, black 35%, transparent 78%)",
          WebkitMaskImage: "radial-gradient(ellipse 90% 60% at 50% 0%, black 35%, transparent 78%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-48 left-1/2 h-[560px] w-[900px] -translate-x-1/2 rounded-full bg-violet-600/20 blur-[140px]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute top-32 right-[8%] h-[300px] w-[380px] rounded-full bg-fuchsia-600/10 blur-[120px]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute top-56 left-[6%] h-[260px] w-[340px] rounded-full bg-cyan-500/10 blur-[120px]"
      />

      <div className="relative mx-auto max-w-7xl px-6">
        <div className="mx-auto max-w-3xl text-center">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <a
              href="#"
              className="group inline-flex items-center gap-2.5 rounded-full border border-white/10 bg-white/5 py-1.5 pr-4 pl-1.5 text-[13px] text-zinc-300 backdrop-blur transition-colors hover:bg-white/10"
            >
              <span className="rounded-full bg-gradient-to-r from-orange-500 to-amber-500 px-2.5 py-0.5 text-[11px] font-bold tracking-wide text-white">
                Y&nbsp;W25
              </span>
              Backed by Y Combinator
              <Icon
                name="arrow"
                className="h-3.5 w-3.5 text-zinc-500 transition-transform group-hover:translate-x-0.5"
              />
            </a>
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.1, ease: [0.21, 0.47, 0.32, 0.98] }}
            className="mt-8 text-balance text-5xl font-semibold tracking-tight text-white sm:text-6xl md:text-7xl md:leading-[1.05]"
          >
            The AI engineer that{" "}
            <span className="bg-gradient-to-r from-violet-400 via-fuchsia-400 to-amber-300 bg-clip-text text-transparent">
              lives in your terminal
            </span>
            .
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.2, ease: [0.21, 0.47, 0.32, 0.98] }}
            className="mx-auto mt-6 max-w-xl text-pretty text-base leading-relaxed text-zinc-400 md:text-lg"
          >
            Jimmy reads your codebase, plans the work, writes production-ready code and opens the
            pull request — all from one command. No IDE. No tab-switching. Just ship.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.3, ease: [0.21, 0.47, 0.32, 0.98] }}
            className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row"
          >
            <PrimaryButton>Start shipping free</PrimaryButton>
            <GhostButton>
              <GithubIcon className="h-4 w-4" />
              View on GitHub
            </GhostButton>
          </motion.div>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.7, delay: 0.45 }}
            className="mt-6"
          >
            <InstallPill />
          </motion.div>
        </div>

        {/* terminal */}
        <motion.div
          initial={{ opacity: 0, y: 40, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.9, delay: 0.5, ease: [0.21, 0.47, 0.32, 0.98] }}
          className="relative mx-auto mt-16 max-w-3xl md:mt-20"
        >
          <div
            aria-hidden
            className="absolute -inset-x-8 -top-8 h-40 bg-gradient-to-b from-violet-500/15 to-transparent blur-2xl"
          />
          <Terminal />

          {/* floating chips */}
          <motion.div
            animate={{ y: [0, -10, 0] }}
            transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
            className="absolute -top-6 -right-4 hidden items-center gap-2 rounded-xl border border-white/10 bg-zinc-900/90 px-3.5 py-2.5 text-xs text-zinc-200 shadow-xl shadow-black/40 backdrop-blur lg:flex"
          >
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
            </span>
            Tests passing · 1.8s
          </motion.div>
          <motion.div
            animate={{ y: [0, 10, 0] }}
            transition={{ duration: 6, repeat: Infinity, ease: "easeInOut", delay: 0.8 }}
            className="absolute -bottom-6 -left-4 hidden items-center gap-2.5 rounded-xl border border-white/10 bg-zinc-900/90 px-3.5 py-2.5 text-xs text-zinc-200 shadow-xl shadow-black/40 backdrop-blur lg:flex"
          >
            <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-violet-500/15 text-violet-300">
              <Icon name="pr" className="h-3.5 w-3.5" />
            </span>
            <div>
              <p className="font-medium">PR #128 opened</p>
              <p className="text-[11px] text-zinc-500">jimmy → main · CI green</p>
            </div>
          </motion.div>
        </motion.div>

        <motion.div
          animate={{ y: [0, 8, 0] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
          className="mt-16 flex justify-center text-zinc-600"
        >
          <a href="#logos" aria-label="Scroll down">
            <Icon name="chevron" className="h-5 w-5" />
          </a>
        </motion.div>
      </div>
    </section>
  );
}

function InstallPill() {
  const [copied, setCopied] = useState(false);
  const cmd = "npm i -g jimmy-code";
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(cmd);
          setCopied(true);
          setTimeout(() => setCopied(false), 1600);
        } catch {
          /* clipboard unavailable */
        }
      }}
      className="group inline-flex items-center gap-3 rounded-full border border-white/10 bg-white/5 py-2 pr-3 pl-5 font-mono text-[13px] text-zinc-300 backdrop-blur transition-colors hover:bg-white/10"
    >
      <span className="text-emerald-400">$</span>
      <span>{cmd}</span>
      <span className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[10px] tracking-wide text-zinc-400 uppercase transition-colors group-hover:text-zinc-200">
        {copied ? "Copied ✓" : "Copy"}
      </span>
    </button>
  );
}

function Logos() {
  return (
    <section id="logos" className="relative border-y border-white/5 bg-white/[0.015] py-12">
      <p className="mb-8 text-center font-mono text-[11px] tracking-[0.25em] text-zinc-500 uppercase">
        Trusted by engineers at
      </p>
      <div
        className="relative overflow-hidden"
        style={{
          maskImage: "linear-gradient(90deg, transparent, black 15%, black 85%, transparent)",
          WebkitMaskImage: "linear-gradient(90deg, transparent, black 15%, black 85%, transparent)",
        }}
      >
        <div className="flex w-max animate-[marquee_32s_linear_infinite] items-center gap-20 pr-20">
          {[...LOGOS, ...LOGOS].map((name, i) => (
            <span
              key={i}
              className={`text-lg whitespace-nowrap text-zinc-500 transition-colors hover:text-zinc-300 ${
                i % 3 === 0
                  ? "font-semibold tracking-tight"
                  : i % 3 === 1
                    ? "font-light tracking-[0.18em] uppercase text-sm"
                    : "font-medium italic tracking-tight"
              }`}
            >
              {name}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

function Features() {
  return (
    <section id="features" className="relative scroll-mt-24 py-24 md:py-32">
      <div className="mx-auto max-w-7xl px-6">
        <SectionHeading
          kicker="Features"
          title={
            <>
              Everything a senior engineer does.
              <br className="hidden md:block" />minus the burnout.
            </>
          }
          sub="Jimmy isn't autocomplete. It plans, edits across files, runs your tests and cleans up after itself."
        />

        <div className="mt-16 grid gap-4 md:grid-cols-6">
          {/* featured card */}
          <Reveal className="md:col-span-4">
            <SpotlightCard className="h-full p-8">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-gradient-to-br from-violet-500/20 to-fuchsia-500/10 text-violet-300">
                <Icon name="terminal" />
              </span>
              <h3 className="mt-6 text-xl font-semibold tracking-tight text-white">
                Terminal-native, zero config
              </h3>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-zinc-400">
                No new IDE, no browser tab. Jimmy lives where you already work and understands your
                repo the moment you <span className="font-mono text-zinc-300">cd</span> into it.
              </p>
              <div className="mt-7 rounded-xl border border-white/10 bg-zinc-950/70 p-5 font-mono text-[12.5px] leading-7">
                <p>
                  <span className="mr-2 text-emerald-400">❯</span>
                  <span className="text-zinc-200">
                    jimmy &quot;add rate limiting to /api/auth&quot;
                  </span>
                </p>
                <p className="text-zinc-500">✻ Planning across 42 files …</p>
                <p className="text-violet-300">
                  ● src/middleware/rate-limit.ts{" "}
                  <span className="text-zinc-500">+86 lines, 3 tests</span>
                </p>
                <p className="text-emerald-400">✔ Done · 14s · all checks passing</p>
              </div>
            </SpotlightCard>
          </Reveal>

          <Reveal className="md:col-span-2" delay={0.08}>
            <SpotlightCard className="h-full p-8">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-gradient-to-br from-emerald-500/20 to-teal-500/10 text-emerald-300">
                <Icon name="shield" />
              </span>
              <h3 className="mt-6 text-xl font-semibold tracking-tight text-white">
                Guardrails & approvals
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-zinc-400">
                Every edit is diffed, sandboxed and reversible. Approve each step — or run on a long
                leash with full audit logs.
              </p>
            </SpotlightCard>
          </Reveal>

          <Reveal className="md:col-span-2" delay={0.05}>
            <SpotlightCard className="h-full p-8">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-gradient-to-br from-fuchsia-500/20 to-pink-500/10 text-fuchsia-300">
                <Icon name="sparkles" />
              </span>
              <h3 className="mt-6 text-xl font-semibold tracking-tight text-white">
                Deep codebase context
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-zinc-400">
                Whole-repo semantic indexing. Jimmy reasons about your architecture, conventions and
                tests — not just the open file.
              </p>
            </SpotlightCard>
          </Reveal>

          <Reveal className="md:col-span-2" delay={0.13}>
            <SpotlightCard className="h-full p-8">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-gradient-to-br from-cyan-500/20 to-blue-500/10 text-cyan-300">
                <Icon name="pr" />
              </span>
              <h3 className="mt-6 text-xl font-semibold tracking-tight text-white">
                One-command pull requests
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-zinc-400">
                It branches, codes, commits with clean messages and shepherds CI until it&apos;s
                green.
              </p>
            </SpotlightCard>
          </Reveal>

          <Reveal className="md:col-span-2" delay={0.2}>
            <SpotlightCard className="h-full p-8">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-gradient-to-br from-amber-500/20 to-orange-500/10 text-amber-300">
                <Icon name="zap" />
              </span>
              <h3 className="mt-6 text-xl font-semibold tracking-tight text-white">
                Local-first & blazing fast
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-zinc-400">
                Runs on your machine, respects your .gitignore and never trains on your code. Median
                task latency: 800ms.
              </p>
            </SpotlightCard>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function HowItWorks() {
  return (
    <section id="how" className="relative scroll-mt-24 border-t border-white/5 py-24 md:py-32">
      <div
        aria-hidden
        className="pointer-events-none absolute top-1/3 left-1/2 h-[400px] w-[700px] -translate-x-1/2 rounded-full bg-violet-600/8 blur-[140px]"
      />
      <div className="relative mx-auto max-w-7xl px-6">
        <SectionHeading
          kicker="How it works"
          title="From ticket to merged PR in three steps"
          sub="A workflow your whole team can trust — visible plans, reviewable diffs, no black boxes."
        />
        <div className="relative mt-16 grid gap-10 md:grid-cols-3 md:gap-6">
          <div
            aria-hidden
            className="absolute top-8 right-[16%] left-[16%] hidden h-px bg-gradient-to-r from-transparent via-white/15 to-transparent md:block"
          />
          {STEPS.map((s, i) => (
            <Reveal key={s.n} delay={i * 0.12}>
              <div className="relative">
                <span className="relative z-10 inline-flex h-16 w-16 items-center justify-center rounded-2xl border border-white/10 bg-zinc-950 font-mono text-lg font-semibold text-violet-300 shadow-lg shadow-black/40">
                  {s.n}
                </span>
                <h3 className="mt-6 text-lg font-semibold tracking-tight text-white">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-zinc-400">{s.desc}</p>
                <p className="mt-5 inline-block rounded-lg border border-white/10 bg-white/[0.03] px-3.5 py-2 font-mono text-[12px] text-zinc-400">
                  {s.cmd}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Showcase() {
  return (
    <section id="showcase" className="relative scroll-mt-24 border-t border-white/5 py-24 md:py-32">
      <div className="mx-auto max-w-7xl px-6">
        <div className="grid items-center gap-14 lg:grid-cols-2">
          <div>
            <Reveal>
              <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3.5 py-1.5 font-mono text-[11px] tracking-[0.2em] text-cyan-300 uppercase">
                Showcase
              </span>
            </Reveal>
            <Reveal delay={0.08}>
              <h2 className="mt-5 text-balance text-3xl font-semibold tracking-tight text-white sm:text-4xl md:text-[44px] md:leading-[1.1]">
                Diffs so clean, reviewers say thanks
              </h2>
            </Reveal>
            <Reveal delay={0.16}>
              <p className="mt-4 max-w-lg text-pretty text-base leading-relaxed text-zinc-400 md:text-lg">
                Jimmy writes minimal, surgical changes with tests included. Every suggestion is a
                reviewable diff — accept it, tweak it, or reject it. You stay the author.
              </p>
            </Reveal>
            <Reveal delay={0.24}>
              <ul className="mt-8 space-y-3.5">
                {[
                  "Minimal, surgical diffs — never rewrites your style",
                  "Tests generated alongside every change",
                  "Conventional commits and PR descriptions, automatic",
                ].map((item) => (
                  <li key={item} className="flex items-start gap-3 text-sm text-zinc-300">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
                      <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className="h-3 w-3"
                        aria-hidden="true"
                      >
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </span>
                    {item}
                  </li>
                ))}
              </ul>
            </Reveal>
          </div>

          <Reveal delay={0.1}>
            <div className="relative">
              <div
                aria-hidden
                className="absolute -inset-6 rounded-3xl bg-gradient-to-br from-cyan-500/10 via-transparent to-violet-500/10 blur-2xl"
              />
              <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-zinc-900/70 shadow-2xl shadow-black/50 backdrop-blur-xl">
                <div className="flex items-center gap-2 border-b border-white/5 px-4 py-3">
                  <span className="h-3 w-3 rounded-full bg-[#ff5f57]" />
                  <span className="h-3 w-3 rounded-full bg-[#febc2e]" />
                  <span className="h-3 w-3 rounded-full bg-[#28c840]" />
                  <span className="ml-3 rounded-md border border-white/10 bg-white/5 px-2.5 py-1 font-mono text-[11px] text-zinc-400">
                    session.ts
                  </span>
                  <span className="ml-auto font-mono text-[11px] text-zinc-600">+2 −1</span>
                </div>
                <div className="overflow-x-auto p-2 font-mono text-[13px] leading-8">
                  {DIFF.map((l, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, x: -10 }}
                      whileInView={{ opacity: 1, x: 0 }}
                      viewport={{ once: true, margin: "-60px" }}
                      transition={{ delay: 0.15 + i * 0.12, duration: 0.35 }}
                      className={`flex items-start gap-4 rounded-md px-4 whitespace-pre ${
                        l.type === "add"
                          ? "bg-emerald-500/10 text-emerald-300"
                          : l.type === "del"
                            ? "bg-red-500/10 text-red-300/90"
                            : "text-zinc-400"
                      }`}
                    >
                      <span
                        className={
                          l.type === "add"
                            ? "text-emerald-500"
                            : l.type === "del"
                              ? "text-red-500"
                              : "text-zinc-700"
                        }
                      >
                        {l.type === "add" ? "+" : l.type === "del" ? "−" : " "}
                      </span>
                      <span>{l.code}</span>
                    </motion.div>
                  ))}
                </div>
                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: 1, duration: 0.4 }}
                  className="flex items-center gap-2.5 border-t border-white/5 px-5 py-3.5"
                >
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="h-3.5 w-3.5"
                      aria-hidden="true"
                    >
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </span>
                  <p className="text-xs text-zinc-400">
                    <span className="font-medium text-zinc-200"> jimmy-bot</span> committed ·
                    “fix: resolve session refresh race”
                  </p>
                </motion.div>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function Stats() {
  return (
    <section className="relative border-y border-white/5 bg-white/[0.015] py-16 md:py-20">
      <div className="mx-auto grid max-w-7xl grid-cols-2 gap-10 px-6 md:grid-cols-4">
        {STATS.map((s, i) => (
          <Reveal key={s.label} delay={i * 0.08} className="text-center">
            <p className="bg-gradient-to-b from-white to-zinc-400 bg-clip-text text-4xl font-semibold tracking-tight text-transparent md:text-5xl">
              <Counter to={s.to} suffix={s.suffix} decimals={s.decimals ?? 0} />
            </p>
            <p className="mt-2.5 text-[13px] text-zinc-500">{s.label}</p>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

function Testimonials() {
  return (
    <section
      id="testimonials"
      className="relative scroll-mt-24 border-t border-white/5 py-24 md:py-32"
    >
      <div className="mx-auto max-w-7xl px-6">
        <SectionHeading
          kicker="Testimonials"
          title="Loved by teams who ship"
          sub="From two-person startups to public companies — engineers trust Jimmy with their codebase."
        />
        <div className="mt-16 grid gap-4 md:grid-cols-3">
          {TESTIMONIALS.map((t, i) => (
            <Reveal key={t.name} delay={i * 0.1}>
              <SpotlightCard className="flex h-full flex-col p-8">
                <div className="flex gap-1 text-amber-400" aria-hidden="true">
                  {Array.from({ length: 5 }).map((_, s) => (
                    <svg
                      key={s}
                      viewBox="0 0 24 24"
                      fill="currentColor"
                      className="h-3.5 w-3.5"
                      aria-hidden="true"
                    >
                      <path d="M12 2l2.9 6.6 7.1.6-5.4 4.7 1.6 7-6.2-3.7-6.2 3.7 1.6-7L2 9.2l7.1-.6L12 2z" />
                    </svg>
                  ))}
                </div>
                <p className="mt-5 flex-1 text-[15px] leading-relaxed text-zinc-300">
                  &ldquo;{t.quote}&rdquo;
                </p>
                <div className="mt-7 flex items-center gap-3.5">
                  <span
                    className={`flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br ${t.grad} text-[13px] font-bold text-white`}
                  >
                    {t.initials}
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-white">{t.name}</p>
                    <p className="text-[13px] text-zinc-500">{t.role}</p>
                  </div>
                </div>
              </SpotlightCard>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function CTA() {
  return (
    <section className="relative overflow-hidden border-t border-white/5 py-28 md:py-36">
      <div
        aria-hidden
        className="pointer-events-none absolute top-1/2 left-1/2 h-[420px] w-[820px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-violet-600/15 blur-[140px]"
      />
      <div className="relative mx-auto max-w-3xl px-6 text-center">
        <Reveal>
          <h2 className="text-balance text-4xl font-semibold tracking-tight text-white sm:text-5xl md:text-6xl md:leading-[1.05]">
            Ship your next feature{" "}
            <span className="bg-gradient-to-r from-violet-400 via-fuchsia-400 to-amber-300 bg-clip-text text-transparent">
              before your coffee cools
            </span>
            .
          </h2>
        </Reveal>
        <Reveal delay={0.1}>
          <p className="mx-auto mt-5 max-w-xl text-pretty text-base leading-relaxed text-zinc-400 md:text-lg">
            Free for individuals. Two-minute setup. Your terminal will never feel empty again.
          </p>
        </Reveal>
        <Reveal delay={0.2}>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <PrimaryButton>Start shipping free</PrimaryButton>
            <GhostButton>Read the docs</GhostButton>
          </div>
        </Reveal>
        <Reveal delay={0.3}>
          <div className="mt-6">
            <InstallPill />
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function Footer() {
  const cols = [
    { h: "Product", links: ["Features", "Changelog", "Roadmap", "Pricing"] },
    { h: "Resources", links: ["Docs", "API", "Community", "Status"] },
    { h: "Company", links: ["About", "Blog", "Careers", "Contact"] },
  ];
  return (
    <footer className="border-t border-white/5 py-14">
      <div className="mx-auto max-w-7xl px-6">
        <div className="grid gap-10 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div>
            <Logo />
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-zinc-500">
              The terminal-native AI coding agent. Plan, code and ship — without leaving the command
              line.
            </p>
            <div className="mt-5 flex items-center gap-3">
              <a
                href="#"
                aria-label="GitHub"
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-zinc-400 transition-colors hover:border-white/20 hover:text-white"
              >
                <GithubIcon />
              </a>
              <a
                href="#"
                aria-label="X"
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-zinc-400 transition-colors hover:border-white/20 hover:text-white"
              >
                <XIcon />
              </a>
            </div>
          </div>
          {cols.map((c) => (
            <div key={c.h}>
              <p className="text-[13px] font-semibold tracking-wide text-zinc-300 uppercase">
                {c.h}
              </p>
              <ul className="mt-4 space-y-2.5">
                {c.links.map((l) => (
                  <li key={l}>
                    <a
                      href="#"
                      className="text-sm text-zinc-500 transition-colors hover:text-zinc-200"
                    >
                      {l}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-white/5 pt-8 sm:flex-row">
          <p className="text-[13px] text-zinc-600">© 2025 Jimmy Code, Inc. All rights reserved.</p>
          <p className="font-mono text-[12px] text-zinc-600">built with ♥ in san francisco</p>
        </div>
      </div>
    </footer>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function Page() {
  return (
    <div className="min-h-screen bg-[#09090b] font-sans text-zinc-200 antialiased selection:bg-violet-500/30 selection:text-white">
      <style>{`
        html { scroll-behavior: smooth; }
        @keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
      `}</style>
      <Nav />
      <main>
        <Hero />
        <Logos />
        <Features />
        <HowItWorks />
        <Showcase />
        <Stats />
        <Testimonials />
        <CTA />
      </main>
      <Footer />
    </div>
  );
}
