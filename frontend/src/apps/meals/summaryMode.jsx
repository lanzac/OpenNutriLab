import { createContext, useContext, useState } from 'react';

// How the day against the needs is shown: gauges, or the table with every figure.
// A way of looking, which the user keeps from one visit to the next.
const KEY = 'meals.summaryMode';
export const MODES = ['gauges', 'table'];

function stored() {
  try {
    const found = window.localStorage.getItem(KEY);
    return MODES.includes(found) ? found : MODES[0];
  } catch {
    // No storage (a private window, blocked data): the page works without.
    return MODES[0];
  }
}

const SummaryModeContext = createContext({
  mode: MODES[0],
  setMode: () => {},
});

export function SummaryModeProvider({ children }) {
  const [mode, setModeState] = useState(stored);

  const setMode = (next) => {
    setModeState(next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // Nothing to keep it in: it holds for this visit.
    }
  };

  return (
    <SummaryModeContext.Provider value={{ mode, setMode }}>
      {children}
    </SummaryModeContext.Provider>
  );
}

export const useSummaryMode = () => useContext(SummaryModeContext);
