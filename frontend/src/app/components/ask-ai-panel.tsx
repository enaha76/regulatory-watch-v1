import { useState, useEffect, useRef } from "react";
import {
  Sparkles,
  X,
  Mic,
  Send,
  Bot,
  User as UserIcon,
  Check,
  Archive,
  ThumbsUp,
  ThumbsDown,
  FileDown,
  ExternalLink,
  StopCircle,
  Loader2,
} from "lucide-react";
import { Button } from "@/app/components/ui/button";
import { Sheet, SheetContent } from "@/app/components/ui/sheet";

// ─────────────────────────────────────────────────────────────────────
// Ask AI panel — STATIC mock UI.
//
// This is the visual layer for an AI assistant scoped to a single
// alert. The conversation and voice flow are pre-scripted so the UX
// can be evaluated end-to-end before the real model + tool-use
// backend is wired in. When development reaches that point, replace:
//   - `MOCK_CONVERSATION`       → a streaming chat from the LLM
//   - `MOCK_VOICE_TRANSCRIPT`   → a real STT pipeline (Whisper, etc.)
//   - the action-card "Confirm" handlers → real PATCH calls
//
// The skeleton below is intentionally a faithful preview of the
// production shape: assistant turns, tool-use proposal cards, voice
// recording with a live waveform, suggestion chips when the chat is
// empty. Everything you see can be wired to real APIs later without
// touching layout.
// ─────────────────────────────────────────────────────────────────────

export interface AskAiContext {
  /** Short string shown as the context chip at the top of the panel. */
  alertTitle?: string;
  /** Score, summary, deadline, etc. that the model would condition on
   *  in the real implementation. Surface only the title and authority
   *  in the UI. */
  authority?: string;
}

type ChatTurn =
  | { role: "user"; text: string }
  | { role: "assistant"; text: string; thinking?: boolean }
  | {
      role: "action";
      title: string;
      description: string;
      cta: string;
      icon: "archive" | "relevant" | "not_relevant" | "draft" | "export";
      done?: boolean;
    };

const SUGGESTIONS = [
  "What's the deadline?",
  "Who's affected by this?",
  "Draft a Slack note for my team",
  "Find similar past alerts",
  "Mark this as not relevant",
];

const MOCK_VOICE_TRANSCRIPT =
  "What's the deadline and who exactly does this apply to?";

// A fully scripted conversation that walks the user through the
// product's intended capabilities: free-form Q&A, citations, an
// agent-style action proposal, and a follow-up.
const MOCK_REPLY_FOR_DEADLINE: ChatTurn[] = [
  {
    role: "assistant",
    text:
      "Two deadlines apply.\n\n" +
      "• **Comments due:** July 6, 2026 — reporting obligation on importers " +
      "of defense articles.\n" +
      "• **Effective date:** not yet set — this is a *proposed rule*, so the " +
      "final regulation will publish later with its own compliance date.\n\n" +
      "The proposal applies to any importer registered under 27 CFR part 447, " +
      "but only the Russian Federation remains on the prohibited-origin list.",
  },
  {
    role: "action",
    title: "Mark this alert as relevant",
    description:
      "Based on your AOI (CN, Sanctions & Export Control), this is a likely match. " +
      "Mark as relevant to train your filters?",
    cta: "Mark relevant",
    icon: "relevant",
  },
];

