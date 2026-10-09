import { createContext, useContext, useState } from 'react';

// How the day against the needs is shown: gauges, or the table with every figure,
// and which groups of nutrients are folded. Ways of looking, which the user keeps
// from one visit to the next.
const MODE_KEY = 'meals.summaryMode';
const FOLDED_KEY = 'meals.foldedGroups';
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

function storedFolded() {
  try {
    const found = JSON.parse(read(FOLDED_KEY) ?? '[]');
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
  folded: [],
  toggleGroup: () => {},
  setFolded: () => {},
});

export function SummaryModeProvider({ children }) {
  const [mode, setModeState] = useState(storedMode);
  const [folded, setFoldedState] = useState(storedFolded);

  const setMode = (next) => {
    setModeState(next);
    write(MODE_KEY, next);
  };

  const setFolded = (next) => {
    setFoldedState(next);
    write(FOLDED_KEY, JSON.stringify(next));
  };

  const toggleGroup = (group) =>
    setFolded(
      folded.includes(group)
        ? folded.filter((found) => found !== group)
        : [...folded, group],
    );

  return (
    <SummaryModeContext.Provider
      value={{ mode, setMode, folded, toggleGroup, setFolded }}
    >
      {children}
    </SummaryModeContext.Provider>
  );
}

export const useSummaryMode = () => useContext(SummaryModeContext);
