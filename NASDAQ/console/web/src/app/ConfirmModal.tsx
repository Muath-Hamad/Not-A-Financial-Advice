// One 4-step confirm modal for every control action (HANDOFF §4.1–4.3):
// 1 Impact (server preview) · 2 Reason (category + ≥ 10 characters) ·
// 3 Verify (TOTP, plus the typed word for destructive actions) · 4 Result
// (each server step). Never optimistic: a failed step reads "Not applied";
// a 409 returns to step 1 with the fresh preview.

import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError, apply, invalidateAfterControl, preflight as fetchPreflight, preview as fetchPreview } from '@/api/client';
import type { ApplyResult, PreflightPayload, Preview } from '@/api/types';
import { CATEGORIES, categoryFor, quickReasons, type Category } from '@/domain/controls';
import { cx } from '@/lib/format';
import { Icon } from '@/components/icons';
import { Chip, Note, Seg, Sk } from '@/components/ui';
import { Gloss, T } from '@/glossary/Term';
import { useConsole, useCtx } from './console';

const STEP_NAMES = ['Impact', 'Reason', 'Verify', 'Result'];

export function ConfirmModal() {
  const { modal, closeModal, me } = useConsole();
  const ctx = useCtx();
  const qc = useQueryClient();
  const [params, setParams] = useState<Record<string, unknown>>(modal?.params ?? {});
  const [pv, setPv] = useState<Preview | null>(null);
  const [step, setStep] = useState(1);
  const [cat, setCat] = useState<Category>(modal ? categoryFor(modal.action) : 'Operational');
  const [reason, setReason] = useState('');
  const [totp, setTotp] = useState('');
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<ApplyResult | null>(null);
  const action = modal?.action;

  useEffect(() => {
    if (!action) return;
    let live = true;
    setPv(null);
    fetchPreview(action, params).then((p) => { if (live) setPv(p); }).catch((e: Error) => { if (live) setErr(e.message); });
    return () => { live = false; };
  }, [action, params]);

  if (!modal || !action) return null;
  const reasonOk = reason.trim().length >= 10;
  const totpOk = !me?.auth || /^\d{6}$/.test(totp);
  const wordOk = !pv?.word || typed.trim().toUpperCase() === pv.word.toUpperCase();
  const running = step === 4 && busy;

  const run = async () => {
    if (!pv) return;
    setStep(4);
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      const r = await apply({ action, params, reason, category: cat, previewHash: pv.previewHash, totp, typed });
      setRes(r);
      invalidateAfterControl(qc);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const fresh = (e.body as { preview?: Preview } | undefined)?.preview;
        if (fresh) setPv(fresh);
        setStep(1);
        setErr('The state changed since the preview — review the new impact and confirm again.');
      } else {
        setRes({ applied: false, steps: [{ l: (e as Error).message, st: 'fail' }], sha: null, actionId: '', title: pv.title, eff: pv.eff, pending: '' });
      }
    } finally {
      setBusy(false);
      setTotp('');
    }
  };

  const close = () => { if (!running) closeModal(); };

  return (
    <div className="scrim">
      <div className={cx('modal', pv?.danger && 'dz')} role="dialog" aria-modal="true" aria-label={pv?.title ?? 'Confirm'}>
        <div className="modal-h">
          <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
            <div className="col gap4 sp" style={{ minWidth: 0 }}>
              <div className="row" style={{ gap: 6 }}>
                <Chip cls={pv?.danger ? 'danger' : ''}>{pv?.danger ? 'Destructive' : 'Reversible'}</Chip>
                <span className={cx('env', ctx.env)} style={{ height: 20, fontSize: 9.5 }}>{ctx.env.toUpperCase()}</span>
                <span className="xs muted">{me?.user ?? 'owner'} · {ctx.clock.d} {ctx.clock.t}</span>
              </div>
              <h2 style={{ fontSize: 18, fontWeight: 700, letterSpacing: '-.01em' }}>{pv?.title ?? '…'}</h2>
              <span className="sm dim"><Gloss text={pv?.sub ?? ''} /></span>
            </div>
            <button type="button" className="btn ghost icon" onClick={close} aria-label="Close" disabled={running}><Icon name="close" /></button>
          </div>
          <div className="mstp">
            {STEP_NAMES.map((l, i) => (
              <span key={l} className={cx(i + 1 < step && 'done', i + 1 === step && 'cur', i === 3 && res && !res.applied && 'fail')}>
                {i + 1} · {i === 2 && pv?.word ? 'Verify · type ' + pv.word : l}
              </span>
            ))}
          </div>
        </div>

        <div className="modal-b">
          {err && <Note tone="warn">{err}</Note>}
          {step === 1 && (pv ? <Impact pv={pv} action={action} params={params} setParams={setParams} /> : <Sk h={220} />)}
          {step === 2 && (
            <>
              <div className="col gap4"><span className="lbl" style={{ margin: 0 }}>Category</span>
                <Seg<Category> className="lg" label="Category" value={cat} onChange={setCat} items={CATEGORIES.map((c) => ({ k: c, l: c }))} />
              </div>
              <div className="fld">
                <label className="lbl" htmlFor="mreason">Reason — required, at least 10 characters, stored in the commit message</label>
                <textarea id="mreason" className="ta" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why are you doing this?" />
                <span className={cx('xs', reasonOk ? 'pos' : 'muted')} style={{ marginTop: 6 }}>{reasonOk ? reason.trim().length + ' characters ✓' : reason.trim().length + ' / 10 characters minimum'}</span>
              </div>
              <div className="col gap4"><span className="xs muted">Quick reasons</span>
                <div className="qchips">{quickReasons(action).map((q) => <button key={q} type="button" className="qchip" onClick={() => setReason(q)}>{q}</button>)}</div>
              </div>
              <div className="effline"><span className="k">Effective</span><span>{pv?.eff}</span></div>
            </>
          )}
          {step === 3 && (
            <>
              {me?.auth ? (
                <div className="fld">
                  <label className="lbl" htmlFor="mtotp">Authenticator code (<T k="totp">TOTP</T>)</label>
                  <input id="mtotp" className="totp" type="text" inputMode="numeric" autoComplete="one-time-code" value={totp}
                    onChange={(e) => setTotp(e.target.value.replace(/[^0-9]/g, '').slice(0, 6))} placeholder="••••••" autoFocus />
                  <span className="xs muted" style={{ marginTop: 6 }}>Every control asks for a fresh code (step-up). Each code works once.</span>
                </div>
              ) : (
                <Note tone="warn">Authentication is off on this server (CONSOLE_AUTH=off, development) — no code is asked. Turn it on before real use.</Note>
              )}
              {pv?.word && (
                <div className="fld">
                  <label className="lbl" htmlFor="mword">Type <b className="mono danger">{pv.word}</b> to confirm</label>
                  <input id="mword" className="typed" type="text" value={typed} onChange={(e) => setTyped(e.target.value.toUpperCase().slice(0, 12))} />
                  <span className={cx('xs', wordOk ? 'pos' : 'muted')} style={{ marginTop: 6 }}>{wordOk ? 'Matches ✓' : 'Type exactly ' + pv.word}</span>
                </div>
              )}
              <Note tone={pv?.danger ? 'danger' : 'info'}>You are about to: {pv?.title}. Effective: {pv?.eff}. Reason: “{reason.trim()}”.</Note>
            </>
          )}
          {step === 4 && (
            <>
              <div className="res">
                {(res?.steps ?? (pv?.steps ?? []).map((l) => ({ l, st: 'wait' as const }))).map((r, i) => (
                  <div key={i} className={cx('res-i', r.st)}>
                    {r.st === 'wait' ? <span className="spin" /> : <span className="res-g">{r.st === 'ok' ? '✓' : r.st === 'fail' ? '✕' : '–'}</span>}
                    <span>{r.l}</span>
                  </div>
                ))}
              </div>
              {res?.applied && (
                <div className="verdict ok">
                  <span style={{ width: 30, height: 30, borderRadius: '50%', background: 'var(--pos)', color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 800, flex: 'none' }}>✓</span>
                  <div className="col gap4"><span className="vt">Applied</span><span className="sm dim">{res.pending || res.title}</span>
                    <span className="xs muted">Effective: {res.eff}{res.sha ? <> · commit <span className="mono">{res.sha.slice(0, 7)}</span></> : null}</span></div>
                </div>
              )}
              {res && !res.applied && (
                <div className="verdict fail">
                  <Icon name="octagon" className="s22 danger" />
                  <div className="col gap4"><span className="vt">Not applied</span>
                    <span className="sm">The step marked ✕ failed. Anything already committed is listed above; nothing else changed.</span>
                    <span className="xs muted">The attempt is in the audit log. Retry runs the same validated change again.</span></div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="modal-f">
          {step === 1 && <><button type="button" className="btn ghost" onClick={close}>Cancel</button><span className="sp" />
            <button type="button" className="btn primary" disabled={!pv || pv.errors.length > 0} onClick={() => { setErr(null); setStep(2); }}>Continue</button></>}
          {step === 2 && <><button type="button" className="btn ghost" onClick={() => setStep(1)}>Back</button><span className="sp" />
            <button type="button" className="btn primary" disabled={!reasonOk} onClick={() => setStep(3)}>Continue</button></>}
          {step === 3 && <><button type="button" className="btn ghost" onClick={() => setStep(2)}>Back</button><span className="sp" />
            <button type="button" className={cx('btn', pv?.danger ? 'danger' : 'primary')} disabled={!(totpOk && wordOk)} onClick={run}>{pv?.verb ?? 'Confirm'}</button></>}
          {step === 4 && (running
            ? <span className="sm dim row gap4"><span className="spin" />Working — do not close</span>
            : res && !res.applied
              ? <><button type="button" className="btn ghost" onClick={close}>Close</button><span className="sp" /><button type="button" className="btn primary" onClick={() => setStep(3)}>Retry</button></>
              : <><span className="sp" /><button type="button" className="btn primary" onClick={close}>Done</button></>)}
        </div>
      </div>
    </div>
  );
}

function OrderList({ title, items, kind }: { title: string; items: Preview['added']; kind: 'added' | 'blocked' | 'canceled' }) {
  if (!items.length) return null;
  return (
    <div className="col gap4"><span className="up">{title} · {items.length}</span>
      <div className="olist" style={kind === 'added' ? { maxHeight: 180, overflow: 'auto' } : undefined}>
        {items.map((o, i) => (
          <div key={i} className="oitem" style={kind === 'canceled' ? { textDecoration: 'line-through', textDecorationColor: 'var(--danger)' } : undefined}>
            <span className={cx('side', o.side)}>{o.sideL}</span><span className="sym">{o.s}</span><span className="num dim">{o.q}</span><span className="num">{o.v}</span>
            {kind === 'blocked'
              ? <span className="tag gr blk"><span className="rule"><Gloss text={o.tag} /></span></span>
              : <span className={cx('tag chip', kind === 'canceled' ? 'danger' : 'info')} style={kind === 'canceled' ? { textDecoration: 'none' } : undefined}>{kind === 'canceled' ? 'canceled' : o.tag}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function Impact({ pv, action, params, setParams }: { pv: Preview; action: string; params: Record<string, unknown>; setParams: (p: Record<string, unknown>) => void }) {
  return (
    <>
      <div className="effline"><span className="k">Effective</span><span className="b">{pv.eff}</span></div>
      {pv.errors.length > 0 && <Note tone="danger">{pv.errors.join(' · ')}</Note>}
      {action === 'trim' && (
        <div className="row wrap" style={{ gap: 8 }}>
          <span className="sm dim">Sell</span>
          <Seg className="lg" label="Trim size" value={String(params.pct ?? 50)} onChange={(v) => setParams({ ...params, pct: Number(v) })} items={['25', '50', '75', '100'].map((k) => ({ k, l: k + '%' }))} />
        </div>
      )}
      <div className="col" style={{ gap: 0 }}>
        <span className="up" style={{ marginBottom: 2 }}>What changes</span>
        {pv.rows.map((r, i) => <div key={i} className="ba-row"><span className="dim"><Gloss text={r.k} /></span><span className="from num">{r.a}</span><span className="arrow muted">→</span><span className="to num">{r.b}</span></div>)}
      </div>
      <OrderList title="Orders added" items={pv.added} kind="added" />
      <OrderList title="Orders blocked" items={pv.blocked} kind="blocked" />
      <OrderList title="Orders canceled" items={pv.canceled} kind="canceled" />
      {!pv.added.length && !pv.blocked.length && !pv.canceled.length && <div className="sm muted">No orders are added, blocked or canceled.</div>}
      <div className="g3">
        <div className="statbox"><span className="l">Estimated proceeds</span><span className="sm b" style={{ whiteSpace: 'normal' }}>{pv.proceeds}</span></div>
        <div className="statbox"><span className="l"><T k="realized">P&amp;L locked in</T></span><span className="sm b" style={{ whiteSpace: 'normal' }}>{pv.pnl}</span></div>
        <div className="statbox"><span className="l"><T k="drift">Drift impact</T></span><span className="sm" style={{ whiteSpace: 'normal' }}>{pv.drift}</span></div>
      </div>
      {pv.fid && <Note tone="warn"><b>Fidelity:</b> <Gloss text={pv.fid} /></Note>}
    </>
  );
}

/* ───────── resume preflight (docs/08 §7.3) ───────── */

export function PreflightModal() {
  const { setPreflightOpen, openModal, go } = useConsole();
  const ctx = useCtx();
  const [ticks, setTicks] = useState<Record<string, boolean>>({});
  const [note, setNote] = useState('');
  const [pf, setPf] = useState<PreflightPayload | null>(null);
  useEffect(() => {
    let live = true;
    fetchPreflight(ticks, note).then((p) => { if (live) setPf(p); }).catch(() => undefined);
    return () => { live = false; };
  }, [ticks, note]);
  const close = () => setPreflightOpen(false);
  return (
    <div className="scrim">
      <div className="modal" role="dialog" aria-modal="true" aria-label="Resume preflight checklist">
        <div className="modal-h">
          <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
            <div className="col gap4 sp">
              <div className="row" style={{ gap: 6 }}><Chip>Preflight</Chip><span className={cx('env', ctx.env)} style={{ height: 20, fontSize: 9.5 }}>{ctx.env.toUpperCase()}</span></div>
              <h2 style={{ fontSize: 18, fontWeight: 700 }}>Resume trading · preflight checklist</h2>
              <span className="sm dim">Resume is enabled only when every check passes. Manual items need your tick.</span>
            </div>
            <button type="button" className="btn ghost icon" onClick={close} aria-label="Close"><Icon name="close" /></button>
          </div>
        </div>
        <div className="modal-b" style={{ gap: 0 }}>
          {!pf && <Sk h={300} />}
          {pf?.checks.map((c) => {
            const ticked = !!ticks[c.id];
            return (
              <div key={c.id} className="pf-i">
                {c.s === 'man'
                  ? <button type="button" className={cx('pf-s man', ticked && 'ticked')} onClick={() => setTicks({ ...ticks, [c.id]: !ticked })} aria-label={'Tick: ' + c.l} aria-pressed={ticked}>{ticked ? '✓' : ''}</button>
                  : <span className={cx('pf-s', c.s)}>{c.s === 'pass' ? '✓' : '✕'}</span>}
                <div className="col gap4 sp" style={{ minWidth: 0 }}>
                  <span className="b sm"><Gloss text={c.l} /></span><span className="xs muted"><Gloss text={c.d} /></span>
                  {c.note && ticked && <input className="inp" placeholder="Note: why it is safe to resume anyway (required)" value={note} onChange={(e) => setNote(e.target.value)} style={{ marginTop: 6 }} aria-label="Acknowledgement note" />}
                  {c.fix && <button type="button" className="a xs" onClick={() => { close(); go('alerts'); }} style={{ alignSelf: 'flex-start', marginTop: 2 }}>Resolve in Alerts →</button>}
                </div>
                <Chip cls={c.pass ? 'pos' : c.s === 'fail' ? 'danger' : 'warn'}>{c.pass ? 'Pass' : c.s === 'fail' ? 'Fail' : ticked && c.note ? 'Add a note' : 'Tick to acknowledge'}</Chip>
              </div>
            );
          })}
        </div>
        <div className="modal-f">
          <span className={cx('sm', pf?.ok ? 'pos' : 'warn')}>{pf ? (pf.ok ? 'All ' + pf.checks.length + ' checks pass' : pf.n + ' of ' + pf.checks.length + ' pass') : '…'}</span>
          <span className="sp" />
          <button type="button" className="btn ghost" onClick={close}>Cancel</button>
          <button type="button" className="btn primary" disabled={!pf?.ok} onClick={() => { close(); openModal('resume', { ticks, note }); }}>Continue to confirm</button>
        </div>
      </div>
    </div>
  );
}