export function AskAiPanel({
  open,
  onOpenChange,
  context,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  context?: AskAiContext;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [recording, setRecording] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Reset the conversation when the panel closes — the model has no
  // memory across sessions in the static prototype.
  useEffect(() => {
    if (!open) {
      setTurns([]);
      setInput("");
      setThinking(false);
      setRecording(false);
    }
  }, [open]);

  // Auto-scroll to the newest turn whenever the list grows.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, thinking]);

  // Mock send — pretends to think for a beat, then replies. The
  // reply ladder is hand-written; pick the most-relevant scripted
  // response so the demo feels grounded.
  const sendMessage = (text: string) => {
    if (!text.trim()) return;
    setInput("");
    const userTurn: ChatTurn = { role: "user", text: text.trim() };
    setTurns((prev) => [...prev, userTurn]);
    setThinking(true);
    window.setTimeout(() => {
      setThinking(false);
      // Always append the canned demo reply for now. In production
      // this becomes a streamed response from the LLM with tool-use.
      setTurns((prev) => [...prev, ...MOCK_REPLY_FOR_DEADLINE]);
    }, 1100);
  };

  // Voice flow — fake the STT pipeline with a delay. Tap to start,
  // tap again to stop. While recording the waveform animates and a
  // pulsing red dot signals "live".
  const toggleRecording = () => {
    if (recording) {
      setRecording(false);
      // Simulate transcription delay then send the mock transcript.
      window.setTimeout(() => sendMessage(MOCK_VOICE_TRANSCRIPT), 350);
    } else {
      setRecording(true);
      // Auto-stop after ~3.5s in the prototype so the user doesn't
      // have to tap twice during a demo.
      window.setTimeout(() => {
        setRecording((r) => {
          if (!r) return r;
          window.setTimeout(() => sendMessage(MOCK_VOICE_TRANSCRIPT), 350);
          return false;
        });
      }, 3500);
    }
  };

  // When the user clicks "Confirm" on an action card, mutate that
  // turn into its `done: true` form. In production the same handler
  // would call the real PATCH and surface the success/error.
  const confirmAction = (idx: number) => {
    setTurns((prev) =>
      prev.map((t, i) =>
        i === idx && t.role === "action" ? { ...t, done: true } : t,
      ),
    );
  };

  const cancelAction = (idx: number) => {
    setTurns((prev) => prev.filter((_, i) => i !== idx));
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="!max-w-none w-[440px] sm:w-[480px] p-0 flex flex-col gap-0"
      >
        {/* Header */}
        <div className="px-5 py-4 border-b flex items-start gap-3">
          <div className="size-9 rounded-lg bg-gradient-to-br from-primary to-accent flex items-center justify-center shrink-0">
            <Sparkles className="size-4 text-primary-foreground" />
          </div>
          <div className="flex-1 min-w-0">
            <h3
              className="leading-tight"
              style={{
                fontWeight: "var(--font-weight-bold)",
                fontSize: "var(--text-base)",
              }}
            >
              Ask AI
            </h3>
            <p
              className="text-muted-foreground"
              style={{ fontSize: "var(--text-xs)" }}
            >
              Voice or text · scoped to this alert
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onOpenChange(false)}
            className="size-8"
          >
            <X className="size-4" />
          </Button>
        </div>

        {/* Context chip — what the AI is looking at */}
        {context?.alertTitle && (
          <div className="px-5 pt-3">
            <div className="rounded-lg border bg-muted/40 px-3 py-2 text-muted-foreground flex items-start gap-2">
              <span
                className="size-1.5 rounded-full bg-accent mt-1.5 shrink-0"
                aria-hidden
              />
              <div className="min-w-0">
                <p
                  className="text-foreground line-clamp-2"
                  style={{
                    fontSize: "var(--text-sm)",
                    fontWeight: "var(--font-weight-medium)",
                  }}
                >
                  {context.alertTitle}
                </p>
                {context.authority && (
                  <p style={{ fontSize: "var(--text-xs)" }}>
                    {context.authority}
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Conversation area */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-5 py-4 space-y-4"
        >
          {turns.length === 0 ? (
            <EmptyState onPick={sendMessage} />
          ) : (
            turns.map((turn, idx) => (
              <ChatBubble
                key={idx}
                turn={turn}
                onConfirm={() => confirmAction(idx)}
                onCancel={() => cancelAction(idx)}
              />
            ))
          )}
          {thinking && <ThinkingBubble />}
        </div>

        {/* Composer */}
        <Composer
          value={input}
          onChange={setInput}
          onSend={() => sendMessage(input)}
          onToggleRecord={toggleRecording}
          recording={recording}
        />
      </SheetContent>
    </Sheet>
  );
}

// ── Empty state — suggestion chips ────────────────────────────────

function EmptyState({ onPick }: { onPick: (s: string) => void }) {
  return (
    <div className="space-y-4 pt-2">
      <div className="text-center pt-4 pb-2">
        <div className="size-12 mx-auto rounded-full bg-gradient-to-br from-primary/15 to-accent/15 flex items-center justify-center mb-3">
          <Sparkles className="size-5 text-primary" />
        </div>
        <p
          className="text-foreground"
          style={{
            fontSize: "var(--text-sm)",
            fontWeight: "var(--font-weight-medium)",
          }}
        >
          Ask anything about this alert
        </p>
        <p
          className="text-muted-foreground mt-1"
          style={{ fontSize: "var(--text-xs)" }}
        >
          Try a question, or hold the mic and speak.
        </p>
      </div>
      <div className="space-y-1.5">
        <p
          className="text-muted-foreground uppercase tracking-wider px-1"
          style={{
            fontSize: "var(--text-xs)",
            fontWeight: "var(--font-weight-medium)",
          }}
        >
          Suggestions
        </p>
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            className="w-full text-left rounded-md border bg-card hover:bg-muted/60 hover:border-primary/30 transition px-3 py-2 group"
          >
            <span
              className="text-foreground group-hover:text-primary"
              style={{ fontSize: "var(--text-sm)" }}
            >
              {s}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Chat bubbles ──────────────────────────────────────────────────

function ChatBubble({
  turn,
  onConfirm,
  onCancel,
}: {
  turn: ChatTurn;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (turn.role === "user") {
    return (
      <div className="flex items-start gap-2 justify-end">
        <div
          className="rounded-lg rounded-tr-sm bg-primary text-primary-foreground px-3 py-2 max-w-[80%] whitespace-pre-wrap"
          style={{ fontSize: "var(--text-sm)" }}
        >
          {turn.text}
        </div>
        <div className="size-7 rounded-full bg-muted flex items-center justify-center shrink-0">
          <UserIcon className="size-3.5 text-muted-foreground" />
        </div>
      </div>
    );
  }
  if (turn.role === "assistant") {
    return (
      <div className="flex items-start gap-2">
        <div className="size-7 rounded-full bg-gradient-to-br from-primary to-accent flex items-center justify-center shrink-0">
          <Bot className="size-3.5 text-primary-foreground" />
        </div>
        <div
          className="rounded-lg rounded-tl-sm bg-card border px-3 py-2 max-w-[85%] whitespace-pre-wrap leading-relaxed"
          style={{ fontSize: "var(--text-sm)" }}
        >
          {turn.text.split("\n").map((line, i) => (
            <p key={i} className={i > 0 ? "mt-1" : ""}>
              <RenderInline text={line} />
            </p>
          ))}
        </div>
      </div>
    );
  }
  // Action proposal
  return <ActionCard turn={turn} onConfirm={onConfirm} onCancel={onCancel} />;
}

// Tiny markdown-bold renderer (`**foo**` → <strong>foo</strong>) so
// the canned replies feel typeset without pulling in a markdown lib.
function RenderInline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") && p.endsWith("**") ? (
          <strong key={i}>{p.slice(2, -2)}</strong>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

function ThinkingBubble() {
  return (
    <div className="flex items-start gap-2">
      <div className="size-7 rounded-full bg-gradient-to-br from-primary to-accent flex items-center justify-center shrink-0">
        <Bot className="size-3.5 text-primary-foreground" />
      </div>
      <div className="rounded-lg rounded-tl-sm bg-card border px-3 py-2.5 inline-flex items-center gap-1.5">
        <span className="size-1.5 rounded-full bg-muted-foreground/60 animate-pulse [animation-delay:-0.3s]" />
        <span className="size-1.5 rounded-full bg-muted-foreground/60 animate-pulse [animation-delay:-0.15s]" />
        <span className="size-1.5 rounded-full bg-muted-foreground/60 animate-pulse" />
      </div>
    </div>
  );
}

// ── Action / tool-use card ────────────────────────────────────────

function ActionCard({
  turn,
  onConfirm,
  onCancel,
}: {
  turn: Extract<ChatTurn, { role: "action" }>;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const Icon = ACTION_ICONS[turn.icon];

  if (turn.done) {
    return (
      <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2.5 flex items-center gap-2">
        <Check className="size-4 text-emerald-600 shrink-0" />
        <p
          className="text-foreground"
          style={{ fontSize: "var(--text-sm)" }}
        >
          Done — {turn.title.toLowerCase()}.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-accent/40 bg-accent/[0.04] overflow-hidden">
      <div className="px-3.5 py-2.5 flex items-start gap-2.5 border-b border-accent/20">
        <div className="size-7 rounded-md bg-accent/15 flex items-center justify-center shrink-0">
          <Icon className="size-3.5 text-accent-foreground" />
        </div>
        <div className="flex-1 min-w-0">
          <p
            className="text-foreground"
            style={{
              fontSize: "var(--text-sm)",
              fontWeight: "var(--font-weight-medium)",
            }}
          >
            {turn.title}
          </p>
          <p
            className="text-muted-foreground mt-0.5"
            style={{ fontSize: "var(--text-xs)" }}
          >
            {turn.description}
          </p>
        </div>
      </div>
      <div className="px-3.5 py-2 flex items-center justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button size="sm" onClick={onConfirm} className="gap-1.5">
          <Check className="size-3.5" />
          {turn.cta}
        </Button>
      </div>
    </div>
  );
}

const ACTION_ICONS = {
  archive: Archive,
  relevant: ThumbsUp,
  not_relevant: ThumbsDown,
  draft: ExternalLink,
  export: FileDown,
} as const;

// ── Composer (input + voice button + send) ────────────────────────

function Composer({
  value,
  onChange,
  onSend,
  onToggleRecord,
  recording,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onToggleRecord: () => void;
  recording: boolean;
}) {
  return (
    <div className="border-t bg-card px-4 py-3 space-y-2">
      {recording && <RecordingBar />}
      <div className="flex items-end gap-2">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          rows={1}
          placeholder={recording ? "Listening…" : "Type or press the mic"}
          disabled={recording}
          className="flex-1 resize-none rounded-md border bg-background px-3 py-2 outline-none focus:ring-2 focus:ring-ring/30 disabled:opacity-60 max-h-32"
          style={{ fontSize: "var(--text-sm)" }}
        />
        <Button
          variant={recording ? "destructive" : "outline"}
          size="icon"
          onClick={onToggleRecord}
          aria-label={recording ? "Stop recording" : "Start voice input"}
          className="size-10 shrink-0"
        >
          {recording ? (
            <StopCircle className="size-4" />
          ) : (
            <Mic className="size-4" />
          )}
        </Button>
        <Button
          size="icon"
          onClick={onSend}
          disabled={!value.trim() || recording}
          aria-label="Send"
          className="size-10 shrink-0"
        >
          <Send className="size-4" />
        </Button>
      </div>
      <p
        className="text-muted-foreground px-1"
        style={{ fontSize: "var(--text-xs)" }}
      >
        Static preview · the real assistant will use voice + tools to
        act on your behalf.
      </p>
    </div>
  );
}

// Live waveform shown while the user is recording. Pure CSS — twelve
// thin bars with offset animation. No mic-stream wired up yet.
function RecordingBar() {
  return (
    <div className="flex items-center gap-2 rounded-md bg-destructive/10 border border-destructive/30 px-3 py-2">
      <span className="size-2 rounded-full bg-destructive animate-pulse shrink-0" />
      <p
        className="text-destructive font-medium shrink-0"
        style={{ fontSize: "var(--text-xs)" }}
      >
        Listening
      </p>
      <div className="flex-1 flex items-center justify-center gap-0.5 h-5">
        {Array.from({ length: 18 }).map((_, i) => (
          <span
            key={i}
            className="w-0.5 bg-destructive rounded-full"
            style={{
              animation: `regwatch-wave 0.9s ease-in-out infinite`,
              animationDelay: `${(i % 9) * 0.07}s`,
              height: "30%",
            }}
          />
        ))}
      </div>
      <Loader2
        className="size-3.5 text-destructive animate-spin shrink-0"
        aria-hidden
      />
    </div>
  );
}
