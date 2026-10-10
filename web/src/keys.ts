/**
 * The page's keyboard rules (M11; contract §5.8.10 focus rule, §5.8.11 shortcuts and Esc) — pure, DOM-free and
 * unit-tested (`web/test/plane.test.ts`). `main.ts` describes the `keydown` event and its target and acts on the
 * answer. This step binds the history shortcuts (Ctrl / ⌘+Z undo, Ctrl / ⌘+Shift+Z redo) and Esc; Delete, Backspace
 * and Ctrl / ⌘+Shift+L (§5.8.10, §5.8.7) join `shortcut_action` with the selection and library modules.
 */

/** A `keydown` target: tag name, an `<input>`'s type (the browser's normalised `type`), `contenteditable`. */
export interface KeyTarget {
  tag: string;
  type?: string | null;
  editable?: boolean;
}

/** `<input>` types that do not take typed text: they take the shortcuts (§5.8.10). Every other type, missing or
 * unknown included (the equation field is `type="text"`), is text-like. */
const NON_TEXT_INPUTS: ReadonlySet<string> = new Set(["range", "checkbox", "radio", "button", "submit", "reset", "file", "color", "image", "hidden"]);

/** Whether the focus is in a text-like target, where the browser keeps its own keys (§5.8.10): a `<textarea>`, a
 * `contenteditable` element, or an `<input>` that takes text. `<select>`, buttons, range, checkbox and file inputs are
 * not text-like. */
export function is_typing_target(t: KeyTarget | null): boolean {
  if (t === null) return false;
  if (t.editable === true) return true;
  const tag = t.tag.toLowerCase();
  if (tag === "textarea") return true;
  if (tag !== "input") return false;
  return !NON_TEXT_INPUTS.has((t.type ?? "").toLowerCase());
}

/** The part of a `KeyboardEvent` the shortcuts read. */
export interface KeyLike {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  isComposing?: boolean;
  target: KeyTarget | null;
}

export type ShortcutAction = "undo" | "redo";

/**
 * The shortcut a `keydown` stands for (§5.8.11), or `null` (the event is left to the browser): `Ctrl+Z` / `⌘Z` undo
 * and `Ctrl+Shift+Z` / `⌘⇧Z` redo — exactly one of Ctrl and Meta, no Alt, not during an IME composition, not with the
 * focus in a text-like target, and nothing while previewing (the scene is read-only, §5.8.14). `Ctrl+Y` is not bound.
 * `has_selection` is read by the selection shortcuts (Delete, Backspace) that join this table later.
 */
export function shortcut_action(ev: KeyLike, ctx: { has_selection: boolean; previewing: boolean }): ShortcutAction | null {
  if (ctx.previewing || ev.isComposing === true || is_typing_target(ev.target)) return null;
  if (ev.ctrlKey === ev.metaKey || ev.altKey) return null;
  if (ev.key !== "z" && ev.key !== "Z") return null;
  return ev.shiftKey ? "redo" : "undo";
}

export type EscapeAction = "field" | "leave_preview" | "clear_selection";

/**
 * What one Esc does (§5.8.11; the user's answer to Q3), exactly one thing: with the focus in the equation field its own
 * Esc (the field drops the typed text and stops the event); during a drag (object, vertical, ring or arrow) nothing;
 * while previewing, return to the edit view (the selection is kept); in the edit view, clear the selection (nothing
 * when there is none). Esc never opens or closes the library.
 */
export function escape_action(s: { in_equation: boolean; dragging: boolean; previewing: boolean; has_selection: boolean }): EscapeAction | null {
  if (s.in_equation) return "field";
  if (s.dragging) return null;
  if (s.previewing) return "leave_preview";
  return s.has_selection ? "clear_selection" : null;
}
