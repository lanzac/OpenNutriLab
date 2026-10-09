import { formatAmount, formatInterval, formatNumber } from './format.js';

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

export function DaySummary({ report, labels, languageCode, needsUrl }) {
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

  return (
    <section className="mt-4" aria-label={labels.dayTitle}>
      <h2 className="h4">{labels.dayTitle}</h2>
      <p className="small text-body-secondary">{labels.coverageNote}</p>
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
    </section>
  );
}
