import { formatAmount, formatInterval, formatNumber } from './format.js';
import { Gauge } from './Gauge.jsx';
import { countStatuses } from './gauge.js';
import { useSummaryMode } from './summaryMode.jsx';

const BADGE = {
  within: 'text-bg-success',
  below: 'text-bg-warning',
  above: 'text-bg-danger',
  unknown: 'text-bg-secondary',
};

function Status({ status, certain, labels }) {
  return (
    <span
      className={`badge ${BADGE[status]}`}
      title={certain ? undefined : labels.uncertain}
    >
      {labels[status]}
      {!certain && ' ?'}
    </span>
  );
}

function Coverage({ value, labels }) {
  const percent = Math.round(Number(value));
  return (
    <span
      className={percent < 100 ? 'text-warning-emphasis' : undefined}
      title={labels.coverageNote}
    >
      {percent} %
    </span>
  );
}

/** The ends of a need, "≥ 66,3 g ≤ 133 g", in the unit it is written in. */
function NeedRange({ need, languageCode }) {
  return (
    <>
      {need.low !== null && (
        <span className="d-block text-nowrap">
          ≥ {formatAmount(need.low, need.unit, languageCode)}
        </span>
      )}
      {need.high !== null && (
        <span className="d-block text-nowrap">
          ≤ {formatAmount(need.high, need.unit, languageCode)}
        </span>
      )}
    </>
  );
}

function groupsOf(needs) {
  const groups = new Map();
  for (const need of needs) {
    if (!groups.has(need.group)) {
      groups.set(need.group, { label: need.group_label, needs: [] });
    }
    groups.get(need.group).needs.push(need);
  }
  return [...groups.values()];
}

function StatusBar({ counts, total, labels }) {
  const order = ['within', 'below', 'above', 'unknown'];
  return (
    <div className="mb-3">
      <div
        className="status-bar"
        role="img"
        aria-label={`${counts.within} / ${total} ${labels.within}`}
      >
        {order
          .filter((status) => counts[status] > 0)
          .map((status) => (
            <div
              key={status}
              className={`status-bar-part--${status}`}
              style={{ width: `${(counts[status] / total) * 100}%` }}
              title={`${labels[status]} : ${counts[status]}`}
            />
          ))}
      </div>
      <div className="small mt-1 d-flex flex-wrap gap-3">
        {order
          .filter((status) => counts[status] > 0)
          .map((status) => (
            <span key={status}>
              <span className={`legend-swatch status-bar-part--${status}`} />
              {labels[status]} {counts[status]}
            </span>
          ))}
      </div>
    </div>
  );
}

/** What the drawing of a gauge means: said once, small, above them. */
function Legend({ labels }) {
  return (
    <p className="small text-body-secondary d-flex flex-wrap gap-3">
      <span>
        <span
          className="legend-swatch"
          style={{ background: 'rgba(var(--bs-success-rgb), 0.3)' }}
        />
        {labels.legendZone}
      </span>
      <span>
        <span
          className="legend-swatch"
          style={{
            borderTop: '2px solid var(--bs-body-color)',
            height: 0,
            verticalAlign: '0.2rem',
          }}
        />
        {labels.legendRange}
      </span>
      <span>
        <span
          className="legend-swatch"
          style={{
            background:
              'repeating-linear-gradient(135deg, var(--bs-warning) 0 0.25rem, rgba(255,255,255,.6) 0.25rem 0.5rem)',
          }}
        />
        {labels.legendUncertain}
      </span>
      <span>{labels.legendOpen}</span>
    </p>
  );
}

/** Each need and each ratio of the day on a gauge, by group. */
function Gauges({ report, labels, languageCode }) {
  return (
    <>
      <Legend labels={labels} />
      {groupsOf(report.needs).map((group) => (
        <div key={group.label} className="mb-3">
          <h3 className="h6 text-body-secondary mb-0">{group.label}</h3>
          {group.needs.map((need) => (
            <Gauge
              key={need.name + need.unit + String(need.low)}
              name={need.name}
              unit={need.unit}
              amount={need.total.amount}
              low={need.total.low}
              high={need.total.high}
              needLow={need.low}
              needHigh={need.high}
              status={need.status}
              certain={need.certain}
              coverage={need.total.coverage}
              ends={need.ends}
              labels={labels}
              languageCode={languageCode}
            />
          ))}
        </div>
      ))}
      <h3 className="h6 text-body-secondary mb-0">{labels.ratios}</h3>
      {report.ratios.map((ratio) => (
        <Gauge
          key={ratio.numerator + ratio.denominator}
          ratio
          name={`${ratio.numerator} / ${ratio.denominator}${
            ratio.molar ? ` (${labels.inMoles})` : ''
          }`}
          amount={ratio.value}
          low={ratio.value_low}
          high={ratio.value_high}
          needLow={ratio.low}
          needHigh={ratio.high}
          status={ratio.status}
          certain={ratio.certain}
          ends={[ratio.end]}
          labels={labels}
          languageCode={languageCode}
        />
      ))}
    </>
  );
}

