"use client";

import {
  Fragment,
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  AnimatePresence,
  MotionConfig,
  motion,
  useMotionTemplate,
  useMotionValue,
  useMotionValueEvent,
  useScroll,
  type Variants,
} from "framer-motion";
import {
  ArrowRight,
  BookOpen,
  Brain,
  Check,
  ChevronRight,
  Code,
  Command,
  Copy,
  Database,
  FileDiff,
  FilePen,
  FilePlus,
  FlaskConical,
  FolderOpen,
  GitBranch,

  ListTodo,
  Menu,
  Music,
  Rocket,
  Search,
  ShieldCheck,
  Sparkles,
  Terminal,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";

/* ================================================================== */
/*  Data — everything real, straight from the project                  */
/* ================================================================== */

const REPO_URL = "https://github.com/StarDust130/Jimmy-Code";
const CLONE_CMD = "git clone https://github.com/StarDust130/Jimmy-Code.git";
const VERSION = "v0.1.0";

const NAV_LINKS = [
  { label: "the loop", href: "#loop" },
  { label: "tools", href: "#tools" },
  { label: "permissions", href: "#permissions" },
  { label: "the app", href: "#app" },
  { label: "install", href: "#install" },
];

const LETTER_COLORS = ["#22d3ee", "#f472b6", "#fbbf24", "#4ade80", "#a78bfa"];

const HERO_TASKS = [
  "explain",
  "fix the failing tests in src/",
  "add rate limiting to /api/auth",
  "commit everything with a fun message",
  "ship it",
];

/* --- session demo scenes -------------------------------------------- */

type Tone = "ok" | "dim" | "info" | "edit";
type ApprovalResult = "allow" | "session" | "deny";

type TermLine =
  | { k: "spin"; label: string; done: string; ms: number }
  | { k: "text"; v: string; tone?: Tone }
  | { k: "approval"; cmd: string };

type Scene = { cmd: string; lines: TermLine[] };

const SCENES: Scene[] = [
  {
    cmd: "fix the failing tests, then push it",
    lines: [
      { k: "spin", label: "reading src/", done: "✓ 42 files indexed · 0.4s", ms: 900 },
      { k: "text", v: "edit_files   jimmy/agent/loop.py   +4 −2", tone: "edit" },
      { k: "spin", label: "running pytest", done: "✓ pytest · 293 passed · 1.2s", ms: 1200 },
      { k: "approval", cmd: "git push origin main" },
      { k: "text", v: "✓ pushed · branch fix/agent-loop", tone: "ok" },
      { k: "text", v: "✦ 11.2s · 12k in · 510 out · 6 tools · 3 rounds", tone: "info" },
    ],
  },
  {
    cmd: "commit that all 4 with short fun emoji message",
    lines: [
      { k: "spin", label: "checking git status", done: "✓ checking git status      8ms", ms: 800 },
      { k: "spin", label: "reading jimmy.tcss", done: "✓ reading jimmy.tcss      90ms", ms: 650 },
      { k: "text", v: "✓ committed “styling widgets nicely 🍜”", tone: "ok" },
      { k: "text", v: "4 files · committed individually, as requested", tone: "dim" },
      { k: "text", v: "✦ 9.5s · 9.8k in · 393 out · 9 tools · 4 rounds", tone: "info" },
    ],
  },
  {
    cmd: "add rate limiting to /api/auth",
    lines: [
      { k: "text", v: "planning across 14 files…", tone: "dim" },
      { k: "text", v: "write_file   src/api/rate_limit.py       +86", tone: "edit" },
      { k: "text", v: "write_file   tests/test_rate_limit.py    +41", tone: "edit" },
      { k: "spin", label: "running pytest", done: "✓ pytest · 290 passed · 1.0s", ms: 1100 },
      { k: "text", v: "✓ committed · feat: rate-limit auth", tone: "ok" },
      { k: "text", v: "✦ 34s · 21k in · 890 out · 9 tools · 5 rounds", tone: "info" },
    ],
  },
];

/* --- loop / tools / features ----------------------------------------- */

const LOOP_CHIPS: { icon: LucideIcon; label: string }[] = [
  { icon: ListTodo, label: "task" },
  { icon: Brain, label: "think" },
  { icon: Code, label: "code" },
  { icon: FlaskConical, label: "test" },
  { icon: Rocket, label: "ship" },
];

const TOOLS: { icon: LucideIcon; name: string; desc: string }[] = [
  { icon: BookOpen, name: "read_files", desc: "Reads code before writing it." },
  { icon: Search, name: "search_files", desc: "Finds the needle anywhere in the repo." },
  { icon: FilePen, name: "edit_files", desc: "Surgical edits across files." },
  { icon: FilePlus, name: "write_file", desc: "Creates what’s missing." },
  { icon: FileDiff, name: "apply_patch", desc: "Clean diffs, applied safely." },
  { icon: FolderOpen, name: "list_files", desc: "Knows its way around your tree." },
  { icon: Terminal, name: "shell", desc: "Runs commands — with your approval." },
  { icon: FlaskConical, name: "run_tests", desc: "Green, or it keeps going." },
  { icon: GitBranch, name: "git", desc: "Branches, commits, tidy messages." },
];

const MODES = [
  {
    id: "ask" as const,
    dot: "bg-emerald-400",
    name: "Ask",
    blurb: "Asks before anything risky. The sensible default.",
  },
  {
    id: "auto" as const,
    dot: "bg-amber-400",
    name: "Auto",
    blurb: "Safe actions run automatically. Risky ones still check in.",
  },
  {
    id: "full" as const,
    dot: "bg-red-400",
    name: "Full Access",
    blurb: "No approval prompts. You know what you’re doing. Probably.",
  },
];

const APP_FEATURES: { icon: LucideIcon; title: string; desc: string }[] = [
  {
    icon: Terminal,
    title: "A TUI that feels like an app",
    desc: "A full interface rendered in your terminal by Textual — not a wall of print().",
  },
  {
    icon: Command,
    title: "Command palette",
    desc: "Ctrl+P brings up every action. Slash commands live right in the input.",
  },
  {
    icon: Database,
    title: "Sessions that remember",
    desc: "SQLite + WAL persistence. Stop, close the lid, come back tomorrow — continue.",
  },
  {
    icon: Sparkles,
    title: "Bring your own brain",
    desc: "Any provider through LiteLLM — Claude, GPT, Gemini or a local model. Ctrl+M to switch.",
  },
  {
    icon: Music,
    title: "Sound & themes",
    desc: "Subtle, toggleable sound and themable UI. Ctrl+S if the vibe is too much.",
  },
  {
    icon: FlaskConical,
    title: "Battle-tested",
    desc: "290+ tests covering the loop, permissions, persistence and the UI — all passing.",
  },
];

const INSTALL_STEPS: Record<"uv" | "pip", string[]> = {
  uv: [CLONE_CMD, "cd Jimmy-Code", "uv sync"],
  pip: [CLONE_CMD, "cd Jimmy-Code", "pip install -e ."],
};

const RUN_CMDS = [
  { cmd: "jimmy", comment: "opens the TUI" },
  { cmd: 'jimmy "fix the failing tests in src/"', comment: "one-shot a task" },
];

const SHORTCUTS: { keys: string[]; label: string }[] = [
  { keys: ["Enter"], label: "Send" },
  { keys: ["Esc"], label: "Stop / go back" },
  { keys: ["Ctrl", "P"], label: "Command palette" },
  { keys: ["Ctrl", "M"], label: "Model picker" },
  { keys: ["Ctrl", "O"], label: "Session browser" },
  { keys: ["Ctrl", "N"], label: "New session" },
  { keys: ["Ctrl", "C"], label: "Copy last result" },
  { keys: ["Ctrl", "A"], label: "Copy full transcript" },
  { keys: ["Ctrl", "L"], label: "Clear input" },
  { keys: ["Ctrl", "S"], label: "Toggle sound" },
  { keys: ["Ctrl", "Q"], label: "Quit" },
  { keys: ["/"], label: "Slash commands" },
];

const SLASH = [
  "model",
  "permissions",
  "sessions",
  "new",
  "theme",
  "sound",
  "clear",
  "copy",
  "copyall",
  "help",
  "quit",
];

const FOOTER_COLS: { h: string; links: [string, string][] }[] = [
  {
    h: "product",
    links: [
      ["The loop", "#loop"],
      ["Tools", "#tools"],
      ["Permissions", "#permissions"],
      ["Install", "#install"],
    ],
  },
  {
    h: "manual",
    links: [
      ["The app", "#app"],
      ["Controls", "#shortcuts"],
      ["GitHub", REPO_URL],
    ],
  },
  {
    h: "project",
    links: [
      ["Repository", REPO_URL],
      ["Issues", `${REPO_URL}/issues`],
      ["License · MIT", `${REPO_URL}/blob/main/LICENSE`],
    ],
  },
];

const MASK_X = {
  maskImage: "linear-gradient(90deg, transparent, black 12%, black 88%, transparent)",
  WebkitMaskImage: "linear-gradient(90deg, transparent, black 12%, black 88%, transparent)",
};

const GLOBAL_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Press+Start+2P&display=swap');
  html { scroll-behavior: smooth; }
  .font-display { font-family: 'Space Grotesk', ui-sans-serif, system-ui, sans-serif; }
  .font-mono, code, kbd, pre { font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  .font-pixel { font-family: 'Press Start 2P', 'JetBrains Mono', monospace; }
  @keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
  @keyframes huecycle { to { filter: hue-rotate(360deg); } }
  .hue-cycle { animation: huecycle 18s linear infinite; }
  @keyframes floorshift { to { background-position-y: 44px; } }
  .dance-floor {
    background-image:
      linear-gradient(rgba(139,92,246,0.30) 1px, transparent 1px),
      linear-gradient(90deg, rgba(139,92,246,0.30) 1px, transparent 1px);
    background-size: 44px 44px;
    animation: floorshift 1.5s linear infinite;
  }
  @media (prefers-reduced-motion: reduce) {
    .hue-cycle, .dance-floor { animation: none !important; }
  }
`;

/* ================================================================== */
/*  Pixel wordmark — the brand, straight from the TUI                  */
/* ================================================================== */

const GLYPHS: Record<string, string[]> = {
  J: ["...##", "...#.", "...#.", "#..#.", "#..#.", "#..#.", ".##.."],
  I: ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"],
  M: ["#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"],
  Y: ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
  C: [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
  O: [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
  D: ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
  E: ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
};

function PixelGlyph({ ch, color, cell }: { ch: string; color: string; cell: number }) {
  const rows = GLYPHS[ch] ?? [];
  return (
    <svg
      width={5 * cell}
      height={7 * cell}
      viewBox="0 0 5 7"
      shapeRendering="crispEdges"
      aria-hidden="true"
    >
      {rows.map((row, y) =>
        row.split("").map((c, x) =>
          c === "#" ? (
            <rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill={color} />
          ) : null
        )
      )}
    </svg>
  );
}

type PixelWordProps = {
  word: string;
  colors: string[] | string;
  cell: number;
  dance?: boolean;
  delayBase?: number;
  stagger?: number;
  className?: string;
  style?: CSSProperties;
};

function PixelWord({
  word,
  colors,
  cell,
  dance = false,
  delayBase = 0,
  stagger = 0.08,
  className = "",
  style,
}: PixelWordProps) {
  const letters = word.split("");
  const colorFor = (i: number) => (Array.isArray(colors) ? colors[i % colors.length] : colors);
  return (
    <div
      className={`flex select-none items-end ${className}`}
      style={{ gap: cell * 0.7, ...style }}
      role="img"
      aria-label={word}
    >
      {letters.map((ch, i) => {
        const color = colorFor(i);
        return (
          <motion.span
            key={`${ch}-${i}`}
            initial={{ opacity: 0, y: 24, scale: 0.5 }}
            whileInView={{ opacity: 1, y: 0, scale: 1 }}
            viewport={{ once: true, margin: "-20px" }}
            transition={{
              delay: delayBase + i * stagger,
              type: "spring",
              stiffness: 320,
              damping: 16,
            }}
            whileHover={{ y: -cell * 1.3, transition: { type: "spring", stiffness: 500, damping: 10 } }}
            className="inline-block cursor-default"
            style={{ filter: `drop-shadow(0 0 ${Math.max(6, cell * 0.9)}px ${color}59)` }}
          >
            <motion.span
              className="block"
              animate={dance ? { y: [0, -cell * 0.45, 0] } : { y: 0 }}
              transition={
                dance
                  ? { duration: 1.9, repeat: Infinity, ease: "easeInOut", delay: i * 0.21 }
                  : undefined
              }
            >
              <PixelGlyph ch={ch} color={color} cell={cell} />
            </motion.span>
          </motion.span>
        );
      })}
    </div>
  );
}

/* ================================================================== */
/*  Primitives                                                         */
/* ================================================================== */

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { duration: 0.65, ease: [0.21, 0.47, 0.32, 0.98] } },
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
  const bg = useMotionTemplate`radial-gradient(240px circle at ${mx}px ${my}px, rgba(139,92,246,0.10), transparent 70%)`;
  return (
    <div
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        mx.set(e.clientX - r.left);
        my.set(e.clientY - r.top);
      }}
      className={`group relative h-full overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] transition-colors duration-300 hover:border-violet-400/30 ${className}`}
    >
      <motion.div
        style={{ background: bg }}
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
      />
      <div className="relative h-full">{children}</div>
    </div>
  );
}

function SectionHead({
  num,
  kicker,
  title,
  sub,
}: {
  num: string;
  kicker: string;
  title: ReactNode;
  sub?: string;
}) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <Reveal>
        <p className="font-pixel text-[9px] text-violet-400">{`[ ${num} · ${kicker} ]`}</p>
      </Reveal>
      <Reveal delay={0.07}>
        <h2 className="mt-5 font-display text-3xl font-semibold tracking-tight text-white sm:text-4xl md:text-[42px] md:leading-[1.1]">
          {title}
        </h2>
      </Reveal>
      {sub && (
        <Reveal delay={0.14}>
          <p className="mt-4 text-pretty text-base leading-relaxed text-zinc-400 md:text-lg">{sub}</p>
        </Reveal>
      )}
    </div>
  );
}

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-6 min-w-[24px] items-center justify-center rounded-md border border-b-2 border-white/15 bg-white/5 px-1.5 font-mono text-[11px] font-medium text-zinc-300">
      {children}
    </kbd>
  );
}

function BlockCursor({ dim = false }: { dim?: boolean }) {
  return (
    <motion.span
      animate={{ opacity: [1, 1, 0, 0] }}
      transition={{ duration: 1, repeat: Infinity, times: [0, 0.5, 0.5, 1], ease: "linear" }}
      className={`ml-1 inline-block h-[16px] w-[9px] translate-y-[3px] ${dim ? "bg-zinc-600" : "bg-violet-400"}`}
    />
  );
}

function toneClass(t?: Tone) {
  switch (t) {
    case "ok":
      return "text-emerald-400";
    case "dim":
      return "text-zinc-500";
    case "info":
      return "text-violet-300";
    case "edit":
      return "text-sky-300";
    default:
      return "text-zinc-300";
  }
}

function useCopy() {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );

  const copy = useCallback(async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopiedKey(null), 1600);
    } catch {
      /* clipboard unavailable */
    }
  }, []);

  return { copiedKey, copy };
}

function CopyButton({ copied, onClick, label }: { copied: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md border transition-colors ${
        copied
          ? "border-emerald-500/40 text-emerald-400"
          : "border-white/10 bg-white/5 text-zinc-500 hover:text-zinc-200"
      }`}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

