import { useState } from 'react';

// How a panel of figures is looked at: which of its views, and which of its groups are
// open (none at first, so that it is seen at a glance). Ways of looking, which the
// user keeps from one visit to the next, each panel under keys of its own.

function read(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    // No storage (a private window, blocked data): the page works without.
    return null;
  }
}

function write(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Nothing to keep it in: it holds for this visit.
  }
}

function storedMode(key, modes) {
  const found = read(key);
  return modes.includes(found) ? found : modes[0];
}

function storedOpen(key) {
  try {
    const found = JSON.parse(read(key) ?? '[]');
    return Array.isArray(found) && found.every((g) => typeof g === 'string')
      ? found
      : [];
  } catch {
    return [];
  }
}

/**
 * A choice among `choices` (the first at first), kept under `key` of the browser's
 * storage: the unit a person reads the figures in, say.
 */
export function useStoredChoice(key, choices) {
  const [choice, setChoiceState] = useState(() => storedMode(key, choices));

  const setChoice = (next) => {
    setChoiceState(next);
    write(key, next);
  };

  return [choice, setChoice];
}

/**
 * A set of keys kept under `key` of the browser's storage: the groups of a list that
 * are folded away, say.
 */
export function useStoredSet(key) {
  const [keys, setKeysState] = useState(() => new Set(storedOpen(key)));

  const setKeys = (next) => {
    setKeysState(next);
    write(key, JSON.stringify([...next]));
  };

  return [keys, setKeys];
}

/**
 * The view chosen (the first of `modes` at first) and the groups that are open, kept
 * under `modeKey` and `openKey` of the browser's storage.
 */
export function useViewState({ modeKey, openKey, modes }) {
  const [mode, setModeState] = useState(() => storedMode(modeKey, modes));
  const [open, setOpenState] = useState(() => storedOpen(openKey));

  const setMode = (next) => {
    setModeState(next);
    write(modeKey, next);
  };

  const setOpen = (next) => {
    setOpenState(next);
    write(openKey, JSON.stringify(next));
  };

  const toggleGroup = (group) =>
    setOpen(
      open.includes(group)
        ? open.filter((found) => found !== group)
        : [...open, group],
    );

  return { mode, setMode, open, toggleGroup, setOpen };
}