/** The same figures as a table, every one of them. */
function Table({ report, labels, languageCode }) {
  return (
    <>
      <div className="table-responsive">
        <table className="table table-sm align-middle">
          <thead>
            <tr>
              <th>{labels.nutrient}</th>
              <th className="text-end">{labels.total}</th>
              <th className="text-end">{labels.need}</th>
              <th>{labels.status}</th>
              <th className="text-end">{labels.coverage}</th>
            </tr>
          </thead>
          {groupsOf(report.needs).map((group) => (
            <tbody key={group.label}>
              <tr className="table-light">
                <th colSpan={5}>{group.label}</th>
              </tr>
              {group.needs.map((need) => (
                <tr key={need.name + need.unit + String(need.low)}>
                  <td>{need.name}</td>
                  <td className="text-end">
                    {formatAmount(need.total.amount, need.unit, languageCode)}
                    <small className="d-block text-body-secondary text-nowrap">
                      {formatInterval(
                        need.total.low,
                        need.total.high,
                        need.unit,
                        languageCode,
                      )}
                    </small>
                  </td>
                  <td className="text-end" title={need.ends.join(' / ')}>
                    <NeedRange need={need} languageCode={languageCode} />
                  </td>
                  <td>
                    <Status
                      status={need.status}
                      certain={need.certain}
                      labels={labels}
                    />
                  </td>
                  <td className="text-end">
                    <Coverage value={need.total.coverage} labels={labels} />
                  </td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>

      <h2 className="h5 mt-4">{labels.ratios}</h2>
      <div className="table-responsive">
        <table className="table table-sm align-middle">
          <thead>
            <tr>
              <th>{labels.ratio}</th>
              <th className="text-end">{labels.total}</th>
              <th className="text-end">{labels.need}</th>
              <th>{labels.status}</th>
            </tr>
          </thead>
          <tbody>
            {report.ratios.map((ratio) => (
              <tr key={ratio.numerator + ratio.denominator}>
                <td title={ratio.end}>
                  {ratio.numerator} / {ratio.denominator}
                  {ratio.molar && (
                    <small className="text-body-secondary">
                      {' '}
                      ({labels.inMoles})
                    </small>
                  )}
                </td>
                <td className="text-end">
                  {ratio.value === null
                    ? '–'
                    : formatNumber(ratio.value, languageCode)}
                  {ratio.value !== null && (
                    <small className="d-block text-body-secondary text-nowrap">
                      {formatInterval(
                        ratio.value_low,
                        ratio.value_high,
                        '',
                        languageCode,
                      )}
                    </small>
                  )}
                </td>
                <td className="text-end">
                  {ratio.low !== null && (
                    <span className="d-block text-nowrap">
                      ≥ {formatNumber(ratio.low, languageCode)}
                    </span>
                  )}
                  {ratio.high !== null && (
                    <span className="d-block text-nowrap">
                      ≤ {formatNumber(ratio.high, languageCode)}
                    </span>
                  )}
                </td>
                <td>
                  <Status
                    status={ratio.status}
                    certain={ratio.certain}
                    labels={labels}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** The choice between the gauges, which say it at a glance, and the table. */
function ViewChoice({ labels }) {
  const { mode, setMode } = useSummaryMode();
  return (
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
          className={`btn ${mode === value ? 'btn-primary' : 'btn-outline-primary'}`}
          aria-pressed={mode === value}
          onClick={() => setMode(value)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

export function DaySummary({ report, labels, languageCode, needsUrl }) {
  const { mode } = useSummaryMode();
  if (report.needs === null) {
    return (
      <p className="alert alert-info mt-4">
        {labels.noProfile} <a href={needsUrl}>{labels.myNeeds}</a>
      </p>
    );
  }
  if (Number(report.mass) === 0) {
    return <p className="mt-4 text-body-secondary">{labels.emptyDay}</p>;
  }

  const counts = countStatuses([...report.needs, ...report.ratios]);
  const total = report.needs.length + report.ratios.length;

  return (
    <section className="mt-4" aria-label={labels.dayTitle}>
      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
        <h2 className="h4 mb-0">{labels.dayTitle}</h2>
        <ViewChoice labels={labels} />
      </div>
      <StatusBar counts={counts} total={total} labels={labels} />
      <p className="small text-body-secondary">{labels.coverageNote}</p>
      {mode === 'table' ? (
        <Table report={report} labels={labels} languageCode={languageCode} />
      ) : (
        <Gauges report={report} labels={labels} languageCode={languageCode} />
      )}
    </section>
  );
}
