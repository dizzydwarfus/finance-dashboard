import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, ApiError, format, label } from './api';
import type { Company, Metrics, Price, Split, Statement, Ticker } from './api';
const Chart = lazy(() => import('./Chart'));
type View = 'overview' | 'statements' | 'prices';
function pathSymbol() { try { return decodeURIComponent(location.pathname.match(/^\/companies\/([^/]+)\/?$/)?.[1] || '').toUpperCase(); } catch { return ''; } }
function initialTheme() { return localStorage.getItem('theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); }
function Notice({ text, retry }: { text: string; retry?: () => void }) { return <div className="notice" role="status"><span>{text}</span>{retry && <button onClick={retry}>Try again ↗</button>}</div>; }
function Pending() { return <div className="pending" role="status">Loading stored data<span className="loading-dots">…</span></div>; }
export default function App() {
  const [symbol, setSymbol] = useState(pathSymbol);
  const [search, setSearch] = useState('');
  const [view, setView] = useState<View>('overview');
  const [theme, setTheme] = useState(initialTheme);
  const [period, setPeriod] = useState('FY');
  const [statementType, setStatementType] = useState('income');
  const [years, setYears] = useState('10');
  const [selectedMetrics, setSelectedMetrics] = useState(['revenue', 'netIncome']);
  const [from, setFrom] = useState(''); const [to, setTo] = useState('');
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('theme', theme); }, [theme]);
  useEffect(() => { const listener = () => setSymbol(pathSymbol()); window.addEventListener('popstate', listener); return () => window.removeEventListener('popstate', listener); }, []);
  function navigate(next: string, replace = false) {
    history[replace ? 'replaceState' : 'pushState']({}, '', `/companies/${encodeURIComponent(next)}`); setSymbol(next); setFrom(''); setTo('');
  }
  const tickers = useQuery({ queryKey: ['tickers', search], queryFn: ({ signal }) => api<Ticker[]>(`/tickers?limit=2000&q=${encodeURIComponent(search)}`, signal) });
  useEffect(() => { if (!symbol && tickers.data?.length) navigate(tickers.data[0].symbol, true); }, [symbol, tickers.data]);
  const company = useQuery({ queryKey: ['company', symbol], queryFn: ({ signal }) => api<Company>(`/companies/${encodeURIComponent(symbol)}`, signal), enabled: !!symbol });
  const metrics = useQuery({ queryKey: ['metrics', symbol, period, years], queryFn: ({ signal }) => api<Metrics>(`/companies/${encodeURIComponent(symbol)}/metrics?period=${period}&limit=${years}`, signal), enabled: !!symbol });
  const statements = useQuery({ queryKey: ['statements', symbol, statementType, period, years], queryFn: ({ signal }) => api<Statement[]>(`/companies/${encodeURIComponent(symbol)}/statements/${statementType}?period=${period}&limit=${years}`, signal), enabled: !!symbol && view === 'statements' });
  const prices = useQuery({ queryKey: ['prices', symbol, from, to], queryFn: ({ signal }) => api<Price[]>(`/companies/${encodeURIComponent(symbol)}/prices?limit=5000&from=${from}&to=${to}`, signal), enabled: !!symbol && view === 'prices' && (!from || !to || from <= to) });
  const splits = useQuery({ queryKey: ['splits', symbol], queryFn: ({ signal }) => api<Split[]>(`/companies/${encodeURIComponent(symbol)}/splits`, signal), enabled: !!symbol && view === 'prices' });
  const current = company.data;
  const latest = metrics.data?.points.at(-1);
  const currency = latest?.currency || current?.currency || '';
  const points = metrics.data?.points.filter(p => p.currency === currency) || [];
  const latestPrice = prices.data?.at(-1);
  const metricOption = useMemo(() => ({
    color: ['#63a68c', '#d7a25d', '#8d97c7', '#d1837a'],
    tooltip: { trigger: 'axis', confine: true }, legend: { bottom: 0, textStyle: { color: theme === 'dark' ? '#aaa' : '#555' } },
    grid: { top: 30, left: 65, right: 65, bottom: 65 },
    xAxis: { type: 'category', data: points.map(p => `${p.year} ${p.period === 'FY' ? '' : p.period}`.trim()), axisLine: { show: false }, axisTick: { show: false } },
    yAxis: [{ type: 'value', name: currency, splitLine: { lineStyle: { opacity: .12 } }, axisLabel: { formatter: (value: number) => format(value, 'number', currency, true) } }, { type: 'value', name: 'Ratio / YoY', splitLine: { show: false }, axisLabel: { formatter: (v: number) => format(v, 'percent') } }],
    series: selectedMetrics.flatMap(key => {
      const definition = metrics.data?.definitions.find(m => m.key === key);
      return [
        { name: definition?.label || key, type: 'bar', barMaxWidth: 35, data: points.map(p => p.values[key]), itemStyle: { borderRadius: [3, 3, 0, 0] }, yAxisIndex: definition?.format === 'percent' ? 1 : 0 },
        ...(selectedMetrics.length === 1 ? [{ name: `${definition?.label || key} YoY`, type: 'line', yAxisIndex: 1, data: points.map(p => p.growth[key]), connectNulls: false, lineStyle: { type: 'dashed' } }] : []),
      ];
    }),
  }), [metrics.data, selectedMetrics, theme, currency]);
  const priceOption = useMemo(() => ({
    tooltip: { trigger: 'axis', confine: true },
    grid: [{ left: 65, right: 25, top: 15, height: '55%' }, { left: 65, right: 25, top: '73%', height: '12%' }],
    xAxis: [{ type: 'category', data: prices.data?.map(p => p.date) || [], boundaryGap: true, axisLabel: { show: false } }, { type: 'category', gridIndex: 1, data: prices.data?.map(p => p.date) || [], axisLabel: { fontSize: 10 } }],
    yAxis: [{ scale: true, splitLine: { lineStyle: { opacity: .12 } } }, { gridIndex: 1, splitNumber: 2, axisLabel: { formatter: (v: number) => format(v, 'number', currency, true) }, splitLine: { show: false } }],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }, { type: 'slider', xAxisIndex: [0, 1], bottom: 0, height: 18 }],
    series: [{ name: 'OHLC', type: 'candlestick', data: prices.data?.map(p => [p.open, p.close, p.low, p.high]) || [], itemStyle: { color: '#63a68c', color0: '#d1837a', borderColor: '#63a68c', borderColor0: '#d1837a' },
      markLine: { symbol: 'none', label: { position: 'insideEndTop', formatter: (p: { name: string }) => p.name }, data: (splits.data || []).filter(s => prices.data?.some(p => p.date === s.date)).map(s => ({ name: `${s.numerator ?? '?'}:${s.denominator ?? '?'} split`, xAxis: s.date })) } },
      { name: 'Volume', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: prices.data?.map(p => p.volume) || [], itemStyle: { color: '#63a68c66' } }],
  }), [prices.data, splits.data, currency]);
  function toggleMetric(key: string) { setSelectedMetrics(old => old.includes(key) ? old.filter(k => k !== key) : [...old, key]); }
  const cols = statements.data || [];
  const tableKeys = Array.from(new Set(cols.flatMap(row => Object.keys(row.values))));
  const kpis = ['revenue', 'netIncome', 'freeCashFlow', 'grossProfitRatio'];
  return <div className="shell">
    <aside className="sidebar">
      <a className="brand" href="/" onClick={e => { e.preventDefault(); if (tickers.data?.[0]) navigate(tickers.data[0].symbol); }}><span className="brand-mark">▥</span> ledger<span className="brand-dot">.</span></a>
      <div className="workspace-label">YOUR RESEARCH WORKSPACE</div>
      <label className="search"><span aria-hidden="true">⌕</span><input aria-label="Search tickers" placeholder="Find a company…" value={search} onChange={e => setSearch(e.target.value)} /></label>
      <div className="list-heading"><span>COMPANIES</span><span>{tickers.data?.length ?? '—'}</span></div>
      <nav aria-label="Companies" className="company-list">
        {tickers.isPending && <Pending />}
        {tickers.isError && <Notice text="Company list unavailable" retry={() => void tickers.refetch()} />}
        {tickers.data?.map(t => <a key={t.symbol} href={`/companies/${encodeURIComponent(t.symbol)}`} className={t.symbol === symbol ? 'company-link active' : 'company-link'} aria-current={t.symbol === symbol ? 'page' : undefined} onClick={e => { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); navigate(t.symbol); } }}><span className="ticker-avatar">{t.symbol.slice(0, 2)}</span><span>{t.symbol}<small>{t.coverage.filter(c => c.includes('statement') || c === 'balance_sheet').length} statement types</small></span><span className="link-arrow">↗</span></a>)}
        {tickers.data?.length === 0 && <Notice text={search ? 'No matching companies.' : 'No stored companies yet.'} />}
      </nav>
      <div className="sidebar-bottom"><span className="status-dot" /> Private workspace <button className="theme-button" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? '☀' : '☾'}</button></div>
    </aside>
    <main>
      <header className="topbar"><span>WORKSPACE <span className="breadcrumb-slash">/</span> COMPANY RESEARCH</span><span className="topbar-actions"><span className="snapshot-badge">◷ Stored financial data</span><button className="mobile-theme" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? '☀' : '☾'}</button></span></header>
      {!symbol ? <div className="empty-workspace"><div className="eyebrow">START EXPLORING</div><h1>Your next insight<br />starts here.</h1><p>Select a company to explore its financial story.</p>{tickers.isError && <Notice text="We couldn’t connect to your data." retry={() => void tickers.refetch()} />}</div> : <>
        <section className="company-heading"><div><div className="eyebrow">{current?.sector || 'COMPANY RESEARCH'} <span> / {symbol}</span></div><h1>{current?.name || symbol}<span className="company-symbol">{symbol}</span></h1><p>{[current?.exchange, current?.industry, current?.country].filter(Boolean).join(' · ') || 'Financial statements and historical performance'}</p></div><div className="stored-price"><span>Stored share price</span><strong>{format(current?.price, 'currency', current?.currency || currency)}</strong><small>{current?.asOf ? `As of ${current.asOf.slice(0, 10)}` : 'Snapshot date unavailable'}</small></div></section>
        {company.isError && <Notice text={(company.error as ApiError).message} retry={() => void company.refetch()} />}
        <div className="toolbar"><div className="tabs" role="tablist" aria-label="Company views">{(['overview', 'statements', 'prices'] as View[]).map(tab => <button key={tab} role="tab" aria-selected={view === tab} onClick={() => setView(tab)}>{tab === 'prices' ? 'Price history' : label(tab)}</button>)}</div>{view !== 'prices' && <div className="filters"><label>Period<select aria-label="Reporting period" value={period} onChange={e => setPeriod(e.target.value)}>{['FY', 'Q1', 'Q2', 'Q3', 'Q4'].map(p => <option key={p} value={p}>{p === 'FY' ? 'Annual' : p}</option>)}</select></label><label>History<select aria-label="History length" value={years} onChange={e => setYears(e.target.value)}>{['5', '10', '20'].map(y => <option key={y} value={y}>{y} periods</option>)}</select></label></div>}</div>
        {view === 'overview' && <section aria-label="Overview">
          <div className="section-heading"><h2>The financial picture</h2><span>{latest ? `${latest.year} ${latest.period} · ${currency}` : 'Stored reporting periods'}</span></div>
          {metrics.isPending && <Pending />}{metrics.isError && <Notice text="Financial metrics unavailable." retry={() => void metrics.refetch()} />}
          <div className="kpi-grid">{kpis.map(key => { const def = metrics.data?.definitions.find(m => m.key === key); const growth = latest?.growth[key]; return <article className="kpi" key={key}><span>{def?.label || label(key)}</span><strong>{format(latest?.values[key], def?.format, currency, true)}</strong><small className={growth == null ? '' : growth < 0 ? 'negative' : 'positive'}>{growth == null ? 'YoY unavailable' : `${growth >= 0 ? '↗' : '↘'} ${format(growth, 'percent')} year over year`}</small></article>; })}</div>
          <section className="panel"><div className="panel-header"><div><div className="eyebrow">PERFORMANCE OVER TIME</div><h2>Behind the numbers</h2></div><span className="subtle">{currency} · {period === 'FY' ? 'Annual' : period}</span></div><div className="metric-picker">{metrics.data?.definitions.map(d => <label key={d.key} className={selectedMetrics.includes(d.key) ? 'metric-chip selected' : 'metric-chip'}><input type="checkbox" checked={selectedMetrics.includes(d.key)} onChange={() => toggleMetric(d.key)} />{d.label}</label>)}</div>{!metrics.isPending && points.length === 0 ? <Notice text="No financial metrics for this reporting period." /> : selectedMetrics.length === 0 ? <Notice text="Choose a metric to draw a chart." /> : <Suspense fallback={<Pending />}><Chart theme={theme} option={metricOption} title="Financial metrics and year-over-year growth" /></Suspense>}<p className="chart-caption">Select one metric to show its year-over-year growth. Missing values appear as gaps.</p></section>
          <section className="panel about"><div><div className="eyebrow">COMPANY PROFILE</div><h2>About {current?.name || symbol}</h2><p>{current?.description || 'No company description is stored for this symbol.'}</p>{current?.website && /^https?:\/\//i.test(current.website) && <a href={current.website} target="_blank" rel="noreferrer">Company website ↗</a>}</div><dl>{[['Sector', current?.sector], ['CEO', current?.ceo], ['Employees', format(current?.employees, 'number')], ['Market cap', format(current?.marketCap, 'currency', current?.currency || currency, true)]].map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v || '—'}</dd></div>)}</dl></section>
        </section>}
        {view === 'statements' && <section className="panel"><div className="panel-header"><div><div className="eyebrow">REPORTED FINANCIALS</div><h2>Financial statements</h2></div><select aria-label="Statement type" value={statementType} onChange={e => setStatementType(e.target.value)}><option value="income">Income statement</option><option value="balance">Balance sheet</option><option value="cash-flow">Cash flow</option></select></div>{statements.isPending ? <Pending /> : statements.isError ? <Notice text="Statement data unavailable." retry={() => void statements.refetch()} /> : !cols.length ? <Notice text="No statements for this reporting period." /> : <div className="table-scroll"><table><caption className="sr-only">{label(statementType)} financial statement</caption><thead><tr><th scope="col">Financial line item</th>{cols.map(c => <th scope="col" key={`${c.date}-${c.period}-${c.currency}`}>{c.year} {c.period}<small>{c.currency || 'Currency unavailable'} · {c.date}</small></th>)}</tr></thead><tbody>{tableKeys.map(key => <tr key={key}><th scope="row">{label(key)}</th>{cols.map(c => <td key={`${c.date}-${c.period}-${c.currency}`} className={(c.values[key] || 0) < 0 ? 'negative' : ''}>{format(c.values[key], /ratio/i.test(key) ? 'percent' : /weightedAverage/i.test(key) ? 'number' : 'currency', c.currency || currency)}</td>)}</tr>)}</tbody></table></div>}</section>}
        {view === 'prices' && <section className="panel"><div className="panel-header"><div><div className="eyebrow">STORED MARKET DATA</div><h2>Price & volume</h2></div><div className="date-filters"><label>From<input aria-label="Price from date" type="date" value={from} onChange={e => setFrom(e.target.value)} /></label><label>To<input aria-label="Price to date" type="date" value={to} onChange={e => setTo(e.target.value)} /></label>{(from || to) && <button onClick={() => { setFrom(''); setTo(''); }}>Reset</button>}</div></div>{from && to && from > to ? <Notice text="Choose an end date on or after the start date." /> : prices.isPending ? <Pending /> : prices.isError ? <Notice text="Price history unavailable. Other financial views are still available." retry={() => void prices.refetch()} /> : !prices.data?.length ? <Notice text="No stored prices for this date range." /> : <><div className="price-summary"><strong>{format(latestPrice?.close, 'currency', current?.currency || currency)}</strong><span>Latest stored close · {latestPrice?.date}</span></div><Suspense fallback={<Pending />}><Chart theme={theme} option={priceOption} title="Historical candlestick prices, volume, and stock split events" /></Suspense></>}<p className="chart-caption">Stored OHLC prices, without split adjustment. Showing up to 5,000 of the most recent observations in the selected range. Prices use the profile currency when available.</p>{splits.isError ? <Notice text="Stock split history unavailable." retry={() => void splits.refetch()} /> : <details className="split-details"><summary>Stock split history <span>{splits.data?.length ?? 0}</span></summary>{splits.data?.length ? <ul>{splits.data.map(s => <li key={s.date}><time>{s.date}</time><strong>{s.numerator ?? '—'} : {s.denominator ?? '—'}</strong></li>)}</ul> : <p>No stored stock splits.</p>}</details>}</section>}
        <footer><span><span className="status-dot" /> MongoDB · Stored snapshots</span><span>Built for a longer view.</span></footer>
      </>}
    </main>
  </div>;
}
