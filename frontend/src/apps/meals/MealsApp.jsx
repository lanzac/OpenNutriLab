import { useEffect, useRef, useState } from 'react';

import {
  addItem,
  changeItem,
  fetchDay,
  fetchInventory,
  removeItem,
} from './api/client.js';
import { DaySummary } from './DaySummary.jsx';
import { shiftDay } from './format.js';
import { MealCard } from './MealCard.jsx';

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
  // The day asked for last: an answer for another is not shown.
  const current = useRef(day);

  useEffect(() => {
    current.current = day;
    let cancelled = false;
    setReport(null);
    setError(null);
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

  const save = (write) => {
    setError(null);
    write()
      .then((data) => {
        if (data.day === current.current) setReport(data);
      })
      .catch((err) => {
        console.error(err);
        setError(labels.saveError);
      });
  };

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
        </>
      )}
    </div>
  );
}