/* ================================================================== */
/*  Hero pieces — disco ball, beams, floor, confetti, autotyping input  */
/* ================================================================== */

const SPARKLE_CELLS: [number, number][] = [
  [2, 2],
  [6, 3],
  [4, 5],
  [3, 6],
  [6, 6],
  [1, 4],
  [7, 5],
  [4, 1],
];

function DiscoBall() {
  const cells: { x: number; y: number }[] = [];
  const N = 9;
  const c = (N - 1) / 2;
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      if (Math.hypot(x - c, y - c) <= 4.2) cells.push({ x, y });
    }
  }
  return (
    <motion.div
      aria-hidden
      animate={{ rotate: [-6, 6, -6] }}
      transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
      style={{ x: "-50%", transformOrigin: "top center" }}
      className="pointer-events-none absolute top-0 left-1/2 z-[3] flex flex-col items-center"
    >
      <div className="h-20 w-px bg-gradient-to-b from-transparent via-zinc-700 to-zinc-500 sm:h-28" />
      <svg
        width="72"
        height="72"
        viewBox="0 0 9 9"
        shapeRendering="crispEdges"
        className="drop-shadow-[0_0_18px_rgba(167,139,250,0.35)]"
      >
        {cells.map(({ x, y }) => {
          const isSpark = SPARKLE_CELLS.some(([sx, sy]) => sx === x && sy === y);
          if (isSpark) {
            const color = LETTER_COLORS[(x + y) % 5];
            return (
              <motion.rect
                key={`${x}-${y}`}
                x={x}
                y={y}
                width={1}
                height={1}
                fill={color}
                animate={{ opacity: [0.15, 1, 0.15] }}
                transition={{
                  duration: 2 + ((x * y) % 3) * 0.7,
                  repeat: Infinity,
                  delay: ((x * 7 + y * 3) % 20) / 10,
                  ease: "easeInOut",
                }}
              />
            );
          }
          return (
            <rect
              key={`${x}-${y}`}
              x={x}
              y={y}
              width={1}
              height={1}
              fill={(x + y) % 2 === 0 ? "#52525b" : "#3f3f46"}
            />
          );
        })}
      </svg>
    </motion.div>
  );
}

