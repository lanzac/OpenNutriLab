import { useEffect, useRef, useState } from 'react';

import {
  addItem,
  changeItem,
  fetchDay,
  fetchInventory,
  proposeDay,
  removeItem,
  replaceDay,
  setMealEaten,
  suggestFoods,
} from './api/client.js';
import { DayPicker } from './DayPicker.jsx';
import { DaySummary } from './DaySummary.jsx';
import { readIsoDay, shiftDay } from './format.js';
import { LimitsEditor } from './LimitsEditor.jsx';
import { MealCard } from './MealCard.jsx';
import { ProposalPanel } from './ProposalPanel.jsx';
import { SuggestionsPanel } from './SuggestionsPanel.jsx';
import { SummaryModeProvider } from './summaryMode.jsx';

// The day is kept in the address ("?day=2026-10-12"), so that a page loaded again
// shows the same day, and so does a link to it. Today is the address without it.
function dayOfAddress(today) {
  const asked = new URLSearchParams(window.location.search).get('day');
  return readIsoDay(asked) ?? today;
}

function keepDayInAddress(day, today) {
  const address = new URL(window.location.href);
  if (day === today) address.searchParams.delete('day');
  else address.searchParams.set('day', day);
  window.history.replaceState(window.history.state, '', address);
}

/**
 * The meals of a day, with what each brings and the day against the user's
 * needs. Everything the server owes it arrives through a |json_script blob
 * (see MealsView): `labels` already translated, so the .po catalogue stays
 * the single source of truth; `csrfToken`, which cannot come from the cookie
 * because CSRF_COOKIE_HTTPONLY hides it from JS; `languageCode`, so figures
 * follow the language Django is serving; `today`, the server's own date; and
 * `groupNames`, the names of the food groups in that language.
 *
 * Every figure is the server's: a write answers with the whole day, which
 * replaces the one shown.
 */
