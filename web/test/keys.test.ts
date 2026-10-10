/** Tests of the page's keyboard rules (`web/src/keys.ts`; contract §5.8.10 focus rule, §5.8.11 shortcuts and Esc): the
 * text-like target table, the undo / redo shortcut table (Ctrl and ⌘ forms, modifier combinations, IME, previewing)
 * and the Esc order. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { escape_action, is_typing_target, shortcut_action } from "../src/keys.js";
import type { KeyLike, KeyTarget } from "../src/keys.js";

const BODY: KeyTarget = { tag: "BODY" };
const key = (k: string, mods: Partial<Omit<KeyLike, "key">> = {}): KeyLike =>
  ({ key: k, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, isComposing: false, target: BODY, ...mods });
const EDIT = { has_selection: true, previewing: false };

test("is_typing_target: textarea, contenteditable and text-like inputs keep their keys; others take the shortcuts", () => {
  for (const type of ["text", "search", "number", "email", "url", "tel", "password", "", null, undefined, "weird", "TEXT", "date"]) {
    assert.equal(is_typing_target({ tag: "INPUT", type }), true, `input type ${String(type)}`);
  }
  for (const type of ["range", "checkbox", "radio", "button", "submit", "reset", "file", "color", "image", "hidden", "Range"]) {
    assert.equal(is_typing_target({ tag: "INPUT", type }), false, `input type ${type}`);
  }
  assert.equal(is_typing_target({ tag: "TEXTAREA" }), true);
  assert.equal(is_typing_target({ tag: "DIV", editable: true }), true);
  assert.equal(is_typing_target({ tag: "DIV", editable: false }), false);
  for (const tag of ["SELECT", "BUTTON", "BODY", "CANVAS", "SECTION"]) assert.equal(is_typing_target({ tag }), false, tag);
  assert.equal(is_typing_target(null), false);
});

test("shortcut_action: Ctrl / ⌘+Z undo, Ctrl / ⌘+Shift+Z redo; the focus rule, IME and preview (§5.8.10, §5.8.11)", () => {
  assert.equal(shortcut_action(key("z", { ctrlKey: true }), EDIT), "undo");
  assert.equal(shortcut_action(key("z", { metaKey: true }), EDIT), "undo", "⌘Z");
  assert.equal(shortcut_action(key("Z", { ctrlKey: true, shiftKey: true }), EDIT), "redo");
  assert.equal(shortcut_action(key("Z", { metaKey: true, shiftKey: true }), EDIT), "redo", "⌘⇧Z");
  assert.equal(shortcut_action(key("z", { ctrlKey: true, shiftKey: true }), EDIT), "redo", "lower-case key with Shift");
  assert.equal(shortcut_action(key("Z", { ctrlKey: true }), { has_selection: false, previewing: false }), "undo", "Caps Lock; no selection needed");
  // not bound
  assert.equal(shortcut_action(key("z"), EDIT), null, "plain z");
  assert.equal(shortcut_action(key("y", { ctrlKey: true }), EDIT), null, "Ctrl+Y is not bound");
  assert.equal(shortcut_action(key("z", { ctrlKey: true, altKey: true }), EDIT), null, "Ctrl+Alt+Z");
  assert.equal(shortcut_action(key("z", { metaKey: true, altKey: true }), EDIT), null, "⌘⌥Z");
  assert.equal(shortcut_action(key("z", { ctrlKey: true, metaKey: true }), EDIT), null, "Ctrl+⌘+Z");
  assert.equal(shortcut_action(key("z", { altKey: true }), EDIT), null, "Alt+Z");
  assert.equal(shortcut_action(key("z", { shiftKey: true }), EDIT), null, "Shift+Z");
  // IME composition and text-like targets: left to the browser
  assert.equal(shortcut_action(key("z", { ctrlKey: true, isComposing: true }), EDIT), null, "IME");
  assert.equal(shortcut_action(key("z", { ctrlKey: true, target: { tag: "INPUT", type: "text" } }), EDIT), null, "equation field");
  assert.equal(shortcut_action(key("Z", { metaKey: true, shiftKey: true, target: { tag: "TEXTAREA" } }), EDIT), null);
  assert.equal(shortcut_action(key("z", { ctrlKey: true, target: { tag: "SPAN", editable: true } }), EDIT), null);
  // non-text targets take it: a focused button, slider, checkbox, select
  for (const target of [{ tag: "BUTTON" }, { tag: "INPUT", type: "range" }, { tag: "INPUT", type: "checkbox" }, { tag: "SELECT" }]) {
    assert.equal(shortcut_action(key("z", { ctrlKey: true, target }), EDIT), "undo", JSON.stringify(target));
  }
  // previewing: no shortcut acts (board entries included, §5.8.14)
  for (const ev of [key("z", { ctrlKey: true }), key("z", { metaKey: true }), key("Z", { ctrlKey: true, shiftKey: true }), key("Z", { metaKey: true, shiftKey: true })]) {
    assert.equal(shortcut_action(ev, { has_selection: true, previewing: true }), null);
    assert.equal(shortcut_action(ev, { has_selection: false, previewing: true }), null);
  }
});

test("escape_action: the equation field's own Esc > nothing during a drag > leave 預覽 > clear the selection > nothing (Q3)", () => {
  const all = [true, false];
  for (const dragging of all) for (const previewing of all) for (const has_selection of all) {
    assert.equal(escape_action({ in_equation: true, dragging, previewing, has_selection }), "field");
    const want = dragging ? null : previewing ? "leave_preview" : has_selection ? "clear_selection" : null;
    assert.equal(escape_action({ in_equation: false, dragging, previewing, has_selection }), want,
      JSON.stringify({ dragging, previewing, has_selection }));
  }
});