const CONFETTI = [
  { left: "10%", top: "30%", color: "#22d3ee", size: 5, dur: 6, delay: 0 },
  { left: "86%", top: "24%", color: "#f472b6", size: 4, dur: 7, delay: 1.2 },
  { left: "18%", top: "62%", color: "#fbbf24", size: 4, dur: 5.5, delay: 0.6 },
  { left: "78%", top: "58%", color: "#4ade80", size: 5, dur: 6.5, delay: 2 },
  { left: "30%", top: "18%", color: "#a78bfa", size: 4, dur: 7.5, delay: 0.3 },
  { left: "68%", top: "70%", color: "#22d3ee", size: 4, dur: 6, delay: 1.6 },
  { left: "8%", top: "52%", color: "#f472b6", size: 3, dur: 5, delay: 2.4 },
  { left: "92%", top: "44%", color: "#fbbf24", size: 4, dur: 6.8, delay: 0.9 },
];

function TypeInput() {
  const [text, setText] = useState("");

  useEffect(() => {
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];
    let taskI = 0;

    const run = () => {
      const t = HERO_TASKS[taskI % HERO_TASKS.length];
      let i = 0;
      const type = () => {
        if (cancelled) return;
        if (i <= t.length) {
          setText(t.slice(0, i));
          i += 1;
          timers.push(setTimeout(type, 42 + Math.random() * 46));
        } else {
          timers.push(setTimeout(erase, 2100));
        }
      };
      const erase = () => {
        if (cancelled) return;
        if (i > 0) {
          i -= 1;
          setText(t.slice(0, i));
          timers.push(setTimeout(erase, 16));
        } else {
          taskI += 1;
          timers.push(setTimeout(run, 400));
        }
      };
      type();
    };

    timers.push(setTimeout(run, 900));
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, []);

  return (
    <div className="relative mx-auto mt-10 w-full max-w-xl">
      <div className="rounded-xl border-2 border-violet-500/70 bg-[#0a0812]/90 px-5 py-4 shadow-[0_0_45px_-10px_rgba(139,92,246,0.55)]">
        <div className="flex items-center gap-3 font-mono text-[14px] sm:text-[15px]">
          <span className="text-violet-400">❯</span>
          <span className="min-w-0 truncate text-zinc-200">{text}</span>
          <BlockCursor />
        </div>
      </div>
      <p className="mt-3 font-mono text-[11px] text-zinc-600">
        give jimmy a task — it takes it from here
      </p>
    </div>
  );
}

