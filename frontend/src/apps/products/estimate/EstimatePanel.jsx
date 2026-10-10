import { useEffect, useId, useMemo } from 'react';

import { FoldHead } from '../../../shared/FoldHead.jsx';
import { fill, formatNumber } from '../../../shared/format.js';
import { useStoredChoice, useViewState } from '../../../shared/useViewState.js';
import { convertDeclared, convertRange } from './convert.js';
import { EstimateGauge } from './EstimateGauge.jsx';
import { countVerdicts, sharedScaleOf, showsTolerance } from './layout.js';

const MODES = ['gauges', 'table'];
const KEYS = {
  modeKey: 'products.estimateMode',
  openKey: 'products.estimateOpenGroups',
  modes: MODES,
};
// The unit the amounts are read in, per 100 g or per 100 ml, kept like the rest.
const UNIT_KEY = 'products.estimateUnit';
// What an estimate is worked out in (see estimate_validation).
const ESTIMATE_UNIT = 'g';

function groupsOf(nutrients) {
  const groups = new Map();
  for (const nutrient of nutrients) {
    if (!groups.has(nutrient.group)) {
      groups.set(nutrient.group, {
        key: nutrient.group,
        label: nutrient.group_label,
        nutrients: [],
      });
    }
    groups.get(nutrient.group).nutrients.push(nutrient);
  }
  return [...groups.values()];
}

const KINDS = ['agrees', 'differs', 'used', 'none'];

/** What the label says of the estimates of a group of nutrients, in words. */
function summaryOf(counts, labels) {
  const compared = counts.agrees + counts.differs;
  return compared === 0
    ? labels.notCompared
    : fill(labels.groupAgree, { agree: counts.agrees, compared });
}

/** The legend of the drawing: said once, small, above the gauges. */
function Legend({ labels, tolerance }) {
  return (
    <p className="small text-body-secondary d-flex flex-wrap gap-3">
      <span>
        <span className="est-swatch est-swatch--band" />
        {labels.legendEstimate}
      </span>
      <span>
        <span
          className="est-swatch"
          style={{ width: '0.15rem', background: 'var(--bs-body-color)' }}
        />
        {labels.legendLabel}
      </span>
      {tolerance && (
        <span>
          <span className="est-swatch est-swatch--tolerance" />
          {labels.legendTolerance}
        </span>
      )}
      <span>{labels.legendOpen}</span>
    </p>
  );
}

function Ingredients({ rows, labels, languageCode }) {
  const gauges = rows.map((row) => ({
    estimated: row.estimated,
    declared:
      row.declared === null
        ? null
        : { amount: row.declared, low: row.declared, high: row.declared },
  }));
  // The shares are compared with each other: one track for them all.
  // What an ingredient that is a nutrient adds is an amount, not a share: it has a
  // track of its own, and is left out of the one the shares are compared on.
  const max = sharedScaleOf(gauges.filter((_, index) => !rows[index].added));
  return (
    <>
      <h3 className="h6 mt-3">{labels.ingredients}</h3>
      {rows.map((row, index) =>
        row.added ? (
          <EstimateGauge
            key={`${index}-${row.name}`}
            name={`${row.name} (${labels.added})`}
            unit={row.added_unit}
            unitInName={false}
            depth={row.depth}
            estimated={row.added}
            labels={labels}
            languageCode={languageCode}
          />
        ) : (
          <EstimateGauge
            key={`${index}-${row.name}`}
            name={row.name}
            unit="%"
            unitInName={false}
            depth={row.depth}
            estimated={gauges[index].estimated}
            declared={gauges[index].declared}
            max={max}
            labels={labels}
            languageCode={languageCode}
          />
        ),
      )}
    </>
  );
}

function NutrientGauge({ nutrient, labels, languageCode }) {
  return (
    <EstimateGauge
      name={nutrient.name}
      unit={nutrient.unit}
      estimated={nutrient.estimated}
      declared={nutrient.declared}
      verdict={nutrient.verdict}
      constrained={nutrient.constrained}
      tolerated={nutrient.tolerated}
      confidence={nutrient.confidence}
      coverage={nutrient.coverage}
      labels={labels}
      languageCode={languageCode}
    />
  );
}

