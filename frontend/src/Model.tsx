import { useState } from 'react';
import type { components } from './api.generated';
import { Saves, mutate } from './Analyst';
import { periodLabel, ReportedCell } from './Research';
import { factValue } from './sec-api';

type S = components['schemas'];
const names = ['bear', 'base', 'bull'] as const;
const drivers = {
  growth: 'Revenue growth',
  margin: 'Operating margin',
  tax: 'Tax on operating income',
  da: 'D&A / revenue',
  capex: 'Capex / revenue',
  wc: 'Non-cash working capital / revenue',
};
const historicalDriver = {
  margin: 'operatingMargin',
  da: 'daRatio',
  capex: 'capexRatio',
  tax: 'taxRate',
} as const;
const bridge = {
  revenue: 'Revenue',
  operatingIncome: 'Operating income',
  tax: 'Operating taxes',
  da: 'Depreciation and amortization',
  capex: 'Capital expenditure',
  workingCapital: 'Non-cash working capital',
  changeWC: 'Change in working capital',
  fcff: 'Free cash flow to the firm',
};
const blankYear = (): S['Drivers'] => ({ growth: '', margin: '', tax: '', da: '', capex: '', wc: '' });
function blankScenario(): S['Scenario'] {
  return { openingWC: '', wacc: '', terminalGrowth: '', years: Array.from({ length: 5 }, blankYear) };
}
type Document = {
  baseline: S['ResearchRow'] | null;
  scenarios: Record<string, S['Scenario']>;
  result: S['Evaluation'] | null;
};
function input(label: string, value: string, onChange: (value: string) => void) {
  return (
    <input
      aria-label={label}
      type="number"
      step="any"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
export default function Model({
  symbol,
  metrics,
  error,
}: {
  symbol: string;
  metrics?: S['ResearchTable'];
  error?: string;
}) {
  const [doc, setDoc] = useState<Document>(() => ({
    baseline: null,
    scenarios: { bear: blankScenario(), base: blankScenario(), bull: blankScenario() },
    result: null,
  }));
  const [active, setActive] = useState<(typeof names)[number]>('base');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const rows =
    metrics?.rows.filter(
      (r) =>
        r.period.mode === 'annual' && r.values.revenue?.value != null && Number(r.values.revenue.value) > 0,
    ) || [];
  const [candidate, setCandidate] = useState('');
  const row = rows.find((r) => r.period.start + '/' + r.period.end === candidate) || rows[0];
  const base = doc.baseline;
  const scenario = doc.scenarios[active];
  const forecast = doc.result?.forecasts[active];
  function update(next: S['Scenario']) {
    setDoc({ ...doc, result: null, scenarios: { ...doc.scenarios, [active]: next } });
  }
  function setDriver(key: keyof S['Drivers'], i: number, val: string) {
    update({ ...scenario, years: scenario.years.map((y, j) => (j === i ? { ...y, [key]: val } : y)) });
  }
  async function evaluate() {
    if (!base) return;
    setBusy(true);
    setMessage('');
    try {
      const result = await mutate<S['Evaluation']>('/model/evaluate', 'POST', {
        revenue: base.values.revenue.value,
        scenarios: doc.scenarios,
      });
      setDoc({ ...doc, result });
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section className="panel">
        <h2>Operating model and DCF</h2>
        <fieldset disabled={busy}>
          <legend>Historical baseline</legend>
          {error && <p role="alert">{error}</p>}
          {!rows.length && (
            <p>{metrics ? 'No positive annual revenue baseline available.' : 'Loading reported history…'}</p>
          )}
          <label>
            Annual revenue period
            <select
              value={row ? row.period.start + '/' + row.period.end : ''}
              onChange={(e) => setCandidate(e.target.value)}
            >
              {rows.map((r) => (
                <option key={r.period.start + r.period.end} value={r.period.start + '/' + r.period.end}>
                  {periodLabel(r.period)} · {r.values.revenue.unit}
                </option>
              ))}
            </select>
          </label>
          <button disabled={!row} onClick={() => setDoc({ ...doc, baseline: row, result: null })}>
            {base ? 'Rebase on selected filing' : 'Use selected baseline'}
          </button>
          {base && (
            <>
              <h3>Historical inputs · {periodLabel(base.period)}</h3>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      {[
                        'Revenue',
                        'Operating margin',
                        'D&A',
                        'Capital expenditure',
                        'Income tax expense',
                        'Pretax income',
                      ].map((t) => (
                        <th key={t}>{t}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      {['revenue', 'operatingMargin', 'da', 'capex', 'taxExpense', 'pretaxIncome'].map(
                        (k) => (
                          <td key={k}>
                            <ReportedCell cell={base.values[k]} />
                          </td>
                        ),
                      )}
                    </tr>
                  </tbody>
                </table>
              </div>
              <p>
                Opening non-cash working capital requires an analyst estimate. All drivers below are
                percentages.
              </p>
            </>
          )}
        </fieldset>
        {base && (
          <fieldset disabled={busy}>
            <legend>Forecast assumptions</legend>
            <div className="tabs">
              {names.map((n) => (
                <button key={n} aria-pressed={n === active} onClick={() => setActive(n)}>
                  {n}
                </button>
              ))}
            </div>
            <div className="sec-filters">
              {(
                [
                  ['openingWC', 'Opening working capital / baseline revenue'],
                  ['wacc', 'WACC'],
                  ['terminalGrowth', 'Terminal growth'],
                ] as const
              ).map(([k, l]) => (
                <label key={k}>
                  {l} (%){input(l, scenario[k], (v) => update({ ...scenario, [k]: v }))}
                </label>
              ))}
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Driver (%)</th>
                    {scenario.years.map((_, i) => (
                      <th key={i}>Year {i + 1}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(Object.keys(drivers) as (keyof S['Drivers'])[]).map((k) => (
                    <tr key={k}>
                      <th>{drivers[k]}</th>
                      {scenario.years.map((y, i) => (
                        <td key={i}>
                          {input(drivers[k] + ' year ' + (i + 1), y[k], (v) => setDriver(k, i, v))}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button
              onClick={() => {
                const year = { ...scenario.years[0] };
                for (const [driver, field] of Object.entries(historicalDriver)) {
                  const value = base.values[field]?.value;
                  if (value != null)
                    year[driver as keyof typeof historicalDriver] = String(
                      Number((100 * Number(value)).toFixed(4)),
                    );
                }
                const growth = base.growth?.revenue;
                if (growth != null) year.growth = String(Number((100 * growth).toFixed(4)));
                update({ ...scenario, years: [year, ...scenario.years.slice(1)] });
              }}
            >
              Use reported ratios in Year 1
            </button>
            <button
              onClick={() =>
                update({ ...scenario, years: scenario.years.map(() => ({ ...scenario.years[0] })) })
              }
            >
              Apply Year 1 to all years
            </button>
            {names
              .filter((n) => n !== active)
              .map((n) => (
                <button
                  key={n}
                  onClick={() =>
                    setDoc({
                      ...doc,
                      result: null,
                      scenarios: { ...doc.scenarios, [active]: structuredClone(doc.scenarios[n]) },
                    })
                  }
                >
                  Copy assumptions from {n}
                </button>
              ))}
            <button onClick={() => void evaluate()}>Evaluate scenarios</button>
          </fieldset>
        )}
        {message && <p role="alert">{message}</p>}
        {doc.result && forecast && (
          <>
            <h3>Enterprise value · {base?.values.revenue.unit}</h3>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Scenario</th>
                    <th>PV of forecasts</th>
                    <th>PV of terminal value</th>
                    <th>Enterprise value</th>
                  </tr>
                </thead>
                <tbody>
                  {names.map((n) => {
                    const f = doc.result!.forecasts[n];
                    return (
                      <tr key={n}>
                        <th>{n}</th>
                        {[f.pv, f.terminalPV, f.ev].map((v, i) => (
                          <td key={i}>{factValue(v)}</td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <h3>{active} cash-flow bridge</h3>
            {forecast.issue && <p>{forecast.issue}</p>}
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Forecast line</th>
                    {forecast.years.map((_, i) => (
                      <th key={i}>Year {i + 1}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(bridge).map(([k, l]) => (
                    <tr key={k}>
                      <th>{l}</th>
                      {forecast.years.map((y, i) => (
                        <td key={i}>{factValue(y[k])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3>Enterprise value sensitivity · {active}</h3>
            <div className="table-scroll">
              <table>
                <caption>WACC by terminal growth · {doc.result.version}</caption>
                <thead>
                  <tr>
                    <th>WACC / growth</th>
                    {[-2, -1, 0, 1, 2].map((j) => (
                      <th key={j}>
                        {scenario.terminalGrowth
                          ? (Number(scenario.terminalGrowth) + j * 0.5).toFixed(2) + '%'
                          : '—'}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {forecast.grid.map((r, i) => (
                    <tr key={i}>
                      <th>{scenario.wacc ? (Number(scenario.wacc) + i - 2).toFixed(2) + '%' : '—'}</th>
                      {r.map((v, j) => (
                        <td key={j}>{factValue(v)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
      <Saves kind="model" symbol={symbol} state={doc} restore={setDoc} ready={!busy && !!doc.result} />
    </>
  );
}
