import { createContext, useContext } from 'react';

import { useViewState } from '../../shared/useViewState.js';

// How the day against the needs is shown: gauges, or the table with every figure, and
// which groups of nutrients are open (see useViewState).
export const MODES = ['gauges', 'table'];
const KEYS = {
  modeKey: 'meals.summaryMode',
  openKey: 'meals.openGroups',
  modes: MODES,
};

const SummaryModeContext = createContext({
  mode: MODES[0],
  setMode: () => {},
  open: [],
  toggleGroup: () => {},
  setOpen: () => {},
});

export function SummaryModeProvider({ children }) {
  return (
    <SummaryModeContext.Provider value={useViewState(KEYS)}>
      {children}
    </SummaryModeContext.Provider>
  );
}

export const useSummaryMode = () => useContext(SummaryModeContext);
