import { useRef, useState } from 'react';

import { formatDay, parseDay } from './format.js';

/**
 * The day of the page, written as the language writes a date ("10/10/2026" in
 * French). A native date field writes it as the browser does, whatever the language
 * of the page, so this is a text field that reads what is typed in the language's
 * order, with a button for the browser's calendar to choose a day from.
 *
 * `day` and what `onChange` is given are ISO dates ("2026-10-10").
 */
export function DayPicker({ day, onChange, labels, languageCode }) {
  // What is being typed, for the day it was typed over: another way of changing the
  // day (a button, the calendar) leaves it behind.
  const [draft, setDraft] = useState(null);
  const calendar = useRef(null);
  const typed = draft?.day === day ? draft.text : null;

  const settle = () => {
    const found = typed === null ? null : parseDay(typed, languageCode);
    setDraft(null);
    if (found !== null && found !== day) onChange(found);
  };

  const openCalendar = () => {
    // Not every browser opens its calendar from a script.
    if (typeof calendar.current?.showPicker === 'function') {
      calendar.current.showPicker();
    }
  };

  return (
    <div className="position-relative">
      <div className="input-group flex-nowrap">
        <input
          type="text"
          inputMode="numeric"
          className="form-control"
          style={{ width: '9rem' }}
          aria-label={labels.day}
          placeholder={labels.dateHint}
          value={typed ?? formatDay(day, languageCode)}
          onChange={(event) => setDraft({ day, text: event.target.value })}
          onBlur={settle}
          onKeyDown={(event) => {
            if (event.key === 'Enter') settle();
          }}
        />
        <button
          type="button"
          className="btn btn-outline-secondary"
          aria-label={labels.chooseDay}
          title={labels.chooseDay}
          onClick={openCalendar}
        >
          <i className="fa-regular fa-calendar" />
        </button>
      </div>
      {/* The browser's calendar, out of sight: it only gives a day to choose. */}
      <input
        ref={calendar}
        type="date"
        tabIndex={-1}
        aria-hidden="true"
        value={day}
        style={{
          position: 'absolute',
          insetInlineEnd: 0,
          bottom: 0,
          width: 0,
          height: 0,
          opacity: 0,
          pointerEvents: 'none',
        }}
        onChange={(event) => event.target.value && onChange(event.target.value)}
      />
    </div>
  );
}
