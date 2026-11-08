import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from './api';
import { SECError, secAPI, terminal, conceptName, factValue, sourceLink, type SECCompany, type SECFiling, type SECFact, type SECJob } from './sec-api';

export function ScrapeButton({ symbol, onJob }: { symbol: string; onJob: (job: SECJob) => void }) {
  const key = useRef(crypto.randomUUID());
  const retryAccess = useRef(false);
  const start = useMutation({ mutationFn: () => secAPI<SECJob>('/jobs', { method: 'POST', body: { symbol, action: 'scrape', selection: 'latest', ...(retryAccess.current ? { retryAccess: true } : {}) }, key: key.current }), onSuccess: result => onJob(result.data) });
  useEffect(() => { key.current = crypto.randomUUID(); retryAccess.current = false; start.reset(); }, [symbol]);
  return <div className="sec-action"><button className="primary-button" disabled={start.isPending} onClick={() => start.mutate()}>{start.isPending ? 'Starting import…' : `Scrape ${symbol} from SEC`}</button>{start.isError && <p role="alert">{start.error.message}{start.error instanceof SECError && ['sec_blocked', 'sec_rate_limited', 'cooldown_active'].includes(start.error.code || '') && <button onClick={() => { retryAccess.current = true; key.current = crypto.randomUUID(); start.mutate(); }}>Retry SEC access after diagnosis</button>}</p>}</div>;
}

