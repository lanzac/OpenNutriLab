import { DaySummary } from './DaySummary.jsx';
import { MealCard } from './MealCard.jsx';

/**
 * A day as it would be, not saved: its four meals, which only read, and the day
 * against the needs. What a proposal and a suggestion both show.
 */
export function DayPreview({
  day,
  labels,
  languageCode,
  needsUrl,
  placeholderImage,
}) {
  return (
    <>
      <div className="row g-3">
        {day.meals.map((meal) => (
          <div key={meal.kind} className="col-lg-6">
            <MealCard
              meal={meal}
              nutrients={day.nutrients}
              inventory={[]}
              labels={labels}
              languageCode={languageCode}
              placeholderImage={placeholderImage}
              readOnly
            />
          </div>
        ))}
      </div>
      <DaySummary
        report={day}
        labels={labels}
        languageCode={languageCode}
        needsUrl={needsUrl}
      />
    </>
  );
}
