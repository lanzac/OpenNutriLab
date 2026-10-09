import { createContext, useContext, useState } from 'react';

// How the day against the needs is shown: gauges, or the table with every figure,
// and which groups of nutrients are open: none at first, so that the day is seen at a
// glance, each group saying how it stands. Ways of looking, which the user keeps from
// one visit to the next.
const MODE_KEY = 'meals.summaryMode';
const OPEN_KEY = 'meals.openGroups';
export const MODES = ['gauges', 'table'];

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

function storedMode() {
  const found = read(MODE_KEY);
  return MODES.includes(found) ? found : MODES[0];
}

function storedOpen() {
  try {
    const found = JSON.parse(read(OPEN_KEY) ?? '[]');
    return Array.isArray(found) && found.every((g) => typeof g === 'string')
      ? found
      : [];
  } catch {
    return [];
  }
}

const SummaryModeContext = createContext({
  mode: MODES[0],
  setMode: () => {},
  open: [],
  toggleGroup: () => {},
  setOpen: () => {},
});

export function SummaryModeProvider({ children }) {
  const [mode, setModeState] = useState(storedMode);
  const [open, setOpenState] = useState(storedOpen);

  const setMode = (next) => {
    setModeState(next);
    write(MODE_KEY, next);
  };

  const setOpen = (next) => {
    setOpenState(next);
    write(OPEN_KEY, JSON.stringify(next));
  };

  const toggleGroup = (group) =>
    setOpen(
      open.includes(group)
        ? open.filter((found) => found !== group)
        : [...open, group],
    );

  return (
    <SummaryModeContext.Provider
      value={{ mode, setMode, open, toggleGroup, setOpen }}
    >
      {children}
    </SummaryModeContext.Provider>
  );
}

export const useSummaryMode = () => useContext(SummaryModeContext);