function useHeroCell() {
  const [cell, setCell] = useState(9);
  useEffect(() => {
    const update = () => {
      const w = window.innerWidth;
      setCell(w >= 1024 ? 13 : w >= 768 ? 11 : w >= 640 ? 9 : 7);
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return cell;
}

/* ================================================================== */
/*  Nav                                                                */
/* ================================================================== */

function Logo() {
  return (
    <a href="#" className="flex items-center gap-2.5">
      <PixelWord word="JIMMY" colors={LETTER_COLORS} cell={2} />
      <span className="font-mono text-[13px] font-medium text-zinc-500">code</span>
    </a>
  );
}

function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const { scrollY } = useScroll();
  useMotionValueEvent(scrollY, "change", (v) => setScrolled(v > 24));

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-all duration-300 ${
        scrolled
          ? "border-b border-white/10 bg-[#030304]/85 backdrop-blur-xl"
          : "border-b border-transparent"
      }`}
    >
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Logo />
        <div className="hidden items-center gap-7 md:flex">
          {NAV_LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="font-mono text-[13px] text-zinc-400 transition-colors hover:text-white"
            >
              {l.label}
            </a>
          ))}
        </div>
        <div className="hidden items-center gap-3 md:flex">
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="GitHub"
            className="flex h-9 w-9 items-center justify-center rounded-full border border-white/10 text-zinc-400 transition hover:border-white/25 hover:text-white"
          >
           
          </a>
          <a
            href="#install"
            className="rounded-full bg-violet-400 px-4 py-2 text-[13px] font-semibold text-zinc-950 shadow-[0_0_28px_-8px_rgba(167,139,250,0.7)] transition hover:bg-violet-300"
          >
            Install
          </a>
        </div>
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-zinc-300 md:hidden"
          aria-label="Toggle menu"
        >
          {open ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
        </button>
      </nav>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden border-b border-white/10 bg-[#030304]/95 backdrop-blur-xl md:hidden"
          >
            <div className="space-y-1 px-6 py-4">
              {NAV_LINKS.map((l) => (
                <a
                  key={l.href}
                  href={l.href}
                  onClick={() => setOpen(false)}
                  className="block rounded-lg px-3 py-2.5 font-mono text-sm text-zinc-300 hover:bg-white/5"
                >
                  {l.label}
                </a>
              ))}
              <a
                href="#install"
                onClick={() => setOpen(false)}
                className="mt-2 block rounded-full bg-violet-400 px-4 py-2.5 text-center text-sm font-semibold text-zinc-950"
              >
                Install Jimmy
              </a>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}

/* ================================================================== */
/*  Hero — the landing page IS the TUI home screen                     */
/* ================================================================== */

function Hero() {
  const cell = useHeroCell();
  const codeCell = Math.max(3, Math.round(cell * 0.42));

  return (
    <section className="relative flex min-h-screen flex-col overflow-hidden">
      {/* rotating disco beams */}
      <motion.div
        aria-hidden
        className="pointer-events-none absolute top-[-45%] left-1/2 z-0 h-[130vh] w-[150vmax]"
        style={{
          x: "-50%",
          background:
            "repeating-conic-gradient(from 0deg, transparent 0deg 25deg, rgba(139,92,246,0.05) 25deg 27deg, transparent 27deg 50deg, rgba(232,121,249,0.04) 50deg 52deg, transparent 52deg 75deg, rgba(34,211,238,0.035) 75deg 77deg, transparent 77deg 100deg)",
          maskImage: "radial-gradient(ellipse 60% 50% at 50% 38%, black 0%, transparent 70%)",
          WebkitMaskImage: "radial-gradient(ellipse 60% 50% at 50% 38%, black 0%, transparent 70%)",
        }}
        animate={{ rotate: 360 }}
        transition={{ duration: 80, repeat: Infinity, ease: "linear" }}
      />

      {/* glow behind wordmark */}
      <div
        aria-hidden
        className="pointer-events-none absolute top-[30%] left-1/2 z-[1] h-[380px] w-[620px] -translate-x-1/2 rounded-full bg-violet-600/15 blur-[120px]"
      />

      {/* scrolling dance floor */}
      <div
        aria-hidden
        className="dance-floor pointer-events-none absolute inset-x-[-12%] bottom-0 z-[1] h-[38%]"
        style={{
          transform: "perspective(600px) rotateX(63deg) scale(1.6)",
          transformOrigin: "top center",
          opacity: 0.5,
          maskImage: "radial-gradient(ellipse 70% 95% at 50% 100%, black 25%, transparent 75%)",
          WebkitMaskImage: "radial-gradient(ellipse 70% 95% at 50% 100%, black 25%, transparent 75%)",
        }}
      />

      <DiscoBall />

      {/* floating confetti pixels */}
      <div aria-hidden className="pointer-events-none absolute inset-0 z-[2]">
        {CONFETTI.map((p, i) => (
          <motion.span
            key={i}
            className="absolute rounded-[1px]"
            style={{
              left: p.left,
              top: p.top,
              width: p.size,
              height: p.size,
              background: p.color,
            }}
            animate={{ y: [0, -16, 0], opacity: [0.12, 0.6, 0.12] }}
            transition={{ duration: p.dur, repeat: Infinity, delay: p.delay, ease: "easeInOut" }}
          />
        ))}
      </div>

      {/* content */}
      <div className="relative z-10 mx-auto flex w-full max-w-4xl flex-1 flex-col items-center justify-center px-6 pt-28 pb-16 text-center sm:pt-32">
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="flex items-center gap-2.5 rounded-full border border-white/10 bg-white/[0.03] px-4 py-2"
        >
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
            <span className="relative h-1.5 w-1.5 rounded-full bg-emerald-400" />
          </span>
          <span className="font-pixel text-[8px] text-zinc-400">
            {VERSION} · open source · MIT
          </span>
        </motion.div>

        {/* the wordmark — same pixel JIMMY as the TUI, alive */}
        <div className="hue-cycle mt-9">
          <PixelWord word="JIMMY" colors={LETTER_COLORS} cell={cell} dance delayBase={0.1} />
        </div>
        <PixelWord
          word="CODE"
          colors="#d4d4d8"
          cell={codeCell}
          delayBase={0.5}
          className="mt-3"
        />

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.9, duration: 0.6 }}
          className="mt-5 font-mono text-sm text-zinc-400 sm:text-base"
        >
          terminal-native AI coding agent
        </motion.p>

        <motion.p
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1, duration: 0.6 }}
          className="mt-4 max-w-xl text-pretty text-[15px] leading-relaxed text-zinc-500 sm:text-base"
        >
          Give it a task — Jimmy reads your codebase, plans, edits files, runs commands and tests,
          and keeps going until the job is done. No browser. No Electron. No tab explosion.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.1, duration: 0.6 }}
        >
          <TypeInput />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.2, duration: 0.6 }}
          className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row"
        >
          <a
            href="#install"
            className="group inline-flex items-center gap-2 rounded-full bg-violet-400 px-6 py-3 text-sm font-semibold text-zinc-950 shadow-[0_0_45px_-12px_rgba(167,139,250,0.65)] transition-all hover:bg-violet-300 hover:shadow-[0_0_60px_-10px_rgba(167,139,250,0.8)]"
          >
            Install Jimmy
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </a>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-6 py-3 text-sm font-medium text-zinc-200 backdrop-blur transition hover:bg-white/10"
          >
            View on GitHub
          </a>
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.35, duration: 0.6 }}
          className="mt-10 flex flex-wrap items-center justify-center gap-x-7 gap-y-2 font-mono text-[12px] text-zinc-600"
        >
          <span>
            <span className="text-zinc-300">9</span> tools
          </span>
          <span>
            <span className="text-zinc-300">3</span> permission modes
          </span>
          <span>
            <span className="text-zinc-300">290+</span> passing tests
          </span>
          <span>
            <span className="text-zinc-300">0</span> browser tabs
          </span>
        </motion.div>
      </div>

      {/* TUI-style status footer — exactly like the app */}
      <div className="relative z-10 border-t border-white/5 bg-black/40">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-2.5 font-mono text-[10px] text-zinc-600 sm:px-6 sm:text-[11px]">
          <span className="truncate">~/Projects/Jimmy-Code</span>
          <span className="hidden md:inline">Ctrl+S sound · Ctrl+P commands · Ctrl+Q quit</span>
          <span className="font-pixel text-[8px] text-violet-400/70">{VERSION}</span>
        </div>
      </div>
    </section>
  );
}

/* ================================================================== */
/*  Loop marquee strip                                                 */
/* ================================================================== */

function LoopStrip() {
  const seq = ["task", "think", "code", "test", "ship"];
  return (
    <section className="overflow-hidden border-y border-white/5 bg-white/[0.015] py-4">
      <div className="relative overflow-hidden" style={MASK_X}>
        <div className="flex w-max animate-[marquee_28s_linear_infinite] items-center">
          {[0, 1].map((half) => (
            <div key={half} className="flex items-center gap-8 pr-8">
              {seq.map((w, i) => (
                <Fragment key={`${half}-${w}`}>
                  <span className="font-mono text-[13px] whitespace-nowrap text-zinc-500">{w}</span>
                  {i < seq.length - 1 && <ChevronRight className="h-3.5 w-3.5 text-violet-500/60" />}
                </Fragment>
              ))}
              <span className="font-mono text-[13px] text-violet-400/50">✦</span>
              <span className="font-mono text-[13px] whitespace-nowrap text-zinc-600">
                give jimmy a task
              </span>
              <span className="font-mono text-[13px] text-violet-400/50">✦</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ================================================================== */
/*  01 — The loop: live session demo with clickable approval            */
/* ================================================================== */

const SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

function Spinner({ label, done, ms }: { label: string; done: string; ms: number }) {
  const [n, setN] = useState(0);
  const [fin, setFin] = useState(false);
  useEffect(() => {
    const iv = setInterval(() => setN((x) => x + 1), 80);
    const t = setTimeout(() => setFin(true), ms);
    return () => {
      clearInterval(iv);
      clearTimeout(t);
    };
  }, [ms]);
  if (fin) return <p className="text-emerald-400/90">{done}</p>;
  return (
    <p className="text-zinc-500">
      {SPIN[n % SPIN.length]} {label}···
    </p>
  );
}

function ApprovalButtons({ onResolve }: { onResolve: (r: ApprovalResult) => void }) {
  const base =
    "rounded-md px-3.5 py-1.5 font-mono text-[11px] font-medium transition-colors duration-200";
  return (
    <div className="mt-4 flex flex-wrap gap-2">
      <button
        type="button"
        onClick={() => onResolve("allow")}
        className={`${base} border border-emerald-400/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25`}
      >
        Allow
      </button>
      <button
        type="button"
        onClick={() => onResolve("session")}
        className={`${base} border border-violet-400/40 bg-violet-500/15 text-violet-300 hover:bg-violet-500/25`}
      >
        Allow session
      </button>
      <button
        type="button"
        onClick={() => onResolve("deny")}
        className={`${base} border border-red-400/40 bg-red-500/10 text-red-300 hover:bg-red-500/20`}
      >
        Deny
      </button>
    </div>
  );
}

function SessionDemo() {
  const [sceneIdx, setSceneIdx] = useState(0);
  const [typed, setTyped] = useState("");
  const [visible, setVisible] = useState(0);
  const [showModal, setShowModal] = useState(false);
  const [result, setResult] = useState<ApprovalResult>("allow");
  const scene = SCENES[sceneIdx];
  const approvalIdx = scene.lines.findIndex((l) => l.k === "approval");
  const approvalLine =
    approvalIdx >= 0
      ? (scene.lines[approvalIdx] as Extract<TermLine, { k: "approval" }>)
      : null;

  /* scene timeline */
  useEffect(() => {
    const sc = SCENES[sceneIdx];
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];

    setTyped("");
    setVisible(0);
    setShowModal(false);
    setResult("allow");

    let t = 650; /* post-typing start */
    const schedule = (start: number) => {
      let acc = start;
      sc.lines.forEach((line, idx) => {
        if (line.k === "approval") {
          timers.push(
            setTimeout(() => {
              if (!cancelled) setShowModal(true);
            }, acc)
          );
          acc += 3600; /* time for the human to decide */
          timers.push(
            setTimeout(() => {
              if (!cancelled) {
                setShowModal(false);
                setVisible((v) => Math.max(v, idx + 1));
              }
            }, acc)
          );
          acc += 500;
        } else if (line.k === "spin") {
          timers.push(
            setTimeout(() => {
              if (!cancelled) setVisible((v) => Math.max(v, idx + 1));
            }, acc)
          );
          acc += line.ms + 550;
        } else {
          timers.push(
            setTimeout(() => {
              if (!cancelled) setVisible((v) => Math.max(v, idx + 1));
            }, acc)
          );
          acc += 850;
        }
      });
      timers.push(
        setTimeout(() => {
          if (!cancelled) setSceneIdx((s) => (s + 1) % SCENES.length);
        }, acc + 4200)
      );
    };

    let i = 0;
    const typeCmd = () => {
      if (cancelled) return;
      if (i <= sc.cmd.length) {
        setTyped(sc.cmd.slice(0, i));
        i += 1;
        timers.push(setTimeout(typeCmd, 22 + Math.random() * 36));
      } else {
        schedule(t);
      }
    };
    timers.push(setTimeout(typeCmd, 650));

    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, [sceneIdx]);

  /* deny → jimmy re-plans, skip ahead */
  useEffect(() => {
    if (result !== "deny") return;
    const t = setTimeout(() => setSceneIdx((s) => (s + 1) % SCENES.length), 1700);
    return () => clearTimeout(t);
  }, [result, sceneIdx]);

  const resolveModal = useCallback((r: ApprovalResult) => {
    setResult(r);
    setShowModal(false);
    setVisible((v) => Math.max(v, approvalIdx + 1));
  }, [approvalIdx]);

  const renderLine = (line: TermLine, idx: number) => {
    if (line.k !== "approval" && result === "deny" && approvalIdx >= 0 && idx > approvalIdx) {
      return null;
    }
    if (line.k === "approval") {
      const text =
        result === "allow"
          ? `✓ ${line.cmd} — approved`
          : result === "session"
            ? `✓ ${line.cmd} — approved for this session`
            : `✗ ${line.cmd} — denied · re-planning`;
      return (
        <p key={idx} className={result === "deny" ? "text-red-400" : "text-emerald-400"}>
          {text}
        </p>
      );
    }
    if (line.k === "spin") {
      return (
        <Spinner key={`${sceneIdx}-${idx}`} label={line.label} done={line.done} ms={line.ms} />
      );
    }
    return (
      <p key={idx} className={toneClass(line.tone)}>
        {line.v}
      </p>
    );
  };

  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-[#0a0a0d]/95 shadow-[0_40px_90px_-30px_rgba(0,0,0,0.9)] backdrop-blur">
      {/* header */}
      <div className="flex items-center gap-3 border-b border-white/[0.06] px-4 py-2.5 font-mono text-[11px] sm:px-5">
        <span className="flex items-center gap-1.5 font-semibold text-violet-300">
          <Terminal className="h-3.5 w-3.5" />
          jimmy
        </span>
        <span className="hidden text-zinc-600 sm:inline">~/Projects/Jimmy-Code</span>
        <span className="ml-auto flex items-center gap-2 text-zinc-500">
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            ask mode
          </span>
          <span className="text-zinc-700">·</span>
          <span className="hidden sm:inline">claude-sonnet-4</span>
          <span className="rounded-sm border border-emerald-400/30 px-1.5 py-0.5 font-pixel text-[7px] text-emerald-400">
            LIVE
          </span>
        </span>
      </div>

      {/* transcript */}
      <div className="relative h-[300px] p-4 font-mono text-[12px] leading-[26px] sm:p-5 sm:text-[13.5px]">
        <div className="flex items-start gap-2">
          <span className="text-violet-400">❯</span>
          <span className="min-w-0 break-words text-zinc-100">{typed}</span>
          {visible === 0 && <BlockCursor />}
        </div>
        <div className="mt-1">{scene.lines.slice(0, visible).map(renderLine)}</div>

        <div className="absolute right-4 bottom-3 flex gap-1.5">
          {SCENES.map((_, i) => (
            <span
              key={i}
              className={`h-1 w-5 rounded-full transition-colors duration-300 ${
                i === sceneIdx ? "bg-violet-400" : "bg-white/10"
              }`}
            />
          ))}
        </div>

        {/* approval overlay */}
        <AnimatePresence>
          {showModal && approvalLine && (
            <motion.div
              key="approval"
              initial={{ opacity: 0, scale: 0.97 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.98 }}
              transition={{ duration: 0.22 }}
              className="absolute inset-0 z-20 flex items-center justify-center bg-black/70 p-4 backdrop-blur-[2px]"
            >
              <div className="w-[min(360px,92%)] rounded-xl border border-violet-400/30 bg-[#12101a] p-4 shadow-2xl shadow-black/60">
                <p className="font-mono text-[10px] tracking-[0.2em] text-violet-300 uppercase">
                  approval required
                </p>
                <p className="mt-2.5 font-mono text-[13px] text-zinc-400">
                  run: <span className="text-zinc-100">{approvalLine.cmd}</span>
                </p>
                <ApprovalButtons onResolve={resolveModal} />
                <p className="mt-3 font-mono text-[10px] text-zinc-600">
                  live demo — your call
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* input bar */}
      <div className="flex items-center gap-2 border-t border-white/[0.06] px-4 py-3 font-mono text-[13px] sm:px-5">
        <span className="text-violet-400">❯</span>
        <span className="text-zinc-600">Ask Jimmy anything…</span>
        <BlockCursor dim />
      </div>

      {/* keybind footer */}
      <div className="flex items-center gap-4 border-t border-white/[0.06] bg-black/30 px-4 py-2 font-mono text-[10px] text-zinc-600 sm:px-5">
        <span>
          <span className="text-zinc-500">^P</span> palette
        </span>
        <span>
          <span className="text-zinc-500">^M</span> model
        </span>
        <span className="hidden sm:inline">
          <span className="text-zinc-500">^O</span> sessions
        </span>
        <span className="ml-auto hidden sm:inline">
          <span className="text-zinc-500">esc</span> stop
        </span>
      </div>
    </div>
  );
}

function LoopSection() {
  return (
    <section id="loop" className="relative scroll-mt-24 py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <SectionHead
          num="01"
          kicker="the loop"
          title={
            <>
              Give it a task.{" "}
              <span className="bg-gradient-to-r from-violet-300 to-fuchsia-400 bg-clip-text text-transparent">
                It loops until it’s done.
              </span>
            </>
          }
          sub="Jimmy isn’t autocomplete. It reads your code, acts with real tools, watches the results and fixes what breaks — think, act, observe, fix, test."
        />

        <Reveal className="mt-10">
          <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-3">
            {LOOP_CHIPS.map((s, i) => (
              <Fragment key={s.label}>
                <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 font-mono text-[13px] text-zinc-300">
                  <s.icon className="h-4 w-4 text-violet-400" />
                  {s.label}
                </span>
                {i < LOOP_CHIPS.length - 1 && <ChevronRight className="h-4 w-4 text-zinc-700" />}
              </Fragment>
            ))}
          </div>
          <p className="mt-5 text-center font-mono text-[12px] text-zinc-600">
            not <s className="decoration-red-400/60 decoration-2">prompt → code → good luck</s>
          </p>
        </Reveal>

        <Reveal delay={0.1} className="mt-12">
          <div className="relative mx-auto max-w-3xl">
            <div
              aria-hidden
              className="absolute -inset-x-10 -top-10 h-44 bg-gradient-to-b from-violet-600/[0.14] to-transparent blur-2xl"
            />
            <SessionDemo />
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/* ================================================================== */
/*  02 — Tools                                                         */
/* ================================================================== */

function ToolsSection() {
  return (
    <section id="tools" className="scroll-mt-24 border-t border-white/5 py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <SectionHead
          num="02"
          kicker="the toolbox"
          title={
            <>
              Nine tools.{" "}
              <span className="bg-gradient-to-r from-violet-300 to-fuchsia-400 bg-clip-text text-transparent">
                Zero plugins.
              </span>
            </>
          }
          sub="No marketplace, no extension hell. Jimmy ships with everything it needs to do real work on a real repository."
        />

        <div className="mt-14 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {TOOLS.map((t, i) => (
            <Reveal key={t.name} delay={(i % 3) * 0.06} className="h-full">
              <SpotlightCard className="p-6">
                <div className="flex items-start justify-between">
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-zinc-300 transition-colors group-hover:text-violet-300">
                    <t.icon className="h-4 w-4" />
                  </span>
                  <span className="font-mono text-[11px] text-zinc-700">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                </div>
                <h3 className="mt-4 font-mono text-[15px] font-medium text-zinc-100">{t.name}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-zinc-500">{t.desc}</p>
              </SpotlightCard>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ================================================================== */
/*  03 — Permissions playground                                         */
/* ================================================================== */

type PermPhase = "boot" | "working" | "approval" | "allowed" | "session" | "denied" | "done";

function PermissionsDemo() {
  const [mode, setMode] = useState<"ask" | "auto" | "full">("ask");
  const [run, setRun] = useState(0);
  const [phase, setPhase] = useState<PermPhase>("boot");

  useEffect(() => {
    setPhase("boot");
    const ts: ReturnType<typeof setTimeout>[] = [];
    ts.push(setTimeout(() => setPhase("working"), 500));
    if (mode === "ask") ts.push(setTimeout(() => setPhase("approval"), 1600));
    else if (mode === "auto") ts.push(setTimeout(() => setPhase("approval"), 2200));
    else ts.push(setTimeout(() => setPhase("done"), 2000));
    return () => ts.forEach(clearTimeout);
  }, [mode, run]);

  const line = (key: string, node: ReactNode) => (
    <motion.p
      key={`${mode}-${run}-${key}`}
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3 }}
      className="leading-7"
    >
      {node}
    </motion.p>
  );

  const showApproval = phase === "approval";
  const resolved = phase === "allowed" || phase === "session" || phase === "denied" || phase === "done";

  return (
    <div className="grid items-center gap-10 lg:grid-cols-[1fr_1.15fr] lg:gap-14">
      {/* mode selector */}
      <div className="space-y-3">
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            onClick={() => setMode(m.id)}
            className={`w-full rounded-2xl border p-5 text-left transition-all duration-300 ${
              mode === m.id
                ? "border-violet-400/50 bg-violet-500/[0.08]"
                : "border-white/10 bg-white/[0.02] hover:border-white/20"
            }`}
          >
            <div className="flex items-center gap-3">
              <span className={`h-2.5 w-2.5 rounded-full ${m.dot}`} />
              <span className="font-display font-semibold text-white">{m.name}</span>
              {mode === m.id && (
                <span className="ml-auto font-pixel text-[7px] text-violet-300">ON</span>
              )}
            </div>
            <p className="mt-2 text-sm leading-relaxed text-zinc-400">{m.blurb}</p>
          </button>
        ))}
        <p className="pt-2 font-mono text-[11px] text-zinc-600">
          default: ask — because trust is earned, not installed.
        </p>
      </div>

      {/* terminal */}
      <div className="rounded-2xl border border-white/10 bg-[#0a0a0d]/95 p-5 font-mono text-[13px] leading-7 shadow-[0_40px_80px_-30px_rgba(0,0,0,0.9)] sm:p-6">
        <div className="mb-4 flex items-center justify-between border-b border-white/[0.06] pb-3 text-xs text-zinc-500">
          <span>permissions — live demo</span>
          <button
            type="button"
            onClick={() => setRun((r) => r + 1)}
            className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-zinc-400 transition hover:text-violet-300"
          >
            ↺ replay
          </button>
        </div>

        <p>
          <span className="text-violet-400">❯</span>{" "}
          <span className="text-zinc-100">jimmy “push it to main”</span>
        </p>

        <AnimatePresence mode="wait">
          <motion.div
            key={`${mode}-${run}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            {(phase === "working" || phase === "approval") && (
              <div>
                {mode === "auto" && line("a1", <span className="text-emerald-400/80">✓ read_files <span className="text-zinc-600">safe · auto-approved</span></span>)}
                {mode === "auto" && line("a2", <span className="text-emerald-400/80">✓ run_tests <span className="text-zinc-600">safe · auto-approved</span></span>)}
                {mode === "full" && line("f1", <span className="text-emerald-400/80">✓ read_files <span className="text-zinc-600">auto</span></span>)}
                {mode === "full" && line("f2", <span className="text-emerald-400/80">✓ run_tests <span className="text-zinc-600">auto</span></span>)}
                {line("want", (
                  <span className="text-zinc-500">
                    wants to run: <span className="text-zinc-300">git push origin main</span>
                  </span>
                ))}
              </div>
            )}

            {phase === "boot" && line("boot", <span className="text-zinc-600">…</span>)}

            {showApproval && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
                className="mt-4 rounded-xl border border-violet-400/30 bg-[#12101a] p-4"
              >
                <p className="text-xs text-violet-300">approval required</p>
                <p className="mt-2 text-sm text-zinc-400">
                  run: <span className="text-white">git push origin main</span>
                </p>
                <ApprovalButtons
                  onResolve={(r) => setPhase(r === "allow" ? "allowed" : r === "session" ? "session" : "denied")}
                />
                <p className="mt-3 font-mono text-[10px] text-zinc-600">live demo — your call</p>
              </motion.div>
            )}

            {phase === "done" && (
              <div>
                {line("f3", <span className="text-emerald-400/80">✓ git push origin main <span className="text-zinc-600">auto · no prompts</span></span>)}
                {line("f4", <span className="text-emerald-400">✓ pushed to origin/main</span>)}
              </div>
            )}

            {resolved && (
              <div className="mt-3">
                {phase === "allowed" &&
                  line("r1", <span className="text-emerald-400">✓ pushed to origin/main — you approved</span>)}
                {phase === "session" &&
                  line("r2", <span className="text-emerald-400">✓ pushed · pushes auto-approved this session</span>)}
                {phase === "denied" &&
                  line("r3", <span className="text-red-400">✗ denied — jimmy stopped, re-planned, touched nothing</span>)}
                {phase === "done" &&
                  line("r4", <span className="text-emerald-400">✓ pushed · zero prompts asked</span>)}
                {line("r5", <span className="text-zinc-600">✦ sneaky escalations: 0</span>)}
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

function PermissionsSection() {
  return (
    <section id="permissions" className="scroll-mt-24 border-t border-white/5 py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <SectionHead
          num="03"
          kicker="permissions"
          title={
            <>
              You hold{" "}
              <span className="bg-gradient-to-r from-violet-300 to-fuchsia-400 bg-clip-text text-transparent">
                the leash.
              </span>
            </>
          }
          sub="Three modes, one rule: no sneaky permission escalation. Try each mode below — then decide Jimmy’s fate when it tries to push."
        />
        <Reveal className="mt-14">
          <PermissionsDemo />
        </Reveal>
      </div>
    </section>
  );
}

/* ================================================================== */
/*  04 — The app                                                       */
/* ================================================================== */

function AppSection() {
  return (
    <section id="app" className="scroll-mt-24 border-t border-white/5 py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <SectionHead
          num="04"
          kicker="the app"
          title={
            <>
              A terminal that{" "}
              <span className="bg-gradient-to-r from-violet-300 to-fuchsia-400 bg-clip-text text-transparent">
                feels like an app.
              </span>
            </>
          }
          sub="Command palette, model picker, session browser, themes, sound. Everything a real interface has — rendered in text."
        />
        <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {APP_FEATURES.map((f, i) => (
            <Reveal key={f.title} delay={(i % 3) * 0.07} className="h-full">
              <SpotlightCard className="p-6">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-violet-300">
                  <f.icon className="h-5 w-5" />
                </span>
                <h3 className="mt-5 font-display text-lg font-semibold tracking-tight text-white">
                  {f.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-zinc-400">{f.desc}</p>
              </SpotlightCard>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ================================================================== */
/*  05 — Install                                                       */
/* ================================================================== */

function InstallSection() {
  const [tab, setTab] = useState<"uv" | "pip">("uv");
  const { copiedKey, copy } = useCopy();
  const steps = INSTALL_STEPS[tab];
  const copiedAll = copiedKey === "all";

  return (
    <section
      id="install"
      className="relative scroll-mt-24 overflow-hidden border-t border-white/5 py-24 md:py-32"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute top-1/2 left-1/2 h-[380px] w-[720px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-violet-600/[0.1] blur-[130px]"
      />
      <div className="relative mx-auto max-w-3xl px-6">
        <SectionHead
          num="05"
          kicker="install"
          title={
            <>
              Three commands and{" "}
              <span className="bg-gradient-to-r from-violet-300 to-fuchsia-400 bg-clip-text text-transparent">
                you’re cooking.
              </span>
            </>
          }
          sub="Clone the repo, sync the dependencies, launch the TUI. Python 3.12 or newer is all Jimmy asks of you."
        />

        <Reveal className="mt-12">
          <div className="flex justify-center">
            <div className="inline-flex rounded-full border border-white/10 bg-white/[0.03] p-1">
              <button
                type="button"
                onClick={() => setTab("uv")}
                className={`rounded-full px-5 py-2 font-mono text-[13px] transition-colors ${
                  tab === "uv"
                    ? "bg-violet-400 font-semibold text-zinc-950"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                uv
                <span className="ml-2 text-[10px] tracking-wider uppercase opacity-60">recommended</span>
              </button>
              <button
                type="button"
                onClick={() => setTab("pip")}
                className={`rounded-full px-5 py-2 font-mono text-[13px] transition-colors ${
                  tab === "pip"
                    ? "bg-violet-400 font-semibold text-zinc-950"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                pip
              </button>
            </div>
          </div>
        </Reveal>

        <Reveal delay={0.08}>
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            className="mt-6 overflow-hidden rounded-2xl border border-white/10 bg-[#0a0a0d]"
          >
            {steps.map((cmd, i) => (
              <div
                key={cmd}
                className="group flex items-center gap-3 border-b border-white/[0.06] px-4 py-3.5 last:border-b-0 sm:px-5"
              >
                <span className="w-6 shrink-0 font-mono text-[11px] text-zinc-600">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <code className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-zinc-200 sm:text-[13.5px]">
                  {cmd}
                </code>
                <CopyButton
                  copied={copiedKey === cmd}
                  onClick={() => copy(cmd, cmd)}
                  label={`Copy: ${cmd}`}
                />
              </div>
            ))}
          </motion.div>
        </Reveal>

        <Reveal delay={0.12}>
          <div className="mt-4 flex justify-center">
            <button
              type="button"
              onClick={() => copy(steps.join("\n"), "all")}
              className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 font-mono text-[12px] transition-colors ${
                copiedAll
                  ? "border-emerald-500/40 text-emerald-400"
                  : "border-white/10 bg-white/[0.03] text-zinc-400 hover:border-white/25 hover:text-zinc-200"
              }`}
            >
              {copiedAll ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              {copiedAll ? "copied to clipboard" : "copy all three"}
            </button>
          </div>
        </Reveal>

        <Reveal delay={0.16}>
          <div className="mt-8 rounded-2xl border border-white/10 bg-[#0a0a0d] p-5">
            <p className="font-mono text-[10px] tracking-[0.25em] text-zinc-600 uppercase">
              then run it
            </p>
            <div className="mt-4 space-y-3">
              {RUN_CMDS.map((r) => (
                <div key={r.cmd} className="flex items-center gap-3">
                  <span className="shrink-0 text-violet-400">$</span>
                  <code className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-zinc-200 sm:text-[13.5px]">
                    {r.cmd}
                  </code>
                  <span className="hidden shrink-0 font-mono text-[11px] text-zinc-600 md:inline">
                    {r.comment}
                  </span>
                  <CopyButton
                    copied={copiedKey === r.cmd}
                    onClick={() => copy(r.cmd, r.cmd)}
                    label={`Copy: ${r.cmd}`}
                  />
                </div>
              ))}
            </div>
          </div>
        </Reveal>

        <Reveal delay={0.2}>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-center font-mono text-[12px] text-zinc-600">
            <span>python 3.12+ · a terminal · an api key</span>
            <span className="text-zinc-800">·</span>
            <span>
              sessions → <span className="text-zinc-400">~/.jimmy/sessions.db</span>
            </span>
            <span className="text-zinc-800">·</span>
            <span>
              models → <span className="text-zinc-400">~/.jimmy/models.json</span>
            </span>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/* ================================================================== */
/*  06 — Controls                                                      */
/* ================================================================== */

function ShortcutsSection() {
  return (
    <section id="shortcuts" className="scroll-mt-24 border-t border-white/5 py-24 md:py-32">
      <div className="mx-auto max-w-4xl px-6">
        <SectionHead
          num="06"
          kicker="controls"
          title={
            <>
              Built for{" "}
              <span className="bg-gradient-to-r from-violet-300 to-fuchsia-400 bg-clip-text text-transparent">
                keyboards.
              </span>
            </>
          }
          sub="Every action is a keystroke away — the way a terminal app should be."
        />
        <div className="mt-12 grid gap-x-12 gap-y-4 sm:grid-cols-2">
          {SHORTCUTS.map((s, i) => (
            <Reveal key={s.label} delay={(i % 2) * 0.05}>
              <div className="flex items-center gap-3">
                <span className="flex shrink-0 gap-1">
                  {s.keys.map((k) => (
                    <Kbd key={k}>{k}</Kbd>
                  ))}
                </span>
                <span className="flex-1 border-b border-dotted border-white/10" />
                <span className="text-sm text-zinc-400">{s.label}</span>
              </div>
            </Reveal>
          ))}
        </div>
        <Reveal className="mt-14">
          <p className="text-center font-mono text-[11px] tracking-[0.25em] text-zinc-600 uppercase">
            or just type / in the input
          </p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {SLASH.map((c) => (
              <span
                key={c}
                className="rounded-md border border-white/10 bg-white/[0.03] px-2.5 py-1 font-mono text-[12px] text-zinc-400"
              >
                <span className="text-violet-400/80">/</span>
                {c}
              </span>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/* ================================================================== */
/*  Closing + footer                                                   */
/* ================================================================== */

function Closing() {
  const { copiedKey, copy } = useCopy();
  const copied = copiedKey === "clone";
  return (
    <section className="relative overflow-hidden border-t border-white/5 py-24 md:py-32">
      <div
        aria-hidden
        className="pointer-events-none absolute top-1/2 left-1/2 h-[380px] w-[720px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-violet-600/[0.12] blur-[130px]"
      />
      <div className="relative mx-auto max-w-2xl px-6 text-center">
        <PixelWord word="JIMMY" colors={LETTER_COLORS} cell={5} />
        <Reveal className="mt-8">
          <h2 className="font-display text-4xl font-bold tracking-tight text-white sm:text-5xl md:text-6xl md:leading-[1.05]">
            Give Jimmy a task.{" "}
            <span className="bg-gradient-to-r from-violet-300 to-fuchsia-400 bg-clip-text text-transparent">
              Let Jimmy cook.
            </span>
          </h2>
        </Reveal>
        <Reveal delay={0.1}>
          <button
            type="button"
            onClick={() => copy(CLONE_CMD, "clone")}
            className="group mx-auto mt-9 inline-flex max-w-full items-center gap-3 rounded-full border border-white/10 bg-white/[0.03] py-2 pr-2 pl-5 font-mono text-[12px] backdrop-blur transition-colors hover:border-white/20 sm:text-[13px]"
          >
            <span className="shrink-0 text-violet-400">$</span>
            <span className="truncate text-zinc-300">{CLONE_CMD}</span>
            <span
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border transition-colors ${
                copied
                  ? "border-emerald-500/40 text-emerald-400"
                  : "border-white/10 bg-white/5 text-zinc-500 group-hover:text-zinc-200"
              }`}
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            </span>
          </button>
          <p className="mt-4 font-mono text-[12px] text-zinc-600">
            then{" "}
            <a
              href="#install"
              className="text-violet-400/80 underline decoration-violet-400/30 underline-offset-4 transition-colors hover:text-violet-300"
            >
              uv sync → full install guide
            </a>
          </p>
        </Reveal>
        <Reveal delay={0.16}>
          <p className="mt-10 font-mono text-sm text-zinc-600">
            task <span className="text-violet-400">→</span> think{" "}
            <span className="text-violet-400">→</span> code{" "}
            <span className="text-violet-400">→</span> test{" "}
            <span className="text-violet-400">→</span> ship
          </p>
        </Reveal>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-white/5 py-14">
      <div className="mx-auto max-w-6xl px-6">
        <div className="grid gap-12 md:grid-cols-[1.5fr_1fr_1fr_1fr]">
          <div>
            <Logo />
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-zinc-500">
              The terminal-native AI coding agent. Give it a task — it reads, edits, tests and ships
              until the job is done.
            </p>
            <a
              href={REPO_URL}
              target="_blank"
              rel="noreferrer"
              aria-label="GitHub"
              className="mt-5 flex h-9 w-9 items-center justify-center rounded-full border border-white/10 text-zinc-400 transition hover:border-violet-400/40 hover:text-white"
            >
             
            </a>
          </div>
          {FOOTER_COLS.map((c) => (
            <div key={c.h}>
              <p className="font-mono text-[11px] font-semibold tracking-[0.2em] text-zinc-400 uppercase">
                {c.h}
              </p>
              <ul className="mt-4 space-y-2.5">
                {c.links.map(([label, href]) => (
                  <li key={label}>
                    <a
                      href={href}
                      target={href.startsWith("http") ? "_blank" : undefined}
                      rel={href.startsWith("http") ? "noreferrer" : undefined}
                      className="text-sm text-zinc-500 transition-colors hover:text-violet-300"
                    >
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-12 flex flex-col items-center justify-between gap-3 border-t border-white/5 pt-8 sm:flex-row">
          <p className="font-mono text-[12px] text-zinc-600">MIT license</p>
          <p className="font-pixel text-[8px] text-violet-400/60">{VERSION}</p>
          <p className="font-mono text-[12px] text-zinc-600">
            task → think → code → test → ship
          </p>
        </div>
      </div>
    </footer>
  );
}

/* ================================================================== */
/*  Page                                                               */
/* ================================================================== */

export default function Page() {
  const { scrollYProgress } = useScroll();

  return (
    <MotionConfig reducedMotion="user">
      <div className="relative min-h-screen bg-[#030304] font-display text-zinc-300 antialiased selection:bg-violet-400/30 selection:text-white">
        <style>{GLOBAL_CSS}</style>

        <motion.div
          style={{ scaleX: scrollYProgress }}
          className="fixed inset-x-0 top-0 z-[60] h-[2px] origin-left bg-gradient-to-r from-violet-400 to-fuchsia-500"
        />

        <Nav />

        <main>
          <Hero />
          <LoopStrip />
          <LoopSection />
          <ToolsSection />
          <PermissionsSection />
          <AppSection />
          <InstallSection />
          <ShortcutsSection />
          <Closing />
        </main>

        <Footer />
      </div>
    </MotionConfig>
  );
}