export default function SECPanel({ symbol, company, companyError, jobId, onJob, canDiscover }: { symbol: string; company?: SECCompany; companyError?: Error | null; jobId: string; onJob: (job: SECJob) => void; canDiscover: boolean }) {
  const cache = useQueryClient();
  const [clock, setClock] = useState(Date.now);
  useEffect(() => { const timer = setInterval(() => setClock(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const [selected, setSelected] = useState('');
  const [concept, setConcept] = useState(''); const [dimension, setDimension] = useState(''); const [offset, setOffset] = useState(0);
  const [selection, setSelection] = useState('latest'); const [fromDate, setFrom] = useState(''); const [toDate, setTo] = useState('');
  const [companyFacts, setCompanyFacts] = useState(false);
  const requestKey = useRef(crypto.randomUUID());
  useEffect(() => { setSelected(''); setConcept(''); setDimension(''); setOffset(0); setCompanyFacts(false); requestKey.current = crypto.randomUUID(); }, [symbol]);
  const job = useQuery({ queryKey: ['sec-job', jobId], queryFn: ({ signal }) => secAPI<SECJob>(`/jobs/${encodeURIComponent(jobId)}`, { signal }), enabled: !!jobId,
    refetchInterval: query => query.state.data && terminal.has(query.state.data.data.status) ? false : 1500 });
  const currentJob = job.data?.data;
  const hasSavedRequest = !!currentJob && terminal.has(currentJob.status);
  const running = !!jobId && (!currentJob || !terminal.has(currentJob.status));
  const completed = useRef('');
  useEffect(() => {
    if (currentJob && terminal.has(currentJob.status) && completed.current !== `${currentJob.id}/${currentJob.updatedAt}`) {
      completed.current = `${currentJob.id}/${currentJob.updatedAt}`;
      const keys = [['sec-company', symbol], ['sec-companies'], ['sec-filings', symbol], ['sec-facts', symbol]];
      // Cancel an initial "not imported" request before refreshing. Otherwise a
      // late 404 can overwrite the newly completed import's company metadata.
      void Promise.all(keys.map(queryKey => cache.cancelQueries({ queryKey })))
        .then(() => Promise.all(keys.map(queryKey => cache.invalidateQueries({ queryKey }))));
    }
  }, [currentJob, cache, symbol]);
  const filings = useQuery({ queryKey: ['sec-filings', symbol], queryFn: ({ signal }) => secAPI<SECFiling[]>(`/companies/${encodeURIComponent(symbol)}/filings?limit=100`, { signal }), enabled: !!company });
  const accession = selected || filings.data?.data[0]?.accession || '';
  const factsPath = companyFacts ? `/companies/${encodeURIComponent(symbol)}/company-facts` : `/filings/${encodeURIComponent(accession)}/facts`;
  const facts = useQuery({ queryKey: ['sec-facts', symbol, accession, companyFacts, concept, dimension, offset], queryFn: ({ signal }) => secAPI<SECFact[]>(`${factsPath}?limit=100&offset=${offset}&concept=${encodeURIComponent(concept)}${companyFacts ? '' : `&dimension=${encodeURIComponent(dimension)}`}`, { signal }), enabled: !!company && (!!accession || companyFacts) });
  const refresh = useMutation({ mutationFn: () => secAPI<SECJob>('/jobs', { method: 'POST', body: { symbol, action: company || hasSavedRequest ? 'refresh' : 'scrape', selection, ...(selection === 'range' ? { fromDate, toDate } : {}) }, key: requestKey.current }), onSuccess: result => { requestKey.current = crypto.randomUUID(); onJob(result.data); } });
  const control = useMutation({ mutationFn: (action: 'cancel' | 'retry') => secAPI<SECJob>(`/jobs/${encodeURIComponent(jobId)}/${action}`, { method: 'POST', body: {} }), onSuccess: result => { onJob(result.data); void cache.invalidateQueries({ queryKey: ['sec-job', jobId] }); } });
  const missing = companyError instanceof ApiError && companyError.status === 404;
  const canStart = !!company || (missing && canDiscover && /^[A-Z0-9][A-Z0-9.\-]{0,19}$/.test(symbol));
  const importError = refresh.error || control.error;
  const count = facts.data?.meta?.total ?? 0;
  function filterConcept(value: string) { setConcept(value); setOffset(0); }
  return <section className="sec-workspace" aria-label="SEC filings">
    <section className="panel">
      <div className="panel-header"><div><div className="eyebrow">SOURCE FILINGS</div><h2>SEC filings & facts</h2></div><span className="snapshot-badge">{company?.lastSuccessfullyScrapedAt ? `Last successful import · ${company.lastSuccessfullyScrapedAt.slice(0, 10)}` : 'Imported on request'}</span></div>
      <p>Reported facts and segment detail from US annual and quarterly filings. SEC data is separate from the stored financial statements and market prices.</p>
      {companyError && !missing && <div className="notice" role="alert">{companyError.message}<button onClick={() => void cache.invalidateQueries({ queryKey: ['sec-company', symbol] })}>Try again ↗</button></div>}
      {company?.activeJobId && company.activeJobId !== jobId && <button className="primary-button" onClick={() => onJob({ id: company.activeJobId!, symbol } as SECJob)}>View active import</button>}
      {canStart && <div className="sec-controls"><label>Import selection<select aria-label="SEC import selection" value={selection} onChange={e => { setSelection(e.target.value); requestKey.current = crypto.randomUUID(); }}><option value="latest">Latest 10-K and 10-Q, including amendments</option><option value="10-K">Latest 10-K and amendments</option><option value="10-Q">Latest 10-Q and amendments</option><option value="range">Filing date range</option>{company && <option value="company-facts">Company facts API snapshot</option>}</select></label>{selection === 'range' && <><label>Filed from<input aria-label="SEC filed from" type="date" min="2009-01-01" value={fromDate} onChange={e => { setFrom(e.target.value); requestKey.current = crypto.randomUUID(); }} /></label><label>Filed to<input aria-label="SEC filed to" type="date" min="2009-01-01" value={toDate} onChange={e => { setTo(e.target.value); requestKey.current = crypto.randomUUID(); }} /></label></>}<button className="primary-button" disabled={running || refresh.isPending || (selection === 'range' && (!fromDate || !toDate || fromDate > toDate))} onClick={() => refresh.mutate()}>{refresh.isPending ? 'Starting import…' : company ? 'Refresh SEC data' : hasSavedRequest ? 'Start updated import' : `Scrape ${symbol} from SEC`}</button></div>}
      {selection === 'range' && <p className="subtle">Up to five years and 25 filings per import, starting in 2009.</p>}
      {importError && <p role="alert">{importError.message}</p>}
      {jobId && <div className="sec-progress" role="status" aria-live="polite"><strong>{currentJob ? `${currentJob.status.replaceAll('_', ' ')} · ${currentJob.stage.replaceAll('_', ' ')}` : 'Loading import progress…'}</strong>{currentJob && <><progress max={Math.max(currentJob.total, 1)} value={currentJob.completed} /><span>{currentJob.completed} / {currentJob.total} filings completed</span>{currentJob.currentAccession && <small>{currentJob.currentAccession}</small>}{currentJob.retryAt && <p>SEC cooldown until {new Date(currentJob.retryAt).toLocaleString()}. You can leave this page; accepted work is saved.</p>}{currentJob.accessBlocked && <p role="alert">SEC access is blocked for the queue. Review the requester identity and egress before retrying.{currentJob.accessRetryAt && Date.parse(currentJob.accessRetryAt) > clock ? ` Cooldown until ${new Date(currentJob.accessRetryAt).toLocaleString()}.` : ''}</p>}{currentJob.error && <p role="alert">{currentJob.error.message}</p>}{currentJob.failures?.map(failure => <p key={failure.accession} role="alert">{failure.accession}: {failure.message}</p>)}{!!currentJob.warnings?.length && <details><summary>Import warnings ({currentJob.warnings.length})</summary><ul>{currentJob.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}{!terminal.has(currentJob.status) ? <button disabled={control.isPending} onClick={() => control.mutate('cancel')}>Cancel import</button> : null}{(['failed', 'partial_failed', 'blocked', 'cancelled'].includes(currentJob.status) || currentJob.accessBlocked) && <button className="primary-button" disabled={control.isPending || (!!(currentJob.accessRetryAt || currentJob.retryAt) && Date.parse(currentJob.accessRetryAt || currentJob.retryAt!) > clock)} onClick={() => control.mutate('retry')}>{currentJob.accessBlocked ? 'Retry SEC access after diagnosis' : 'Retry saved import'}</button>}</>}{job.isError && <p role="alert">{job.error.message}<button onClick={() => void job.refetch()}>Reconnect</button></p>}</div>}
    </section>
    {company && <section className="panel"><div className="panel-header"><h2>Explore reported facts</h2><div className="sec-filters">{filings.data?.data.length ? <label>Filing<select aria-label="SEC filing" value={accession} onChange={e => { setSelected(e.target.value); setCompanyFacts(false); setOffset(0); }}>{filings.data.data.map(f => <option key={f.accession} value={f.accession}>{f.form} · filed {f.filingDate} · {f.accession}</option>)}</select></label> : null}{!!company.companyFactsCount && <label><input type="checkbox" checked={companyFacts} onChange={e => { setCompanyFacts(e.target.checked); setOffset(0); }} /> Company facts snapshot</label>}</div></div>
      {filings.isPending && <p role="status">Loading filings…</p>}{filings.isError && <div className="notice" role="alert">{filings.error.message}<button onClick={() => void filings.refetch()}>Try again</button></div>}
      {!companyFacts && filings.data?.data.find(f => f.accession === accession) && <p className="subtle">{(() => { const filing = filings.data!.data.find(f => f.accession === accession)!; return <>{filing.factCount.toLocaleString()} numeric facts · report date {filing.reportDate || 'unavailable'} · <a href={sourceLink(filing.sourceUrl)} target="_blank" rel="noreferrer">View original SEC filing ↗</a>{filing.sourceAvailability === 'unavailable' && ' · Source currently unavailable; previously imported data is retained.'}</>; })()}</p>}
      <div className="sec-filters"><label>Find a concept<input aria-label="SEC concept filter" placeholder="Revenue, assets…" value={concept} onChange={e => filterConcept(e.target.value)} /></label>{!companyFacts && <label>Segment or dimension<input aria-label="SEC dimension filter" placeholder="Hardware, ProductAxis, consolidated…" value={dimension} onChange={e => { setDimension(e.target.value); setOffset(0); }} /></label>}</div>
      {facts.isFetching && <p role="status">Loading facts…</p>}{facts.isError && <div className="notice" role="alert">{facts.error.message}<button onClick={() => void facts.refetch()}>Try again</button></div>}
      {facts.data && !facts.data.data.length && <div className="notice">No facts match these filters.</div>}
      {!!facts.data?.data.length && <div className="table-scroll"><table className="sec-facts-table"><caption className="sr-only">SEC numeric facts and segment dimensions</caption><thead><tr><th>Concept / label</th><th>Reported value</th><th>Unit</th><th>Period</th><th>Dimensions</th></tr></thead><tbody>{facts.data.data.map(f => <tr key={f.id}><th scope="row"><span>{f.label || conceptName(f.concept)}</span><small title={f.concept}>{conceptName(f.concept)}</small></th><td>{f.nil ? 'Nil' : factValue(f.value)}</td><td>{f.unit ? `${f.unit.numerator.map(conceptName).join(' × ')}${f.unit.denominator.length ? ` / ${f.unit.denominator.map(conceptName).join(' × ')}` : ''}` : f.unitRef || '—'}</td><td>{f.instant || `${f.startDate || '—'} → ${f.endDate || '—'}`}</td><td>{f.dimensions?.length ? f.dimensions.map((d, i) => <span className="sec-dimension" key={i}>{conceptName(d.axis)}: {d.member ? conceptName(d.member) : d.typedValue}</span>) : 'Consolidated'}</td></tr>)}</tbody></table></div>}
      {!!count && <div className="sec-pagination"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous</button><span>{offset + 1}–{Math.min(offset + 100, count)} of {count.toLocaleString()}</span><button disabled={offset + 100 >= count} onClick={() => setOffset(offset + 100)}>Next</button></div>}
    </section>}
  </section>;
}
