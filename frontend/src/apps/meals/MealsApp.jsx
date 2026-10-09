import { useEffect, useRef, useState } from 'react';

import {
  addItem,
  changeItem,
  fetchDay,
  fetchInventory,
  proposeDay,
  removeItem,
  replaceDay,
  suggestFoods,
} from './api/client.js';
import { DaySummary } from './DaySummary.jsx';
import { shiftDay } from './format.js';
import { LimitsEditor } from './LimitsEditor.jsx';
import { MealCard } from './MealCard.jsx';
import { ProposalPanel } from './ProposalPanel.jsx';
import { SuggestionsPanel } from './SuggestionsPanel.jsx';

/**
 * The meals of a day, with what each brings and the day against the user's
 * needs. Everything the server owes it arrives through a |json_script blob
 * (see MealsView): `labels` already translated, so the .po catalogue stays
 * the single source of truth; `csrfToken`, which cannot come from the cookie
 * because CSRF_COOKIE_HTTPONLY hides it from JS; `languageCode`, so figures
 * follow the language Django is serving; and `today`, the server's own date.
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
}) {
  const [day, setDay] = useState(today);
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
  }, [day, labels.loadError]);

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

  const save = (write, done) => {
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
      });
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
    // What is in the day goes: the user is asked first.
    const filled = report.meals.some((meal) => meal.items.length > 0);
    if (filled && !window.confirm(labels.confirmReplace)) return;
    save(
      () => replaceDay(day, proposal.items, csrfToken),
      () => setProposal(null),
    );
  };

  const canPropose = report !== null && report.needs !== null && !proposing;
  const canSuggest = report !== null && report.needs !== null && !suggesting;

  return (
    <div>
      <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
        <button
          type="button"
          className="btn btn-outline-secondary"
          aria-label={labels.previousDay}
          onClick={() => setDay(shiftDay(day, -1))}
        >
          <i className="fa-solid fa-chevron-left" />
        </button>
        <input
          type="date"
          className="form-control w-auto"
          aria-label={labels.day}
          value={day}
          onChange={(event) => event.target.value && setDay(event.target.value)}
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
                    save(() => addItem(day, kind, item, csrfToken))
                  }
                  onChange={(id, change) =>
                    save(() => changeItem(id, change, csrfToken))
                  }
                  onRemove={(id) => save(() => removeItem(id, csrfToken))}
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
          />
        </>
      )}
    </div>
  );
}