function Nutrients({ nutrients, heading, labels, languageCode, view, prefix }) {
  const groups = groupsOf(nutrients);
  const all = countVerdicts(nutrients);
  return (
    <>
      <h3 className="h6 mt-4">{heading}</h3>
      <p className="small text-body-secondary">{summaryOf(all, labels)}</p>
      {groups.map((group) => {
        const isFolded = !view.open.includes(group.key);
        const region = `${prefix}-${group.key}`;
        const counts = countVerdicts(group.nutrients);
        return (
          <div key={group.key} className="mb-3">
            <FoldHead
              id={region}
              label={group.label}
              summary={summaryOf(counts, labels)}
              parts={KINDS.filter((kind) => counts[kind] > 0).map((kind) => ({
                className: `est-part--${kind}`,
                share: counts[kind] / group.nutrients.length,
              }))}
              isFolded={isFolded}
              onToggle={() => view.toggleGroup(group.key)}
            />
            <div id={region}>
              {!isFolded &&
                group.nutrients.map((nutrient) => (
                  <NutrientGauge
                    key={nutrient.code}
                    nutrient={nutrient}
                    labels={labels}
                    languageCode={languageCode}
                  />
                ))}
            </div>
          </div>
        );
      })}
    </>
  );
}

/**
 * The estimate of a product as gauges, or as the tables the server wrote, which are
 * `tables` and are shown or hidden here: they stay the page's own where this does not
 * run. What is in `data` is the server's (see estimate_panel.py); this only draws it.
 */
export function EstimatePanel({ data, labels, languageCode, tables = [] }) {
  const view = useViewState(KEYS);
  const prefix = useId();
  const gauges = view.mode === 'gauges';
  const groups = groupsOf(data.nutrients).map((group) => group.key);
  const allFolded = groups.every((group) => !view.open.includes(group));

  // The unit of the amounts. The label's own at first, the one on the pack; and only
  // where the density of the product is known, which is what converts one to the other.
  const density = data.density ?? null;
  const labelUnit = data.label_unit ?? ESTIMATE_UNIT;
  const [chosen, setUnit] = useStoredChoice(
    UNIT_KEY,
    labelUnit === 'ml' ? ['ml', 'g'] : ['g', 'ml'],
  );
  const unit = density ? chosen : ESTIMATE_UNIT;
  const nutrients = useMemo(
    () =>
      data.nutrients.map((nutrient) => ({
        ...nutrient,
        estimated: convertRange(
          nutrient.estimated,
          density,
          ESTIMATE_UNIT,
          unit,
        ),
        declared: convertDeclared(nutrient.declared, density, labelUnit, unit),
      })),
    [data.nutrients, density, labelUnit, unit],
  );

  // What an ingredient adds is an amount per 100 g or 100 ml, like the nutrients.
  const ingredients = useMemo(
    () =>
      data.ingredients.map((row) => ({
        ...row,
        added: convertRange(row.added, density, ESTIMATE_UNIT, unit),
      })),
    [data.ingredients, density, unit],
  );

  useEffect(() => {
    for (const table of tables) table.hidden = gauges;
    return () => {
      for (const table of tables) table.hidden = false;
    };
  }, [tables, gauges]);

  return (
    <div className="mb-3">
      <div className="d-flex flex-wrap justify-content-end align-items-center gap-2 mb-2">
        {gauges && groups.length > 0 && (
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            onClick={() => view.setOpen(allFolded ? groups : [])}
          >
            {allFolded ? labels.expandAll : labels.collapseAll}
          </button>
        )}
        {gauges && density && (
          <div
            className="btn-group btn-group-sm"
            role="group"
            aria-label={labels.per}
          >
            {[
              ['g', labels.unitG],
              ['ml', labels.unitMl],
            ].map(([value, text]) => (
              <button
                key={value}
                type="button"
                className={`btn ${unit === value ? 'btn-primary' : 'btn-outline-primary'}`}
                aria-pressed={unit === value}
                onClick={() => setUnit(value)}
              >
                {text}
              </button>
            ))}
          </div>
        )}
        <div
          className="btn-group btn-group-sm"
          role="group"
          aria-label={labels.view}
        >
          {[
            ['gauges', labels.viewGauges],
            ['table', labels.viewTable],
          ].map(([value, text]) => (
            <button
              key={value}
              type="button"
              className={`btn ${view.mode === value ? 'btn-primary' : 'btn-outline-primary'}`}
              aria-pressed={view.mode === value}
              onClick={() => view.setMode(value)}
            >
              {text}
            </button>
          ))}
        </div>
      </div>
      {gauges && density && (
        <p className="small text-body-secondary text-end">
          {fill(labels.density, {
            low: formatNumber(density.low, languageCode),
            high: formatNumber(density.high, languageCode),
          })}
        </p>
      )}
      {gauges && (
        <>
          <Legend labels={labels} tolerance={nutrients.some(showsTolerance)} />
          {data.ingredients.length > 0 && (
            <Ingredients
              rows={ingredients}
              labels={labels}
              languageCode={languageCode}
            />
          )}
          {nutrients.length > 0 && (
            <Nutrients
              nutrients={nutrients}
              heading={unit === 'ml' ? labels.nutrientsMl : labels.nutrients}
              labels={labels}
              languageCode={languageCode}
              view={view}
              prefix={prefix}
            />
          )}
        </>
      )}
    </div>
  );
}