export function MealsApp({
  labels,
  csrfToken,
  languageCode,
  today,
  needsUrl,
  inventoryUrl,
  groupNames,
}) {
  const [day, setDay] = useState(() => dayOfAddress(today));
  const [report, setReport] = useState(null);
  const [inventory, setInventory] = useState(null);
  const [error, setError] = useState(null);
  // A day proposed, not saved, and whether one is being looked for.
  const [proposal, setProposal] = useState(null);
  const [proposing, setProposing] = useState(false);
  // Foods to get for the inventory, and whether they are being looked for.
  const [suggestions, setSuggestions] = useState(null);
  const [suggesting, setSuggesting] = useState(false);
  // The day asked for last: an answer for another is not shown.
  const current = useRef(day);

  useEffect(() => {
    current.current = day;
    keepDayInAddress(day, today);
    let cancelled = false;
    setReport(null);
    setError(null);
    setProposal(null);
    setSuggestions(null);
    fetchDay(day)
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch((err) => {
        console.error(err);
        if (!cancelled) setError(labels.loadError);
      });
    return () => {
      cancelled = true;
    };
  }, [day, today, labels.loadError]);

  useEffect(() => {
    let cancelled = false;
    fetchInventory()
      .then((data) => {
        if (!cancelled) setInventory(data);
      })
      .catch((err) => {
        console.error(err);
        if (!cancelled) setError(labels.loadError);
      });
    return () => {
      cancelled = true;
    };
  }, [labels.loadError]);

  // A proposal or a suggestion is made on the meals eaten, so it is out of date as
  // soon as one of them changes, or which meals are eaten: it is closed.
  const closeProposals = () => {
    setProposal(null);
    setSuggestions(null);
  };
  const closeIfEaten = (kind) => {
    if (report.meals.some((meal) => meal.kind === kind && meal.eaten)) {
      closeProposals();
    }
  };
  const mealOfItem = (id) =>
    report.meals.find((meal) => meal.items.some((item) => item.id === id));

  const save = (write, done, failed) => {
    setError(null);
    write()
      .then((data) => {
        if (data.day === current.current) {
          setReport(data);
          done?.();
        }
      })
      .catch((err) => {
        console.error(err);
        setError(labels.saveError);
        failed?.();
      });
  };

  // The switch of a meal answers at once, as a switch should; the server's day
  // (which takes a moment to work out) replaces it when it comes, or, if the change
  // is refused, puts the meal back as the server has it.
  const eat = (kind, eaten) => {
    setReport((shown) => ({
      ...shown,
      meals: shown.meals.map((meal) =>
        meal.kind === kind ? { ...meal, eaten } : meal,
      ),
    }));
    save(
      () => setMealEaten(day, kind, eaten, csrfToken),
      closeProposals,
      () =>
        fetchDay(day)
          .then((data) => {
            if (data.day === current.current) setReport(data);
          })
          .catch((err) => console.error(err)),
    );
  };

  const propose = () => {
    setError(null);
    setProposal(null);
    setProposing(true);
    proposeDay(day, csrfToken)
      .then((data) => {
        if (data.day.day === current.current) setProposal(data);
      })
      .catch((err) => {
        console.error(err);
        setError(labels.proposeError);
      })
      .finally(() => setProposing(false));
  };

  const suggest = () => {
    setError(null);
    setSuggestions(null);
    setSuggesting(true);
    suggestFoods(day, csrfToken)
      .then((data) => {
        if (data.day.day === current.current) setSuggestions(data);
      })
      .catch((err) => {
        console.error(err);
        setError(labels.suggestError);
      })
      .finally(() => setSuggesting(false));
  };

  const useProposal = () => {
    // What is in the meals not eaten goes: the user is asked first.
    const filled = report.meals.some(
      (meal) => !meal.eaten && meal.items.length > 0,
    );
    if (filled && !window.confirm(labels.confirmReplace)) return;
    save(
      () => replaceDay(day, proposal.items, csrfToken),
      () => setProposal(null),
    );
  };

  const canPropose = report !== null && report.needs !== null && !proposing;
  const canSuggest = report !== null && report.needs !== null && !suggesting;

  return (
    <SummaryModeProvider>
      <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
        <button
          type="button"
          className="btn btn-outline-secondary"
          aria-label={labels.previousDay}
          onClick={() => setDay(shiftDay(day, -1))}
        >
          <i className="fa-solid fa-chevron-left" />
        </button>
        <DayPicker
          day={day}
          onChange={setDay}
          labels={labels}
          languageCode={languageCode}
        />
        <button
          type="button"
          className="btn btn-outline-secondary"
          aria-label={labels.nextDay}
          onClick={() => setDay(shiftDay(day, 1))}
        >
          <i className="fa-solid fa-chevron-right" />
        </button>
        <button
          type="button"
          className="btn btn-outline-primary"
          disabled={day === today}
          onClick={() => setDay(today)}
        >
          {labels.today}
        </button>
        <button
          type="button"
          className="btn btn-primary ms-lg-auto"
          disabled={!canPropose}
          title={
            report?.needs === null ? labels.proposeNeedsProfile : undefined
          }
          onClick={propose}
        >
          <i className="fa-solid fa-wand-magic-sparkles" />{' '}
          {proposing ? labels.proposing : labels.proposeDay}
        </button>
        <button
          type="button"
          className="btn btn-outline-primary"
          disabled={!canSuggest}
          title={
            report?.needs === null ? labels.proposeNeedsProfile : undefined
          }
          onClick={suggest}
        >
          <i className="fa-solid fa-basket-shopping" />{' '}
          {suggesting ? labels.suggesting : labels.suggestFoods}
        </button>
      </div>

      <p className="small text-body-secondary">{labels.eatenHelp}</p>

      {error && (
        <p className="alert alert-danger" role="alert">
          {error}
        </p>
      )}

      {report === null || inventory === null ? (
        !error && <p>{labels.loading}</p>
      ) : (
        <>
          {inventory.length === 0 && (
            <p className="alert alert-info">
              {labels.emptyInventory}{' '}
              <a href={inventoryUrl}>{labels.goInventory}</a>
            </p>
          )}
          {suggestions && (
            <SuggestionsPanel
              suggestions={suggestions}
              labels={labels}
              languageCode={languageCode}
              needsUrl={needsUrl}
              onClose={() => setSuggestions(null)}
            />
          )}
          {proposal && (
            <ProposalPanel
              proposal={proposal}
              labels={labels}
              languageCode={languageCode}
              needsUrl={needsUrl}
              onUse={useProposal}
              onClose={() => setProposal(null)}
            />
          )}
          <div className="row g-3">
            {report.meals.map((meal) => (
              <div key={meal.kind} className="col-lg-6">
                <MealCard
                  meal={meal}
                  nutrients={report.nutrients}
                  inventory={inventory}
                  labels={labels}
                  languageCode={languageCode}
                  onAdd={(kind, item) =>
                    save(
                      () => addItem(day, kind, item, csrfToken),
                      () => closeIfEaten(kind),
                    )
                  }
                  onChange={(id, change) => {
                    const kind = mealOfItem(id)?.kind;
                    save(
                      () => changeItem(id, change, csrfToken),
                      () => closeIfEaten(kind),
                    );
                  }}
                  onRemove={(id) => {
                    const kind = mealOfItem(id)?.kind;
                    save(
                      () => removeItem(id, csrfToken),
                      () => closeIfEaten(kind),
                    );
                  }}
                  onEat={eat}
                />
              </div>
            ))}
          </div>
          <DaySummary
            report={report}
            labels={labels}
            languageCode={languageCode}
            needsUrl={needsUrl}
          />
          <LimitsEditor
            meals={report.meals}
            inventory={inventory}
            labels={labels}
            csrfToken={csrfToken}
            languageCode={languageCode}
            groupNames={groupNames}
          />
        </>
      )}
    </SummaryModeProvider>
  );
}
